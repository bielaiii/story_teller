from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

from storyteller.domain.content import MARKER_CLASSIFICATIONS
from storyteller.domain.errors import DomainError, NotFoundError
from storyteller.domain.uow import MutationResult, UnitOfWork
from storyteller.storage.connection import Database


class DiagnosticService:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id
        self.uow = UnitOfWork(database, project_id)

    @staticmethod
    def _project_extra(connection: sqlite3.Connection, project_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT extra_json FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise NotFoundError("项目不存在")
        try:
            value = json.loads(str(row[0] or "{}"))
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _item(
        identifier: str,
        level: str,
        title: str,
        detail: str,
        suggestion: str,
        *,
        entity_id: str = "",
        kind: str = "",
    ) -> dict[str, Any]:
        return {
            "id": identifier,
            "level": level,
            "title": title,
            "detail": detail,
            "suggestion": suggestion,
            "entityId": entity_id,
            "kind": kind,
        }

    def _collect(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        active = "deleted_at IS NULL"

        for row in connection.execute(
            f"""
            SELECT plot_entity.id, plot_entity.title, chapter_entity.title AS chapter_title
            FROM plots plot
            JOIN entities plot_entity ON plot_entity.id=plot.entity_id AND plot_entity.{active}
            JOIN entities chapter_entity ON chapter_entity.id=plot.chapter_id
            WHERE chapter_entity.deleted_at IS NOT NULL
            """
        ):
            items.append(self._item(
                f"plot.deleted-chapter:{row['id']}", "error", "剧情位于已删除篇章",
                f"《{row['title']}》仍指向回收站中的篇章“{row['chapter_title']}”。",
                "恢复该篇章，或在篇章与阅读顺序中把剧情移动到活动篇章。",
                entity_id=str(row["id"]), kind="plot",
            ))

        for row in connection.execute(
            """
            SELECT plot.entity_id, plot.title FROM active_plots plot
            WHERE NOT EXISTS(
                SELECT 1 FROM active_timeline_nodes node WHERE node.plot_id=plot.entity_id
            ) ORDER BY plot.sort_key
            """
        ):
            items.append(self._item(
                f"timeline.missing-plot:{row['entity_id']}", "warning", "剧情尚未进入时间线",
                f"《{row['title']}》没有任何活动剧情线节点，因此无法在故事时间中定位。",
                "在时间线编辑器中为它选择至少一条剧情线。",
                entity_id=str(row["entity_id"]), kind="plot",
            ))

        for row in connection.execute(
            """
            SELECT line.entity_id, line.title FROM active_timeline_lines line
            WHERE NOT EXISTS(
                SELECT 1 FROM active_timeline_nodes node WHERE node.line_id=line.entity_id
            ) ORDER BY line.sort_key
            """
        ):
            items.append(self._item(
                f"timeline.empty-line:{row['entity_id']}", "info", "剧情线没有节点",
                f"剧情线“{row['title']}”目前没有承载任何剧情。",
                "如果这是预留线路可以忽略；否则添加节点或删除该线路。",
                entity_id=str(row["entity_id"]), kind="timeline_line",
            ))

        for row in connection.execute(
            """
            SELECT reference.source_entity_id, source.kind, source.title,
                   target.id AS target_id, target.title AS target_title
            FROM entity_references reference
            JOIN entities source ON source.id=reference.source_entity_id AND source.deleted_at IS NULL
            JOIN entities target ON target.id=reference.target_entity_id
            WHERE target.deleted_at IS NOT NULL
            ORDER BY reference.source_entity_id, reference.target_entity_id
            """
        ):
            items.append(self._item(
                f"reference.deleted:{row['source_entity_id']}:{row['target_id']}", "warning", "正文引用指向回收站",
                f"“{row['title']}”的结构化引用仍指向已删除内容“{row['target_title']}”。",
                "确认是否恢复被引用内容，或在编辑器中移除这条引用。",
                entity_id=str(row["source_entity_id"]), kind=str(row["kind"]),
            ))

        relation_tables = (
            ("plot_characters", "plot_id", "character_id", "人物", "plot"),
            ("plot_entries", "plot_id", "entry_id", "设定", "plot"),
            ("entry_characters", "entry_id", "character_id", "人物", "entry"),
        )
        for table, owner_column, target_column, label, owner_kind in relation_tables:
            for row in connection.execute(
                f"""
                SELECT relation.{owner_column} AS owner_id, owner.title AS owner_title,
                       target.id AS target_id, target.title AS target_title
                FROM {table} relation
                JOIN entities owner ON owner.id=relation.{owner_column} AND owner.deleted_at IS NULL
                JOIN entities target ON target.id=relation.{target_column}
                WHERE target.deleted_at IS NOT NULL
                """
            ):
                items.append(self._item(
                    f"relation.deleted:{table}:{row['owner_id']}:{row['target_id']}", "warning",
                    f"结构化{label}关联指向回收站",
                    f"“{row['owner_title']}”仍关联已删除{label}“{row['target_title']}”。",
                    "恢复目标，或在对应编辑器中移除关联。",
                    entity_id=str(row["owner_id"]), kind=owner_kind,
                ))

        for row in connection.execute(
            """
            SELECT relation.entity_id, relation_entity.title,
                   CASE WHEN from_entity.deleted_at IS NOT NULL THEN from_entity.title ELSE to_entity.title END AS target_title
            FROM relationships relation
            JOIN entities relation_entity ON relation_entity.id=relation.entity_id AND relation_entity.deleted_at IS NULL
            JOIN entities from_entity ON from_entity.id=relation.from_character_id
            JOIN entities to_entity ON to_entity.id=relation.to_character_id
            WHERE from_entity.deleted_at IS NOT NULL OR to_entity.deleted_at IS NOT NULL
            """
        ):
            items.append(self._item(
                f"relationship.deleted-person:{row['entity_id']}", "warning", "人物关系连接到已删除人物",
                f"关系“{row['title']}”的一端“{row['target_title']}”已在回收站中。",
                "恢复人物，或确认该关系无需继续保留。",
                entity_id=str(row["entity_id"]), kind="relationship",
            ))

        graph_checks = (
            ("graph_nodes", "character_id", "图谱节点"),
            ("graph_nodes", "orbit_of", "人物环绕"),
            ("graph_distances", "from_character_id", "图谱距离"),
            ("graph_distances", "to_character_id", "图谱距离"),
            ("graph_cluster_members", "character_id", "图谱分组"),
        )
        for table, column, label in graph_checks:
            for row in connection.execute(
                f"""
                SELECT config.{column} AS target_id, target.title
                FROM {table} config JOIN entities target ON target.id=config.{column}
                WHERE config.{column} IS NOT NULL AND target.deleted_at IS NOT NULL
                """
            ):
                items.append(self._item(
                    f"graph.deleted:{table}:{column}:{row['target_id']}", "warning", f"{label}包含已删除人物",
                    f"{label}仍保留回收站人物“{row['title']}”的配置。",
                    "恢复人物，或在人物图谱编辑器中移除这项配置。",
                    entity_id=str(row["target_id"]), kind="character",
                ))

        for row in connection.execute(
            """
            SELECT chapter.entity_id, chapter.title FROM active_chapters chapter
            WHERE NOT EXISTS(SELECT 1 FROM active_plots plot WHERE plot.chapter_id=chapter.entity_id)
            ORDER BY chapter.sort_key
            """
        ):
            items.append(self._item(
                f"chapter.empty:{row['entity_id']}", "info", "篇章中没有剧情",
                f"篇章“{row['title']}”目前是空的。",
                "如果不是预留篇章，可以在篇章与阅读顺序中删除。",
                entity_id=str(row["entity_id"]), kind="chapter",
            ))

        marker_rows: dict[str, list[str]] = {}
        for row in connection.execute("SELECT character_id, marker FROM character_markers ORDER BY position"):
            marker_rows.setdefault(str(row["character_id"]), []).append(str(row["marker"]))
        for row in connection.execute("SELECT * FROM active_characters"):
            actual = {
                "narrative_role": str(row["narrative_role"]),
                "character_scope": str(row["character_scope"]),
                "side": str(row["side"]),
            }
            for marker in marker_rows.get(str(row["entity_id"]), []):
                rule = MARKER_CLASSIFICATIONS.get(marker)
                if rule and actual[rule[0]] != rule[1]:
                    items.append(self._item(
                        f"character.marker-conflict:{row['entity_id']}:{marker}", "error", "人物定位互相冲突",
                        f"人物“{row['name']}”的标识“{marker}”与当前结构化定位“{actual[rule[0]]}”冲突。",
                        "打开人物档案，保留其中一个明确定位。",
                        entity_id=str(row["entity_id"]), kind="character",
                    ))

        priority = {"error": 0, "warning": 1, "info": 2}
        return sorted(items, key=lambda item: (priority[item["level"]], item["title"], item["id"]))

    def list(self) -> dict[str, Any]:
        with self.database.read() as connection:
            project = connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()
            if not project:
                raise NotFoundError("项目不存在")
            extra = self._project_extra(connection, self.project_id)
            ignores = extra.get("diagnosticIgnores", {})
            ignores = ignores if isinstance(ignores, dict) else {}
            items = self._collect(connection)
        for item in items:
            reason = str(ignores.get(item["id"], "") or "")
            item["ignored"] = bool(reason)
            item["ignoreReason"] = reason
        return {
            "projectRevision": int(project[0]),
            "items": items,
            "summary": {
                "errors": sum(item["level"] == "error" and not item["ignored"] for item in items),
                "warnings": sum(item["level"] == "warning" and not item["ignored"] for item in items),
                "info": sum(item["level"] == "info" and not item["ignored"] for item in items),
                "ignored": sum(item["ignored"] for item in items),
            },
        }

    def set_ignore(self, diagnostic_id: str, reason: str | None, base_revision: int) -> MutationResult:
        identifier = str(diagnostic_id or "").strip()
        clean_reason = str(reason or "").strip()
        if not identifier:
            raise DomainError("诊断 ID 不能为空")
        if clean_reason and len(clean_reason) > 240:
            raise DomainError("忽略原因不能超过 240 个字符")
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            if identifier not in {item["id"] for item in self._collect(connection)}:
                raise NotFoundError("这条诊断已经不存在")
            extra = self._project_extra(connection, self.project_id)
            ignores = extra.get("diagnosticIgnores", {})
            ignores = dict(ignores) if isinstance(ignores, dict) else {}
            if clean_reason:
                ignores[identifier] = clean_reason
            else:
                ignores.pop(identifier, None)
            extra["diagnosticIgnores"] = ignores
            connection.execute(
                "UPDATE projects SET extra_json=?, updated_at=? WHERE id=?",
                (json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(",", ":")), now, self.project_id),
            )
            return {"diagnosticId": identifier, "ignored": bool(clean_reason)}

        return self.uow.mutate(
            base_revision=base_revision,
            label=("忽略检查提醒" if clean_reason else "恢复检查提醒"),
            action="update",
            entity_kind="diagnostic",
            callback=mutation,
            details={"diagnosticId": identifier},
            now=now,
        )
