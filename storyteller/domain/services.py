from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any

from storyteller.domain.errors import ConflictError, DomainError, NotFoundError
from storyteller.domain.uow import MutationResult, UnitOfWork
from storyteller.storage.connection import Database


RETENTION_SECONDS = 7 * 24 * 60 * 60
RANK_STEP = 10**12
FRAGMENT_CHAPTER_TITLE = re.compile(r"^第\s*(\d+)\s*章(?:\s*[：:·—-]\s*|\s+)")
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

    @staticmethod
    def _fragment_chapter_number(entity: sqlite3.Row, extra: dict[str, Any]) -> int | None:
        raw_number = extra.get("chapterNumber")
        if isinstance(raw_number, int) and raw_number > 0:
            return raw_number
        match = FRAGMENT_CHAPTER_TITLE.match(str(entity["title"] or ""))
        if match:
            return int(match.group(1))
        parent_id = extra.get("parentFragmentId")
        order = extra.get("fragmentOrder")
        return int(order) + 1 if parent_id and isinstance(order, int) else None

    @staticmethod
    def _update_fragment_chapter_number(
        connection: sqlite3.Connection,
        entity_id: str,
        extra: dict[str, Any],
        chapter_number: int,
        timestamp: int,
    ) -> None:
        next_extra = {**extra, "chapterNumber": chapter_number}
        connection.execute(
            """
            UPDATE entities
            SET extra_json=?, revision=revision+1, updated_at=?
            WHERE id=?
            """,
            (
                json.dumps(
                    next_extra,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                timestamp,
                entity_id,
            ),
        )

    @staticmethod
    def _active_fragment_chapters(
        connection: sqlite3.Connection,
        parent_id: str,
    ) -> dict[int, tuple[str, dict[str, Any]]]:
        chapters: dict[int, tuple[str, dict[str, Any]]] = {}
        for row in connection.execute(
            """
            SELECT entity_id, title, extra_json
            FROM active_fragments
            """
        ):
            extra = EntityService._extra_dict(row["extra_json"])
            if extra.get("parentFragmentId") != parent_id:
                continue
            number = EntityService._fragment_chapter_number(row, extra)
            if number is not None:
                chapters[number] = (str(row["entity_id"]), extra)
        return chapters

    @staticmethod
    def _compact_plot_chapters(
        connection: sqlite3.Connection,
        deleted_number: int,
        timestamp: int,
    ) -> None:
        occupied = {
            int(row["chapter_number"]): str(row["entity_id"])
            for row in connection.execute(
                """
                SELECT p.entity_id, p.chapter_number
                FROM active_plots p
                WHERE p.chapter_number IS NOT NULL
                """
            )
        }
        next_number = deleted_number + 1
        while next_number in occupied:
            entity_id = occupied[next_number]
            connection.execute("UPDATE plots SET chapter_number=? WHERE entity_id=?", (next_number - 1, entity_id))
            next_number += 1

    @staticmethod
    def _open_plot_chapter_slot(
        connection: sqlite3.Connection,
        chapter_number: int,
        timestamp: int,
    ) -> None:
        occupied = {
            int(row["chapter_number"]): str(row["entity_id"])
            for row in connection.execute(
                """
                SELECT p.entity_id, p.chapter_number
                FROM active_plots p
                JOIN active_entities e ON e.id=p.entity_id
                WHERE p.chapter_number IS NOT NULL
                """
            )
        }
        displaced: list[tuple[int, str]] = []
        next_number = chapter_number
        while next_number in occupied:
            displaced.append((next_number, occupied[next_number]))
            next_number += 1
        for number, entity_id in reversed(displaced):
            connection.execute("UPDATE plots SET chapter_number=? WHERE entity_id=?", (number + 1, entity_id))

    @staticmethod
    def _compact_fragment_chapters(
        connection: sqlite3.Connection,
        parent_id: str,
        deleted_number: int,
        timestamp: int,
    ) -> None:
        occupied = EntityService._active_fragment_chapters(connection, parent_id)
        next_number = deleted_number + 1
        while next_number in occupied:
            entity_id, extra = occupied[next_number]
            EntityService._update_fragment_chapter_number(
                connection,
                entity_id,
                extra,
                next_number - 1,
                timestamp,
            )
            next_number += 1

    @staticmethod
    def _open_fragment_chapter_slot(
        connection: sqlite3.Connection,
        parent_id: str,
        chapter_number: int,
        timestamp: int,
    ) -> None:
        occupied = EntityService._active_fragment_chapters(connection, parent_id)
        displaced: list[tuple[int, str, dict[str, Any]]] = []
        next_number = chapter_number
        while next_number in occupied:
            entity_id, extra = occupied[next_number]
            displaced.append((next_number, entity_id, extra))
            next_number += 1
        for number, entity_id, extra in reversed(displaced):
            EntityService._update_fragment_chapter_number(
                connection,
                entity_id,
                extra,
                number + 1,
                timestamp,
            )

    def delete(self, entity_id: str, base_revision: int, now: int | None = None) -> MutationResult:
        timestamp = int(time.time()) if now is None else int(now)

        def mutation(connection: sqlite3.Connection) -> dict[str, Any]:
            entity = connection.execute(
                "SELECT * FROM entities WHERE id=? AND project_id=? AND deleted_at IS NULL",
                (entity_id, self.project_id),
            ).fetchone()
            if not entity:
                raise NotFoundError("要删除的内容不存在或已经进入回收站")
            deleted_plot_number: int | None = None
            deleted_fragment_parent: str | None = None
            deleted_fragment_number: int | None = None
            if entity["kind"] == "plot":
                plot_row = connection.execute("SELECT chapter_number FROM plots WHERE entity_id=?", (entity_id,)).fetchone()
                deleted_plot_number = int(plot_row[0]) if plot_row and plot_row[0] is not None else None
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
            if entity["kind"] == "fragment":
                extra = self._extra_dict(entity["extra_json"])
                if extra.get("fragmentType") == "line":
                    children = [
                        row for row in connection.execute(
                            "SELECT entity_id, extra_json FROM active_fragments"
                        )
                        if self._extra_dict(row["extra_json"]).get("parentFragmentId") == entity_id
                    ]
                    if children:
                        connection.executemany(
                            """
                            UPDATE entities
                            SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=?
                            WHERE id=? AND project_id=? AND deleted_at IS NULL
                            """,
                            [
                                (
                                    timestamp,
                                    timestamp + RETENTION_SECONDS,
                                    timestamp,
                                    str(child["entity_id"]),
                                    self.project_id,
                                )
                                for child in children
                            ],
                        )
                else:
                    parent_id = extra.get("parentFragmentId")
                    if isinstance(parent_id, str) and parent_id:
                        deleted_fragment_parent = parent_id
                        deleted_fragment_number = self._fragment_chapter_number(
                            entity, extra
                        )
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
            if deleted_plot_number is not None:
                self._compact_plot_chapters(
                    connection, deleted_plot_number, timestamp
                )
            if (
                deleted_fragment_parent
                and deleted_fragment_number is not None
            ):
                self._compact_fragment_chapters(
                    connection,
                    deleted_fragment_parent,
                    deleted_fragment_number,
                    timestamp,
                )
            return {
                "entityId": entity_id,
                "kind": str(entity["kind"]),
                "title": str(entity["title"]),
                "childCount": len(children) if entity["kind"] == "fragment" and extra.get("fragmentType") == "line" else 0,
            }

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
            if entity["kind"] == "entry":
                name = connection.execute("SELECT name FROM entries WHERE entity_id=?", (entity_id,)).fetchone()[0]
                duplicate = connection.execute(
                    "SELECT 1 FROM active_entries WHERE name=? AND entity_id<>?",
                    (name, entity_id),
                ).fetchone()
                if duplicate:
                    raise ConflictError(f"已有同名设定“{name}”，请先处理名称冲突")
            restored_children: list[str] = []
            if entity["kind"] == "fragment":
                extra = self._extra_dict(entity["extra_json"])
                if extra.get("fragmentType") == "line":
                    restored_children = [
                        str(row["id"])
                        for row in connection.execute(
                            """
                            SELECT e.id, e.extra_json
                            FROM entities e
                            JOIN fragments f ON f.entity_id=e.id
                            WHERE e.project_id=? AND e.deleted_at=?
                            """,
                            (self.project_id, entity["deleted_at"]),
                        )
                        if (
                            row["id"] != entity_id
                            and self._extra_dict(row["extra_json"]).get("parentFragmentId") == entity_id
                        )
                    ]
                    if restored_children:
                        connection.executemany(
                            """
                            UPDATE entities
                            SET deleted_at=NULL, purge_at=NULL, revision=revision+1, updated_at=?
                            WHERE id=? AND project_id=? AND deleted_at IS NOT NULL
                            """,
                            [
                                (timestamp, child_id, self.project_id)
                                for child_id in restored_children
                            ],
                        )
                else:
                    parent_id = extra.get("parentFragmentId")
                    chapter_number = self._fragment_chapter_number(entity, extra)
                    if (
                        isinstance(parent_id, str)
                        and parent_id
                        and chapter_number is not None
                    ):
                        self._open_fragment_chapter_slot(
                            connection,
                            parent_id,
                            chapter_number,
                            timestamp,
                        )
            if entity["kind"] == "plot":
                plot_row = connection.execute("SELECT chapter_number FROM plots WHERE entity_id=?", (entity_id,)).fetchone()
                if plot_row and plot_row[0] is not None:
                    self._open_plot_chapter_slot(
                        connection,
                        int(plot_row[0]),
                        timestamp,
                    )
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
            return {
                "entityId": entity_id,
                "kind": str(entity["kind"]),
                "title": str(entity["title"]),
                "restoredChildCount": len(restored_children),
            }

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

    @staticmethod
    def _extra_dict(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
