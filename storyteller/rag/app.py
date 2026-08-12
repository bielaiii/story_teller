from __future__ import annotations

import asyncio
import contextlib
import secrets

from fastapi import FastAPI, Query
from fastapi.responses import RedirectResponse

from storyteller import API_VERSION, SCHEMA_VERSION
from storyteller.rag.http import create_rag_router
from storyteller.rag.manager import RagManager
from storyteller.rag.mcp import create_mcp_server
from storyteller.settings import Settings


RAG_FEATURES = [
    "rag-http-v1",
    "rag-mcp-v1",
    "rag-startup-warmup-v1",
    "rag-embedding-model-switch-v1",
    "world-schema-registry-v1",
    "structured-world-reader-v1",
    "rag-request-revision-sync-v1",
    "confirmed-fragments-search-v1",
    "rag-stdio-autodiscovery-v1",
]


def create_rag_app(settings: Settings) -> FastAPI:
    manager = RagManager(settings)
    mcp_server = create_mcp_server(manager, settings)
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        host=settings.host,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        await asyncio.to_thread(manager.startup)
        async with mcp_server.session_manager.run():
            yield

    app = FastAPI(title="Story Teller RAG", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.mutation_token = secrets.token_urlsafe(32)
    app.state.rag_manager = manager
    app.state.mcp_server = mcp_server

    @app.get("/api/v1/meta")
    def meta(project: str = Query(default="")):
        project_id = project or settings.default_project
        status = None
        error = ""
        if project_id:
            try:
                status = manager.status(project_id)
            except (ValueError, OSError, RuntimeError) as caught:
                error = str(caught)
        return {
            "service": "story-teller-rag",
            "apiVersion": API_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "project": project_id,
            "features": RAG_FEATURES,
            "syncMode": "background-incremental-with-request-fallback",
            "status": status,
            "mutationToken": app.state.mutation_token,
            "error": error,
        }

    @app.get("/api/v1/health")
    def health():
        return {
            "ok": True,
            "service": "story-teller-rag",
            "syncMode": "background-incremental-with-request-fallback",
        }

    app.include_router(create_rag_router(manager))

    @app.api_route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"], include_in_schema=False)
    async def mcp_mount_redirect():
        return RedirectResponse(url="/mcp/", status_code=307)

    app.mount("/mcp", mcp_app, name="mcp")
    return app
