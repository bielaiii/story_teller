from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import signal
import socket
import time
from pathlib import Path
from typing import Any

import httpx

from storyteller.rag.hub_registry import HubRegistry, WorkspaceRegistration
from storyteller.rag.hub_workers import WorkerPool


WEB_LEASE_TTL = 15.0


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except OSError:
        return False
    return True


def _parent_process_id(process_id: int) -> int:
    try:
        # The command name may contain spaces inside parentheses; fields after it are stable.
        suffix = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1]
        return int(suffix.split()[1])
    except (OSError, ValueError, IndexError):
        return 0


class WebWorkerSession:
    def __init__(self, registration: WorkspaceRegistration, state_dir: Path):
        self.registration = registration
        self.state_dir = state_dir
        self.port = 0
        self.process: asyncio.subprocess.Process | None = None
        self.projects: tuple[str, ...] = ()
        self._log_stream = None
        self.started_at = 0
        self.last_error = ""
        self.log_path = self.state_dir / "web" / f"{self.registration.workspace_id}.log"
        self.pid_path = self.state_dir / "web" / f"{self.registration.workspace_id}.pid.json"

    @property
    def running(self) -> bool:
        return bool(self.process and self.process.returncode is None and self.port)

    @property
    def target_url(self) -> str:
        return f"http://127.0.0.1:{self.port}" if self.running else ""

    @property
    def process_id(self) -> int:
        return int(self.process.pid) if self.process and self.process.returncode is None else 0

    async def start(self, default_project: str, projects: list[str]) -> None:
        if self.running:
            return
        self.projects = tuple(projects)
        framework = Path(self.registration.framework_root)
        launcher = framework / "scripts" / "python.sh"
        if not launcher.is_file():
            raise RuntimeError(f"找不到 Web Worker 启动器：{launcher}")
        self.port = _free_loopback_port()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_stream = self.log_path.open("ab", buffering=0)
        self.process = await asyncio.create_subprocess_exec(
            str(launcher), "-m", "storyteller",
            "--bind", "127.0.0.1",
            "--port", str(self.port),
            "--content-root", self.registration.content_root,
            "--frontend-root", str(framework / "dist"),
            "--default-project", default_project,
            "--projects", ",".join(projects),
            "--parent-pid", str(os.getpid()),
            cwd=framework,
            stdout=self._log_stream,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self.started_at = int(time.time())
        self.last_error = ""
        self.pid_path.write_text(json.dumps({
            "processId": self.process.pid,
            "parentProcessId": os.getpid(),
            "contentRoot": self.registration.content_root,
            "workspaceId": self.registration.workspace_id,
            "startedAt": self.started_at,
        }, ensure_ascii=False) + "\n", encoding="utf-8")
        deadline = time.monotonic() + 20
        try:
            async with httpx.AsyncClient(timeout=0.5, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if self.process.returncode is not None:
                        self.last_error = f"Web Worker 启动失败，日志：{self.log_path}"
                        raise RuntimeError(self.last_error)
                    try:
                        response = await client.get(self.target_url + "/api/v1/health")
                        if response.status_code == 200 and response.json().get("ok") is True:
                            return
                    except (httpx.HTTPError, ValueError):
                        pass
                    await asyncio.sleep(0.1)
        except BaseException:
            await self.close(preserve_error=True)
            raise
        self.last_error = f"Web Worker 启动超时，日志：{self.log_path}"
        await self.close(preserve_error=True)
        raise RuntimeError(self.last_error)

    async def close(self, *, force: bool = False, preserve_error: bool = False) -> None:
        process, self.process = self.process, None
        self.port = 0
        self.projects = ()
        if process and process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3 if not force else 1)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        self.pid_path.unlink(missing_ok=True)
        if self._log_stream is not None:
            self._log_stream.close()
            self._log_stream = None
        if not preserve_error:
            self.last_error = ""


class HubRuntime:
    def __init__(self, registry: HubRegistry, workers: WorkerPool, state_dir: Path):
        self.registry = registry
        self.workers = workers
        self.state_dir = Path(state_dir).resolve()
        self._web_workers: dict[str, WebWorkerSession] = {}
        self._web_leases: dict[str, dict[str, float]] = {}
        self._web_last_heartbeat: dict[str, int] = {}
        self._project_statuses: dict[str, dict[str, dict[str, Any]]] = {}
        self._runtime_errors: dict[str, str] = {}
        self._guard = asyncio.Lock()
        self._sweeper: asyncio.Task | None = None
        self._restorers: set[asyncio.Task] = set()

    async def start(self) -> None:
        await self._cleanup_orphan_web_workers()
        self._sweeper = asyncio.create_task(self._sweep(), name="story-hub-lease-sweeper")
        for record in self.registry.records():
            if not (record.independent_mcp or record.managed_web):
                continue
            task = asyncio.create_task(
                self._restore_record(record),
                name=f"story-hub-restore-{record.workspace_id}",
            )
            self._restorers.add(task)
            task.add_done_callback(self._restorers.discard)

    async def _restore_record(self, record: WorkspaceRegistration) -> None:
        async with self._guard:
            try:
                await self._check_projects_unlocked(record)
                await self._reconcile_unlocked(record)
            except Exception as error:
                self._runtime_errors[record.workspace_id] = str(error)

    async def close(self) -> None:
        restorers = list(self._restorers)
        self._restorers.clear()
        for task in restorers:
            task.cancel()
        if restorers:
            await asyncio.gather(*restorers, return_exceptions=True)
        if self._sweeper:
            self._sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sweeper
            self._sweeper = None
        async with self._guard:
            web_workers = list(self._web_workers.values())
            self._web_workers.clear()
            self._web_leases.clear()
            self._web_last_heartbeat.clear()
        for worker in web_workers:
            await worker.close()
        await self.workers.close()

    async def _cleanup_orphan_web_workers(self) -> None:
        web_dir = self.state_dir / "web"
        if not web_dir.is_dir():
            return
        for path in web_dir.glob("*.pid.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                process_id = int(value.get("processId") or 0)
            except (OSError, ValueError, TypeError):
                path.unlink(missing_ok=True)
                continue
            if not _process_alive(process_id):
                path.unlink(missing_ok=True)
                continue
            parent_id = _parent_process_id(process_id)
            if parent_id and _process_alive(parent_id):
                # A live owner must never be terminated by a second state-dir user.
                continue
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process_id, signal.SIGTERM)
            deadline = time.monotonic() + 3
            while _process_alive(process_id) and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            if _process_alive(process_id):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process_id, signal.SIGKILL)
            path.unlink(missing_ok=True)

    def _has_web_lease(self, workspace_id: str) -> bool:
        now = time.monotonic()
        return any(expiry > now for expiry in self._web_leases.get(workspace_id, {}).values())

    def web_desired(self, record: WorkspaceRegistration) -> bool:
        return record.managed_web or self._has_web_lease(record.workspace_id)

    def mcp_desired(self, record: WorkspaceRegistration) -> bool:
        return record.independent_mcp or self.web_desired(record)

    def available_projects(self, record: WorkspaceRegistration) -> list[str]:
        statuses = self._project_statuses.get(record.workspace_id, {})
        return sorted(
            project for project in self.registry.projects(record)
            if statuses.get(project, {}).get("state") == "ready"
        )

    def active_records(self) -> list[WorkspaceRegistration]:
        return [
            record for record in self.registry.records()
            if self.mcp_desired(record) and self.available_projects(record)
        ]

    def default_project(self, record: WorkspaceRegistration) -> str:
        projects = self.available_projects(record)
        matches = [item for item in projects if item.casefold() == record.display_name.casefold()]
        if len(matches) == 1:
            return matches[0]
        if len(projects) == 1:
            return projects[0]
        return ""

    def resolve_project(self, record: WorkspaceRegistration, selector: str = "") -> str:
        projects = self.available_projects(record)
        clean = str(selector or "").strip()
        if clean:
            if clean in projects:
                return clean
            status = self._project_statuses.get(record.workspace_id, {}).get(clean, {})
            error = str(status.get("error") or "")
            raise ValueError(f"Project 当前不可用：{clean}{'；' + error if error else ''}")
        default = self.default_project(record)
        if default:
            return default
        raise ValueError(
            f"工作区 {record.display_name} 包含多个项目，请指定 project："
            f"{', '.join(projects) or '无'}"
        )

    @staticmethod
    def _same_web_target(left: WorkspaceRegistration, right: WorkspaceRegistration) -> bool:
        return (
            left.repository_root, left.content_root, left.framework_root,
        ) == (
            right.repository_root, right.content_root, right.framework_root,
        )

    async def _check_one_project(
        self, record: WorkspaceRegistration, project: str,
    ) -> tuple[str, dict[str, Any]]:
        checked_at = int(time.time())
        framework = Path(record.framework_root)
        launcher = framework / "scripts" / "python.sh"
        project_root = Path(record.content_root) / project
        log_dir = self.state_dir / "projects" / record.workspace_id
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{project}.log"
        try:
            process = await asyncio.create_subprocess_exec(
                str(launcher), "-m", "storyteller.bootstrap", str(project_root),
                cwd=framework,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output_bytes, _ = await process.communicate()
            except BaseException:
                if process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        process.terminate()
                    await process.wait()
                raise
            output = output_bytes.decode("utf-8", errors="replace")
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Project check\n")
                stream.write(output)
            if process.returncode != 0:
                detail = output.strip().splitlines()[-1] if output.strip() else "启动检查失败"
                raise RuntimeError(detail)
            lines = [line for line in output.splitlines() if line.strip()]
            result = json.loads(lines[-1]) if lines else {}
            return project, {
                "project": project,
                "state": "ready",
                "ready": True,
                "error": "",
                "checkedAt": checked_at,
                "schemaVersion": result.get("schemaVersion"),
                "migrated": bool(result.get("migrated")),
                "mergeRequired": bool(result.get("mergeRequired")),
                "logPath": str(log_path),
            }
        except Exception as error:
            return project, {
                "project": project,
                "state": "error",
                "ready": False,
                "error": str(error),
                "checkedAt": checked_at,
                "schemaVersion": None,
                "migrated": False,
                "mergeRequired": False,
                "logPath": str(log_path),
            }

    async def _check_projects_unlocked(
        self,
        record: WorkspaceRegistration,
        *,
        projects: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        all_projects = self.registry.all_projects(record)
        enabled = set(self.registry.projects(record))
        current = self._project_statuses.setdefault(record.workspace_id, {})
        for project in list(current):
            if project not in all_projects:
                current.pop(project, None)
        for project in all_projects:
            if project not in enabled:
                current[project] = {
                    "project": project, "state": "disabled", "ready": False,
                    "error": "", "checkedAt": int(time.time()), "schemaVersion": None,
                    "migrated": False, "mergeRequired": False, "logPath": "",
                }
        selected = [item for item in (projects or sorted(enabled)) if item in enabled]
        checked = await asyncio.gather(*(self._check_one_project(record, item) for item in selected))
        current.update(dict(checked))
        return current

    async def _ensure_projects_checked_unlocked(self, record: WorkspaceRegistration) -> None:
        statuses = self._project_statuses.get(record.workspace_id, {})
        enabled = set(self.registry.projects(record))
        if any(statuses.get(project, {}).get("state") not in {"ready", "error"} for project in enabled):
            await self._check_projects_unlocked(record)
        elif set(statuses) != set(self.registry.all_projects(record)):
            await self._check_projects_unlocked(record)

    async def _ensure_web_unlocked(self, record: WorkspaceRegistration) -> WebWorkerSession:
        worker = self._web_workers.get(record.workspace_id)
        if worker and not self._same_web_target(worker.registration, record):
            await worker.close()
            worker = None
        if worker is None:
            worker = WebWorkerSession(record, self.state_dir)
            self._web_workers[record.workspace_id] = worker
        projects = self.available_projects(record)
        if worker.running and worker.projects != tuple(projects):
            await worker.close()
        if not worker.running:
            if not projects:
                raise RuntimeError("Content 没有通过启动检查的 Project")
            default_project = self.default_project(record) or (
                record.project if record.project in projects else projects[0]
            )
            try:
                await worker.start(default_project, projects)
            except Exception as error:
                self._runtime_errors[record.workspace_id] = str(error)
                raise
        return worker

    async def _reconcile_unlocked(self, record: WorkspaceRegistration) -> None:
        await self._ensure_projects_checked_unlocked(record)
        web_desired = self.web_desired(record)
        if web_desired:
            await self._ensure_web_unlocked(record)
        else:
            web = self._web_workers.pop(record.workspace_id, None)
            if web:
                await web.close()
        projects = self.available_projects(record)
        if (record.independent_mcp or web_desired) and projects:
            await self.workers.register(record, projects=projects, warm=False)
        else:
            await self.workers.unregister(record.workspace_id)
        self._runtime_errors.pop(record.workspace_id, None)

    async def acquire_web(self, record: WorkspaceRegistration) -> tuple[str, dict[str, Any]]:
        token = secrets.token_urlsafe(24)
        async with self._guard:
            self._web_leases.setdefault(record.workspace_id, {})[token] = time.monotonic() + WEB_LEASE_TTL
            self._web_last_heartbeat[record.workspace_id] = int(time.time())
            try:
                await self._check_projects_unlocked(record)
                await self._reconcile_unlocked(record)
            except BaseException:
                self._web_leases.get(record.workspace_id, {}).pop(token, None)
                raise
            return token, self.snapshot(record)

    async def heartbeat(self, workspace_id: str, lease: str) -> dict[str, Any]:
        async with self._guard:
            leases = self._web_leases.get(workspace_id, {})
            if lease not in leases:
                raise ValueError("Web 租约不存在或已经停止")
            leases[lease] = time.monotonic() + WEB_LEASE_TTL
            self._web_last_heartbeat[workspace_id] = int(time.time())
            record = self.registry.resolve(workspace_id)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    async def release_web(self, workspace_id: str, lease: str) -> None:
        async with self._guard:
            leases = self._web_leases.get(workspace_id, {})
            leases.pop(lease, None)
            if not leases:
                self._web_leases.pop(workspace_id, None)
                if not self.registry.resolve(workspace_id).managed_web:
                    self._web_last_heartbeat.pop(workspace_id, None)
            record = self.registry.resolve(workspace_id)
            await self._reconcile_unlocked(record)

    async def start_content(self, workspace_id: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.set_managed_web(workspace_id, True)
            self._web_last_heartbeat[workspace_id] = int(time.time())
            try:
                await self._check_projects_unlocked(record)
                await self._reconcile_unlocked(record)
            except BaseException:
                self.registry.set_managed_web(workspace_id, False)
                raise
            return self.snapshot(record)

    async def set_independent(self, workspace_id: str, enabled: bool) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.set_independent_mcp(workspace_id, enabled)
            await self._check_projects_unlocked(record)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    async def restart_content(self, workspace_id: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.resolve(workspace_id)
            if not self.web_desired(record):
                raise ValueError("Content Web 当前没有运行")
            web = self._web_workers.pop(workspace_id, None)
            if web:
                await web.close()
            if not record.independent_mcp:
                await self.workers.unregister(workspace_id)
            await self._check_projects_unlocked(record)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    async def stop_content(self, workspace_id: str, *, force: bool = False) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.set_managed_web(workspace_id, False)
            self._web_leases.pop(workspace_id, None)
            self._web_last_heartbeat.pop(workspace_id, None)
            web = self._web_workers.pop(workspace_id, None)
            if web:
                await web.close(force=force)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    async def remove_content(self, workspace_id: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.resolve(workspace_id)
            self.registry.set_managed_web(workspace_id, False)
            self._web_leases.pop(workspace_id, None)
            self._web_last_heartbeat.pop(workspace_id, None)
            web = self._web_workers.pop(workspace_id, None)
            if web:
                await web.close()
            await self.workers.unregister(workspace_id)
            self.registry.remove(workspace_id)
            self._project_statuses.pop(workspace_id, None)
            self._runtime_errors.pop(workspace_id, None)
            return {"workspaceId": workspace_id, "displayName": record.display_name, "removed": True}

    async def restart_mcp(self, workspace_id: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.resolve(workspace_id)
            if not self.mcp_desired(record):
                raise ValueError("MCP 当前未启用")
            await self._check_projects_unlocked(record)
            projects = self.available_projects(record)
            if not projects:
                raise ValueError("没有可供 MCP 使用的 Project")
            await self.workers.unregister(workspace_id)
            await self.workers.register(record, projects=projects, warm=False)
            return self.snapshot(record)

    async def set_project_enabled(self, workspace_id: str, project: str, enabled: bool) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.set_project_enabled(workspace_id, project, enabled)
            if not self.registry.projects(record):
                self.registry.set_project_enabled(workspace_id, project, True)
                raise ValueError("至少需要保留一个启用的 Project")
            await self._check_projects_unlocked(record, projects=[project] if enabled else [])
            await self.workers.unregister(workspace_id)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    async def reload_project(self, workspace_id: str, project: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.resolve(workspace_id)
            if project not in self.registry.projects(record):
                raise ValueError(f"Project 未启用：{project}")
            await self._check_projects_unlocked(record, projects=[project])
            status = self._project_statuses[workspace_id][project]
            if status["state"] != "ready":
                raise ValueError(f"Project 检查失败：{status['error']}")
            await self.workers.unregister(workspace_id)
            await self._reconcile_unlocked(record)
            if self.mcp_desired(record):
                rag = await self.workers.call(record, "rag_status", {"project": project})
                status["rag"] = rag
            return self.snapshot(record)

    async def scan_projects(self, workspace_id: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.resolve(workspace_id)
            await self._check_projects_unlocked(record)
            await self.workers.unregister(workspace_id)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    async def create_project(self, workspace_id: str, project: str, title: str) -> dict[str, Any]:
        async with self._guard:
            record = self.registry.resolve(workspace_id)
            if not project or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in project):
                raise ValueError("Project ID 只能包含字母、数字、下划线和短横线")
            framework = Path(record.framework_root)
            launcher = framework / "scripts" / "python.sh"
            project_root = Path(record.content_root) / project
            process = await asyncio.create_subprocess_exec(
                str(launcher), "-m", "storyteller.bootstrap", str(project_root),
                "--create", "--title", str(title or project),
                cwd=framework,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            output_bytes, _ = await process.communicate()
            output = output_bytes.decode("utf-8", errors="replace").strip()
            if process.returncode != 0:
                raise ValueError(output.splitlines()[-1] if output else "Project 创建失败")
            await self._check_projects_unlocked(record, projects=[project])
            await self.workers.unregister(workspace_id)
            await self._reconcile_unlocked(record)
            return self.snapshot(record)

    def web_target(self, workspace_id: str) -> str:
        worker = self._web_workers.get(workspace_id)
        return worker.target_url if worker else ""

    def snapshot(self, record: WorkspaceRegistration) -> dict[str, Any]:
        worker = self._web_workers.get(record.workspace_id)
        projects = self.available_projects(record)
        statuses = self._project_statuses.get(record.workspace_id, {})
        return {
            **self.registry.public_dict(record),
            "projects": projects,
            "defaultProject": self.default_project(record),
            "requiresProjectSelection": not bool(self.default_project(record)) and len(projects) > 1,
            "projectStatuses": [statuses[item] for item in self.registry.all_projects(record) if item in statuses],
            "web": {
                "running": bool(self.web_target(record.workspace_id)),
                "desired": self.web_desired(record),
                "mode": "managed" if record.managed_web else ("attached" if self._has_web_lease(record.workspace_id) else "stopped"),
                "leaseCount": len(self._web_leases.get(record.workspace_id, {})),
                "lastHeartbeatAt": self._web_last_heartbeat.get(record.workspace_id, 0),
                "processId": worker.process_id if worker else 0,
                "startedAt": worker.started_at if worker else 0,
                "lastError": (worker.last_error if worker else "") or self._runtime_errors.get(record.workspace_id, ""),
                "logPath": str(worker.log_path) if worker else str(self.state_dir / "web" / f"{record.workspace_id}.log"),
            },
            "mcp": {
                "running": self.workers.connected(record.workspace_id),
                "mode": "independent" if record.independent_mcp else "follow-web",
                "desired": self.mcp_desired(record),
                "status": self.workers.status(record.workspace_id),
            },
        }

    def log_tail(self, workspace_id: str, *, lines: int = 120) -> str:
        record = self.registry.resolve(workspace_id)
        path = self.state_dir / "web" / f"{record.workspace_id}.log"
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "\n".join(content[-max(1, min(int(lines), 500)):])

    async def _sweep(self) -> None:
        while True:
            await asyncio.sleep(2)
            async with self._guard:
                invalid = [
                    record for record in self.registry.records(valid_only=False)
                    if not self.registry.is_valid(record)
                ]
                for record in invalid:
                    self._web_leases.pop(record.workspace_id, None)
                    web = self._web_workers.pop(record.workspace_id, None)
                    if web:
                        await web.close()
                    await self.workers.unregister(record.workspace_id)
                    self._project_statuses.pop(record.workspace_id, None)
                    self._runtime_errors.pop(record.workspace_id, None)
                    self.registry.remove(record.workspace_id)
                now = time.monotonic()
                changed: list[str] = []
                for workspace_id, leases in list(self._web_leases.items()):
                    expired = [token for token, expiry in leases.items() if expiry <= now]
                    for token in expired:
                        leases.pop(token, None)
                    if expired:
                        changed.append(workspace_id)
                    if not leases:
                        self._web_leases.pop(workspace_id, None)
                for workspace_id in changed:
                    with contextlib.suppress(ValueError, RuntimeError):
                        await self._reconcile_unlocked(self.registry.resolve(workspace_id))
