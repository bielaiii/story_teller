from __future__ import annotations

import asyncio
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
    def __init__(self, registration: WorkspaceRegistration):
        self.registration = registration
        self._lock = asyncio.Lock()
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self.tools: set[str] = set()

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
                "--default-project", self.registration.project,
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
            await stack.aclose()
            raise
        self._stack = stack
        self._client = client
        self.tools = tools

    async def start(self) -> None:
        async with self._lock:
            await self._start_unlocked()

    async def close(self) -> None:
        async with self._lock:
            stack, self._stack = self._stack, None
            self._client = None
            self.tools = set()
            if stack is not None:
                await stack.aclose()

    @staticmethod
    def _error_text(result: Any) -> str:
        parts = []
        for item in getattr(result, "content", []) or []:
            text = getattr(item, "text", "")
            if text:
                parts.append(str(text))
        return "\n".join(parts) or "项目 worker 调用失败"

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self._lock:
            await self._start_unlocked()
            assert self._client is not None
            result = await self._client.call_tool(tool, arguments or {})
            if bool(getattr(result, "is_error", False)):
                raise ValueError(self._error_text(result))
            structured = getattr(result, "structured_content", None)
            if isinstance(structured, dict):
                return structured
            return {"content": self._error_text(result)}


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

    async def register(self, record: WorkspaceRegistration, *, warm: bool = True) -> dict[str, Any]:
        async with self._guard:
            current = self._workers.get(record.workspace_id)
            if current and self._same_target(current.registration, record):
                worker = current
            else:
                if current:
                    await current.close()
                worker = WorkerSession(record)
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
