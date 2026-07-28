from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Iterable

from storyteller.domain.errors import ConflictError, DomainError, NotFoundError
from storyteller.domain.uow import MutationResult, UnitOfWork
from storyteller.storage.connection import Database


HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
STABLE_TEXT = re.compile(r"^[A-Za-z0-9_-]+$")
RANK_STEP = 10**12
TRASH_RETENTION_SECONDS = 7 * 24 * 60 * 60
NARRATIVE_ROLES = {"主角", "配角"}
CHARACTER_SCOPES = {"主线人物", "常驻人物", "待定角色", "一次性角色"}
CHARACTER_SIDES = {"主角方", "中立", "反派方"}
MARKER_CLASSIFICATIONS = {
    "主角": ("narrative_role", "主角"), "男主": ("narrative_role", "主角"),
    "女主": ("narrative_role", "主角"), "配角": ("narrative_role", "配角"),
    "主线人物": ("character_scope", "主线人物"), "常驻人物": ("character_scope", "常驻人物"),
    "一次性角色": ("character_scope", "一次性角色"), "待定角色": ("character_scope", "待定角色"),
    "正派": ("side", "主角方"), "主角方": ("side", "主角方"), "主角团": ("side", "主角方"),
    "反派": ("side", "反派方"), "反派方": ("side", "反派方"), "中立": ("side", "中立"),
}
PLOT_CHAPTER_TITLE = re.compile(r"^第\s*(\d+)\s*章$")
PLOT_SPEAKER_LABEL = re.compile(
    r"(?m)^\s*\*\*([^*\r\n：:]{2,20})[：:]\*\*\s*$"
)
GENERIC_SPEAKER_LABELS = {
    "旁白", "场景", "女主", "男主", "主角", "反派", "众人", "男人", "女人",
    "男人甲", "男人乙", "女人甲", "女人乙", "声音", "广播", "系统",
    "手下", "反派手下", "同事", "同事甲", "同事乙", "领导", "老板", "副总", "高管",
    "管家", "秘书", "潜伏秘书", "司机", "保安", "安保", "管理员", "服务员", "店员",
    "护士", "护士长", "医生", "主持人", "财经主持人", "现场主持人", "辅导员",
    "经理", "主管", "前台经理", "部门经理", "财务经理", "会务主管", "后厨主管",
    "清洁主管", "工作人员", "维护员", "维保员", "档案员", "收费员", "洗车工",
    "搓澡工", "球童", "音响师", "中间人", "规则维护者",
}
NON_REFERENCE_CHARACTER_TERMS = {"反派"}


def entity_id(kind: str, stable_id: object) -> str:
    return f"{kind}:{str(stable_id).strip()}"


def clean_text(value: Any, label: str, maximum: int = 120, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise DomainError(f"请填写{label}")
    if len(text) > maximum or "\n" in text or "\r" in text:
        raise DomainError(f"{label}不能超过 {maximum} 个字符")
    return text


def clean_body(value: Any, label: str, maximum: int = 200_000) -> str:
    text = str(value or "")
    if len(text) > maximum:
        raise DomainError(f"{label}不能超过 {maximum} 个字符")
    return text


def clean_values(value: Any, label: str, maximum: int = 80) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise DomainError(f"{label}格式不合法")
    result = []
    for item in value:
        clean = clean_text(item, label, 100)
        if clean and clean not in result:
            result.append(clean)
    return result


def clean_persona(value: Any, label: str, maximum: int = 100) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum:
        raise DomainError(f"{label}格式不合法")
    result: list[dict[str, str]] = []
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise DomainError(f"{label}格式不合法")
        key = clean_text(item.get("key"), f"{label}名称", 80, required=True)
        raw_value = str(item.get("value") or "").strip()
        if not raw_value:
            raise DomainError(f"请填写{label}“{key}”的内容")
        if len(raw_value) > 10_000:
            raise DomainError(f"{label}“{key}”不能超过 10000 个字符")
        if key in keys:
            raise DomainError(f"{label}名称“{key}”重复")
        keys.add(key)
        result.append({"key": key, "value": raw_value})
    return result


def persona_plain_text(items: list[dict[str, str]]) -> str:
    return "\n".join(f"{item['key']}：{item['value']}" for item in items)


def replace_json_text(value: Any, old_text: str, new_text: str) -> Any:
    if isinstance(value, str):
        return value.replace(old_text, new_text)
    if isinstance(value, list):
        return [replace_json_text(item, old_text, new_text) for item in value]
    if isinstance(value, dict):
        return {key: replace_json_text(item, old_text, new_text) for key, item in value.items()}
    return value


def clean_color(value: Any, fallback: str = "#7d6bd6") -> str:
    color = str(value or fallback).strip().lower()
    if not HEX_COLOR.fullmatch(color):
        raise DomainError("颜色格式不合法")
    return color


def validate_character_classification(values: dict[str, Any]) -> None:
    role = str(values.get("narrative_role") or "")
    scope = str(values.get("character_scope") or "")
    side = str(values.get("side") or "")
    if role not in NARRATIVE_ROLES:
        raise DomainError("人物戏份定位不合法")
    if scope not in CHARACTER_SCOPES:
        raise DomainError("人物出场类型不合法")
    if side not in CHARACTER_SIDES:
        raise DomainError("人物阵营不合法")
    actual = {"narrative_role": role, "character_scope": scope, "side": side}
    labels = {"narrative_role": "戏份定位", "character_scope": "出场类型", "side": "人物阵营"}
    for marker in values.get("markers", []):
        rule = MARKER_CLASSIFICATIONS.get(str(marker))
        if rule and actual[rule[0]] != rule[1]:
            raise DomainError(f"人物标识“{marker}”与{labels[rule[0]]}“{actual[rule[0]]}”冲突")


class ContentService:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id
        self.uow = UnitOfWork(database, project_id)

    @staticmethod
    def _next_numeric_id(connection: sqlite3.Connection, project_id: str, kind: str) -> str:
        values = [
            int(row[0]) for row in connection.execute(
                "SELECT stable_id FROM entities WHERE project_id=? AND kind=?",
                (project_id, kind),
            ) if str(row[0]).isdigit()
        ]
        return str(max(values, default=0) + 1)

    @staticmethod
    def _next_rank(connection: sqlite3.Connection, table: str) -> str:
        source = "active_plots" if table == "plots" else table
        values = [
            int(row[0]) for row in connection.execute(f"SELECT sort_key FROM {source}")
            if str(row[0]).isdigit()
        ]
        current = max(values, default=0)
        return f"{current + RANK_STEP:024d}"

    @staticmethod
    def _rank_after(connection: sqlite3.Connection, table: str, owner_id: str | None) -> str:
        if not owner_id:
            return ContentService._next_rank(connection, table)
        current = connection.execute(f"SELECT sort_key FROM {table} WHERE entity_id=?", (owner_id,)).fetchone()
        if not current:
            raise DomainError("插入位置不存在")
        source = "active_plots" if table == "plots" else table
        following = connection.execute(
            f"SELECT sort_key FROM {source} WHERE sort_key>? ORDER BY sort_key LIMIT 1", (current[0],)
        ).fetchone()
        lower = int(current[0])
        if not following:
            return f"{lower + RANK_STEP:024d}"
        upper = int(following[0])
        if upper - lower <= 1:
            rows = list(connection.execute(f"SELECT entity_id FROM {source} ORDER BY sort_key"))
            for index, row in enumerate(rows, start=1):
                connection.execute(
                    f"UPDATE {table} SET sort_key=? WHERE entity_id=?",
                    (f"{index * RANK_STEP:024d}", row[0]),
                )
            return ContentService._rank_after(connection, table, owner_id)
        return f"{(lower + upper) // 2:024d}"

    def _create_entity(
        self, connection: sqlite3.Connection, kind: str, stable_id: str, title: str, now: int
    ) -> str:
        identifier = entity_id(kind, stable_id)
        if connection.execute(
            "SELECT 1 FROM entities WHERE project_id=? AND kind=? AND stable_id=?",
            (self.project_id, kind, stable_id),
        ).fetchone():
            raise ConflictError(f"{stable_id} 已经被使用，稳定 ID 不能复用")
        connection.execute(
            """
            INSERT INTO entities(id, project_id, kind, stable_id, title, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (identifier, self.project_id, kind, stable_id, title, now, now),
        )
        return identifier

    @staticmethod
    def _move_references_and_assets(
        connection: sqlite3.Connection, source_id: str, target_id: str
    ) -> None:
        connection.execute(
            """
            UPDATE entity_references
            SET target_entity_id=?,
                marker=CASE WHEN marker=? THEN ? ELSE marker END
            WHERE target_entity_id=? AND source_entity_id<>?
            """,
            (target_id, source_id, target_id, source_id, target_id),
        )
        connection.execute(
            "UPDATE assets SET entity_id=? WHERE entity_id=?",
            (target_id, source_id),
        )

    @staticmethod
    def _soft_delete_converted_source(
        connection: sqlite3.Connection, source_id: str, kind: str, now: int
    ) -> None:
        if kind == "plot":
            previous_rank = str(connection.execute(
                "SELECT sort_key FROM plots WHERE entity_id=?", (source_id,)
            ).fetchone()[0])
            connection.execute(
                "UPDATE plots SET sort_key=? WHERE entity_id=?",
                (f"~trash-{previous_rank}-{now}-{source_id}", source_id),
            )
        connection.execute(
            """
            UPDATE entities
            SET deleted_at=?, purge_at=?, revision=revision+1, updated_at=?
            WHERE id=?
            """,
            (now, now + TRASH_RETENTION_SECONDS, now, source_id),
        )

    def _active_entity(self, connection: sqlite3.Connection, identifier: str, kind: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM entities WHERE id=? AND project_id=? AND kind=? AND deleted_at IS NULL",
            (identifier, self.project_id, kind),
        ).fetchone()
        if not row:
            raise NotFoundError("要编辑的内容不存在或已进入回收站")
        return row

    @staticmethod
    def _apply_plot_chapter_number(
        connection: sqlite3.Connection,
        target_id: str,
        chapter_number: int,
        shift_following: bool,
        now: int,
    ) -> None:
        rows = list(connection.execute(
            """
            SELECT p.entity_id, p.sort_key, e.title
            FROM active_plots p JOIN active_entities e ON e.id=p.entity_id
            ORDER BY p.sort_key
            """
        ))
        numbered: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            match = PLOT_CHAPTER_TITLE.fullmatch(str(row["title"]).strip())
            numbered.append({
                "id": str(row["entity_id"]),
                "number": int(match.group(1)) if match else index,
                "order": index,
                "title": str(row["title"]),
            })
        conflicts = [
            item for item in numbered
            if item["id"] != target_id and item["number"] == chapter_number
        ]
        if conflicts and not shift_following:
            raise DomainError(f"第 {chapter_number} 章已经存在，请重新设置章号或顺延后续章节")
        if shift_following:
            target = next((item for item in numbered if item["id"] == target_id), None)
            if not target:
                raise NotFoundError("要设置章号的剧情不存在")
            others = [item for item in numbered if item["id"] != target_id]
            occupied = {item["number"]: item for item in others}
            available_number = chapter_number
            displaced: list[dict[str, Any]] = []
            while available_number in occupied:
                item = occupied[available_number]
                displaced.append(item)
                available_number += 1
            for item in reversed(displaced):
                item["number"] += 1
            target["number"] = chapter_number
            ordered = sorted([*others, target], key=lambda item: (item["number"], item["order"]))
        else:
            target = next((item for item in numbered if item["id"] == target_id), None)
            if not target:
                raise NotFoundError("要设置章号的剧情不存在")
            target["number"] = chapter_number
            ordered = sorted(numbered, key=lambda item: (item["number"], item["order"]))
        for index, item in enumerate(ordered, start=1):
            connection.execute(
                "UPDATE plots SET sort_key=? WHERE entity_id=?",
                (f"~chapter-number-{index:06d}", item["id"]),
            )
        for index, item in enumerate(ordered, start=1):
            connection.execute(
                "UPDATE plots SET sort_key=? WHERE entity_id=?",
                (f"{index * RANK_STEP:024d}", item["id"]),
            )
            next_title = f"第 {item['number']} 章"
            if item["title"] != next_title:
                connection.execute(
                    "UPDATE entities SET title=?, revision=revision+1, updated_at=? WHERE id=?",
                    (next_title, now, item["id"]),
                )
        ContentService._sync_plot_timeline_story_sort_keys(connection)

    @staticmethod
    def _sync_plot_timeline_story_sort_keys(connection: sqlite3.Connection) -> None:
        """Align timeline order with plot order while preserving the existing spacing slots."""
        ordered_plot_ids = [
            str(row["entity_id"])
            for row in connection.execute(
                "SELECT entity_id FROM active_plots ORDER BY sort_key, entity_id"
            )
        ]
        existing_keys_by_plot: dict[str, str] = {}
        for row in connection.execute(
            """
            SELECT plot_id, MIN(story_sort_key) AS story_sort_key
            FROM plot_timeline_lines
            GROUP BY plot_id
            """
        ):
            story_key = str(row["story_sort_key"])
            if story_key.isdigit():
                existing_keys_by_plot[str(row["plot_id"])] = story_key
        spacing_slots = sorted(
            existing_keys_by_plot.values(),
            key=lambda value: (int(value), value),
        )
        if len(spacing_slots) != len(ordered_plot_ids) or len(set(spacing_slots)) != len(spacing_slots):
            spacing_slots = [f"{index * RANK_STEP:024d}" for index in range(1, len(ordered_plot_ids) + 1)]
        target_key_by_plot = dict(zip(ordered_plot_ids, spacing_slots, strict=True))
        rows = list(connection.execute(
            """
            SELECT ptl.plot_id, ptl.line_id
            FROM plot_timeline_lines ptl
            JOIN active_plots p ON p.entity_id=ptl.plot_id
            ORDER BY ptl.line_id, p.sort_key, ptl.plot_id
            """
        ))
        for index, row in enumerate(rows, start=1):
            connection.execute(
                """
                UPDATE plot_timeline_lines SET story_sort_key=?
                WHERE plot_id=? AND line_id=?
                """,
                (f"~plot-rank-sync-{index:06d}", row["plot_id"], row["line_id"]),
            )
        for row in rows:
            connection.execute(
                """
                UPDATE plot_timeline_lines SET story_sort_key=?
                WHERE plot_id=? AND line_id=?
                """,
                (target_key_by_plot[str(row["plot_id"])], row["plot_id"], row["line_id"]),
            )

    @staticmethod
    def _replace_values(
        connection: sqlite3.Connection, table: str, owner_column: str, owner_id: str,
        value_column: str, values: Iterable[str],
    ) -> None:
        connection.execute(f"DELETE FROM {table} WHERE {owner_column}=?", (owner_id,))
        connection.executemany(
            f"INSERT INTO {table}({owner_column}, {value_column}, position) VALUES(?, ?, ?)",
            [(owner_id, value, index) for index, value in enumerate(values)],
        )

    @staticmethod
    def _require_targets(
        connection: sqlite3.Connection, identifiers: Iterable[str], view: str, label: str
    ) -> list[str]:
        values = list(dict.fromkeys(identifiers))
        for identifier in values:
            if not connection.execute(f"SELECT 1 FROM {view} WHERE entity_id=?", (identifier,)).fetchone():
                raise DomainError(f"{label}不存在或已删除：{identifier}")
        return values

    def _replace_entity_references(
        self, connection: sqlite3.Connection, source_id: str, payload: dict[str, Any]
    ) -> None:
        """Replace the body references owned by an editor without scanning Markdown text."""
        if "references" not in payload:
            return
        references = clean_values(payload["references"], "正文引用", 500)
        if source_id in references:
            raise DomainError("正文不能引用自身")
        targets = list(dict.fromkeys(references))
        active_targets: list[str] = []
        for target_id in targets:
            target = connection.execute(
                "SELECT deleted_at FROM entities WHERE id=? AND project_id=?",
                (target_id, self.project_id),
            ).fetchone()
            if not target:
                raise DomainError(f"引用内容不存在或已删除：{target_id}")
            # An editor opened before a soft delete can still submit the old
            # reference. Discard that stale reference instead of blocking an
            # otherwise valid save; restoring the target remains reversible.
            if target["deleted_at"] is None:
                active_targets.append(target_id)
        connection.execute(
            "DELETE FROM entity_references WHERE source_entity_id=? AND context='body'",
            (source_id,),
        )
        connection.executemany(
            """
            INSERT INTO entity_references(
                source_entity_id, target_entity_id, context, marker, source
            ) VALUES(?, ?, 'body', ?, 'editor')
            """,
            [(source_id, target_id, target_id) for target_id in active_targets],
        )

    @staticmethod
    def _automatic_plot_people(
        connection: sqlite3.Connection,
        identifier: str,
        payload: dict[str, Any],
    ) -> list[str]:
        row = connection.execute(
            "SELECT body_markdown, summary FROM plots WHERE entity_id=?", (identifier,)
        ).fetchone()
        text = "\n".join((
            str(payload.get("summary", row["summary"] if row else "") or ""),
            str(payload.get("body", row["body_markdown"] if row else "") or ""),
        ))
        if "references" in payload:
            stable_references = set(clean_values(payload["references"], "正文引用", 500))
        else:
            stable_references = {
                str(item[0]) for item in connection.execute(
                    """
                    SELECT target_entity_id FROM active_entity_references
                    WHERE source_entity_id=? AND context='body'
                    """,
                    (identifier,),
                )
            }
        characters: dict[str, list[str]] = {}
        for item in connection.execute(
            """
            SELECT c.entity_id, c.name, a.alias
            FROM active_characters c
            LEFT JOIN character_aliases a ON a.character_id=c.entity_id
            ORDER BY c.entity_id, a.position
            """
        ):
            character_id = str(item["entity_id"])
            characters.setdefault(character_id, [])
            for term in (str(item["name"]), str(item["alias"] or "")):
                clean = term.strip()
                if (
                    clean
                    and clean not in NON_REFERENCE_CHARACTER_TERMS
                    and clean not in characters[character_id]
                ):
                    characters[character_id].append(clean)
        owners: dict[str, set[str]] = {}
        for character_id, terms in characters.items():
            for term in terms:
                owners.setdefault(term.casefold(), set()).add(character_id)

        def mentioned(term: str) -> bool:
            if len(term) == 1 and term.isascii():
                return False
            if term.isascii() and all(character.isalnum() or character in "_-" for character in term):
                return re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None
            return term in text

        result: list[str] = []
        for character_id, terms in characters.items():
            for term in terms:
                if not mentioned(term):
                    continue
                term_owners = owners.get(term.casefold(), set())
                if len(term_owners) == 1 or character_id in stable_references:
                    result.append(character_id)
                    break
        return result

    def _archive_unknown_plot_speakers(
        self,
        connection: sqlite3.Connection,
        identifier: str,
        payload: dict[str, Any],
        now: int,
    ) -> list[str]:
        """Create one-time character cards for explicit, name-like dialogue labels."""
        row = connection.execute(
            """
            SELECT p.body_markdown, e.title
            FROM plots p JOIN entities e ON e.id=p.entity_id
            WHERE p.entity_id=?
            """,
            (identifier,),
        ).fetchone()
        body = str(payload.get("body", row["body_markdown"] if row else "") or "")
        if not body:
            return []
        known_labels = {
            str(item[0]).strip()
            for item in connection.execute(
                """
                SELECT name FROM active_characters
                UNION
                SELECT alias FROM character_aliases a
                JOIN active_characters c ON c.entity_id=a.character_id
                """
            )
            if str(item[0]).strip()
        }
        names: list[str] = []
        for match in PLOT_SPEAKER_LABEL.finditer(body):
            name = re.sub(r"[（(][^）)]*[）)]$", "", match.group(1)).strip()
            if (
                not re.fullmatch(r"[\u3400-\u9fff]{2,6}", name)
                or name in GENERIC_SPEAKER_LABELS
                or name in known_labels
                or name in names
            ):
                continue
            names.append(name)
        if not names:
            return []

        if payload.get("chapter_number") is not None:
            plot_title = f"第 {int(payload['chapter_number'])} 章"
        else:
            plot_title = str(row["title"] if row else "").strip() or "未命名剧情"
        created: list[str] = []
        for name in names:
            stable = self._next_numeric_id(connection, self.project_id, "character")
            character_id = self._create_entity(connection, "character", stable, name, now)
            intro = f"首次出场：{plot_title}\n\n由剧情正文中的角色台词自动归档。"
            connection.execute(
                """
                INSERT INTO characters(
                    entity_id, name, intro_markdown, narrative_role, character_scope, side,
                    main_plot_impact, color, gradient, group_name, graph_visible
                ) VALUES(?, ?, ?, '配角', '一次性角色', '中立', 0, '#8b95a7', '', '一次性角色', 0)
                """,
                (character_id, name, intro),
            )
            connection.executemany(
                """
                INSERT INTO character_markers(character_id, marker, position)
                VALUES(?, ?, ?)
                """,
                (
                    (character_id, "配角", 0),
                    (character_id, "一次性角色", 1),
                    (character_id, "中立", 2),
                ),
            )
            connection.execute(
                """
                INSERT INTO character_facts(character_id, fact_key, fact_value, position)
                VALUES(?, '首次出场', ?, 0)
                """,
                (character_id, plot_title),
            )
            connection.execute(
                "UPDATE entities SET extra_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "autoArchived": True,
                            "archiveSource": "plot-speaker",
                            "sourcePlotId": identifier,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    character_id,
                ),
            )
            known_labels.add(name)
            created.append(character_id)
        return created

    @staticmethod
    def _replace_reference_display_text(
        connection: sqlite3.Connection,
        target_id: str,
        old_name: str,
        new_name: str,
        now: int,
    ) -> list[str]:
        """Rename readable mention text only in bodies carrying a stable reference."""
        if not old_name or old_name == new_name:
            return []
        sources = [str(row[0]) for row in connection.execute(
            "SELECT DISTINCT source_entity_id FROM entity_references WHERE target_entity_id=?",
            (target_id,),
        )]
        locations = {
            "character": ("characters", "intro_markdown"),
            "plot": ("plots", "body_markdown"),
            "entry": ("entries", "body_markdown"),
            "fragment": ("fragments", "body_markdown"),
            "relationship": ("relationships", "body_markdown"),
        }
        changed: list[str] = []
        for source_id in sources:
            entity = connection.execute("SELECT kind, extra_json FROM entities WHERE id=?", (source_id,)).fetchone()
            location = locations.get(str(entity["kind"])) if entity else None
            if not location:
                continue
            row = connection.execute(
                f"SELECT {location[1]} FROM {location[0]} WHERE entity_id=?", (source_id,)
            ).fetchone()
            body = str(row[0] or "") if row else ""
            replacement = body.replace(old_name, new_name)
            extra = str(entity["extra_json"] or "{}")
            extra_replacement = extra
            if str(entity["kind"]) == "character":
                try:
                    replaced_extra = replace_json_text(json.loads(extra), old_name, new_name)
                    extra_replacement = json.dumps(
                        replaced_extra, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                    )
                except (TypeError, json.JSONDecodeError):
                    extra_replacement = extra
            if replacement == body and extra_replacement == extra:
                continue
            if replacement != body:
                connection.execute(
                    f"UPDATE {location[0]} SET {location[1]}=? WHERE entity_id=?",
                    (replacement, source_id),
                )
            connection.execute(
                "UPDATE entities SET extra_json=?, revision=revision+1, updated_at=? WHERE id=?",
                (extra_replacement, now, source_id),
            )
            changed.append(source_id)
        return changed

    def create_character(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())
        name = clean_text(payload.get("name"), "人物名称", required=True)
        markers = clean_values(payload.get("markers", []), "人物标识")
        values = {
            "narrative_role": str(payload.get("narrative_role") or "配角"),
            "character_scope": str(payload.get("character_scope") or "常驻人物"),
            "side": str(payload.get("side") or "中立"),
            "markers": markers,
        }
        validate_character_classification(values)
        graph_visible = payload.get("graph_visible")
        if graph_visible is None:
            graph_visible = (
                values["narrative_role"] == "主角"
                or values["side"] in {"反派方", "中立"}
            ) and values["character_scope"] not in {"一次性角色", "待定角色"}

        def mutation(connection: sqlite3.Connection):
            stable = clean_text(payload.get("stable_id"), "人物 ID", 60) or self._next_numeric_id(connection, self.project_id, "character")
            identifier = self._create_entity(connection, "character", stable, name, now)
            impact = int(payload.get("main_plot_impact", 0))
            if not 0 <= impact <= 100:
                raise DomainError("主线影响必须在 0 到 100 之间")
            connection.execute(
                """
                INSERT INTO characters(
                    entity_id, name, intro_markdown, narrative_role, character_scope, side,
                    main_plot_impact, color, gradient, group_name, graph_visible
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier, name, clean_body(payload.get("intro", ""), "人物设定"),
                    values["narrative_role"], values["character_scope"], values["side"], impact,
                    clean_color(payload.get("color")), str(payload.get("gradient") or ""),
                    clean_text(payload.get("group", ""), "人物分组", 80), graph_visible,
                ),
            )
            self._replace_values(connection, "character_aliases", "character_id", identifier, "alias", clean_values(payload.get("aliases", []), "别名"))
            self._replace_values(connection, "character_markers", "character_id", identifier, "marker", markers)
            self._replace_character_details(connection, identifier, payload)
            self._replace_entity_references(connection, identifier, payload)
            return {"entityId": identifier}

        return self.uow.mutate(
            base_revision=base_revision, label=f"新建人物：{name}", action="create",
            entity_kind="character", callback=mutation,
        )

    def update_character(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            entity = self._active_entity(connection, identifier, "character")
            row = connection.execute("SELECT * FROM characters WHERE entity_id=?", (identifier,)).fetchone()
            current_markers = [str(item[0]) for item in connection.execute(
                "SELECT marker FROM character_markers WHERE character_id=? ORDER BY position", (identifier,)
            )]
            merged = {
                "narrative_role": payload.get("narrative_role", row["narrative_role"]),
                "character_scope": payload.get("character_scope", row["character_scope"]),
                "side": payload.get("side", row["side"]),
                "markers": clean_values(payload["markers"], "人物标识") if "markers" in payload else current_markers,
            }
            validate_character_classification(merged)
            updates: dict[str, Any] = {}
            mappings = {
                "name": ("name", lambda value: clean_text(value, "人物名称", required=True)),
                "intro": ("intro_markdown", lambda value: clean_body(value, "人物设定")),
                "narrative_role": ("narrative_role", str), "character_scope": ("character_scope", str),
                "side": ("side", str),
                "main_plot_impact": ("main_plot_impact", int),
                "color": ("color", clean_color), "gradient": ("gradient", str),
                "group": ("group_name", lambda value: clean_text(value, "人物分组", 80)),
                "graph_visible": ("graph_visible", bool),
            }
            for key, (column, cleaner) in mappings.items():
                if key in payload:
                    updates[column] = cleaner(payload[key])
            if "main_plot_impact" in updates and not 0 <= updates["main_plot_impact"] <= 100:
                raise DomainError("主线影响必须在 0 到 100 之间")
            if "name" in updates and str(updates["name"]) != str(row["name"]):
                self._replace_reference_display_text(
                    connection, identifier, str(row["name"]), str(updates["name"]), now
                )
                connection.execute("UPDATE entities SET title=? WHERE id=?", (updates["name"], identifier))
            if updates:
                connection.execute(
                    f"UPDATE characters SET {', '.join(column+'=?' for column in updates)} WHERE entity_id=?",
                    tuple(updates.values()) + (identifier,),
                )
            if "aliases" in payload:
                self._replace_values(connection, "character_aliases", "character_id", identifier, "alias", clean_values(payload["aliases"], "别名"))
            if "markers" in payload:
                self._replace_values(connection, "character_markers", "character_id", identifier, "marker", merged["markers"])
            self._replace_character_details(connection, identifier, payload)
            self._replace_entity_references(connection, identifier, payload)
            connection.execute(
                "UPDATE entities SET revision=revision+1, updated_at=? WHERE id=?", (now, identifier)
            )
            return {"entityId": identifier, "title": updates.get("name", entity["title"])}

        title = self._title(identifier)
        new_title = clean_text(payload.get("name"), "人物名称") if "name" in payload else ""
        return self.uow.mutate(
            base_revision=base_revision,
            label=(f"重命名人物：{title} → {new_title}" if new_title and new_title != title else f"编辑人物：{title}"),
            action=("rename" if new_title and new_title != title else "update"),
            entity_kind="character", callback=mutation, expected_entity_id=identifier,
            expected_entity_revision=payload.get("entity_revision"),
        )

    @staticmethod
    def _replace_character_details(connection: sqlite3.Connection, identifier: str, payload: dict[str, Any]) -> None:
        if "facts" in payload:
            facts = payload["facts"]
            if not isinstance(facts, dict) or len(facts) > 100:
                raise DomainError("人物事实格式不合法")
            connection.execute("DELETE FROM character_facts WHERE character_id=?", (identifier,))
            for index, (key, value) in enumerate(facts.items()):
                connection.execute(
                    "INSERT INTO character_facts(character_id, fact_key, fact_value, position) VALUES(?, ?, ?, ?)",
                    (identifier, clean_text(key, "事实名称", 80, required=True), clean_text(value, "事实内容", 500, required=True), index),
                )
        if "supplements" in payload:
            values = clean_values(payload["supplements"], "补充设定", 200)
            ContentService._replace_values(
                connection, "character_supplements", "character_id", identifier, "content", values
            )
        persona_requested = "core_persona" in payload or "supplement_persona" in payload
        legacy_persona_requested = "intro" in payload or "supplements" in payload
        outline_requested = "destiny_outline" in payload
        if persona_requested or legacy_persona_requested or outline_requested:
            entity = connection.execute(
                "SELECT extra_json FROM entities WHERE id=?", (identifier,)
            ).fetchone()
            try:
                extra = json.loads(str(entity[0] or "{}")) if entity else {}
            except (TypeError, json.JSONDecodeError):
                extra = {}
            if not isinstance(extra, dict):
                extra = {}
            raw_persona = extra.get("characterPersona")
            persona = dict(raw_persona) if isinstance(raw_persona, dict) else {}
            if "core_persona" in payload:
                core = clean_persona(payload["core_persona"], "核心人设")
                persona["core"] = core
                connection.execute(
                    "UPDATE characters SET intro_markdown=? WHERE entity_id=?",
                    (persona_plain_text(core), identifier),
                )
            elif "intro" in payload:
                persona.pop("core", None)
            if "supplement_persona" in payload:
                supplementary = clean_persona(payload["supplement_persona"], "补充人设")
                persona["supplement"] = supplementary
                ContentService._replace_values(
                    connection, "character_supplements", "character_id", identifier, "content",
                    [persona_plain_text([item]) for item in supplementary],
                )
            elif "supplements" in payload:
                persona.pop("supplement", None)
            if persona:
                extra["characterPersona"] = persona
            else:
                extra.pop("characterPersona", None)
            if outline_requested:
                outline = clean_body(payload.get("destiny_outline", ""), "人物大纲").strip()
                if outline:
                    extra["destinyOutline"] = outline
                else:
                    extra.pop("destinyOutline", None)
            connection.execute(
                "UPDATE entities SET extra_json=? WHERE id=?",
                (json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(",", ":")), identifier),
            )

    def create_plot(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())
        chapter_number = payload.get("chapter_number")
        title = (
            f"第 {int(chapter_number)} 章"
            if chapter_number is not None
            else clean_text(payload.get("title"), "剧情标题", required=True)
        )
        body = clean_body(payload.get("body", ""), "剧情正文")

        def mutation(connection: sqlite3.Connection):
            stable = clean_text(payload.get("stable_id"), "剧情 ID", 60) or self._next_numeric_id(connection, self.project_id, "plot")
            identifier = self._create_entity(connection, "plot", stable, title, now)
            chapter = payload.get("chapter_id") or None
            if chapter and not connection.execute("SELECT 1 FROM active_chapters WHERE entity_id=?", (chapter,)).fetchone():
                raise DomainError("篇章不存在")
            rank = self._rank_after(connection, "plots", payload.get("after_entity_id"))
            connection.execute(
                """
                INSERT INTO plots(entity_id, chapter_id, sort_key, summary, body_markdown, status, accent, is_key, is_climax)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier, chapter, rank, clean_text(payload.get("summary", ""), "剧情摘要", 1000),
                    body, clean_text(payload.get("status", "草稿"), "剧情状态", 40, required=True),
                    clean_color(payload.get("accent")), int(bool(payload.get("key"))), int(bool(payload.get("climax"))),
                ),
            )
            self._replace_plot_collections(connection, identifier, payload, rank, now)
            self._replace_entity_references(connection, identifier, payload)
            if chapter_number is not None:
                self._apply_plot_chapter_number(
                    connection, identifier, int(chapter_number), bool(payload.get("shift_following")), now
                )
            return {"entityId": identifier}

        return self.uow.mutate(
            base_revision=base_revision, label=f"新建剧情：{title}", action="create",
            entity_kind="plot", callback=mutation,
        )

    def update_plot(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())
        chapter_number = payload.get("chapter_number")

        def mutation(connection: sqlite3.Connection):
            entity = self._active_entity(connection, identifier, "plot")
            row = connection.execute("SELECT * FROM plots WHERE entity_id=?", (identifier,)).fetchone()
            updates: dict[str, Any] = {}
            mappings = {
                "chapter_id": ("chapter_id", lambda value: value or None),
                "title": ("__title", lambda value: clean_text(value, "剧情标题", required=True)),
                "summary": ("summary", lambda value: clean_text(value, "剧情摘要", 1000)),
                "body": ("body_markdown", lambda value: clean_body(value, "剧情正文")),
                "status": ("status", lambda value: clean_text(value, "剧情状态", 40, required=True)),
                "accent": ("accent", clean_color), "key": ("is_key", lambda value: int(bool(value))),
                "climax": ("is_climax", lambda value: int(bool(value))),
            }
            if chapter_number is not None:
                mappings.pop("title")
            for key, (column, cleaner) in mappings.items():
                if key in payload:
                    updates[column] = cleaner(payload[key])
            if "chapter_id" in updates and updates["chapter_id"] and not connection.execute(
                "SELECT 1 FROM active_chapters WHERE entity_id=?", (updates["chapter_id"],)
            ).fetchone():
                raise DomainError("篇章不存在")
            if "__title" in updates:
                connection.execute("UPDATE entities SET title=? WHERE id=?", (updates.pop("__title"), identifier))
            if updates:
                connection.execute(
                    f"UPDATE plots SET {', '.join(column+'=?' for column in updates)} WHERE entity_id=?",
                    tuple(updates.values()) + (identifier,),
                )
            self._replace_plot_collections(connection, identifier, payload, str(row["sort_key"]), now)
            self._replace_entity_references(connection, identifier, payload)
            if chapter_number is not None:
                self._apply_plot_chapter_number(
                    connection, identifier, int(chapter_number), bool(payload.get("shift_following")), now
                )
            connection.execute("UPDATE entities SET revision=revision+1, updated_at=? WHERE id=?", (now, identifier))
            return {"entityId": identifier, "title": entity["title"]}

        return self.uow.mutate(
            base_revision=base_revision, label=f"编辑剧情：{self._title(identifier)}", action="update",
            entity_kind="plot", callback=mutation, expected_entity_id=identifier,
            expected_entity_revision=payload.get("entity_revision"),
        )

    def move_plot_to_fragment(self, identifier: str, base_revision: int) -> MutationResult:
        now = int(time.time())
        source_title = self._title(identifier)

        def mutation(connection: sqlite3.Connection):
            entity = self._active_entity(connection, identifier, "plot")
            row = connection.execute(
                "SELECT * FROM plots WHERE entity_id=?", (identifier,)
            ).fetchone()
            tags = [
                str(item[0]) for item in connection.execute(
                    "SELECT tag FROM plot_tags WHERE plot_id=? ORDER BY position",
                    (identifier,),
                )
            ]
            references = list(dict.fromkeys(
                str(item[0]) for item in connection.execute(
                    """
                    SELECT target_entity_id FROM active_entity_references
                    WHERE source_entity_id=? AND context='body'
                    UNION
                    SELECT character_id FROM plot_characters WHERE plot_id=?
                    UNION
                    SELECT entry_id FROM plot_entries WHERE plot_id=?
                    """,
                    (identifier, identifier, identifier),
                )
                if str(item[0]) != identifier
            ))
            stable = self._next_numeric_id(connection, self.project_id, "fragment")
            target_id = self._create_entity(
                connection, "fragment", stable, str(entity["title"]), now
            )
            connection.execute(
                """
                INSERT INTO fragments(entity_id, body_markdown, status, accent)
                VALUES(?, ?, ?, ?)
                """,
                (
                    target_id,
                    str(row["body_markdown"]),
                    str(row["status"]),
                    str(row["accent"]),
                ),
            )
            self._replace_values(
                connection, "fragment_tags", "fragment_id", target_id, "tag", tags
            )
            self._replace_entity_references(
                connection, target_id, {"references": references}
            )
            connection.execute(
                "UPDATE entities SET extra_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "convertedFrom": identifier,
                            "convertedFromKind": "plot",
                            "plotSummary": str(row["summary"]),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    target_id,
                ),
            )
            self._move_references_and_assets(connection, identifier, target_id)
            self._soft_delete_converted_source(connection, identifier, "plot", now)
            return {"entityId": target_id, "sourceEntityId": identifier}

        return self.uow.mutate(
            base_revision=base_revision,
            label=f"剧情放入碎片：{source_title}",
            action="convert",
            entity_kind="fragment",
            callback=mutation,
            details={"sourceEntityId": identifier, "targetKind": "fragment"},
            now=now,
        )

    def move_fragment_to_plot(self, identifier: str, base_revision: int) -> MutationResult:
        now = int(time.time())
        source_title = self._title(identifier)

        def mutation(connection: sqlite3.Connection):
            self._active_entity(connection, identifier, "fragment")
            row = connection.execute(
                "SELECT * FROM fragments WHERE entity_id=?", (identifier,)
            ).fetchone()
            tags = [
                str(item[0]) for item in connection.execute(
                    "SELECT tag FROM fragment_tags WHERE fragment_id=? ORDER BY position",
                    (identifier,),
                )
            ]
            references = [
                str(item[0]) for item in connection.execute(
                    """
                    SELECT target_entity_id FROM active_entity_references
                    WHERE source_entity_id=? AND context='body'
                    """,
                    (identifier,),
                )
                if str(item[0]) != identifier
            ]
            entries = [
                target_id for target_id in references
                if connection.execute(
                    "SELECT 1 FROM active_entities WHERE id=? AND kind='entry'",
                    (target_id,),
                ).fetchone()
            ]
            numbered = [
                int(match.group(1))
                for item in connection.execute(
                    "SELECT title FROM active_plots ORDER BY sort_key"
                )
                if (match := PLOT_CHAPTER_TITLE.fullmatch(str(item[0]).strip()))
            ]
            active_count = int(connection.execute(
                "SELECT COUNT(*) FROM active_plots"
            ).fetchone()[0])
            chapter_number = max(numbered + [active_count], default=0) + 1
            title = f"第 {chapter_number} 章"
            stable = self._next_numeric_id(connection, self.project_id, "plot")
            target_id = self._create_entity(connection, "plot", stable, title, now)
            rank = self._next_rank(connection, "plots")
            connection.execute(
                """
                INSERT INTO plots(
                    entity_id, chapter_id, sort_key, summary, body_markdown,
                    status, accent, is_key, is_climax
                ) VALUES(?, NULL, ?, ?, ?, '草稿', ?, 0, 0)
                """,
                (
                    target_id,
                    rank,
                    source_title,
                    str(row["body_markdown"]),
                    str(row["accent"]),
                ),
            )
            target_payload = {
                "body": str(row["body_markdown"]),
                "summary": source_title,
                "tags": tags,
                "entries": entries,
                "references": references,
                "chapter_number": chapter_number,
            }
            self._replace_plot_collections(
                connection, target_id, target_payload, rank, now
            )
            self._replace_entity_references(connection, target_id, target_payload)
            connection.execute(
                "UPDATE entities SET extra_json=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "convertedFrom": identifier,
                            "convertedFromKind": "fragment",
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    target_id,
                ),
            )
            self._move_references_and_assets(connection, identifier, target_id)
            self._soft_delete_converted_source(connection, identifier, "fragment", now)
            return {
                "entityId": target_id,
                "sourceEntityId": identifier,
                "chapterNumber": chapter_number,
            }

        return self.uow.mutate(
            base_revision=base_revision,
            label=f"碎片放入剧情：{source_title}",
            action="convert",
            entity_kind="plot",
            callback=mutation,
            details={"sourceEntityId": identifier, "targetKind": "plot"},
            now=now,
        )

    def _replace_plot_collections(
        self, connection: sqlite3.Connection, identifier: str, payload: dict[str, Any],
        story_rank: str, now: int,
    ) -> None:
        if "tags" in payload:
            self._replace_values(connection, "plot_tags", "plot_id", identifier, "tag", clean_values(payload["tags"], "剧情标签"))
        self._archive_unknown_plot_speakers(connection, identifier, payload, now)
        automatic_people = self._automatic_plot_people(connection, identifier, payload)
        connection.execute("DELETE FROM plot_characters WHERE plot_id=?", (identifier,))
        connection.executemany(
            "INSERT INTO plot_characters(plot_id, character_id, source) VALUES(?, ?, 'body')",
            [(identifier, character_id) for character_id in automatic_people],
        )
        relation_specs = (
            ("entries", "plot_entries", "entry_id", "active_entries", "设定"),
        )
        for key, table, target_column, view, label in relation_specs:
            if key not in payload:
                continue
            values = self._require_targets(connection, clean_values(payload[key], label), view, label)
            connection.execute(f"DELETE FROM {table} WHERE plot_id=?", (identifier,))
            connection.executemany(
                f"INSERT INTO {table}(plot_id, {target_column}) VALUES(?, ?)",
                [(identifier, value) for value in values],
            )
        if "lanes" in payload:
            values = self._require_targets(
                connection, clean_values(payload["lanes"], "剧情线"), "active_timeline_lines", "剧情线"
            )
            self._sync_plot_timeline_story_sort_keys(connection)
            connection.execute("DELETE FROM plot_timeline_lines WHERE plot_id=?", (identifier,))
            connection.executemany(
                "INSERT INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)",
                [(identifier, value, story_rank) for value in values],
            )

    def create_entry(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._create_text_record("entry", base_revision, payload)

    def update_entry(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._update_text_record("entry", identifier, base_revision, payload)

    def create_fragment(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._create_text_record("fragment", base_revision, payload)

    def update_fragment(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._update_text_record("fragment", identifier, base_revision, payload)

    def _create_text_record(self, kind: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())
        title_key = "name" if kind == "entry" else "title"
        title = clean_text(payload.get(title_key), "名称" if kind == "entry" else "标题", required=True)
        requested_stable = clean_text(payload.get("stable_id"), "稳定 ID", 80)
        if requested_stable and not STABLE_TEXT.fullmatch(requested_stable):
            raise DomainError("稳定 ID 只能包含英文字母、数字、横线和下划线")

        def mutation(connection: sqlite3.Connection):
            stable = requested_stable or self._next_numeric_id(connection, self.project_id, kind)
            table = "entries" if kind == "entry" else "fragments"
            name_column = "name" if kind == "entry" else None
            if name_column and connection.execute(f"SELECT 1 FROM {table} WHERE {name_column}=?", (title,)).fetchone():
                raise ConflictError(f"名称“{title}”已经存在或在回收站中")
            identifier = self._create_entity(connection, kind, stable, title, now)
            if kind == "entry":
                connection.execute(
                    "INSERT INTO entries(entity_id, name, type, subtype, area, body_markdown, status, accent) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identifier, title, clean_text(payload.get("type"), "设定类型", 60, required=True),
                        clean_text(payload.get("subtype", ""), "设定子类型", 80), clean_text(payload.get("area", ""), "区域", 80),
                        clean_body(payload.get("body", ""), "设定正文"), clean_text(payload.get("status", ""), "状态", 40),
                        clean_color(payload.get("accent")),
                    ),
                )
            else:
                connection.execute(
                    "INSERT INTO fragments(entity_id, body_markdown, status, accent) VALUES(?, ?, ?, ?)",
                    (identifier, clean_body(payload.get("body", ""), "碎片正文"), clean_text(payload.get("status", ""), "状态", 40), clean_color(payload.get("accent"))),
                )
            self._replace_text_collections(connection, kind, identifier, payload)
            self._replace_entity_references(connection, identifier, payload)
            return {"entityId": identifier}

        return self.uow.mutate(
            base_revision=base_revision, label=f"新建{'设定' if kind == 'entry' else '碎片'}：{title}",
            action="create", entity_kind=kind, callback=mutation,
        )

    def _update_text_record(
        self, kind: str, identifier: str, base_revision: int, payload: dict[str, Any]
    ) -> MutationResult:
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            entity = self._active_entity(connection, identifier, kind)
            table = "entries" if kind == "entry" else "fragments"
            updates: dict[str, Any] = {}
            if kind == "entry":
                mappings = {
                    "name": ("name", lambda value: clean_text(value, "设定名称", required=True)),
                    "type": ("type", lambda value: clean_text(value, "设定类型", 60, required=True)),
                    "subtype": ("subtype", lambda value: clean_text(value, "子类型", 80)),
                    "area": ("area", lambda value: clean_text(value, "区域", 80)),
                    "body": ("body_markdown", lambda value: clean_body(value, "设定正文")),
                    "status": ("status", lambda value: clean_text(value, "状态", 40)),
                    "accent": ("accent", clean_color),
                }
            else:
                mappings = {
                    "title": ("__title", lambda value: clean_text(value, "碎片标题", required=True)),
                    "body": ("body_markdown", lambda value: clean_body(value, "碎片正文")),
                    "status": ("status", lambda value: clean_text(value, "状态", 40)),
                    "accent": ("accent", clean_color),
                }
            for key, (column, cleaner) in mappings.items():
                if key in payload:
                    updates[column] = cleaner(payload[key])
            title_value = updates.pop("__title", updates.get("name"))
            if kind == "entry" and "name" in updates and str(updates["name"]) != str(entity["title"]):
                duplicate = connection.execute("SELECT 1 FROM entries WHERE name=? AND entity_id<>?", (updates["name"], identifier)).fetchone()
                if duplicate:
                    raise ConflictError(f"名称“{updates['name']}”已经存在或在回收站中")
                self._replace_reference_display_text(
                    connection, identifier, str(entity["title"]), str(updates["name"]), now
                )
            if title_value is not None:
                connection.execute("UPDATE entities SET title=? WHERE id=?", (title_value, identifier))
            if updates:
                connection.execute(
                    f"UPDATE {table} SET {', '.join(column+'=?' for column in updates)} WHERE entity_id=?",
                    tuple(updates.values()) + (identifier,),
                )
            self._replace_text_collections(connection, kind, identifier, payload)
            self._replace_entity_references(connection, identifier, payload)
            connection.execute("UPDATE entities SET revision=revision+1, updated_at=? WHERE id=?", (now, identifier))
            return {"entityId": identifier, "title": title_value or entity["title"]}

        current_title = self._title(identifier)
        renamed_title = clean_text(payload.get("name"), "设定名称") if kind == "entry" and "name" in payload else ""
        return self.uow.mutate(
            base_revision=base_revision,
            label=(f"重命名设定：{current_title} → {renamed_title}" if renamed_title and renamed_title != current_title else f"编辑{'设定' if kind == 'entry' else '碎片'}：{current_title}"),
            action=("rename" if renamed_title and renamed_title != current_title else "update"),
            entity_kind=kind, callback=mutation,
        )

    def _replace_text_collections(
        self, connection: sqlite3.Connection, kind: str, identifier: str, payload: dict[str, Any]
    ) -> None:
        if kind == "entry":
            if "aliases" in payload:
                self._replace_values(connection, "entry_aliases", "entry_id", identifier, "alias", clean_values(payload["aliases"], "别名"))
            if "tags" in payload:
                self._replace_values(connection, "entry_tags", "entry_id", identifier, "tag", clean_values(payload["tags"], "标签"))
            if "people" in payload:
                people = self._require_targets(connection, clean_values(payload["people"], "人物"), "active_characters", "人物")
                connection.execute("DELETE FROM entry_characters WHERE entry_id=?", (identifier,))
                connection.executemany("INSERT INTO entry_characters(entry_id, character_id) VALUES(?, ?)", [(identifier, value) for value in people])
        elif "tags" in payload:
            self._replace_values(connection, "fragment_tags", "fragment_id", identifier, "tag", clean_values(payload["tags"], "标签"))

    def create_relationship(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())
        from_id = str(payload.get("from_character_id") or "")
        to_id = str(payload.get("to_character_id") or "")
        label = clean_text(payload.get("label", ""), "关系名称", 80)

        def mutation(connection: sqlite3.Connection):
            self._require_targets(connection, [from_id, to_id], "active_characters", "人物")
            if from_id == to_id:
                raise DomainError("人物不能与自己建立关系")
            stable = "__".join(value.removeprefix("character:") for value in (from_id, to_id))
            identifier = self._create_entity(connection, "relationship", stable, label or stable, now)
            connection.execute(
                """
                INSERT INTO relationships(
                    entity_id, from_character_id, to_character_id, from_role, to_role,
                    label, type, color, body_markdown
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier, from_id, to_id, clean_text(payload.get("from_role", ""), "关系角色", 80),
                    clean_text(payload.get("to_role", ""), "关系角色", 80), label,
                    clean_text(payload.get("type", ""), "关系类型", 60), clean_color(payload.get("color"), "#8b95a7"),
                    clean_body(payload.get("body", ""), "关系说明"),
                ),
            )
            self._replace_entity_references(connection, identifier, payload)
            return {"entityId": identifier}

        return self.uow.mutate(
            base_revision=base_revision, label=f"新建人物关系：{label or '未命名'}", action="create",
            entity_kind="relationship", callback=mutation,
        )

    def update_relationship(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        now = int(time.time())

        def mutation(connection: sqlite3.Connection):
            entity = self._active_entity(connection, identifier, "relationship")
            updates: dict[str, Any] = {}
            mappings = {
                "from_role": ("from_role", lambda value: clean_text(value, "关系角色", 80)),
                "to_role": ("to_role", lambda value: clean_text(value, "关系角色", 80)),
                "label": ("label", lambda value: clean_text(value, "关系名称", 80)),
                "type": ("type", lambda value: clean_text(value, "关系类型", 60)),
                "color": ("color", lambda value: clean_color(value, "#8b95a7")),
                "body": ("body_markdown", lambda value: clean_body(value, "关系说明")),
            }
            for key, (column, cleaner) in mappings.items():
                if key in payload:
                    updates[column] = cleaner(payload[key])
            if "label" in updates:
                connection.execute("UPDATE entities SET title=? WHERE id=?", (updates["label"] or entity["stable_id"], identifier))
            if updates:
                connection.execute(
                    f"UPDATE relationships SET {', '.join(column+'=?' for column in updates)} WHERE entity_id=?",
                    tuple(updates.values()) + (identifier,),
                )
            self._replace_entity_references(connection, identifier, payload)
            connection.execute("UPDATE entities SET revision=revision+1, updated_at=? WHERE id=?", (now, identifier))
            return {"entityId": identifier}

        return self.uow.mutate(
            base_revision=base_revision, label=f"编辑人物关系：{self._title(identifier)}", action="update",
            entity_kind="relationship", callback=mutation,
        )

    def _title(self, identifier: str) -> str:
        with self.database.read() as connection:
            row = connection.execute("SELECT title FROM entities WHERE id=?", (identifier,)).fetchone()
            return str(row[0]) if row else "内容"
