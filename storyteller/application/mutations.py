from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from storyteller.application.context import ApplicationContext
from storyteller.application.projects import ProjectProvider
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.merge_conflicts import has_open_merge
from storyteller.domain.errors import MergeRequiredError
from storyteller.domain.uow import MutationResult
from storyteller.exports import ExportCoordinator
from storyteller.storage.connection import Database
from storyteller.storage.repositories import ProjectRepository


class RagScheduler(Protocol):
    def schedule(self, project: str, revision: int) -> bool: ...


class ProjectExporter(Protocol):
    def export(self, database: Database, project_id: str) -> dict: ...


class CoordinatorExporter:
    def export(self, database: Database, project_id: str) -> dict:
        return ExportCoordinator(database, project_id).export()


class MutationExecutor:
    """One mutation pipeline for every delivery adapter."""

    def __init__(
        self,
        projects: ProjectProvider,
        rag_sync: RagScheduler,
        exporter: ProjectExporter | None = None,
    ):
        self.projects = projects
        self.rag_sync = rag_sync
        self.exporter = exporter or CoordinatorExporter()

    def execute(
        self,
        context: ApplicationContext,
        mutation: Callable[[Database], MutationResult],
    ) -> MutationOutcome:
        database = self.projects.open(context.project_id)
        if has_open_merge(database, context.project_id):
            raise MergeRequiredError("数据库仍有合并冲突，请先完成合并")
        result = mutation(database)
        return MutationOutcome.model_validate(
            self.finish(database, context.project_id, result)
        )

    def finish(
        self,
        database: Database,
        project_id: str,
        result: MutationResult,
    ) -> dict:
        response = ProjectRepository(database, project_id).mutation_delta(result)
        if result.operation_id is None:
            response["export"] = {
                "status": "ready",
                "revision": result.project_revision,
                "skipped": True,
            }
            response["warnings"] = []
            return response

        scheduled = self.rag_sync.schedule(project_id, result.project_revision)
        try:
            response["export"] = self.exporter.export(database, project_id)
            response["warnings"] = []
        except (OSError, ValueError, RuntimeError) as error:
            response["export"] = {"status": "failed"}
            response["warnings"] = [
                f"数据已经保存，但文本导出待修复：{error}"
            ]
        response["rag"] = {
            "status": "scheduled" if scheduled else "request-fallback",
            "revision": result.project_revision,
        }
        return response
