from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from storyteller.domain.maintenance import MaintenanceService
from storyteller.exports import ExportCoordinator
from storyteller.settings import PROJECT_PATTERN
from storyteller.storage.connection import Database, schema_version
from storyteller.storage.legacy import migrate_database_atomic


def prepare_project(project_root: Path) -> dict[str, Any]:
    """Atomically cut one content package over to V3 and repair derived state."""

    root = Path(project_root).expanduser().resolve()
    if not PROJECT_PATTERN.fullmatch(root.name):
        raise ValueError("项目目录名称不合法")
    database_path = root / "story.db"
    if not database_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{database_path}")

    with sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True) as connection:
        before_version = schema_version(connection)
    migration = migrate_database_atomic(root)
    database = Database(root)
    database.require_v3()
    maintenance = MaintenanceService(database, root.name).purge_expired()

    with database.read() as connection:
        state = connection.execute(
            "SELECT requested_revision, exported_revision, status FROM export_state WHERE project_id=?",
            (root.name,),
        ).fetchone()
        project = connection.execute(
            "SELECT revision FROM projects WHERE id=?", (root.name,)
        ).fetchone()
        if not project:
            raise ValueError("迁移后的数据库缺少项目记录")
        revision = int(project[0])
    snapshot_path = root / "project.snapshot.json"
    export_needed = (
        state is None
        or str(state["status"]) != "ready"
        or int(state["requested_revision"]) != revision
        or int(state["exported_revision"]) != revision
        or not snapshot_path.is_file()
    )
    export = ExportCoordinator(database, root.name).export() if export_needed else {
        "ok": True,
        "revision": revision,
        "status": "ready",
        "skipped": True,
    }
    return {
        "ok": True,
        "project": root.name,
        "sourceSchemaVersion": before_version,
        "schemaVersion": 3,
        "migrated": not bool(migration.get("alreadyMigrated")),
        "backup": migration.get("backup", ""),
        "maintenance": maintenance,
        "export": export,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="准备 Story Teller Schema V3 内容包")
    parser.add_argument("project_root", type=Path)
    args = parser.parse_args()
    try:
        result = prepare_project(args.project_root)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"内容包准备失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
