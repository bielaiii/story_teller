from __future__ import annotations

from contextlib import asynccontextmanager
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from storyteller import API_VERSION, SCHEMA_VERSION
from storyteller.application import ApplicationContext, StoryApplication
from storyteller.application.errors import ProjectAccessError
from storyteller.hub_contract import (
    WORKER_CAPABILITIES,
    WORKER_PROTOCOL_MAJOR,
    WORKER_PROTOCOL_MINOR,
)
from storyteller.api.models import (
    CharacterCreate,
    CharacterPatch,
    ChaptersUpdate,
    EntryCreate,
    EntryPatch,
    FragmentClipboardImport,
    FragmentCreate,
    FragmentPatch,
    GraphUpdate,
    MergeConflictResolutionRequest,
    MergeFinalizeRequest,
    MutationRequest,
    MarkdownImportRequest,
    PlotTitleRepairApply,
    PlotTitleRepairConfirm,
    StoryMigrationApply,
    FragmentToPlotRequest,
    PlotCreate,
    PlotPatch,
    PlotOrderUpdate,
    RelationshipCreate,
    RelationshipPatch,
    StoryStructureUpdate,
    TimelineUpdate,
    UndoRequest,
)
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.maintenance import MaintenanceService
from storyteller.domain.errors import (
    ConflictError,
    DomainError,
    MergeRequiredError,
    NotFoundError,
)
from storyteller.domain.merge_conflicts import MergeConflictService, has_open_merge
from storyteller.exports import ExportCoordinator
from storyteller.rag.background import RagSyncScheduler
from storyteller.rag.manager import RagManager
from storyteller.settings import Settings
from storyteller.storage.repositories import ProjectRepository
from storyteller.imports.markdown import MarkdownFile, MarkdownImportService


FEATURES = [
    "snapshot-v1", "delta-v1", "entity-detail-v1", "history-v2", "trash-v2",
    "soft-delete-v1", "row-undo-v1", "static-snapshot-v1", "content-mutations-v1",
    "story-structure-v1", "graph-layout-v1", "content-conversion-v1",
    "timeline-drag-chapter-swap-v1",
    "fragment-stacks-v1",
    "fragment-clipboard-import-v1",
    "markdown-bulk-import-v1",
    "stories-unification-v1",
    "fragment-plot-planning-v1",
    "appearance-people-v1",
    "organizations-and-layered-relationships-v1",
    "directional-relationship-lines-v1",
    "automatic-content-colors-v1",
    "git-database-merge-v1",
    "git-database-merge-both-v1",
    "rag-rebuild-v1",
    "rag-background-sync-v1",
]

def create_app(settings: Settings) -> FastAPI:
    rag_manager = RagManager(settings)
    rag_sync = RagSyncScheduler(rag_manager)
    application = StoryApplication.create(settings, rag_sync)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        rag_sync.start(rag_manager.projects())
        try:
            yield
        finally:
            rag_sync.close()

    app = FastAPI(title="Story Teller", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.mutation_token = secrets.token_urlsafe(32)
    app.state.rag_manager = rag_manager
    app.state.rag_sync = rag_sync
    app.state.application = application

    def database_for(project: str):
        try:
            return application.projects.open(project)
        except ProjectAccessError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    def require_mutation_token(x_story_teller_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_story_teller_token, app.state.mutation_token):
            raise HTTPException(status_code=403, detail="写入授权已失效，请刷新本地服务能力")

    def require_write_token(
        request: Request,
        x_story_teller_token: str = Header(default=""),
    ) -> None:
        require_mutation_token(x_story_teller_token)
        project = str(request.path_params.get("project") or "")
        if project:
            database = database_for(project)
            if has_open_merge(database, project):
                raise MergeRequiredError("数据库仍有合并冲突，请先完成合并")

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_request: Request, error: NotFoundError):
        return JSONResponse(status_code=404, content={"ok": False, "error": str(error), "code": "not_found"})

    @app.exception_handler(ConflictError)
    async def conflict_handler(_request: Request, error: ConflictError):
        return JSONResponse(status_code=409, content={"ok": False, "error": str(error), "code": "conflict"})

    @app.exception_handler(MergeRequiredError)
    async def merge_required_handler(_request: Request, error: MergeRequiredError):
        return JSONResponse(
            status_code=423,
            content={"ok": False, "error": str(error), "code": "merge_required"},
        )

    @app.exception_handler(DomainError)
    async def domain_handler(_request: Request, error: DomainError):
        return JSONResponse(status_code=422, content={"ok": False, "error": str(error), "code": "validation"})

    @app.exception_handler(ProjectAccessError)
    async def project_access_handler(_request: Request, error: ProjectAccessError):
        # Match the pre-Application HTTPException wire shape for invalid projects.
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.get("/api/v1/meta")
    def meta(project: str = Query(default="")):
        project_id = project or settings.default_project
        writable = False
        merge_required = False
        project_revision = None
        error = ""
        if project_id:
            try:
                database = database_for(project_id)
                with database.read() as connection:
                    row = connection.execute("SELECT revision FROM projects WHERE id=?", (project_id,)).fetchone()
                    project_revision = int(row[0]) if row else None
                    writable = row is not None
                    merge_required = bool(row is not None and has_open_merge(database, project_id))
            except HTTPException as caught:
                error = str(caught.detail)
        return {
            "apiVersion": API_VERSION,
            "schemaVersion": SCHEMA_VERSION,
            "writable": writable,
            "contentWritable": writable and not merge_required,
            "mergeRequired": merge_required,
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
                "storyStructure": True, "contentConversion": True,
                "timelineChapterSwap": True,
                "fragmentStacks": True,
                "fragmentClipboardImport": True,
                "markdownImport": True,
                "fragmentPlotPlanning": True,
                "storiesMaintenance": True,
                "plotTitleMaintenance": True,
                "appearancePeople": True,
                "mergeConflicts": True,
                "ragRebuild": True,
            },
        }

    @app.get("/api/v1/projects/{project}/snapshot")
    def project_snapshot(project: str):
        return ProjectRepository(database_for(project), project).snapshot()

    @app.get("/api/v1/projects/{project}/maintenance/plot-titles")
    def preview_plot_titles(project: str):
        return MaintenanceService(database_for(project), project).preview_plot_titles()

    @app.post("/api/v1/projects/{project}/maintenance/plot-titles/move-to-fragments", dependencies=[Depends(require_write_token)])
    def move_unresolved_plot_titles(project: str, payload: PlotTitleRepairApply):
        database = database_for(project)
        result = MaintenanceService(database, project).move_unresolved_plots_to_fragments(payload.base_revision, payload.plot_ids)
        return application.mutations.finish(database, project, result)

    @app.post("/api/v1/projects/{project}/maintenance/plot-titles/apply", dependencies=[Depends(require_write_token)])
    def apply_plot_title_candidates(project: str, payload: PlotTitleRepairConfirm):
        database = database_for(project)
        result = MaintenanceService(database, project).apply_plot_title_candidates(
            payload.base_revision,
            [item.model_dump() for item in payload.items],
        )
        return application.mutations.finish(database, project, result)

    @app.get("/api/v1/projects/{project}/maintenance/stories")
    def preview_story_migration(project: str):
        return MaintenanceService(database_for(project), project).preview_stories()

    @app.post("/api/v1/projects/{project}/maintenance/stories/migrate", dependencies=[Depends(require_write_token)])
    def migrate_stories(project: str, payload: StoryMigrationApply):
        database = database_for(project)
        result = MaintenanceService(database, project).migrate_stories(
            payload.base_revision,
            acknowledge_warnings=payload.acknowledge_warnings,
        )
        return application.mutations.finish(database, project, result)

    @app.get("/api/v1/projects/{project}/merge-conflicts")
    def merge_conflicts(project: str):
        database = database_for(project)
        return MergeConflictService(database, project).current()

    @app.put(
        "/api/v1/projects/{project}/merge-conflicts/{conflict_id}",
        dependencies=[Depends(require_mutation_token)],
    )
    def resolve_merge_conflict(
        project: str,
        conflict_id: str,
        payload: MergeConflictResolutionRequest,
    ):
        database = database_for(project)
        resolutions = {
            field: value.model_dump(exclude_none=True)
            for field, value in payload.resolutions.items()
        }
        return MergeConflictService(database, project).save(conflict_id, resolutions)

    @app.get("/api/v1/projects/{project}/merge-conflicts/{session_id}/preview")
    def preview_merge(project: str, session_id: str):
        return MergeConflictService(database_for(project), project).preview(session_id)

    @app.post(
        "/api/v1/projects/{project}/merge-conflicts/{session_id}/finalize",
        dependencies=[Depends(require_mutation_token)],
    )
    def finalize_merge(project: str, session_id: str, payload: MergeFinalizeRequest | None = None):
        database = database_for(project)
        result = MergeConflictService(database, project).finalize(session_id, payload.preview_token if payload else None)
        return application.mutations.finish(database, project, result)

    @app.get("/api/v1/projects/{project}/changes")
    def project_changes(project: str, since: int = Query(ge=0)):
        return ProjectRepository(database_for(project), project).changes_since(since)

    @app.get("/api/v1/projects/{project}/entities/{entity_id:path}")
    def entity_detail(project: str, entity_id: str):
        detail = ProjectRepository(database_for(project), project).entity_detail(entity_id)
        if not detail:
            raise HTTPException(status_code=404, detail="内容不存在")
        return detail

    @app.delete(
        "/api/v1/projects/{project}/entities/{entity_id:path}",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="deleteEntity",
    )
    def delete_entity(project: str, entity_id: str, payload: MutationRequest):
        return application.entities.delete(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/entities/{entity_id:path}/restore",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="restoreEntity",
    )
    def restore_entity(project: str, entity_id: str, payload: MutationRequest):
        return application.entities.restore(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/characters",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="createCharacter",
    )
    def create_character(project: str, payload: CharacterCreate):
        return application.characters.create(
            ApplicationContext(project, source="web"), payload
        )

    @app.patch(
        "/api/v1/projects/{project}/characters/{entity_id:path}",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateCharacter",
    )
    def update_character(project: str, entity_id: str, payload: CharacterPatch):
        return application.characters.update(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/plots",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="createPlot",
    )
    def create_plot(project: str, payload: PlotCreate):
        return application.plots.create(
            ApplicationContext(project, source="web"), payload
        )

    @app.patch(
        "/api/v1/projects/{project}/plots/{entity_id:path}",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updatePlot",
    )
    def update_plot(project: str, entity_id: str, payload: PlotPatch):
        return application.plots.update(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/plots/{entity_id}/to-fragment",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="demotePlotToFragment",
    )
    def move_plot_to_fragment(project: str, entity_id: str, payload: MutationRequest):
        return application.plots.move_to_fragment(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/entries",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="createEntry",
    )
    def create_entry(project: str, payload: EntryCreate):
        return application.entries.create(
            ApplicationContext(project, source="web"), payload
        )

    @app.patch(
        "/api/v1/projects/{project}/entries/{entity_id:path}",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateEntry",
    )
    def update_entry(project: str, entity_id: str, payload: EntryPatch):
        return application.entries.update(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/fragments",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="createFragment",
    )
    def create_fragment(project: str, payload: FragmentCreate):
        return application.fragments.create(
            ApplicationContext(project, source="web"), payload
        )

    @app.post(
        "/api/v1/projects/{project}/fragments/import-clipboard",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="importFragmentsFromClipboard",
    )
    def import_fragments_from_clipboard(project: str, payload: FragmentClipboardImport):
        return application.fragments.import_clipboard(
            ApplicationContext(project, source="web"), payload
        )

    @app.post(
        "/api/v1/projects/{project}/imports/markdown/preview",
        dependencies=[Depends(require_write_token)],
    )
    def preview_markdown_import(project: str, payload: MarkdownImportRequest):
        files = [MarkdownFile(item.path, item.text, item.modified_at) for item in payload.files]
        return MarkdownImportService(database_for(project), project).preview(payload.base_revision, files)

    @app.post(
        "/api/v1/projects/{project}/imports/markdown/apply",
        dependencies=[Depends(require_write_token)],
    )
    def apply_markdown_import(project: str, payload: MarkdownImportRequest):
        database = database_for(project)
        files = [MarkdownFile(item.path, item.text, item.modified_at) for item in payload.files]
        result = MarkdownImportService(database, project).apply(
            payload.base_revision, files,
            allow_conflicts=payload.allow_conflicts,
            preview_fingerprint=payload.preview_fingerprint,
        )
        response = application.mutations.finish(database, project, result)
        response["import"] = result.callback_result
        return response

    @app.patch(
        "/api/v1/projects/{project}/fragments/{entity_id:path}",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateFragment",
    )
    def update_fragment(project: str, entity_id: str, payload: FragmentPatch):
        return application.fragments.update(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/fragments/{entity_id}/to-plot",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="promoteFragmentToPlot",
    )
    def move_fragment_to_plot(project: str, entity_id: str, payload: FragmentToPlotRequest):
        return application.fragments.promote(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.post(
        "/api/v1/projects/{project}/relationships",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="createRelationship",
    )
    def create_relationship(project: str, payload: RelationshipCreate):
        return application.relationships.create(
            ApplicationContext(project, source="web"), payload
        )

    @app.patch(
        "/api/v1/projects/{project}/relationships/{entity_id:path}",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateRelationship",
    )
    def update_relationship(project: str, entity_id: str, payload: RelationshipPatch):
        return application.relationships.update(
            ApplicationContext(project, source="web"), entity_id, payload
        )

    @app.put(
        "/api/v1/projects/{project}/chapters",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateChapters",
    )
    def update_chapters(project: str, payload: ChaptersUpdate):
        return application.structures.update_chapters(
            ApplicationContext(project, source="web"), payload
        )

    @app.put(
        "/api/v1/projects/{project}/plots/order",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="reorderPlots",
    )
    def reorder_plots(project: str, payload: PlotOrderUpdate):
        return application.structures.reorder_plots(
            ApplicationContext(project, source="web"), payload
        )

    @app.put(
        "/api/v1/projects/{project}/story-structure",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateStoryStructure",
    )
    def update_story_structure(project: str, payload: StoryStructureUpdate):
        return application.structures.update_story_structure(
            ApplicationContext(project, source="web"), payload
        )

    @app.put(
        "/api/v1/projects/{project}/timeline",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateTimeline",
    )
    def update_timeline(project: str, payload: TimelineUpdate):
        return application.structures.update_timeline(
            ApplicationContext(project, source="web"), payload
        )

    @app.put(
        "/api/v1/projects/{project}/graph",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="updateGraph",
    )
    def update_graph(project: str, payload: GraphUpdate):
        return application.structures.update_graph(
            ApplicationContext(project, source="web"), payload
        )

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

    @app.post(
        "/api/v1/projects/{project}/operations/undo",
        dependencies=[Depends(require_mutation_token)],
        response_model=MutationOutcome,
        operation_id="undoOperation",
    )
    def undo(project: str, payload: UndoRequest):
        return application.history.undo(
            ApplicationContext(project, source="web"), payload
        )

    @app.post("/api/v1/projects/{project}/exports", dependencies=[Depends(require_write_token)])
    def export_project(project: str):
        return ExportCoordinator(database_for(project), project).export()

    @app.post(
        "/api/v1/projects/{project}/rag/rebuild",
        dependencies=[Depends(require_write_token)],
    )
    def rebuild_rag(project: str):
        database_for(project)
        try:
            return rag_manager.rebuild(project)
        except (OSError, RuntimeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"RAG 更新失败：{error}") from error

    @app.get("/api/v1/health")
    def health():
        return {
            "ok": True,
            "service": "story-teller-worker-web",
            "protocolMajor": WORKER_PROTOCOL_MAJOR,
            "protocolMinor": WORKER_PROTOCOL_MINOR,
            "capabilities": list(WORKER_CAPABILITIES),
            "apiVersion": API_VERSION,
            "schemaVersion": SCHEMA_VERSION,
        }

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
