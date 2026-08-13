from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from storyteller.rag.hub_mcp import create_hub_mcp_server
from storyteller.rag.hub_registry import HUB_PROTOCOL_VERSION, HubRegistry
from storyteller.rag.hub_runtime import HubRuntime, WEB_LEASE_TTL
from storyteller.rag.hub_workers import WorkerPool


HUB_SERVICE = "story-world-hub"


class WorkspaceRegistrationRequest(BaseModel):
    repository_root: str = Field(alias="repositoryRoot")
    content_root: str = Field(alias="contentRoot")
    framework_root: str = Field(alias="frameworkRoot")
    project: str
    display_name: str = Field(default="", alias="displayName")


class IndependentMcpRequest(BaseModel):
    enabled: bool


class ProjectStateRequest(BaseModel):
    enabled: bool


class ProjectCreateRequest(BaseModel):
    project: str
    title: str = ""


def create_hub_app(registry_path: Path, token: str, *, host: str = "127.0.0.1") -> FastAPI:
    registry = HubRegistry(registry_path)
    registry.prune()
    workers = WorkerPool()
    runtime = HubRuntime(registry, workers, registry_path.parent)
    mcp_server = create_hub_mcp_server(
        registry,
        workers,
        runtime.active_records,
        runtime.available_projects,
        runtime.default_project,
        runtime.resolve_project,
    )
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        host=host,
    )
    instance_id = secrets.token_hex(12)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        await runtime.start()
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            await runtime.close()

    app = FastAPI(title="Story World Hub", version="1.0.0", lifespan=lifespan)
    app.state.registry = registry
    app.state.workers = workers
    app.state.runtime = runtime
    app.state.mcp_server = mcp_server
    app.state.instance_id = instance_id

    def require_token(x_story_world_hub_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_story_world_hub_token, token):
            raise HTTPException(status_code=403, detail="Hub 注册授权无效")

    @app.get("/api/v1/hub/health")
    def health():
        return {
            "ok": True,
            "service": HUB_SERVICE,
            "protocolVersion": HUB_PROTOCOL_VERSION,
            "instanceId": instance_id,
            "processId": os.getpid(),
            "transport": "streamable-http",
            "mcp": "/mcp/",
        }

    @app.get("/api/v1/hub/workspaces")
    def workspaces():
        return {
            "workspaces": [runtime.snapshot(record) for record in registry.records()]
        }

    @app.post("/api/v1/hub/workspaces")
    async def register(
        payload: WorkspaceRegistrationRequest,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            record = registry.prepare(payload.model_dump(by_alias=True))
            registry.upsert(record)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "ok": True,
            "workspace": runtime.snapshot(record),
        }

    @app.post("/api/v1/hub/workspaces/{workspace_id}/web-leases")
    async def acquire_web_lease(
        workspace_id: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            record = registry.resolve(workspace_id)
            lease, snapshot = await runtime.acquire_web(record)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "lease": lease, "ttlSeconds": WEB_LEASE_TTL, "workspace": snapshot}

    @app.put("/api/v1/hub/workspaces/{workspace_id}/web-leases/{lease}")
    async def heartbeat_web_lease(
        workspace_id: str,
        lease: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            snapshot = await runtime.heartbeat(workspace_id, lease)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": snapshot}

    @app.delete("/api/v1/hub/workspaces/{workspace_id}/web-leases/{lease}")
    async def release_web_lease(
        workspace_id: str,
        lease: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            await runtime.release_web(workspace_id, lease)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"ok": True}

    @app.put("/api/v1/hub/workspaces/{workspace_id}/mcp-independent")
    async def set_independent_mcp(
        workspace_id: str,
        payload: IndependentMcpRequest,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            snapshot = await runtime.set_independent(workspace_id, payload.enabled)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": snapshot}

    @app.post("/api/v1/hub/workspaces/{workspace_id}/actions/{action}")
    async def content_action(
        workspace_id: str,
        action: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            if action == "restart-content":
                snapshot = await runtime.restart_content(workspace_id)
            elif action == "start-content":
                snapshot = await runtime.start_content(workspace_id)
            elif action == "stop-content":
                snapshot = await runtime.stop_content(workspace_id)
            elif action == "force-stop-content":
                snapshot = await runtime.stop_content(workspace_id, force=True)
            elif action == "restart-mcp":
                snapshot = await runtime.restart_mcp(workspace_id)
            elif action == "scan-projects":
                snapshot = await runtime.scan_projects(workspace_id)
            else:
                raise ValueError(f"不支持的管理操作：{action}")
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": snapshot}

    @app.delete("/api/v1/hub/workspaces/{workspace_id}")
    async def remove_workspace(
        workspace_id: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            removed = await runtime.remove_content(workspace_id)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": removed}

    @app.post("/api/v1/hub/workspaces/{workspace_id}/projects")
    async def create_project(
        workspace_id: str,
        payload: ProjectCreateRequest,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            snapshot = await runtime.create_project(workspace_id, payload.project, payload.title)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": snapshot}

    @app.put("/api/v1/hub/workspaces/{workspace_id}/projects/{project}")
    async def set_project_state(
        workspace_id: str,
        project: str,
        payload: ProjectStateRequest,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            snapshot = await runtime.set_project_enabled(workspace_id, project, payload.enabled)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": snapshot}

    @app.post("/api/v1/hub/workspaces/{workspace_id}/projects/{project}/reload")
    async def reload_project(
        workspace_id: str,
        project: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            snapshot = await runtime.reload_project(workspace_id, project)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"ok": True, "workspace": snapshot}

    @app.get("/api/v1/hub/workspaces/{workspace_id}/web-target")
    def web_target(
        workspace_id: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            record = registry.resolve(workspace_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        target = runtime.web_target(record.workspace_id)
        if not target:
            raise HTTPException(status_code=409, detail="Content Web 当前没有运行")
        return {
            "workspaceId": record.workspace_id,
            "target": target,
            "projects": runtime.available_projects(record),
            "disabledProjects": list(record.disabled_projects),
        }

    @app.get("/api/v1/hub/workspaces/{workspace_id}/diagnostics")
    def diagnostics(
        workspace_id: str,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            record = registry.resolve(workspace_id)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"ok": True, "workspace": runtime.snapshot(record)}

    @app.get("/api/v1/hub/workspaces/{workspace_id}/logs")
    def workspace_logs(
        workspace_id: str,
        lines: int = 120,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            value = runtime.log_tail(workspace_id, lines=lines)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"ok": True, "log": value}

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=False)
    async def mcp_mount_redirect():
        return RedirectResponse(url="/mcp/", status_code=307)

    app.mount("/mcp", mcp_app, name="mcp")
    return app
