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
STORY_POSITION_MODES = {"follow_reading", "before", "after", "fixed"}
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
FRAGMENT_CHAPTER_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?第\s*"
    r"([0-9〇零一二三四五六七八九十百千万亿兆京垓秭穰沟溝涧澗正载載兩两"
    r"壹贰叁肆伍陆柒捌玖拾佰仟萬億]+)"
    r"\s*章\s*[：:]\s*(.+?)\s*$"
)
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
CHINESE_DIGITS = {
    "零": 0, "〇": 0,
    "一": 1, "壹": 1,
    "二": 2, "贰": 2, "两": 2, "兩": 2,
    "三": 3, "叁": 3,
    "四": 4, "肆": 4,
    "五": 5, "伍": 5,
    "六": 6, "陆": 6,
    "七": 7, "柒": 7,
    "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
CHINESE_SMALL_UNITS = {
    "十": 10, "拾": 10,
    "百": 100, "佰": 100,
    "千": 1000, "仟": 1000,
}
CHINESE_LARGE_UNITS = {
    "万": 10**4, "萬": 10**4,
    "亿": 10**8, "億": 10**8,
    "兆": 10**12,
    "京": 10**16,
    "垓": 10**20,
    "秭": 10**24,
    "穰": 10**28,
    "沟": 10**32, "溝": 10**32,
    "涧": 10**36, "澗": 10**36,
    "正": 10**40,
    "载": 10**44, "載": 10**44,
}


def parse_positive_chapter_number(value: str) -> int:
    source = str(value or "").strip()
    if source.isdigit():
        result = int(source)
    elif source and all(character in CHINESE_DIGITS for character in source):
        result = int("".join(str(CHINESE_DIGITS[character]) for character in source))
    else:
        total = 0
        section = 0
        number: int | None = None
        previous_small_unit = 10**9
        for character in source:
            if character in CHINESE_DIGITS:
                number = CHINESE_DIGITS[character]
                continue
            if character in CHINESE_SMALL_UNITS:
                unit = CHINESE_SMALL_UNITS[character]
                if unit >= previous_small_unit:
                    raise DomainError(f"章号“{source}”不是有效的中文数字")
                section += (1 if number is None else number) * unit
                number = None
                previous_small_unit = unit
                continue
            if character in CHINESE_LARGE_UNITS:
                unit = CHINESE_LARGE_UNITS[character]
                section += 0 if number is None else number
                if section:
                    total += section * unit
                elif total:
                    total *= unit
                else:
                    total = unit
                section = 0
                number = None
                previous_small_unit = 10**9
                continue
            raise DomainError(f"章号“{source}”不是有效的正整数")
        result = total + section + (0 if number is None else number)
    if result <= 0:
        raise DomainError("章号必须是正整数")
    return result


def _clipboard_title_and_body(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        raise DomainError("剪贴板里没有可导入的文字")
    first = lines[first_index].strip()
    markdown_title = re.fullmatch(r"#{1,6}\s+(.+?)\s*#*\s*", first)
    clean_first = (markdown_title.group(1) if markdown_title else first).strip()
    clean_first = re.sub(r"^[《「『【](.*)[》」』】]$", r"\1", clean_first).strip()
    if markdown_title or len(clean_first) <= 80:
        body = "\n".join(lines[:first_index] + lines[first_index + 1:]).strip()
        title = clean_first
    else:
        body = text.strip()
        title = clean_first[:36].rstrip() + ("…" if len(clean_first) > 36 else "")
    return clean_text(title, "自动读取的标题", required=True), clean_body(body, "碎片正文")


def parse_fragment_clipboard(text: str) -> dict[str, Any]:
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not source:
        raise DomainError("剪贴板里没有可导入的文字")
    lines = source.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = FRAGMENT_CHAPTER_HEADING.fullmatch(line)
        if not match:
            continue
        number = parse_positive_chapter_number(match.group(1))
        title = clean_text(match.group(2), f"第 {number} 章标题", 100, required=True)
        headings.append((index, number, title))
    if not headings:
        title, body = _clipboard_title_and_body(source)
        return {"kind": "chapter", "title": title, "body": body}

    numbers = [number for _, number, _ in headings]
    duplicates = sorted({number for number in numbers if numbers.count(number) > 1})
    if duplicates:
        labels = "、".join(str(number) for number in duplicates)
        raise DomainError(f"章号不能重复：第 {labels} 章")

    preamble = "\n".join(lines[:headings[0][0]]).strip()
    overview = ""
    if preamble:
        line_title, overview = _clipboard_title_and_body(preamble)
    else:
        first_title = headings[0][2]
        last_title = headings[-1][2]
        line_title = (
            f"{first_title} · 故事线"
            if len(headings) == 1
            else f"{first_title}—{last_title}"
        )
        line_title = clean_text(line_title[:120], "剧情线标题", required=True)

    chapters = []
    for heading_index, (line_index, number, title) in enumerate(headings):
        next_line = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
        body = clean_body(
            "\n".join(lines[line_index + 1:next_line]).strip(),
            f"第 {number} 章正文",
        )
        chapters.append({
            "number": number,
            "title": title,
            "body": body,
        })
    chapters.sort(key=lambda item: int(item["number"]))
    return {
        "kind": "line",
        "title": line_title,
        "body": overview,
        "chapters": chapters,
    }


def stored_fragment_chapter_number(
    extra: dict[str, Any],
    title: str,
    fragment_order: int,
    parent_id: str | None,
) -> int | None:
    raw = extra.get("chapterNumber")
    if isinstance(raw, int) and raw > 0:
        return raw
    match = re.match(r"^第\s*(\d+)\s*章(?:\s*[：:·—-]\s*|\s+)", str(title or ""))
    if match:
        return int(match.group(1))
    return fragment_order + 1 if parent_id else None


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

    @staticmethod
    def _main_line_id(connection: sqlite3.Connection) -> str | None:
        row = connection.execute(
            "SELECT main_line_id FROM timeline_settings LIMIT 1"
        ).fetchone()
        return str(row[0]) if row and row[0] else None

    @staticmethod
    def _story_key(value: Any, label: str = "故事时间位置") -> str:
        text = str(value or "").strip()
        if not text.isdigit():
            raise DomainError(f"{label}必须是非负整数位置")
        return f"{int(text):024d}"

    @staticmethod
    def _story_reserved_keys(connection: sqlite3.Connection) -> set[str]:
        return {
            str(row[0])
            for row in connection.execute(
                """
                SELECT ptl.story_sort_key
                FROM plot_timeline_lines ptl
                JOIN entities plot_entity ON plot_entity.id=ptl.plot_id
                WHERE plot_entity.deleted_at IS NOT NULL
                """
            )
            if str(row[0]).isdigit()
        }

    @staticmethod
    def _resequence_story_keys(connection: sqlite3.Connection) -> None:
        """Compact story positions without consulting reading order."""
        rows = list(connection.execute(
            "SELECT entity_id, story_sort_key FROM active_plots ORDER BY story_sort_key, entity_id"
        ))
        reserved = ContentService._story_reserved_keys(connection)
        target: dict[str, str] = {}
        index = 1
        for row in rows:
            candidate = f"{index * RANK_STEP:024d}"
            while candidate in reserved:
                index += 1
                candidate = f"{index * RANK_STEP:024d}"
            target[str(row["entity_id"])] = candidate
            index += 1
        active_nodes = list(connection.execute(
            "SELECT plot_id, line_id FROM active_timeline_nodes ORDER BY line_id, plot_id"
        ))
        for index, row in enumerate(active_nodes, start=1):
            connection.execute(
                "UPDATE plot_timeline_lines SET story_sort_key=? WHERE plot_id=? AND line_id=?",
                (f"~story-resequence-{index:06d}", row["plot_id"], row["line_id"]),
            )
        for plot_id, story_key in target.items():
            connection.execute(
                "UPDATE plots SET story_sort_key=? WHERE entity_id=?",
                (story_key, plot_id),
            )
        for plot_id, story_key in target.items():
            connection.execute(
                "UPDATE plot_timeline_lines SET story_sort_key=? WHERE plot_id=?",
                (story_key, plot_id),
            )

    @staticmethod
    def _story_key_before_or_after(
        connection: sqlite3.Connection, anchor_id: str, side: str, exclude_id: str | None = None
    ) -> str:
        rows = list(connection.execute(
            """
            SELECT entity_id, story_sort_key
            FROM active_plots
            WHERE (? IS NULL OR entity_id<>?)
            ORDER BY story_sort_key, entity_id
            """, (exclude_id, exclude_id)
        ))
        anchor_index = next((index for index, row in enumerate(rows) if str(row["entity_id"]) == anchor_id), None)
        if anchor_index is None:
            raise DomainError("故事时间锚点不存在")
        if side == "before":
            upper = int(rows[anchor_index]["story_sort_key"])
            lower = int(rows[anchor_index - 1]["story_sort_key"]) if anchor_index else 0
        else:
            lower = int(rows[anchor_index]["story_sort_key"])
            upper = int(rows[anchor_index + 1]["story_sort_key"]) if anchor_index + 1 < len(rows) else lower + RANK_STEP
        if upper - lower <= 1:
            ContentService._resequence_story_keys(connection)
            return ContentService._story_key_before_or_after(connection, anchor_id, side, exclude_id)
        candidate = (lower + upper) // 2
        reserved = ContentService._story_reserved_keys(connection)
        while str(candidate).zfill(24) in reserved:
            candidate += 1
            if candidate >= upper:
                ContentService._resequence_story_keys(connection)
                return ContentService._story_key_before_or_after(connection, anchor_id, side, exclude_id)
        return f"{candidate:024d}"

    @staticmethod
    def _sync_follow_reading_story_sort_keys(connection: sqlite3.Connection) -> None:
        """Synchronize only plots explicitly following reading order."""
        ordered = [
            str(row["entity_id"])
            for row in connection.execute("SELECT entity_id FROM active_plots ORDER BY sort_key, entity_id")
        ]
        if not ordered:
            return
        rows = {
            str(row["entity_id"]): row
            for row in connection.execute(
                """
                SELECT p.entity_id, p.story_sort_key, p.story_order_mode,
                       COALESCE(MIN(ptl.story_sort_key), p.story_sort_key) AS effective_story_sort_key
                FROM active_plots p
                LEFT JOIN active_timeline_nodes ptl ON ptl.plot_id=p.entity_id
                GROUP BY p.entity_id
                """
            )
        }
        fixed_keys = {
            str(row["story_sort_key"])
            for row in rows.values()
            if str(row["story_order_mode"]) == "fixed" and str(row["story_sort_key"]).isdigit()
        }
        existing_keys = {
            str(row["effective_story_sort_key"])
            for row in rows.values()
            if str(row["effective_story_sort_key"]).isdigit()
        }
        slots = sorted(existing_keys | fixed_keys, key=lambda value: (int(value), value))
        reserved = ContentService._story_reserved_keys(connection)
        next_index = 1
        while len(slots) < len(ordered):
            candidate = f"{next_index * RANK_STEP:024d}"
            next_index += 1
            if candidate not in reserved and candidate not in slots:
                slots.append(candidate)
                slots.sort(key=lambda value: (int(value), value))
        if len(slots) > len(ordered):
            slots = sorted(fixed_keys | set(slots[:len(ordered)]), key=lambda value: (int(value), value))[:len(ordered)]
            while len(slots) < len(ordered):
                candidate = f"{next_index * RANK_STEP:024d}"
                next_index += 1
                if candidate not in reserved and candidate not in slots:
                    slots.append(candidate)
                    slots.sort(key=lambda value: (int(value), value))
        target = {
            plot_id: rows[plot_id]["story_sort_key"]
            for plot_id in ordered
            if str(rows[plot_id]["story_order_mode"]) == "fixed"
        }
        available = [slot for slot in slots if slot not in set(target.values())]
        for plot_id in ordered:
            if plot_id not in target:
                target[plot_id] = available.pop(0)
        changed = [
            plot_id for plot_id in ordered
            if str(rows[plot_id]["story_sort_key"]) != str(target[plot_id])
            or str(rows[plot_id]["effective_story_sort_key"]) != str(target[plot_id])
        ]
        if not changed:
            return
        active_nodes = list(connection.execute(
            "SELECT plot_id, line_id FROM active_timeline_nodes ORDER BY line_id, plot_id"
        ))
        for index, row in enumerate(active_nodes, start=1):
            if str(row["plot_id"]) in changed:
                connection.execute(
                    "UPDATE plot_timeline_lines SET story_sort_key=? WHERE plot_id=? AND line_id=?",
                    (f"~story-sync-{index:06d}", row["plot_id"], row["line_id"]),
                )
        for plot_id in changed:
            connection.execute("UPDATE plots SET story_sort_key=? WHERE entity_id=?", (target[plot_id], plot_id))
            connection.execute("UPDATE plot_timeline_lines SET story_sort_key=? WHERE plot_id=?", (target[plot_id], plot_id))
        ContentService._refresh_story_anchors(connection)

    @staticmethod
    def _refresh_story_anchors(connection: sqlite3.Connection) -> None:
        anchored = list(connection.execute(
            """
            SELECT entity_id, story_anchor_plot_id, story_anchor_side, story_sort_key
            FROM active_plots
            WHERE story_order_mode='fixed' AND story_anchor_plot_id IS NOT NULL
            ORDER BY story_sort_key, entity_id
            """
        ))
        for row in anchored:
            anchor = connection.execute(
                "SELECT story_sort_key FROM active_plots WHERE entity_id=?",
                (row["story_anchor_plot_id"],),
            ).fetchone()
            if not anchor:
                continue
            current = int(row["story_sort_key"])
            anchor_key = int(anchor[0])
            side = str(row["story_anchor_side"] or "")
            if (side == "before" and current < anchor_key) or (side == "after" and current > anchor_key):
                continue
            next_key = ContentService._story_key_before_or_after(
                connection, str(row["story_anchor_plot_id"]), side, str(row["entity_id"])
            )
            connection.execute("UPDATE plots SET story_sort_key=? WHERE entity_id=?", (next_key, row["entity_id"]))
            connection.execute("UPDATE plot_timeline_lines SET story_sort_key=? WHERE plot_id=?", (next_key, row["entity_id"]))

    def _apply_story_position(
        self,
        connection: sqlite3.Connection,
        identifier: str,
        payload: dict[str, Any],
        default_key: str,
        *,
        is_create: bool,
    ) -> None:
        existing = connection.execute(
            "SELECT story_sort_key, story_order_mode, story_anchor_plot_id, story_anchor_side FROM plots WHERE entity_id=?",
            (identifier,),
        ).fetchone()
        requested = payload.get("story_position_mode")
        mode = str(requested or ("follow_reading" if is_create else existing["story_order_mode"] or "follow_reading"))
        if mode not in STORY_POSITION_MODES:
            raise DomainError("故事时间位置选项无效")
        if mode == "follow_reading":
            connection.execute(
                "UPDATE plots SET story_sort_key=?, story_order_mode='follow_reading', story_anchor_plot_id=NULL, story_anchor_side=NULL WHERE entity_id=?",
                (default_key, identifier),
            )
            return
        anchor_id = str(payload.get("story_anchor_plot_id") or "")
        side = mode if mode in {"before", "after"} else None
        if side:
            if not anchor_id or anchor_id == identifier:
                raise DomainError("请选择有效的故事时间锚点剧情")
            if not connection.execute("SELECT 1 FROM active_plots WHERE entity_id=?", (anchor_id,)).fetchone():
                raise DomainError("故事时间锚点不存在或已删除")
            story_key = self._story_key_before_or_after(connection, anchor_id, side, identifier)
        else:
            story_key = self._story_key(payload.get("story_sort_key") or (existing["story_sort_key"] if existing else default_key))
            anchor_id = ""
        connection.execute(
            "UPDATE plots SET story_sort_key=?, story_order_mode='fixed', story_anchor_plot_id=?, story_anchor_side=? WHERE entity_id=?",
            (story_key, anchor_id or None, side, identifier),
        )

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
        ContentService._sync_follow_reading_story_sort_keys(connection)
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
    def _appearance_text(
        connection: sqlite3.Connection,
        identifier: str,
        payload: dict[str, Any],
        kind: str,
    ) -> str:
        if kind == "plot":
            row = connection.execute(
                "SELECT body_markdown, summary FROM plots WHERE entity_id=?", (identifier,)
            ).fetchone()
            return "\n".join((
                str(payload.get("summary", row["summary"] if row else "") or ""),
                str(payload.get("body", row["body_markdown"] if row else "") or ""),
            ))
        row = connection.execute(
            "SELECT body_markdown FROM fragments WHERE entity_id=?", (identifier,)
        ).fetchone()
        return str(payload.get("body", row["body_markdown"] if row else "") or "")

    def _automatic_text_people(
        self,
        connection: sqlite3.Connection,
        identifier: str,
        payload: dict[str, Any],
        kind: str,
    ) -> list[str]:
        text = self._appearance_text(connection, identifier, payload, kind)
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
        explicit_people = (
            self._require_targets(
                connection,
                clean_values(payload["people"], "出场人物", 200),
                "active_characters",
                "出场人物",
            )
            if "people" in payload
            else []
        )
        stable_references.update(explicit_people)
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
        for character_id in explicit_people:
            if character_id in result:
                continue
            row = connection.execute(
                "SELECT name FROM active_characters WHERE entity_id=?",
                (character_id,),
            ).fetchone()
            display_name = str(row[0]) if row else character_id
            raise DomainError(f"出场人物“{display_name}”没有出现在当前正文中")
        return result

    def _create_one_time_character(
        self,
        connection: sqlite3.Connection,
        name: str,
        source_title: str,
        source_id: str,
        archive_source: str,
        now: int,
    ) -> str:
        stable = self._next_numeric_id(connection, self.project_id, "character")
        character_id = self._create_entity(connection, "character", stable, name, now)
        intro = f"首次出场：{source_title}\n\n由正文中的出场人物自动归档。"
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
            (character_id, source_title),
        )
        connection.execute(
            "UPDATE entities SET extra_json=? WHERE id=?",
            (
                json.dumps(
                    {
                        "autoArchived": True,
                        "archiveSource": archive_source,
                        "sourceEntityId": source_id,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                character_id,
            ),
        )
        return character_id

    def _archive_manual_people(
        self,
        connection: sqlite3.Connection,
        identifier: str,
        payload: dict[str, Any],
        kind: str,
        now: int,
    ) -> list[str]:
        if "appearance_names" not in payload:
            return []
        names = clean_values(payload["appearance_names"], "出场人物", 200)
        if not names:
            return []
        text = self._appearance_text(connection, identifier, payload, kind)
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
        source_title = self._title(identifier)
        created: list[str] = []
        for name in names:
            if name not in text:
                raise DomainError(f"出场人物“{name}”没有出现在当前正文中")
            if name in known_labels:
                continue
            if name in GENERIC_SPEAKER_LABELS:
                raise DomainError(f"“{name}”是通用称谓，请填写正文中出现的具体人名")
            if not re.fullmatch(
                r"[\u3400-\u9fffA-Za-z][\u3400-\u9fffA-Za-z·•._ -]{1,39}",
                name,
            ):
                raise DomainError(f"“{name}”不像有效的人名")
            character_id = self._create_one_time_character(
                connection,
                name,
                source_title,
                identifier,
                f"{kind}-appearance",
                now,
            )
            known_labels.add(name)
            created.append(character_id)
        return created

    @staticmethod
    def _sync_character_references(
        connection: sqlite3.Connection,
        identifier: str,
        character_ids: list[str],
    ) -> None:
        existing = [
            str(row[0]) for row in connection.execute(
                """
                SELECT r.target_entity_id
                FROM entity_references r
                JOIN characters c ON c.entity_id=r.target_entity_id
                WHERE r.source_entity_id=? AND r.context='body'
                ORDER BY r.id
                """,
                (identifier,),
            )
        ]
        desired = set(character_ids)
        connection.executemany(
            """
            DELETE FROM entity_references
            WHERE source_entity_id=? AND target_entity_id=? AND context='body'
            """,
            [
                (identifier, character_id)
                for character_id in existing
                if character_id not in desired
            ],
        )
        connection.executemany(
            """
            INSERT INTO entity_references(
                source_entity_id, target_entity_id, context, marker, source
            ) VALUES(?, ?, 'body', ?, 'automatic')
            """,
            [
                (identifier, character_id, character_id)
                for character_id in character_ids
                if character_id not in existing
            ],
        )

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
            character_id = self._create_one_time_character(
                connection,
                name,
                plot_title,
                identifier,
                "plot-speaker",
                now,
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
            "SELECT DISTINCT source_entity_id FROM entity_references WHERE target_entity_id=? AND source='editor'",
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
                INSERT INTO plots(entity_id, chapter_id, sort_key, story_sort_key, story_order_mode, summary, body_markdown, status, accent, is_key, is_climax)
                VALUES(?, ?, ?, ?, 'follow_reading', ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier, chapter, rank, rank, clean_text(payload.get("summary", ""), "剧情摘要", 1000),
                    body, clean_text(payload.get("status", "草稿"), "剧情状态", 40, required=True),
                    clean_color(payload.get("accent")), int(bool(payload.get("key"))), int(bool(payload.get("climax"))),
                ),
            )
            self._apply_story_position(connection, identifier, payload, rank, is_create=True)
            automatic_people = self._replace_plot_collections(
                connection, identifier, payload, rank, now, default_main_line=True
            )
            self._replace_entity_references(connection, identifier, payload)
            self._sync_character_references(
                connection, identifier, automatic_people
            )
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
            if any(key in payload for key in ("story_position_mode", "story_anchor_plot_id", "story_sort_key")):
                self._apply_story_position(connection, identifier, payload, str(row["sort_key"]), is_create=False)
            automatic_people = self._replace_plot_collections(
                connection, identifier, payload, str(row["sort_key"]), now
            )
            self._replace_entity_references(connection, identifier, payload)
            self._sync_character_references(
                connection, identifier, automatic_people
            )
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
                            "fragmentType": "chapter",
                            "parentFragmentId": None,
                            "fragmentOrder": 0,
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
            entity = self._active_entity(connection, identifier, "fragment")
            fragment_extra = self._extra_dict(entity["extra_json"])
            if fragment_extra.get("fragmentType") == "line":
                raise DomainError("剧情线容器不能直接放入剧情，请展开后选择具体章节")
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
            planned_chapter_number: int | None = None
            parent_id = fragment_extra.get("parentFragmentId")
            parent_extra: dict[str, Any] | None = None
            if parent_id:
                parent = connection.execute(
                    "SELECT extra_json FROM active_fragments WHERE entity_id=?",
                    (str(parent_id),),
                ).fetchone()
                if parent:
                    parent_extra = self._extra_dict(parent["extra_json"])
                    plan = parent_extra.get("plotChapterPlan")
                    planned = plan.get(identifier) if isinstance(plan, dict) else None
                    if isinstance(planned, int) and 1 <= planned <= 99999:
                        planned_chapter_number = planned
            chapter_number = (
                planned_chapter_number
                if planned_chapter_number is not None
                else max(numbered + [active_count], default=0) + 1
            )
            title = f"第 {chapter_number} 章"
            stable = self._next_numeric_id(connection, self.project_id, "plot")
            target_id = self._create_entity(connection, "plot", stable, title, now)
            rank = self._next_rank(connection, "plots")
            connection.execute(
                """
                INSERT INTO plots(
                    entity_id, chapter_id, sort_key, story_sort_key, story_order_mode, summary, body_markdown,
                    status, accent, is_key, is_climax
                ) VALUES(?, NULL, ?, ?, 'follow_reading', ?, ?, '草稿', ?, 0, 0)
                """,
                (
                    target_id,
                    rank,
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
            automatic_people = self._replace_plot_collections(
                connection, target_id, target_payload, rank, now, default_main_line=True
            )
            self._replace_entity_references(connection, target_id, target_payload)
            if planned_chapter_number is not None:
                self._apply_plot_chapter_number(
                    connection,
                    target_id,
                    planned_chapter_number,
                    True,
                    now,
                )
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
            self._sync_character_references(
                connection, target_id, automatic_people
            )
            if parent_id and parent_extra is not None:
                plan = parent_extra.get("plotChapterPlan")
                if isinstance(plan, dict) and identifier in plan:
                    parent_extra["plotChapterPlan"] = {
                        key: value for key, value in plan.items() if key != identifier
                    }
                    connection.execute(
                        """
                        UPDATE entities
                        SET extra_json=?, revision=revision+1, updated_at=?
                        WHERE id=?
                        """,
                        (
                            json.dumps(
                                parent_extra,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            now,
                            str(parent_id),
                        ),
                    )
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
        story_rank: str, now: int, *, default_main_line: bool = False,
    ) -> list[str]:
        if "tags" in payload:
            self._replace_values(connection, "plot_tags", "plot_id", identifier, "tag", clean_values(payload["tags"], "剧情标签"))
        self._archive_manual_people(connection, identifier, payload, "plot", now)
        self._archive_unknown_plot_speakers(connection, identifier, payload, now)
        automatic_people = self._automatic_text_people(
            connection, identifier, payload, "plot"
        )
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
        if "lanes" in payload or default_main_line:
            values = self._require_targets(
                connection, clean_values(payload.get("lanes", []), "剧情线"), "active_timeline_lines", "剧情线"
            )
            if not values and default_main_line:
                main_line_id = self._main_line_id(connection)
                if main_line_id:
                    values = [main_line_id]
            if not values and not default_main_line:
                return automatic_people
            existing = {
                str(row["line_id"]): str(row["story_sort_key"])
                for row in connection.execute(
                    "SELECT line_id, story_sort_key FROM plot_timeline_lines WHERE plot_id=?",
                    (identifier,),
                )
            }
            current_story_key = str(connection.execute(
                "SELECT story_sort_key FROM plots WHERE entity_id=?", (identifier,)
            ).fetchone()[0])
            for line_id in values:
                conflict = connection.execute(
                    """
                    SELECT ptl.plot_id
                    FROM plot_timeline_lines ptl
                    JOIN active_plots p ON p.entity_id=ptl.plot_id
                    WHERE ptl.line_id=? AND ptl.story_sort_key=? AND ptl.plot_id<>?
                    LIMIT 1
                    """,
                    (line_id, current_story_key, identifier),
                ).fetchone()
                if conflict:
                    raise DomainError("这个故事时间位置在所选剧情线上已经被占用")
            if set(existing) != set(values) or any(value != current_story_key for value in existing.values()):
                connection.execute("DELETE FROM plot_timeline_lines WHERE plot_id=?", (identifier,))
                connection.executemany(
                    "INSERT INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)",
                    [(identifier, value, current_story_key) for value in values],
                )
        return automatic_people

    def create_entry(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._create_text_record("entry", base_revision, payload)

    def update_entry(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._update_text_record("entry", identifier, base_revision, payload)

    def create_fragment(self, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._create_text_record("fragment", base_revision, payload)

    def update_fragment(self, identifier: str, base_revision: int, payload: dict[str, Any]) -> MutationResult:
        return self._update_text_record("fragment", identifier, base_revision, payload)

    def import_fragments_from_clipboard(self, base_revision: int, text: str) -> MutationResult:
        parsed = parse_fragment_clipboard(text)
        now = int(time.time())

        def insert_fragment(
            connection: sqlite3.Connection,
            *,
            title: str,
            body: str,
            fragment_type: str,
            parent_id: str | None,
            fragment_order: int,
            chapter_number: int | None = None,
        ) -> str:
            clean_title = clean_text(title, "碎片标题", required=True)
            stable = self._next_numeric_id(connection, self.project_id, "fragment")
            identifier = self._create_entity(
                connection,
                "fragment",
                stable,
                clean_title,
                now,
            )
            connection.execute(
                """
                INSERT INTO fragments(entity_id, body_markdown, status, accent)
                VALUES(?, ?, '灵感', '#d65f8f')
                """,
                (identifier, clean_body(body, "碎片正文")),
            )
            extra = self._fragment_metadata(
                connection,
                {
                    "fragment_type": fragment_type,
                    "parent_fragment_id": parent_id,
                    "fragment_order": fragment_order,
                    "chapter_number": chapter_number,
                },
                identifier=identifier,
                creating=True,
            )
            connection.execute(
                "UPDATE entities SET extra_json=? WHERE id=?",
                (
                    json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    identifier,
                ),
            )
            return identifier

        def mutation(connection: sqlite3.Connection):
            if parsed["kind"] == "chapter":
                identifier = insert_fragment(
                    connection,
                    title=str(parsed["title"]),
                    body=str(parsed["body"]),
                    fragment_type="chapter",
                    parent_id=None,
                    fragment_order=0,
                    chapter_number=None,
                )
                return {
                    "kind": "chapter",
                    "fragmentId": identifier,
                    "chapterCount": 1,
                }

            line_id = insert_fragment(
                connection,
                title=str(parsed["title"]),
                body=str(parsed["body"]),
                fragment_type="line",
                parent_id=None,
                fragment_order=0,
                chapter_number=None,
            )
            chapter_ids = []
            for order, chapter in enumerate(parsed["chapters"]):
                chapter_ids.append(insert_fragment(
                    connection,
                    title=str(chapter["title"]),
                    body=str(chapter["body"]),
                    fragment_type="chapter",
                    parent_id=line_id,
                    fragment_order=order,
                    chapter_number=int(chapter["number"]),
                ))
            return {
                "kind": "line",
                "fragmentId": line_id,
                "chapterIds": chapter_ids,
                "chapterCount": len(chapter_ids),
            }

        chapter_count = len(parsed.get("chapters", [])) if parsed["kind"] == "line" else 1
        return self.uow.mutate(
            base_revision=base_revision,
            label=(
                f"从剪贴板导入剧情线：{parsed['title']}"
                if parsed["kind"] == "line"
                else f"从剪贴板导入灵感：{parsed['title']}"
            ),
            action="import",
            entity_kind="fragment",
            callback=mutation,
            details={
                "source": "clipboard",
                "fragmentType": parsed["kind"],
                "chapterCount": chapter_count,
            },
        )

    @staticmethod
    def _extra_dict(value: object) -> dict[str, Any]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _fragment_metadata(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        *,
        identifier: str,
        current_extra: object = "{}",
        creating: bool = False,
    ) -> dict[str, Any]:
        extra = self._extra_dict(current_extra)
        fragment_type = str(
            payload.get("fragment_type")
            if "fragment_type" in payload
            else extra.get("fragmentType") or "chapter"
        )
        if fragment_type not in {"chapter", "line"}:
            raise DomainError("碎片类型只能是单章或剧情线")
        parent_id = (
            payload.get("parent_fragment_id")
            if "parent_fragment_id" in payload
            else extra.get("parentFragmentId")
        )
        parent_id = clean_text(parent_id, "所属剧情线", 120) or None
        if fragment_type == "line":
            parent_id = None
        elif parent_id:
            if parent_id == identifier:
                raise DomainError("碎片不能归入自身")
            parent = connection.execute(
                """
                SELECT entity_id, extra_json FROM active_fragments
                WHERE entity_id=?
                """,
                (parent_id,),
            ).fetchone()
            if not parent or self._extra_dict(parent["extra_json"]).get("fragmentType") != "line":
                raise DomainError("所属剧情线不存在或已失效")

        if not creating and extra.get("fragmentType") == "line" and fragment_type != "line":
            has_children = any(
                self._extra_dict(row["extra_json"]).get("parentFragmentId") == identifier
                for row in connection.execute(
                    "SELECT extra_json FROM active_fragments WHERE entity_id<>?",
                    (identifier,),
                )
            )
            if has_children:
                raise DomainError("剧情线中仍有章节，请先将章节移出后再改为单章")

        raw_order = payload.get("fragment_order") if "fragment_order" in payload else extra.get("fragmentOrder")
        if raw_order is None:
            if parent_id:
                sibling_orders = [
                    int(sibling_extra.get("fragmentOrder") or 0)
                    for row in connection.execute(
                        "SELECT extra_json FROM active_fragments WHERE entity_id<>?",
                        (identifier,),
                    )
                    if (
                        sibling_extra := self._extra_dict(row["extra_json"])
                    ).get("parentFragmentId") == parent_id
                ]
                fragment_order = max(sibling_orders, default=-1) + 1
            else:
                fragment_order = 0
        else:
            fragment_order = int(raw_order)
            if fragment_order < 0:
                raise DomainError("章节顺序不能小于 0")

        chapter_number: int | None = None
        if fragment_type == "chapter" and parent_id:
            siblings: list[dict[str, Any]] = []
            for row in connection.execute(
                "SELECT entity_id, title, extra_json FROM active_fragments WHERE entity_id<>?",
                (identifier,),
            ):
                sibling_extra = self._extra_dict(row["extra_json"])
                if sibling_extra.get("parentFragmentId") != parent_id:
                    continue
                sibling_order = int(sibling_extra.get("fragmentOrder") or 0)
                sibling_number = stored_fragment_chapter_number(
                    sibling_extra,
                    str(row["title"]),
                    sibling_order,
                    parent_id,
                )
                if sibling_number is not None:
                    siblings.append(
                        {
                            "id": str(row["entity_id"]),
                            "number": sibling_number,
                            "extra": sibling_extra,
                        }
                    )
            sibling_numbers = [item["number"] for item in siblings]

            raw_chapter_number = (
                payload.get("chapter_number")
                if "chapter_number" in payload
                else extra.get("chapterNumber")
            )
            if raw_chapter_number is not None:
                chapter_number = int(raw_chapter_number)
            elif creating:
                chapter_number = max(sibling_numbers, default=0) + 1
            else:
                current_title_row = connection.execute(
                    "SELECT title FROM entities WHERE id=?",
                    (identifier,),
                ).fetchone()
                chapter_number = stored_fragment_chapter_number(
                    extra,
                    str(current_title_row["title"]) if current_title_row else "",
                    fragment_order,
                    parent_id,
                ) or max(sibling_numbers, default=0) + 1
            if chapter_number <= 0:
                raise DomainError("章号必须是正整数")
            if chapter_number in sibling_numbers:
                if not bool(payload.get("shift_following")):
                    raise DomainError(f"同一条剧情线中已经存在第 {chapter_number} 章")
                occupied = {item["number"]: item for item in siblings}
                displaced: list[dict[str, Any]] = []
                available_number = chapter_number
                while available_number in occupied:
                    item = occupied[available_number]
                    displaced.append(item)
                    available_number += 1
                now = int(time.time())
                for item in reversed(displaced):
                    item["extra"]["chapterNumber"] = item["number"] + 1
                    connection.execute(
                        """
                        UPDATE entities
                        SET extra_json=?, revision=revision+1, updated_at=?
                        WHERE id=?
                        """,
                        (
                            json.dumps(
                                item["extra"],
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            now,
                            item["id"],
                        ),
                    )
        extra.update(
            {
                "fragmentType": fragment_type,
                "parentFragmentId": parent_id,
                "fragmentOrder": fragment_order,
                "chapterNumber": chapter_number,
            }
        )
        if fragment_type == "line":
            if "plot_chapter_plan" in payload:
                raw_plan = payload.get("plot_chapter_plan") or {}
                if not isinstance(raw_plan, dict):
                    raise DomainError("正式剧情章号规划格式不正确")
                child_ids = {
                    str(row["entity_id"])
                    for row in connection.execute(
                        "SELECT entity_id, extra_json FROM active_fragments WHERE entity_id<>?",
                        (identifier,),
                    )
                    if self._extra_dict(row["extra_json"]).get("parentFragmentId") == identifier
                }
                plan: dict[str, int] = {}
                occupied: set[int] = set()
                for child_id, raw_number in raw_plan.items():
                    child_id = str(child_id)
                    if child_id not in child_ids:
                        continue
                    number = int(raw_number)
                    if number < 1 or number > 99999:
                        raise DomainError("正式剧情章号必须在 1 到 99999 之间")
                    if number in occupied:
                        raise DomainError(f"正式剧情第 {number} 章被重复规划")
                    occupied.add(number)
                    plan[child_id] = number
                extra["plotChapterPlan"] = plan
            elif creating:
                extra["plotChapterPlan"] = {}
        else:
            extra.pop("plotChapterPlan", None)
        return extra

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
                extra = self._fragment_metadata(
                    connection, payload, identifier=identifier, creating=True
                )
                connection.execute(
                    "UPDATE entities SET extra_json=? WHERE id=?",
                    (
                        json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        identifier,
                    ),
                )
            self._replace_text_collections(connection, kind, identifier, payload)
            self._replace_entity_references(connection, identifier, payload)
            if kind == "fragment":
                self._archive_manual_people(
                    connection, identifier, payload, "fragment", now
                )
                automatic_people = self._automatic_text_people(
                    connection, identifier, payload, "fragment"
                )
                self._sync_character_references(
                    connection, identifier, automatic_people
                )
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
            if kind == "fragment":
                self._archive_manual_people(
                    connection, identifier, payload, "fragment", now
                )
                automatic_people = self._automatic_text_people(
                    connection, identifier, payload, "fragment"
                )
                self._sync_character_references(
                    connection, identifier, automatic_people
                )
                extra = self._fragment_metadata(
                    connection,
                    payload,
                    identifier=identifier,
                    current_extra=entity["extra_json"],
                )
                connection.execute(
                    "UPDATE entities SET extra_json=? WHERE id=?",
                    (
                        json.dumps(extra, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                        identifier,
                    ),
                )
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
