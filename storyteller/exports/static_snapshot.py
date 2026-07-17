from __future__ import annotations

import json

from storyteller.storage.connection import Database
from storyteller.storage.repositories import ProjectRepository


def render_static_snapshot(database: Database, project_id: str) -> bytes:
    repository = ProjectRepository(database, project_id)
    snapshot = repository.snapshot()
    for collection in ("characters", "plots", "entries", "fragments"):
        snapshot[collection] = [
            repository.entity_detail(item["entityId"])["data"] for item in snapshot[collection]
        ]
    snapshot["readonly"] = True
    return (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
