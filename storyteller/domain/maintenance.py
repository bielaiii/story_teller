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
                expired = {
                    str(row["id"]): str(row["kind"])
                    for row in connection.execute(
                        "SELECT id, kind FROM entities WHERE project_id=? AND deleted_at IS NOT NULL AND purge_at<=?",
                        (self.project_id, timestamp),
                    )
                }
                expired_characters = [identifier for identifier, kind in expired.items() if kind == "character"]
                relationship_entities: set[str] = set()
                if expired_characters:
                    placeholders = ",".join("?" for _ in expired_characters)
                    relationship_entities.update(str(row[0]) for row in connection.execute(
                        f"""
                        SELECT entity_id FROM relationships
                        WHERE from_character_id IN ({placeholders}) OR to_character_id IN ({placeholders})
                        """,
                        tuple(expired_characters) * 2,
                    ))
                # Repair databases created by older versions where a character purge
                # cascaded the relationship row but left its generic entity behind.
                relationship_entities.update(str(row[0]) for row in connection.execute(
                    """
                    SELECT entity.id FROM entities entity
                    LEFT JOIN relationships relationship ON relationship.entity_id=entity.id
                    WHERE entity.project_id=? AND entity.kind='relationship' AND relationship.entity_id IS NULL
                    """,
                    (self.project_id,),
                ))
                purge_ids = set(expired) | relationship_entities
                entity_count = len(purge_ids)
                operation_count = int(connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE project_id=? AND expires_at<=?",
                    (self.project_id, timestamp),
                ).fetchone()[0])
                if relationship_entities:
                    connection.executemany(
                        "DELETE FROM entities WHERE id=? AND project_id=?",
                        [(identifier, self.project_id) for identifier in sorted(relationship_entities)],
                    )
                connection.execute(
                    "DELETE FROM entities WHERE project_id=? AND deleted_at IS NOT NULL AND purge_at<=?",
                    (self.project_id, timestamp),
                )
                connection.execute(
                    "DELETE FROM operations WHERE project_id=? AND expires_at<=?",
                    (self.project_id, timestamp),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('maintenance_last_checked_at', ?)",
                    (str(timestamp),),
                )
                if purge_ids:
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
            if purge_ids or operation_count:
                self._vacuum_replace()
                vacuumed = True
        return {
            "ok": True,
            "checkedAt": timestamp,
            "purgedEntities": entity_count,
            "purgedRelationships": len(relationship_entities),
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
