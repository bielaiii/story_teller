from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from storyteller import API_VERSION, SCHEMA_VERSION
from storyteller.api.models import (
    CharacterCreate,
    CharacterPatch,
    ChaptersUpdate,
    EntryCreate,
    EntryPatch,
    FragmentCreate,
    FragmentPatch,
    GraphUpdate,
    MutationRequest,
    PlotCreate,
    PlotPatch,
    PlotOrderUpdate,
    RelationshipCreate,
    RelationshipPatch,
    StoryStructureUpdate,
    TimelineUpdate,
    UndoRequest,
    mutation_payload,
)
from storyteller.domain.content import ContentService
from storyteller.domain.errors import ConflictError, DomainError, NotFoundError
from storyteller.domain.services import EntityService
from storyteller.domain.structure import StructureService
from storyteller.domain.uow import UnitOfWork
from storyteller.exports import ExportCoordinator
from storyteller.settings import Settings
from storyteller.storage.connection import Database
from storyteller.storage.repositories import ProjectRepository


FEATURES = [
    "snapshot-v1", "delta-v1", "entity-detail-v1", "history-v2", "trash-v2",
    "soft-delete-v1", "row-undo-v1", "static-snapshot-v1", "content-mutations-v1",
    "story-structure-v1", "graph-layout-v1",
]


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Story Teller", version="1.0.0")
    app.state.settings = settings
    app.state.mutation_token = secrets.token_urlsafe(32)

    def database_for(project: str) -> Database:
        try:
            root = settings.project_root(project)
            database = Database(root)
            database.require_v3()
            return database
        except (ValueError, RuntimeError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    def require_write_token(x_story_teller_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_story_teller_token, app.state.mutation_token):
            raise HTTPException(status_code=403, detail="写入授权已失效，请刷新本地服务能力")

    def finish_mutation(database: Database, project: str, result) -> dict:
        response = ProjectRepository(database, project).mutation_delta(result)
        if result.operation_id is None:
            response["export"] = {
                "status": "ready", "revision": result.project_revision, "skipped": True,
            }
            response["warnings"] = []
            return response
        try:
            export = ExportCoordinator(database, project).export()
            response["export"] = export
            response["warnings"] = []
        except (OSError, ValueError, RuntimeError) as error:
            response["export"] = {"status": "failed"}
            response["warnings"] = [f"数据已经保存，但文本导出待修复：{error}"]
        return response

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_request: Request, error: NotFoundError):
        return JSONResponse(status_code=404, content={"ok": False, "error": str(error), "code": "not_found"})

    @app.exception_handler(ConflictError)
    async def conflict_handler(_request: Request, error: ConflictError):
        return JSONResponse(status_code=409, content={"ok": False, "error": str(error), "code": "conflict"})

    @app.exception_handler(DomainError)
    async def domain_handler(_request: Request, error: DomainError):
        return JSONResponse(status_code=422, content={"ok": False, "error": str(error), "code": "validation"})

    @app.get("/api/v1/meta")
    def meta(project: str = Query(default="")):
        project_id = project or settings.default_project
        writable = False
        project_revision = None
        error = ""
        if project_id:
            try:
                database = database_for(project_id)
                with database.read() as connection:
                    row = connection.execute("SELECT revision FROM projects WHERE id=?", (project_id,)).fetchone()
                    project_revision = int(row[0]) if row else None
                    writable = row is not None
            except HTTPException as caught:
                error = str(caught.detail)
        return {
            "apiVersion": API_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "writable": writable,
            "project": project_id,
            "projectRevision": project_revision,
            "features": FEATURES,
            "mutationToken": app.state.mutation_token if writable else "",
            "error": error,
            "routes": {
                "snapshot": True, "changes": True, "entityDetail": True,
                "deleteEntity": True, "restoreEntity": True, "trash": True,
                "operations": True, "undo": True, "characters": True,
                "plots": True, "entries": True, "fragments": True, "relationships": True,
                "chapters": True, "timeline": True, "graph": True, "plotOrder": True,
                "storyStructure": True,
            },
        }

    @app.get("/api/v1/projects/{project}/snapshot")
    def project_snapshot(project: str):
        return ProjectRepository(database_for(project), project).snapshot()

    @app.get("/api/v1/projects/{project}/changes")
    def project_changes(project: str, since: int = Query(ge=0)):
        return ProjectRepository(database_for(project), project).changes_since(since)

    @app.get("/api/v1/projects/{project}/entities/{entity_id:path}")
    def entity_detail(project: str, entity_id: str):
        detail = ProjectRepository(database_for(project), project).entity_detail(entity_id)
        if not detail:
            raise HTTPException(status_code=404, detail="内容不存在")
        return detail

    @app.delete("/api/v1/projects/{project}/entities/{entity_id:path}", dependencies=[Depends(require_write_token)])
    def delete_entity(project: str, entity_id: str, payload: MutationRequest):
        database = database_for(project)
        result = EntityService(database, project).delete(entity_id, payload.base_revision)
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/entities/{entity_id:path}/restore", dependencies=[Depends(require_write_token)])
    def restore_entity(project: str, entity_id: str, payload: MutationRequest):
        database = database_for(project)
        result = EntityService(database, project).restore(entity_id, payload.base_revision)
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/characters", dependencies=[Depends(require_write_token)])
    def create_character(project: str, payload: CharacterCreate):
        database = database_for(project)
        result = ContentService(database, project).create_character(payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.patch("/api/v1/projects/{project}/characters/{entity_id:path}", dependencies=[Depends(require_write_token)])
    def update_character(project: str, entity_id: str, payload: CharacterPatch):
        database = database_for(project)
        result = ContentService(database, project).update_character(entity_id, payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/plots", dependencies=[Depends(require_write_token)])
    def create_plot(project: str, payload: PlotCreate):
        database = database_for(project)
        result = ContentService(database, project).create_plot(payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.patch("/api/v1/projects/{project}/plots/{entity_id:path}", dependencies=[Depends(require_write_token)])
    def update_plot(project: str, entity_id: str, payload: PlotPatch):
        database = database_for(project)
        result = ContentService(database, project).update_plot(entity_id, payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/entries", dependencies=[Depends(require_write_token)])
    def create_entry(project: str, payload: EntryCreate):
        database = database_for(project)
        result = ContentService(database, project).create_entry(payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.patch("/api/v1/projects/{project}/entries/{entity_id:path}", dependencies=[Depends(require_write_token)])
    def update_entry(project: str, entity_id: str, payload: EntryPatch):
        database = database_for(project)
        result = ContentService(database, project).update_entry(entity_id, payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/fragments", dependencies=[Depends(require_write_token)])
    def create_fragment(project: str, payload: FragmentCreate):
        database = database_for(project)
        result = ContentService(database, project).create_fragment(payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.patch("/api/v1/projects/{project}/fragments/{entity_id:path}", dependencies=[Depends(require_write_token)])
    def update_fragment(project: str, entity_id: str, payload: FragmentPatch):
        database = database_for(project)
        result = ContentService(database, project).update_fragment(entity_id, payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/relationships", dependencies=[Depends(require_write_token)])
    def create_relationship(project: str, payload: RelationshipCreate):
        database = database_for(project)
        result = ContentService(database, project).create_relationship(payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.patch("/api/v1/projects/{project}/relationships/{entity_id:path}", dependencies=[Depends(require_write_token)])
    def update_relationship(project: str, entity_id: str, payload: RelationshipPatch):
        database = database_for(project)
        result = ContentService(database, project).update_relationship(entity_id, payload.base_revision, mutation_payload(payload))
        return finish_mutation(database, project, result)

    @app.put("/api/v1/projects/{project}/chapters", dependencies=[Depends(require_write_token)])
    def update_chapters(project: str, payload: ChaptersUpdate):
        database = database_for(project)
        records = [item.model_dump() for item in payload.chapters]
        result = StructureService(database, project).update_chapters(payload.base_revision, records)
        return finish_mutation(database, project, result)

    @app.put("/api/v1/projects/{project}/plots/order", dependencies=[Depends(require_write_token)])
    def reorder_plots(project: str, payload: PlotOrderUpdate):
        database = database_for(project)
        result = StructureService(database, project).reorder_plots(payload.base_revision, payload.plot_ids)
        return finish_mutation(database, project, result)

    @app.put("/api/v1/projects/{project}/story-structure", dependencies=[Depends(require_write_token)])
    def update_story_structure(project: str, payload: StoryStructureUpdate):
        database = database_for(project)
        result = StructureService(database, project).update_story_structure(
            payload.base_revision,
            [item.model_dump() for item in payload.chapters],
            [item.model_dump() for item in payload.plots],
        )
        return finish_mutation(database, project, result)

    @app.put("/api/v1/projects/{project}/timeline", dependencies=[Depends(require_write_token)])
    def update_timeline(project: str, payload: TimelineUpdate):
        database = database_for(project)
        result = StructureService(database, project).update_timeline(
            payload.base_revision, mutation_payload(payload)
        )
        return finish_mutation(database, project, result)

    @app.put("/api/v1/projects/{project}/graph", dependencies=[Depends(require_write_token)])
    def update_graph(project: str, payload: GraphUpdate):
        database = database_for(project)
        result = StructureService(database, project).update_graph(
            payload.base_revision, mutation_payload(payload)
        )
        return finish_mutation(database, project, result)

    @app.get("/api/v1/projects/{project}/trash")
    def trash(project: str, limit: int = Query(default=100, ge=1, le=300)):
        repository = ProjectRepository(database_for(project), project)
        return {"items": repository.trash(limit)}

    @app.get("/api/v1/projects/{project}/trash/{entity_id:path}")
    def trash_detail(project: str, entity_id: str):
        detail = ProjectRepository(database_for(project), project).entity_detail(entity_id, include_deleted=True)
        if not detail or detail["deletedAt"] is None:
            raise HTTPException(status_code=404, detail="回收站中没有这项内容")
        return detail

    @app.get("/api/v1/projects/{project}/operations")
    def operations(project: str, limit: int = Query(default=100, ge=1, le=300)):
        repository = ProjectRepository(database_for(project), project)
        return {"items": repository.operations(limit)}

    @app.post("/api/v1/projects/{project}/operations/undo", dependencies=[Depends(require_write_token)])
    def undo(project: str, payload: UndoRequest):
        database = database_for(project)
        result = UnitOfWork(database, project).undo(payload.operation_id, payload.base_revision)
        return finish_mutation(database, project, result)

    @app.post("/api/v1/projects/{project}/exports", dependencies=[Depends(require_write_token)])
    def export_project(project: str):
        return ExportCoordinator(database_for(project), project).export()

    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "apiVersion": API_VERSION, "schemaVersion": SCHEMA_VERSION}

    if settings.frontend_root.is_dir():
        assets = settings.frontend_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            candidate = (settings.frontend_root / path).resolve()
            if settings.frontend_root in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(settings.frontend_root / "index.html")

    return app
