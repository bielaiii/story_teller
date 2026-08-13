from __future__ import annotations

import asyncio
import contextlib
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from storyteller.rag.hub_registry import WorkspaceRegistration


REQUIRED_WORKER_TOOLS = {
    "list_world_projects", "describe_world", "world_catalog", "resolve_world_entity",
    "query_world", "search_world", "get_world_entity", "get_related_world",
    "build_world_context", "rag_status",
}


class WorkerSession:
    def __init__(self, registration: WorkspaceRegistration, projects: list[str]):
        self.registration = registration
        self.projects = tuple(projects)
        self._actor_guard = asyncio.Lock()
        self._queue: asyncio.Queue | None = None
        self._actor: asyncio.Task | None = None
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self.tools: set[str] = set()
        self.started_at = 0
        self.last_error = ""

    @property
    def connected(self) -> bool:
        return self._client is not None

    async def _start_unlocked(self) -> None:
        if self._client is not None:
            return
        framework = Path(self.registration.framework_root)
        parameters = StdioServerParameters(
            command=str(framework / "scripts" / "python.sh"),
            args=[
                "-m", "storyteller.rag.stdio",
                "--content-root", self.registration.content_root,
                "--default-project", (
                    self.registration.project if self.registration.project in self.projects else ""
                ),
                "--projects", ",".join(self.projects),
            ],
            cwd=framework,
        )
        stack = AsyncExitStack()
        await stack.__aenter__()
        try:
            client = Client(stdio_client(parameters), mode="legacy")
            await stack.enter_async_context(client)
            listed = await client.list_tools()
            tools = {tool.name for tool in listed.tools}
            missing = sorted(REQUIRED_WORKER_TOOLS - tools)
            if missing:
                raise RuntimeError(f"项目 worker 缺少工具：{', '.join(missing)}")
        except BaseException:
            self.last_error = "MCP Worker 启动或能力检查失败"
            await stack.aclose()
            raise
        self._stack = stack
        self._client = client
        self.tools = tools
        self.started_at = int(time.time())
        self.last_error = ""

    async def _close_unlocked(self) -> None:
        stack, self._stack = self._stack, None
        self._client = None
        self.tools = set()
        if stack is not None:
            await stack.aclose()

    async def _run(self, queue: asyncio.Queue) -> None:
        try:
            while True:
                operation, arguments, future = await queue.get()
                try:
                    if operation == "start":
                        await self._start_unlocked()
                        result = None
                    elif operation == "call":
                        await self._start_unlocked()
                        assert self._client is not None
                        tool, payload = arguments
                        called = await self._client.call_tool(tool, payload)
                        if bool(getattr(called, "is_error", False)):
                            raise ValueError(self._error_text(called))
                        structured = getattr(called, "structured_content", None)
                        result = structured if isinstance(structured, dict) else {"content": self._error_text(called)}
                    elif operation == "close":
                        await self._close_unlocked()
                        future.set_result(None)
                        return
                    else:
                        raise RuntimeError(f"未知 Worker 操作：{operation}")
                except BaseException as error:
                    self.last_error = str(error)
                    if not future.done():
                        future.set_exception(error)
                else:
                    if not future.done():
                        future.set_result(result)
        finally:
            await self._close_unlocked()

    async def _submit(self, operation: str, arguments=None):
        async with self._actor_guard:
            if self._actor is None or self._actor.done():
                self._queue = asyncio.Queue()
                self._actor = asyncio.create_task(self._run(self._queue))
            queue = self._queue
            actor = self._actor
        assert queue is not None and actor is not None
        future = asyncio.get_running_loop().create_future()
        await queue.put((operation, arguments, future))
        try:
            return await future
        finally:
            if operation == "close":
                with contextlib.suppress(BaseException):
                    await actor
                async with self._actor_guard:
                    if self._actor is actor:
                        self._actor = None
                        self._queue = None

    async def start(self) -> None:
        await self._submit("start")

    async def close(self) -> None:
        if self._actor is not None and not self._actor.done():
            await self._submit("close")

    @staticmethod
    def _error_text(result: Any) -> str:
        parts = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", "")
            if text:
                parts.append(str(text))
        return "\n".join(parts) or "项目 worker 调用失败"

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._submit("call", (tool, arguments or {}))


class WorkerPool:
    def __init__(self):
        self._workers: dict[str, WorkerSession] = {}
        self._guard = asyncio.Lock()

    @staticmethod
    def _same_target(left: WorkspaceRegistration, right: WorkspaceRegistration) -> bool:
        return (
            left.project,
            left.repository_root,
            left.content_root,
            left.framework_root,
        ) == (
            right.project,
            right.repository_root,
            right.content_root,
            right.framework_root,
        )

    async def register(
        self,
        record: WorkspaceRegistration,
        *,
        projects: list[str] | None = None,
        warm: bool = True,
    ) -> dict[str, Any]:
        available = list(projects if projects is not None else [record.project])
        async with self._guard:
            current = self._workers.get(record.workspace_id)
            if (
                current
                and self._same_target(current.registration, record)
                and current.projects == tuple(available)
            ):
                worker = current
            else:
                if current:
                    await current.close()
                worker = WorkerSession(record, available)
                self._workers[record.workspace_id] = worker
            await worker.start()
        return await worker.call("rag_status", {}) if warm else {"connected": True}

    async def call(self, record: WorkspaceRegistration, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        worker = self._workers.get(record.workspace_id)
        if worker is None or not self._same_target(worker.registration, record):
            await self.register(record, warm=False)
            worker = self._workers[record.workspace_id]
        try:
            return await worker.call(tool, arguments)
        except (BrokenPipeError, ConnectionError, EOFError):
            await worker.close()
            return await worker.call(tool, arguments)

    def connected(self, workspace_id: str) -> bool:
        worker = self._workers.get(workspace_id)
        return bool(worker and worker.connected)

    def status(self, workspace_id: str) -> dict[str, Any]:
        worker = self._workers.get(workspace_id)
        if worker is None:
            return {"connected": False, "startedAt": 0, "lastError": "", "projects": []}
        return {
            "connected": worker.connected,
            "startedAt": worker.started_at,
            "lastError": worker.last_error,
            "projects": list(worker.projects),
            "tools": sorted(worker.tools),
        }

    async def unregister(self, workspace_id: str) -> None:
        async with self._guard:
            worker = self._workers.pop(workspace_id, None)
        if worker:
            await worker.close()

    async def close(self) -> None:
        async with self._guard:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            await worker.close()
