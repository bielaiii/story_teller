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
from storyteller.rag.hub_workers import WorkerPool


HUB_SERVICE = "story-world-hub"


class WorkspaceRegistrationRequest(BaseModel):
    repository_root: str = Field(alias="repositoryRoot")
    content_root: str = Field(alias="contentRoot")
    framework_root: str = Field(alias="frameworkRoot")
    project: str
    display_name: str = Field(default="", alias="displayName")


def create_hub_app(registry_path: Path, token: str, *, host: str = "127.0.0.1") -> FastAPI:
    registry = HubRegistry(registry_path)
    registry.prune()
    workers = WorkerPool()
    mcp_server = create_hub_mcp_server(registry, workers)
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        host=host,
    )
    instance_id = secrets.token_hex(12)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        for record in registry.records():
            try:
                await workers.register(record, warm=False)
            except Exception:
                # A repository may be temporarily unavailable; the next request retries it.
                continue
        try:
            async with mcp_server.session_manager.run():
                yield
        finally:
            await workers.close()

    app = FastAPI(title="Story World Hub", version="1.0.0", lifespan=lifespan)
    app.state.registry = registry
    app.state.workers = workers
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
            "workspaces": [
                {**registry.public_dict(record), "connected": workers.connected(record.workspace_id)}
                for record in registry.records()
            ]
        }

    @app.post("/api/v1/hub/workspaces")
    async def register(
        payload: WorkspaceRegistrationRequest,
        x_story_world_hub_token: str = Header(default=""),
    ):
        require_token(x_story_world_hub_token)
        try:
            record = registry.prepare(payload.model_dump(by_alias=True))
            status = await workers.register(record, warm=True)
            registry.upsert(record)
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "ok": True,
            "workspace": registry.public_dict(record),
            "worker": {
                "connected": workers.connected(record.workspace_id),
                "sourceRevision": status.get("sourceRevision"),
                "documents": status.get("documents"),
                "chunks": status.get("chunks"),
                "syncMode": status.get("syncMode"),
            },
        }

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=False)
    async def mcp_mount_redirect():
        return RedirectResponse(url="/mcp/", status_code=307)

    app.mount("/mcp", mcp_app, name="mcp")
    return app
