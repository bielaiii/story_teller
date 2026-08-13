from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import time
import re
from pathlib import Path

from storyteller.storage.connection import Database
from storyteller.domain.content import PLOT_CHAPTER_TITLE, ContentService, entity_id, RANK_STEP
from storyteller.domain.uow import MutationResult
from storyteller.domain.errors import DomainError


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
                detached_reference_count = self._detach_non_cascading_references(
                    connection, purge_ids, timestamp
                )
                if relationship_entities:
                    connection.executemany(
                        "DELETE FROM entities WHERE id=? AND project_id=?",
                        [(identifier, self.project_id) for identifier in sorted(relationship_entities)],
                    )
                if purge_ids:
                    placeholders = ",".join("?" for _ in purge_ids)
                    identifiers = tuple(sorted(purge_ids))
                    # Soft-deleted targets remain available during the recovery window.
                    # Before permanent deletion, detach nullable ordering references that
                    # intentionally use NO ACTION instead of cascading their owners.
                    connection.execute(
                        f"""
                        UPDATE plots
                        SET story_anchor_plot_id=NULL,
                            story_anchor_side=NULL,
                            story_order_mode='follow_reading'
                        WHERE story_anchor_plot_id IN ({placeholders})
                        """,
                        identifiers,
                    )
                    connection.execute(
                        f"UPDATE plots SET chapter_id=NULL WHERE chapter_id IN ({placeholders})",
                        identifiers,
                    )
                    connection.execute(
                        f"UPDATE timeline_lines SET start_plot_id=NULL WHERE start_plot_id IN ({placeholders})",
                        identifiers,
                    )
                    connection.execute(
                        f"UPDATE timeline_lines SET end_plot_id=NULL WHERE end_plot_id IN ({placeholders})",
                        identifiers,
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
            "detachedReferences": detached_reference_count,
            "vacuumed": vacuumed,
        }

    def preview_plot_titles(self) -> dict[str, object]:
        """Return a reviewable report; never invents or writes a title."""
        placeholder = re.compile(r"^第\s*\d+\s*章$")
        generic_heading = re.compile(r"^(?:场景|片段|核心设计|方案(?:修正版)?|背景|设定|讨论|大纲|正文|开场|结尾)(?:[：:、，,\s].*)?$")
        items: list[dict[str, object]] = []
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT p.entity_id, p.chapter_number, e.title, p.summary, p.body_markdown
                FROM active_plots p JOIN entities e ON e.id=p.entity_id
                WHERE e.project_id=? ORDER BY p.chapter_number, p.sort_key
                """, (self.project_id,)
            )
            for row in rows:
                title = str(row["title"])
                if not placeholder.fullmatch(title.strip()):
                    continue
                summary = str(row["summary"] or "").strip()
                headings = re.findall(r"(?m)^#{1,2}\s+(.+?)\s*$", str(row["body_markdown"] or ""))
                heading_candidate = headings[0].strip() if headings else ""
                if generic_heading.fullmatch(heading_candidate):
                    heading_candidate = ""
                candidate = summary or heading_candidate
                source = "summary" if summary else "heading" if heading_candidate else "unresolved"
                stories = [str(item[0]) for item in connection.execute(
                    """
                    SELECT ptl.line_id FROM plot_timeline_lines ptl
                    JOIN active_timeline_lines line ON line.entity_id=ptl.line_id
                    WHERE ptl.plot_id=? ORDER BY line.sort_key
                    """,
                    (row["entity_id"],),
                )]
                items.append({
                    "entityId": str(row["entity_id"]),
                    "chapterNumber": row["chapter_number"],
                    "currentTitle": title,
                    "candidateTitle": candidate,
                    "candidateSource": source,
                    "bodyPreview": str(row["body_markdown"] or "")[:240],
                    "stories": stories,
                    "recommendedAction": "review" if candidate else "moveToFragment",
                })
        return {"project": self.project_id, "items": items, "count": len(items)}

    def apply_plot_title_candidates(self, base_revision: int, items: list[dict[str, object]]) -> MutationResult:
        now = int(time.time())
        service = ContentService(self.database, self.project_id)

        def mutation(connection: sqlite3.Connection):
            seen: set[str] = set()
            updated: list[str] = []
            for item in items:
                identifier = str(item.get("plot_id") or item.get("plotId") or "")
                title = str(item.get("title") or "").strip()
                if not identifier or not title or PLOT_CHAPTER_TITLE.fullmatch(title):
                    raise DomainError("标题确认必须提供真实、非章号占位标题")
                if title in seen:
                    raise DomainError(f"本次标题确认中存在重复标题：{title}")
                row = connection.execute(
                    "SELECT e.title FROM active_plots p JOIN entities e ON e.id=p.entity_id WHERE p.entity_id=?",
                    (identifier,),
                ).fetchone()
                if not row or not PLOT_CHAPTER_TITLE.fullmatch(str(row["title"]).strip()):
                    raise DomainError("只能确认当前仍是‘第 N 章’占位标题的活动剧情")
                duplicate = connection.execute(
                    "SELECT 1 FROM active_entities WHERE kind='plot' AND title=? AND id<>?",
                    (title, identifier),
                ).fetchone()
                if duplicate:
                    raise DomainError(f"剧情标题已经存在：{title}")
                connection.execute(
                    "UPDATE entities SET title=?, revision=revision+1, updated_at=? WHERE id=?",
                    (title, now, identifier),
                )
                seen.add(title)
                updated.append(identifier)
            return {"updated": updated, "count": len(updated)}

        return service.uow.mutate(
            base_revision=base_revision,
            label=f"确认 {len(items)} 个剧情标题",
            action="update",
            entity_kind="plot",
            callback=mutation,
            details={"source": "plot-title-review", "count": len(items)},
            now=now,
        )

    @staticmethod
    def _story_key(value: object) -> str:
        text = str(value or "").strip()
        if text in {"主线", "主故事"}:
            return "主线"
        for suffix in ("篇", "线"):
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[:-len(suffix)].strip()
                break
        return text or "未命名故事"

    @staticmethod
    def _palette_color(connection: sqlite3.Connection) -> str:
        palette = ["#3f7fc1", "#c94f62", "#2b8a72", "#8a64b8", "#b06b2d", "#2e879e"]
        counts = {color: 0 for color in palette}
        for row in connection.execute("SELECT color FROM timeline_lines"):
            if str(row[0]) in counts:
                counts[str(row[0])] += 1
        return min(palette, key=lambda color: (counts[color], palette.index(color)))

    def preview_stories(self) -> dict[str, object]:
        """Preview the legacy chapter → canonical story migration without writes."""
        with self.database.read() as connection:
            chapters = list(connection.execute(
                "SELECT c.entity_id, c.label, c.sort_key FROM active_chapters c ORDER BY c.sort_key"
            ))
            lines = list(connection.execute(
                "SELECT l.entity_id, e.title, l.color, l.side, l.sort_key FROM active_timeline_lines l JOIN entities e ON e.id=l.entity_id ORDER BY l.sort_key"
            ))
            line_by_key: dict[str, list[sqlite3.Row]] = {}
            for line in lines:
                line_by_key.setdefault(self._story_key(line["title"]), []).append(line)
            items: list[dict[str, object]] = []
            warnings: list[dict[str, object]] = []
            for chapter in chapters:
                key = self._story_key(chapter["label"])
                candidates = line_by_key.get(key, [])
                if len(candidates) > 1:
                    warnings.append({
                        "type": "ambiguous-line",
                        "chapterId": str(chapter["entity_id"]),
                        "chapter": str(chapter["label"]),
                        "lineIds": [str(item["entity_id"]) for item in candidates],
                    })
                target = candidates[0] if candidates else None
                if target:
                    warnings.append({
                        "type": "same-name",
                        "chapterId": str(chapter["entity_id"]),
                        "lineId": str(target["entity_id"]),
                        "name": str(chapter["label"]),
                        "message": "旧篇章与时间线名称相同，将合并为一个 story",
                    })
                items.append({
                    "chapterId": str(chapter["entity_id"]),
                    "chapter": str(chapter["label"]),
                    "storyId": str(target["entity_id"]) if target else None,
                    "story": str(target["title"]) if target else str(chapter["label"]),
                    "action": "merge" if target else "create",
                })
            return {
                "project": self.project_id,
                "items": items,
                "warnings": warnings,
                "lineCount": len(lines),
                "chapterCount": len(chapters),
                "requiresAcknowledgement": bool(warnings),
            }

    def migrate_stories(self, base_revision: int, *, acknowledge_warnings: bool = False) -> MutationResult:
        now = int(time.time())
        service = ContentService(self.database, self.project_id)

        def mutation(connection: sqlite3.Connection):
            chapters = list(connection.execute(
                "SELECT c.entity_id, c.label, c.sort_key FROM active_chapters c ORDER BY c.sort_key"
            ))
            lines = list(connection.execute(
                "SELECT l.entity_id, e.title FROM active_timeline_lines l JOIN entities e ON e.id=l.entity_id ORDER BY l.sort_key"
            ))
            line_by_key: dict[str, list[sqlite3.Row]] = {}
            for line in lines:
                line_by_key.setdefault(self._story_key(line["title"]), []).append(line)
            warnings = sum(1 for chapter in chapters if line_by_key.get(self._story_key(chapter["label"])))
            if warnings and not acknowledge_warnings:
                raise DomainError("stories 迁移包含同名篇章/时间线，请先预览并确认")

            created_lines: list[str] = []
            mapping: dict[str, str] = {}
            for chapter in chapters:
                key = self._story_key(chapter["label"])
                candidates = line_by_key.get(key, [])
                if len(candidates) > 1:
                    raise DomainError(f"故事名称“{chapter['label']}”对应多个时间线，无法自动合并")
                if candidates:
                    target = str(candidates[0]["entity_id"])
                else:
                    stable = service._next_numeric_id(connection, self.project_id, "timeline_line")
                    target = entity_id("timeline_line", stable)
                    line_rank = service._next_rank(connection, "timeline_lines")
                    connection.execute(
                        "INSERT INTO entities(id, project_id, kind, stable_id, title, created_at, updated_at) VALUES(?, ?, 'timeline_line', ?, ?, ?, ?)",
                        (target, self.project_id, stable, str(chapter["label"]), now, now),
                    )
                    connection.execute(
                        "INSERT INTO timeline_lines(entity_id, color, side, sort_key) VALUES(?, ?, 'right', ?)",
                        (target, self._palette_color(connection), line_rank),
                    )
                    line_by_key.setdefault(key, []).append({"entity_id": target, "title": str(chapter["label"])}
                    )
                    created_lines.append(target)
                mapping[str(chapter["entity_id"])] = target

            moved_memberships = 0
            for chapter_id, line_id in mapping.items():
                plots = list(connection.execute(
                    "SELECT p.entity_id, p.sort_key, p.story_sort_key FROM active_plots p WHERE p.chapter_id=? ORDER BY p.sort_key",
                    (chapter_id,),
                ))
                for plot in plots:
                    if not connection.execute(
                        "SELECT 1 FROM plot_timeline_lines WHERE plot_id=? AND line_id=?",
                        (plot["entity_id"], line_id),
                    ).fetchone():
                        base_key = str(plot["story_sort_key"] or plot["sort_key"])
                        story_key = base_key
                        suffix = 0
                        while connection.execute(
                            "SELECT 1 FROM plot_timeline_lines WHERE line_id=? AND story_sort_key=?",
                            (line_id, story_key),
                        ).fetchone():
                            suffix += 1
                            story_key = f"{base_key}~legacy-{suffix}"
                        connection.execute(
                            "INSERT INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)",
                            (plot["entity_id"], line_id, story_key),
                        )
                        moved_memberships += 1
                    connection.execute("UPDATE plots SET chapter_id=NULL WHERE entity_id=?", (plot["entity_id"],))
                chapter = connection.execute("SELECT sort_key FROM chapters WHERE entity_id=?", (chapter_id,)).fetchone()
                connection.execute(
                    "UPDATE chapters SET sort_key=? WHERE entity_id=?",
                    (f"~legacy-story-{chapter['sort_key']}-{chapter_id}", chapter_id),
                )
                connection.execute(
                    "UPDATE entities SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=? WHERE id=?",
                    (now, now + 7 * 24 * 60 * 60, now, chapter_id),
                )
            return {
                "migrated": len(mapping),
                "createdStories": created_lines,
                "movedMemberships": moved_memberships,
                "warningsAcknowledged": warnings,
            }

        return service.uow.mutate(
            base_revision=base_revision,
            label="统一篇章与时间线为 stories",
            action="migrate",
            entity_kind="story",
            callback=mutation,
            details={"source": "legacy-chapters", "target": "stories"},
            now=now,
        )

    def move_unresolved_plots_to_fragments(self, base_revision: int, plot_ids: list[str]) -> MutationResult:
        timestamp = int(time.time())
        ids = list(dict.fromkeys(str(value) for value in plot_ids))
        service = ContentService(self.database, self.project_id)

        def mutation(connection):
            moved: list[str] = []
            for identifier in ids:
                entity = connection.execute(
                    "SELECT * FROM active_entities WHERE id=? AND kind='plot'", (identifier,)
                ).fetchone()
                row = connection.execute("SELECT * FROM active_plots WHERE entity_id=?", (identifier,)).fetchone()
                if not entity or not row:
                    raise DomainError(f"剧情不存在或已删除：{identifier}")
                if not PLOT_CHAPTER_TITLE.fullmatch(str(entity["title"]).strip()):
                    raise DomainError(f"“{entity['title']}”已有真实标题，不能作为 unresolved 移入碎片")
                stable = service._next_numeric_id(connection, self.project_id, "fragment")
                target = service._create_entity(connection, "fragment", stable, f"待整理 · 原{entity['title']}", timestamp)
                connection.execute(
                    "INSERT INTO fragments(entity_id, body_markdown, status, accent, is_key, is_climax) VALUES(?, ?, '', ?, ?, ?)",
                    (target, row["body_markdown"], row["accent"], row["is_key"], row["is_climax"]),
                )
                tags = [str(item[0]) for item in connection.execute("SELECT tag FROM plot_tags WHERE plot_id=? ORDER BY position", (identifier,))]
                connection.executemany("INSERT INTO fragment_tags(fragment_id, tag, position) VALUES(?, ?, ?)", [(target, tag, index) for index, tag in enumerate(tags)])
                connection.execute(
                    "UPDATE entities SET extra_json=? WHERE id=?",
                    (json.dumps({"convertedFrom": identifier, "convertedFromKind": "plot", "plotChapterNumber": row["chapter_number"], "plotSummary": row["summary"], "fragmentType": "chapter"}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), target),
                )
                service._move_references_and_assets(connection, identifier, target)
                service._soft_delete_converted_source(connection, identifier, "plot", timestamp)
                moved.append(target)
            return {"moved": moved, "count": len(moved)}

        return service.uow.mutate(
            base_revision=base_revision,
            label=f"将 {len(ids)} 篇未命名剧情移入碎片",
            action="convert",
            entity_kind="fragment",
            callback=mutation,
            details={"sourcePlotIds": ids, "targetKind": "fragment"},
            now=timestamp,
        )

    def _detach_non_cascading_references(
        self, connection: sqlite3.Connection, purge_ids: set[str], timestamp: int
    ) -> int:
        """Clear nullable NO ACTION references before purging their targets.

        Most content relationships use ``ON DELETE CASCADE``, but structural
        pointers intentionally remain nullable and use SQLite's default
        ``NO ACTION`` behavior. A soft-deleted plot can therefore block the
        seven-day purge if a timeline line or another plot still points at it.
        Those pointers are derived state and must be detached as part of the
        purge rather than making startup fail.
        """

        detached = 0
        if purge_ids:
            placeholders = ",".join("?" for _ in purge_ids)
            identifiers = tuple(sorted(purge_ids))
            updates = (
                (
                    "UPDATE plots SET story_anchor_plot_id=NULL, "
                    "story_anchor_side=NULL, story_order_mode='follow_reading' "
                    f"WHERE story_anchor_plot_id IN ({placeholders})",
                    identifiers,
                ),
                (
                    "UPDATE plots SET chapter_id=NULL "
                    f"WHERE chapter_id IN ({placeholders})",
                    identifiers,
                ),
                (
                    "UPDATE timeline_lines SET start_plot_id=NULL, end_plot_id=NULL "
                    f"WHERE start_plot_id IN ({placeholders}) "
                    f"OR end_plot_id IN ({placeholders})",
                    identifiers * 2,
                ),
                (
                    "UPDATE timeline_settings SET main_line_id=NULL "
                    f"WHERE main_line_id IN ({placeholders})",
                    identifiers,
                ),
            )
            for statement, parameters in updates:
                detached += max(0, int(connection.execute(statement, parameters).rowcount))

        detached += max(0, int(connection.execute(
            """
            UPDATE operations SET undone_by=NULL
            WHERE undone_by IN (
                SELECT id FROM operations
                WHERE project_id=? AND expires_at<=?
            )
            """,
            (self.project_id, timestamp),
        ).rowcount))
        return detached

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
