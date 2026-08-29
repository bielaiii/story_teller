from __future__ import annotations

from storyteller.application.errors import ProjectAccessError
from storyteller.settings import Settings
from storyteller.storage.connection import Database


class ProjectProvider:
    """Resolve a configured project without depending on an HTTP adapter."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def open(self, project_id: str) -> Database:
        try:
            root = self.settings.project_root(project_id)
            database = Database(root)
            database.require_v3()
            return database
        except (ValueError, RuntimeError, OSError) as error:
            raise ProjectAccessError(str(error)) from error
