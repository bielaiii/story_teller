from __future__ import annotations

import base64
import json
import sqlite3
import time
from typing import Any

from storyteller.domain.errors import DomainError, NotFoundError
from storyteller.domain.uow import MutationResult, UnitOfWork, canonical_json
from storyteller.storage.connection import Database


FIELD_LABELS = {
    "__row__": "整项内容",
    "title": "标题",
    "name": "名称",
    "label": "名称",
    "body_markdown": "正文",
    "intro_markdown": "人物介绍",
    "summary": "摘要",
    "status": "状态",
    "chapter_id": "所属篇章",
    "sort_key": "排列位置",
    "story_sort_key": "故事顺序",
    "color": "颜色",
    "gradient": "渐变颜色",
    "side": "位置",
    "type": "类型",
    "subtype": "子类型",
    "area": "区域",
    "extra_json": "扩展设置",
    "graph_visible": "是否显示在图谱",
    "main_plot_impact": "主线影响",
    "narrative_role": "叙事角色",
    "character_scope": "人物范围",
    "from_role": "起点角色",
    "to_role": "终点角色",
    "content": "内容",
    "fact_value": "事实内容",
    "value": "内容",
}
LONG_TEXT_COLUMNS = {
    "body_markdown",
    "intro_markdown",
    "summary",
    "content",
    "fact_value",
    "extra_json",
}


def has_open_merge(database: Database, project_id: str) -> bool:
    with database.read() as connection:
        return bool(
            connection.execute(
                "SELECT 1 FROM merge_sessions WHERE project_id=? AND status='open' LIMIT 1",
                (project_id,),
            ).fetchone()
        )


def _json_row(raw: str | None) -> dict[str, Any] | None:
    return json.loads(raw) if raw is not None else None


def _public_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$blob"}:
        try:
            size = len(base64.b64decode(str(value["$blob"])))
        except (ValueError, TypeError):
            size = 0
        return {"binary": True, "bytes": size}
    return value


def _public_row(row: dict[str, Any] | None) -> Any:
    if row is None:
        return None
    hidden = {
        "project_id", "entity_id", "revision", "created_at", "updated_at",
        "deleted_at", "purge_at",
    }
    visible = {
        FIELD_LABELS.get(key, key.replace("_", " ")): _public_value(value)
        for key, value in row.items()
        if key not in hidden
    }
    return visible or {"内容": "存在"}


def _field_kind(column: str, ours: Any, theirs: Any) -> str:
    if column == "__row__":
        return "row"
    if isinstance(ours, dict) and ours.get("$blob") is not None:
        return "binary"
    if isinstance(theirs, dict) and theirs.get("$blob") is not None:
        return "binary"
    if isinstance(ours, str) and isinstance(theirs, str):
        if column in LONG_TEXT_COLUMNS or "\n" in ours or "\n" in theirs:
            return "text"
    return "value"


class MergeConflictService:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id

    def _session(self, connection: sqlite3.Connection, session_id: str | None = None):
        if session_id:
            row = connection.execute(
                """
                SELECT * FROM merge_sessions
                WHERE id=? AND project_id=? AND status='open'
                """,
                (session_id, self.project_id),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT * FROM merge_sessions
                WHERE project_id=? AND status='open'
                ORDER BY created_at, id LIMIT 1
                """,
                (self.project_id,),
            ).fetchone()
        return row

    def current(self) -> dict[str, Any]:
        with self.database.read() as connection:
            session = self._session(connection)
            if not session:
                return {"required": False, "session": None, "items": []}
            rows = list(
                connection.execute(
                    """
                    SELECT * FROM merge_conflicts
                    WHERE session_id=?
                    ORDER BY status, title, table_name, primary_key_json
                    """,
                    (session["id"],),
                )
            )
            items = []
            resolved_fields = 0
            total_fields = 0
            for row in rows:
                base = _json_row(row["base_json"])
                ours = _json_row(row["ours_json"])
                theirs = _json_row(row["theirs_json"])
                columns = list(json.loads(str(row["conflict_columns_json"])))
                resolutions = json.loads(str(row["resolution_json"] or "{}"))
                fields = []
                for column in columns:
                    if column == "__row__":
                        base_value = _public_row(base)
                        ours_value = _public_row(ours)
                        theirs_value = _public_row(theirs)
                    else:
                        base_value = base.get(column) if base else None
                        ours_value = ours.get(column) if ours else None
                        theirs_value = theirs.get(column) if theirs else None
                    saved = resolutions.get(column)
                    if saved:
                        resolved_fields += 1
                    total_fields += 1
                    fields.append(
                        {
                            "name": column,
                            "label": FIELD_LABELS.get(column, column.replace("_", " ")),
                            "kind": _field_kind(column, ours_value, theirs_value),
                            "base": _public_value(base_value),
                            "ours": _public_value(ours_value),
                            "theirs": _public_value(theirs_value),
                            "resolution": saved,
                            "manualAllowed": (
                                column != "__row__"
                                and isinstance(ours_value, str)
                                and isinstance(theirs_value, str)
                            ),
                        }
                    )
                items.append(
                    {
                        "id": str(row["id"]),
                        "title": str(row["title"]),
                        "table": str(row["table_name"]),
                        "entityId": row["entity_id"],
                        "status": str(row["status"]),
                        "fields": fields,
                    }
                )
            return {
                "required": True,
                "session": {
                    "id": str(session["id"]),
                    "sourcePath": str(session["source_path"]),
                    "createdAt": int(session["created_at"]),
                    "baseRevision": int(session["base_revision"]),
                    "oursRevision": int(session["ours_revision"]),
                    "theirsRevision": int(session["theirs_revision"]),
                    "conflictCount": int(session["conflict_count"]),
                    "resolvedFields": resolved_fields,
                    "totalFields": total_fields,
                },
                "items": items,
            }

    def save(self, conflict_id: str, resolutions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        timestamp = int(time.time())
        with self.database.write() as connection:
            row = connection.execute(
                """
                SELECT conflict.*, session.project_id, session.status AS session_status
                FROM merge_conflicts conflict
                JOIN merge_sessions session ON session.id=conflict.session_id
                WHERE conflict.id=? AND session.project_id=?
                """,
                (conflict_id, self.project_id),
            ).fetchone()
            if not row:
                raise NotFoundError("合并项不存在")
            if str(row["session_status"]) != "open":
                raise DomainError("这次合并已经完成")
            columns = list(json.loads(str(row["conflict_columns_json"])))
            ours = _json_row(row["ours_json"])
            theirs = _json_row(row["theirs_json"])
            saved = json.loads(str(row["resolution_json"] or "{}"))
            for column, resolution in resolutions.items():
                if column not in columns:
                    raise DomainError(f"合并字段不存在：{column}")
                choice = str(resolution.get("choice") or "")
                if choice not in {"ours", "theirs", "manual"}:
                    raise DomainError("请选择本地版本、远程版本或手动合并")
                if choice == "manual":
                    ours_value = ours.get(column) if ours else None
                    theirs_value = theirs.get(column) if theirs else None
                    if column == "__row__" or not isinstance(ours_value, str) or not isinstance(theirs_value, str):
                        raise DomainError("这个字段不能手动编辑，请选择一个完整版本")
                    if not isinstance(resolution.get("value"), str):
                        raise DomainError("手动合并内容必须是文本")
                    saved[column] = {"choice": "manual", "value": resolution["value"]}
                else:
                    saved[column] = {"choice": choice}
            complete = all(column in saved for column in columns)
            connection.execute(
                """
                UPDATE merge_conflicts
                SET resolution_json=?, status=?, resolved_at=?
                WHERE id=?
                """,
                (
                    canonical_json(saved),
                    "resolved" if complete else "open",
                    timestamp if complete else None,
                    conflict_id,
                ),
            )
        return self.current()

    @staticmethod
    def _resolved_target(row: sqlite3.Row) -> str | None:
        columns = list(json.loads(str(row["conflict_columns_json"])))
        resolutions = json.loads(str(row["resolution_json"] or "{}"))
        if not all(column in resolutions for column in columns):
            raise DomainError("仍有冲突项没有选择")
        if columns == ["__row__"]:
            choice = resolutions["__row__"]["choice"]
            return row["ours_json"] if choice == "ours" else row["theirs_json"]
        target = _json_row(row["merged_json"])
        ours = _json_row(row["ours_json"])
        theirs = _json_row(row["theirs_json"])
        if target is None or ours is None or theirs is None:
            raise DomainError("合并项缺少可用内容")
        for column in columns:
            resolution = resolutions[column]
            choice = resolution["choice"]
            if choice == "manual":
                target[column] = resolution["value"]
            elif choice == "ours":
                target[column] = ours.get(column)
            else:
                target[column] = theirs.get(column)
        return canonical_json(target)

    def finalize(self, session_id: str) -> MutationResult:
        probe = self.database.connect(readonly=True)
        try:
            self.database.require_v3(probe)
            session = self._session(probe, session_id)
            if not session:
                raise NotFoundError("待处理的合并会话不存在")
            conflicts = list(
                probe.execute(
                    "SELECT * FROM merge_conflicts WHERE session_id=? ORDER BY table_name, primary_key_json",
                    (session_id,),
                )
            )
            if not conflicts:
                raise DomainError("合并会话没有冲突项")
            if any(str(row["status"]) != "resolved" for row in conflicts):
                raise DomainError("请先为每一项冲突选择保留内容")
            targets = [
                (str(row["table_name"]), str(row["primary_key_json"]), self._resolved_target(row))
                for row in conflicts
            ]
            project = probe.execute(
                "SELECT revision FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()
            if not project:
                raise NotFoundError("项目不存在")
            base_revision = int(project[0])
        finally:
            probe.close()

        timestamp = int(time.time())

        def apply(connection: sqlite3.Connection) -> None:
            connection.execute("PRAGMA defer_foreign_keys=ON")
            tables = UnitOfWork._tables(connection)
            depths = UnitOfWork._dependency_depths(tables)
            deletions = sorted(
                (item for item in targets if item[2] is None),
                key=lambda item: depths.get(item[0], 0),
                reverse=True,
            )
            upserts = sorted(
                (item for item in targets if item[2] is not None),
                key=lambda item: depths.get(item[0], 0),
            )
            for table, primary_key, target in [*deletions, *upserts]:
                info = tables.get(table)
                if not info:
                    raise DomainError(f"当前版本不再支持数据表 {table}")
                UnitOfWork._apply_row(connection, info, primary_key, target)

        def mark_resolved(connection: sqlite3.Connection, _operation_id: int) -> None:
            connection.execute(
                "UPDATE merge_sessions SET status='resolved', resolved_at=? WHERE id=?",
                (timestamp, session_id),
            )

        try:
            result = UnitOfWork(self.database, self.project_id).mutate(
                base_revision=base_revision,
                label="完成数据库冲突合并",
                action="merge-resolution",
                entity_kind="project",
                callback=apply,
                details={"mergeSessionId": session_id},
                after_operation=mark_resolved,
                now=timestamp,
            )
        except sqlite3.IntegrityError as error:
            raise DomainError(
                "这些选择组合后会破坏内容关系，请返回调整相关项目的选择"
            ) from error
        if result.operation_id is None:
            with self.database.write() as connection:
                connection.execute(
                    "UPDATE merge_sessions SET status='resolved', resolved_at=? WHERE id=?",
                    (timestamp, session_id),
                )
        return result
