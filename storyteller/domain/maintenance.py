from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from pathlib import Path

from storyteller.storage.connection import Database


class MaintenanceService:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id

    def purge_expired(self, now: int | None = None) -> dict[str, int | bool]:
        timestamp = int(time.time()) if now is None else int(now)
        with self.database.locked():
            connection = self.database.connect()
            try:
                self.database.require_v3(connection)
                connection.execute("BEGIN IMMEDIATE")
                entity_count = int(connection.execute(
                    "SELECT COUNT(*) FROM entities WHERE project_id=? AND deleted_at IS NOT NULL AND purge_at<=?",
                    (self.project_id, timestamp),
                ).fetchone()[0])
                operation_count = int(connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE project_id=? AND expires_at<=?",
                    (self.project_id, timestamp),
                ).fetchone()[0])
                connection.execute(
                    "DELETE FROM entities WHERE project_id=? AND deleted_at IS NOT NULL AND purge_at<=?",
                    (self.project_id, timestamp),
                )
                connection.execute(
                    "DELETE FROM operations WHERE project_id=? AND expires_at<=?",
                    (self.project_id, timestamp),
                )
                if entity_count:
                    revision = int(connection.execute(
                        "SELECT revision FROM projects WHERE id=?", (self.project_id,)
                    ).fetchone()[0])
                    connection.execute(
                        "UPDATE export_state SET requested_revision=?, status='pending', updated_at=? WHERE project_id=?",
                        (revision, timestamp, self.project_id),
                    )
                connection.commit()
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            vacuumed = False
            if entity_count or operation_count:
                self._vacuum_replace()
                vacuumed = True
        return {
            "ok": True,
            "purgedEntities": entity_count,
            "purgedOperations": operation_count,
            "vacuumed": vacuumed,
        }

    def _vacuum_replace(self) -> None:
        descriptor, name = tempfile.mkstemp(
            prefix=".story-vacuum-", suffix=".db", dir=self.database.project_root
        )
        os.close(descriptor)
        target = Path(name)
        target.unlink()
        connection = self.database.connect()
        try:
            escaped = str(target).replace("'", "''")
            connection.execute(f"VACUUM INTO '{escaped}'")
        finally:
            connection.close()
        try:
            check = sqlite3.connect(target)
            try:
                check.execute("PRAGMA foreign_keys=ON")
                if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("维护后的数据库完整性检查失败")
                if list(check.execute("PRAGMA foreign_key_check")):
                    raise RuntimeError("维护后的数据库外键检查失败")
            finally:
                check.close()
            os.replace(target, self.database.path)
        finally:
            target.unlink(missing_ok=True)
