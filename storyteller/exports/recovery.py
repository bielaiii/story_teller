from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path
from typing import Any

from storyteller import SCHEMA_VERSION
from storyteller.storage.connection import Database
from storyteller.storage.schema import initialize_schema


RECOVERY_FILE = "recovery.snapshot.json"
EXCLUDED_TABLES = {"metadata", "export_state", "sqlite_sequence"}


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$bytes": base64.b64encode(value).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$bytes"}:
        return base64.b64decode(value["$bytes"])
    return value


def render_recovery_snapshot(database: Database, project_id: str) -> bytes:
    with database.read() as connection:
        tables: dict[str, dict[str, Any]] = {}
        names = [
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ) if str(row[0]) not in EXCLUDED_TABLES
        ]
        for name in names:
            info = list(connection.execute(f'PRAGMA table_info("{name}")'))
            columns = [str(row[1]) for row in info]
            primary_keys = [
                str(row[1]) for row in sorted(
                    (item for item in info if int(item[5]) > 0), key=lambda item: int(item[5])
                )
            ]
            order = primary_keys or columns
            rows = [
                [_encode(row[column]) for column in columns]
                for row in connection.execute(
                    f'SELECT * FROM "{name}" ORDER BY {", ".join(chr(34)+column+chr(34) for column in order)}'
                )
            ]
            tables[name] = {"columns": columns, "rows": rows}
    payload = {
        "format": "story-teller-recovery",
        "version": 1,
        "schemaVersion": SCHEMA_VERSION,
        "project": project_id,
        "tables": tables,
    }
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


class RecoveryImporter:
    def __init__(self, source: Path, project_id: str):
        self.source = Path(source).expanduser().resolve()
        self.project_id = str(project_id).strip()

    def import_to(self, target_database: Path) -> dict[str, Any]:
        source_file = self.source / RECOVERY_FILE if self.source.is_dir() else self.source
        payload = json.loads(source_file.read_text(encoding="utf-8"))
        if payload.get("format") != "story-teller-recovery" or int(payload.get("version", 0)) != 1:
            raise ValueError("恢复快照格式不受支持")
        if int(payload.get("schemaVersion", 0)) != SCHEMA_VERSION:
            raise ValueError("恢复快照数据库版本与当前程序不一致")
        if str(payload.get("project") or "") != self.project_id:
            raise ValueError("恢复快照项目 ID 不一致")
        tables = payload.get("tables")
        if not isinstance(tables, dict):
            raise ValueError("恢复快照缺少数据表")
        target = Path(target_database).expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"目标数据库已经存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            initialize_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("PRAGMA defer_foreign_keys=ON")
            available = {
                str(row[0]) for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            for name in sorted(tables):
                if name not in available or name in EXCLUDED_TABLES:
                    raise ValueError(f"恢复快照包含未知数据表：{name}")
                table = tables[name]
                columns = table.get("columns") if isinstance(table, dict) else None
                rows = table.get("rows") if isinstance(table, dict) else None
                actual_columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{name}")')]
                if columns != actual_columns or not isinstance(rows, list):
                    raise ValueError(f"恢复快照数据表结构不匹配：{name}")
                if not rows:
                    continue
                placeholders = ",".join("?" for _ in columns)
                quoted = ",".join(f'"{column}"' for column in columns)
                connection.executemany(
                    f'INSERT INTO "{name}"({quoted}) VALUES({placeholders})',
                    [tuple(_decode(value) for value in row) for row in rows],
                )
            violations = list(connection.execute("PRAGMA foreign_key_check"))
            if violations:
                raise ValueError("恢复后的数据库未通过外键检查")
            project = connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()
            if not project:
                raise ValueError("恢复后的数据库缺少项目")
            connection.commit()
            counts = {
                name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
                for name in sorted(tables)
            }
        except Exception:
            connection.rollback()
            connection.close()
            target.unlink(missing_ok=True)
            raise
        connection.close()
        return {
            "ok": True,
            "project": self.project_id,
            "schemaVersion": SCHEMA_VERSION,
            "revision": int(project[0]),
            "tables": counts,
        }
