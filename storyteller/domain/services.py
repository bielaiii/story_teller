from __future__ import annotations

import re
import sqlite3
import time
from typing import Any

from storyteller.domain.errors import ConflictError, DomainError, NotFoundError
from storyteller.domain.uow import MutationResult, UnitOfWork
from storyteller.storage.connection import Database


RETENTION_SECONDS = 7 * 24 * 60 * 60
RANK_STEP = 10**12
ORDERED_ENTITIES = {
    "plot": ("plots", "active_plots"),
    "chapter": ("chapters", "active_chapters"),
    "timeline_line": ("timeline_lines", "active_timeline_lines"),
}


class EntityService:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id
        self.uow = UnitOfWork(database, project_id)

    def delete(self, entity_id: str, base_revision: int, now: int | None = None) -> MutationResult:
        timestamp = int(time.time()) if now is None else int(now)

        def mutation(connection: sqlite3.Connection) -> dict[str, Any]:
            entity = connection.execute(
                "SELECT * FROM entities WHERE id=? AND project_id=? AND deleted_at IS NULL",
                (entity_id, self.project_id),
            ).fetchone()
            if not entity:
                raise NotFoundError("要删除的内容不存在或已经进入回收站")
            if entity["kind"] == "chapter":
                count = int(connection.execute(
                    """
                    SELECT COUNT(*) FROM active_plots WHERE chapter_id=?
                    """,
                    (entity_id,),
                ).fetchone()[0])
                if count:
                    raise DomainError("篇章中仍有剧情，请先移动剧情后再删除")
            if entity["kind"] == "timeline_line":
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM active_timeline_nodes WHERE line_id=?",
                    (entity_id,),
                ).fetchone()[0])
                if count:
                    raise DomainError("剧情线中仍有节点，请先选择接收线并移动节点")
            ordered = ORDERED_ENTITIES.get(str(entity["kind"]))
            if ordered:
                previous_rank = str(connection.execute(
                    f"SELECT sort_key FROM {ordered[0]} WHERE entity_id=?", (entity_id,)
                ).fetchone()[0])
                connection.execute(
                    f"UPDATE {ordered[0]} SET sort_key=? WHERE entity_id=?",
                    (f"~trash-{previous_rank}-{timestamp}-{entity_id}", entity_id),
                )
            connection.execute(
                """
                UPDATE entities SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=?
                WHERE id=?
                """,
                (timestamp, timestamp + RETENTION_SECONDS, timestamp, entity_id),
            )
            return {"entityId": entity_id, "kind": str(entity["kind"]), "title": str(entity["title"])}

        with self.database.read() as connection:
            current = connection.execute("SELECT kind, title FROM entities WHERE id=?", (entity_id,)).fetchone()
        kind = str(current["kind"]) if current else "content"
        title = str(current["title"]) if current else "内容"
        return self.uow.mutate(
            base_revision=base_revision,
            label=f"删除{self.kind_label(kind)}：{title}",
            action="delete",
            entity_kind=kind,
            callback=mutation,
            details={"entityId": entity_id},
            now=timestamp,
        )

    def restore(self, entity_id: str, base_revision: int, now: int | None = None) -> MutationResult:
        timestamp = int(time.time()) if now is None else int(now)

        def mutation(connection: sqlite3.Connection) -> dict[str, Any]:
            entity = connection.execute(
                "SELECT * FROM entities WHERE id=? AND project_id=? AND deleted_at IS NOT NULL",
                (entity_id, self.project_id),
            ).fetchone()
            if not entity:
                raise NotFoundError("回收站中没有这项内容")
            if int(entity["purge_at"] or 0) <= timestamp:
                raise ConflictError("这项内容已经超过七天保留期")
            if entity["kind"] == "character":
                name = connection.execute("SELECT name FROM characters WHERE entity_id=?", (entity_id,)).fetchone()[0]
                duplicate = connection.execute(
                    """
                    SELECT 1 FROM active_characters WHERE name=? AND entity_id<>?
                    """,
                    (name, entity_id),
                ).fetchone()
                if duplicate:
                    raise ConflictError(f"已有同名人物“{name}”，请先处理名称冲突")
            if entity["kind"] == "entry":
                name = connection.execute("SELECT name FROM entries WHERE entity_id=?", (entity_id,)).fetchone()[0]
                duplicate = connection.execute(
                    "SELECT 1 FROM active_entries WHERE name=? AND entity_id<>?",
                    (name, entity_id),
                ).fetchone()
                if duplicate:
                    raise ConflictError(f"已有同名设定“{name}”，请先处理名称冲突")
            ordered = ORDERED_ENTITIES.get(str(entity["kind"]))
            if ordered:
                deleted_rank = str(connection.execute(
                    f"SELECT sort_key FROM {ordered[0]} WHERE entity_id=?", (entity_id,)
                ).fetchone()[0])
                match = re.match(r"^~trash-(\d+)-", deleted_rank)
                preferred_rank = match.group(1) if match else ""
                preferred_available = bool(preferred_rank) and not connection.execute(
                    f"SELECT 1 FROM {ordered[0]} WHERE sort_key=? AND entity_id<>?",
                    (preferred_rank, entity_id),
                ).fetchone()
                ranks = [
                    int(row[0]) for row in connection.execute(f"SELECT sort_key FROM {ordered[1]}")
                    if str(row[0]).isdigit()
                ]
                connection.execute(
                    f"UPDATE {ordered[0]} SET sort_key=? WHERE entity_id=?",
                    (
                        preferred_rank if preferred_available
                        else f"{max(ranks, default=0) + RANK_STEP:024d}",
                        entity_id,
                    ),
                )
            connection.execute(
                """
                UPDATE entities SET deleted_at=NULL, purge_at=NULL, revision=revision+1, updated_at=?
                WHERE id=?
                """,
                (timestamp, entity_id),
            )
            return {"entityId": entity_id, "kind": str(entity["kind"]), "title": str(entity["title"])}

        with self.database.read() as connection:
            current = connection.execute("SELECT kind, title FROM entities WHERE id=?", (entity_id,)).fetchone()
        kind = str(current["kind"]) if current else "content"
        title = str(current["title"]) if current else "内容"
        return self.uow.mutate(
            base_revision=base_revision,
            label=f"恢复{self.kind_label(kind)}：{title}",
            action="restore",
            entity_kind=kind,
            callback=mutation,
            details={"entityId": entity_id},
            now=timestamp,
        )

    @staticmethod
    def kind_label(kind: str) -> str:
        return {
            "character": "人物",
            "plot": "剧情",
            "entry": "设定",
            "fragment": "碎片",
            "relationship": "关系",
            "timeline_line": "剧情线",
            "chapter": "篇章",
        }.get(kind, "内容")
