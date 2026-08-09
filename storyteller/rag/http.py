from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from storyteller.rag.manager import RagManager


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=50)
    kinds: list[str] = Field(default_factory=list)
    include_fragments: bool = False


class RagContextRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=10, ge=1, le=50)
    max_chars: int = Field(default=12000, ge=1000, le=50000)
    include_fragments: bool = False


class EmbeddingConfigRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str = "builtin"
    model: str = "hash-char-2-3-v1"
    dimensions: int = Field(default=384, ge=32, le=8192)
    base_url: str = Field(default="http://127.0.0.1:11434/v1", alias="baseUrl")
    api_key_env: str = Field(default="OPENAI_API_KEY", alias="apiKeyEnv")
    batch_size: int = Field(default=32, ge=1, le=256, alias="batchSize")


def create_rag_router(manager: RagManager) -> APIRouter:
    router = APIRouter(prefix="/api/v1/projects/{project}/rag", tags=["rag"])

    def require_token(request: Request, x_story_teller_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_story_teller_token, request.app.state.mutation_token):
            raise HTTPException(status_code=403, detail="写入授权已失效，请刷新本地服务能力")

    @router.get("/status")
    def status(project: str):
        try:
            manager.ensure_fresh(project)
            return manager.status(project)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/catalog")
    def world_catalog(project: str):
        try:
            return manager.catalog(project)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/search")
    def search(
        project: str,
        q: str = Query(min_length=1, max_length=2000),
        limit: int = Query(default=8, ge=1, le=50),
        kinds: list[str] = Query(default=[]),
        include_fragments: bool = Query(default=False),
    ):
        try:
            return manager.search(project, q, limit=limit, kinds=kinds or None, include_fragments=include_fragments)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/search")
    def search_post(project: str, payload: RagSearchRequest):
        try:
            return manager.search(
                project, payload.query, limit=payload.limit,
                kinds=payload.kinds or None, include_fragments=payload.include_fragments,
            )
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.post("/context")
    def context(project: str, payload: RagContextRequest):
        try:
            return manager.context(
                project, payload.question, limit=payload.limit,
                max_chars=payload.max_chars, include_fragments=payload.include_fragments,
            )
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @router.get("/entities/{entity_id:path}")
    def entity(project: str, entity_id: str):
        try:
            result = manager.entity(project, entity_id)
        except (ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        if not result:
            raise HTTPException(status_code=404, detail="RAG 中没有这项内容")
        return result

    @router.get("/config")
    def config(project: str):
        return manager.status(project)["embedding"]

    @router.put("/config", dependencies=[Depends(require_token)])
    def configure(project: str, payload: EmbeddingConfigRequest):
        try:
            value: dict[str, Any] = {
                "provider": payload.provider, "model": payload.model,
                "dimensions": payload.dimensions, "baseUrl": payload.base_url,
                "apiKeyEnv": payload.api_key_env, "batchSize": payload.batch_size,
            }
            return manager.configure(project, value)
        except (ValueError, OSError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/rebuild", dependencies=[Depends(require_token)])
    def rebuild(project: str):
        try:
            return manager.rebuild(project)
        except (ValueError, OSError, RuntimeError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return router
