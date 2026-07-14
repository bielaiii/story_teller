#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import secrets
import tempfile
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parent
CONTENT_ROOT = ROOT / "content"
STATE_ROOT = ROOT / ".story-teller"
UNDO_PATH = STATE_ROOT / "last-refactor.json"
PROJECT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ASCII_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
FRONTMATTER_PATTERN = re.compile(r"^---\n(?P<meta>[\s\S]*?)\n---(?:\n|$)")
MAX_REQUEST_BYTES = 64 * 1024
PREVIEW_TTL_SECONDS = 15 * 60
PLOT_TRASH_RETENTION_SECONDS = 7 * 24 * 60 * 60
RECORD_TRASH_RETENTION_SECONDS = 7 * 24 * 60 * 60
CONTENT_DIRECTORIES = {
    "characters": "characters",
    "plots": "plots",
    "fragments": "fragments",
    "entries": "entries",
    "relationships": "relationships",
}
CONTENT_CONFIG_FILES = {
    "timeline": "timeline.md",
    "graphLayout": "graph-layout.md",
}
CONTENT_INDEX_NAME = "content-index.json"
FORBIDDEN_FILENAME_PATTERN = re.compile(r'[\x00-\x1f<>:"/\\|?*]')
HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
CHARACTER_SCOPES = {"主线人物", "常驻人物", "待定角色", "一次性角色"}
TIMELINE_SIDES = {"center", "left", "right"}


def parse_frontmatter(text):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return {}
    fields = {}
    for line in match.group("meta").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def update_frontmatter_field(text, key, value):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        raise ValueError("目标档案缺少 frontmatter")
    if isinstance(value, dict):
        replacement = [f"{key}:"]
        for child_key, child_value in value.items():
            label = clean_text(child_key, "档案字段名", 60, required=True)
            replacement.append(f"  {label}: {json.dumps(str(child_value), ensure_ascii=False)}")
    else:
        replacement = [f"{key}: {json.dumps(value, ensure_ascii=False)}"]
    lines = match.group("meta").splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", line):
            end = index + 1
            while end < len(lines) and (not lines[end].strip() or lines[end][:1].isspace()):
                end += 1
            lines[index:end] = replacement
            break
    else:
        insert_at = 0
        for index, line in enumerate(lines):
            if re.match(r"^(id|name)\s*:", line):
                insert_at = index + 1
        lines[insert_at:insert_at] = replacement
    return text[: match.start("meta")] + "\n".join(lines) + text[match.end("meta") :]


def remove_frontmatter_field(text, key):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        raise ValueError("目标档案缺少 frontmatter")
    lines = match.group("meta").splitlines()
    for index, line in enumerate(lines):
        if not re.match(rf"^{re.escape(key)}\s*:", line):
            continue
        end = index + 1
        while end < len(lines) and (not lines[end].strip() or lines[end][:1].isspace()):
            end += 1
        del lines[index:end]
        break
    return text[: match.start("meta")] + "\n".join(lines) + text[match.end("meta") :]


def replace_markdown_body(text, body):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        raise ValueError("目标剧情缺少 frontmatter")
    return text[: match.end()] + str(body).strip() + "\n"


def remove_frontmatter_list_value(text, key, target_value):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return text
    pattern = re.compile(rf"^(?P<prefix>{re.escape(key)}\s*:\s*)\[(?P<items>[^\]]*)\]\s*$")
    lines = match.group("meta").splitlines()
    changed = False
    for index, line in enumerate(lines):
        list_match = pattern.match(line)
        if not list_match:
            continue
        items = [item.strip() for item in list_match.group("items").split(",") if item.strip()]
        kept = [
            item
            for item in items
            if item.strip().strip("\"'") != str(target_value)
        ]
        if len(kept) != len(items):
            lines[index] = f"{list_match.group('prefix')}[{', '.join(kept)}]"
            changed = True
        break
    if not changed:
        return text
    return text[: match.start("meta")] + "\n".join(lines) + text[match.end("meta") :]


def frontmatter_list_values(text, key):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return []
    field = re.search(rf"(?m)^{re.escape(key)}\s*:\s*\[([^\]]*)\]\s*$", match.group("meta"))
    if not field:
        return []
    return [item.strip().strip("\"'") for item in field.group(1).split(",") if item.strip()]


def validate_plot_payload(payload):
    title = str(payload.get("title", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    body = str(payload.get("body", "")).strip()
    chapter = str(payload.get("chapter", "")).strip()
    status = str(payload.get("status", "草稿")).strip()
    accent = str(payload.get("accent", "")).strip().lower()

    if not title or len(title) > 120 or "\n" in title or "\r" in title:
        raise ValueError("剧情标题长度需要在 1 到 120 个字符之间")
    if not body:
        raise ValueError("请填写剧情正文")
    if len(body) > 60000:
        raise ValueError("剧情正文不能超过 60000 个字符")
    if len(summary) > 500:
        raise ValueError("剧情摘要不能超过 500 个字符")
    if not chapter or len(chapter) > 80 or "\n" in chapter or "\r" in chapter:
        raise ValueError("请选择有效的篇章")
    if not status or len(status) > 40 or "\n" in status or "\r" in status:
        raise ValueError("剧情状态不合法")
    if not HEX_COLOR_PATTERN.fullmatch(accent):
        raise ValueError("请选择有效的剧情颜色")

    def clean_list(key, label):
        values = payload.get(key, [])
        if not isinstance(values, list) or len(values) > 30:
            raise ValueError(f"{label}格式不合法")
        cleaned = []
        for item in values:
            value = str(item).strip()
            if not value:
                continue
            if len(value) > 60 or "\n" in value or "\r" in value:
                raise ValueError(f"{label}中的单项不能超过 60 个字符")
            if value not in cleaned:
                cleaned.append(value)
        return cleaned

    return {
        "title": title,
        "summary": summary,
        "body": body,
        "chapter": chapter,
        "status": status,
        "accent": accent,
        "tags": clean_list("tags", "剧情标签"),
        "lanes": clean_list("lanes", "剧情线"),
        "people": clean_list("people", "出场人物") if "people" in payload else None,
        "entries": clean_list("entries", "关联设定") if "entries" in payload else None,
        "key": bool(payload.get("key")),
        "climax": bool(payload.get("climax")),
    }


def update_plot_document(text, values):
    updated = text
    for key in ("chapter", "title", "accent", "status"):
        updated = update_frontmatter_field(updated, key, values[key])
    for key in ("summary", "lanes", "tags", "people", "entries"):
        value = values[key]
        if value is None:
            continue
        updated = update_frontmatter_field(updated, key, value) if value else remove_frontmatter_field(updated, key)
    for key in ("key", "climax"):
        updated = update_frontmatter_field(updated, key, True) if values[key] else remove_frontmatter_field(updated, key)
    return replace_markdown_body(updated, values["body"])


def validate_timeline_payload(payload, plot_records):
    config = payload.get("config")
    assignments = payload.get("assignments")
    if not isinstance(config, dict) or not isinstance(assignments, list):
        raise ValueError("时间线数据格式不合法")

    raw_lines = config.get("lines")
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= 30:
        raise ValueError("时间线需要包含 1 到 30 条剧情线")

    lines = []
    names = set()
    plot_ids = {record["id"] for record in plot_records}
    sequence_by_id = {record["id"]: record["sequence"] for record in plot_records}
    for index, item in enumerate(raw_lines):
        if not isinstance(item, dict):
            raise ValueError("剧情线数据格式不合法")
        name = str(item.get("name", "")).strip()
        color = str(item.get("color", "")).strip().lower()
        side = str(item.get("side", "right")).strip()
        if not name or len(name) > 60 or "\n" in name or "\r" in name:
            raise ValueError("剧情线名称长度需要在 1 到 60 个字符之间")
        if name in names:
            raise ValueError(f"剧情线名称重复：{name}")
        if not HEX_COLOR_PATTERN.fullmatch(color):
            raise ValueError(f"剧情线颜色不合法：{name}")
        if side not in TIMELINE_SIDES:
            raise ValueError(f"剧情线方向不合法：{name}")
        names.add(name)
        line = {
            "name": name,
            "color": color,
            "side": side,
            "order": index + 1,
        }
        for key in ("startPlotId", "endPlotId"):
            raw_plot_id = item.get(key)
            if raw_plot_id in (None, ""):
                continue
            try:
                plot_id = int(raw_plot_id)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{name}的分支锚点不合法") from error
            if plot_id not in plot_ids:
                raise ValueError(f"{name}引用了不存在的剧情：{plot_id}")
            line[key] = plot_id
        if (
            line.get("startPlotId") is not None
            and line.get("endPlotId") is not None
            and sequence_by_id[line["startPlotId"]] >= sequence_by_id[line["endPlotId"]]
        ):
            raise ValueError(f"{name}的汇合剧情必须晚于分支剧情")
        lines.append(line)

    main_line = str(config.get("mainLine", "")).strip()
    if main_line not in names:
        raise ValueError("主线必须对应一条现有剧情线")
    main_config = next(line for line in lines if line["name"] == main_line)
    main_config["side"] = "center"
    main_config.pop("startPlotId", None)
    main_config.pop("endPlotId", None)

    clean_assignments = {}
    for item in assignments:
        if not isinstance(item, dict):
            raise ValueError("剧情节点归属格式不合法")
        try:
            plot_id = int(item.get("plotId"))
        except (TypeError, ValueError) as error:
            raise ValueError("剧情节点缺少有效 ID") from error
        if plot_id not in plot_ids or plot_id in clean_assignments:
            raise ValueError(f"剧情节点归属重复或不存在：{plot_id}")
        raw_lanes = item.get("lanes", [])
        if not isinstance(raw_lanes, list) or len(raw_lanes) > len(lines):
            raise ValueError(f"剧情 {plot_id} 的剧情线归属不合法")
        lanes = []
        for raw_lane in raw_lanes:
            lane = str(raw_lane).strip()
            if lane not in names:
                raise ValueError(f"剧情 {plot_id} 引用了不存在的剧情线：{lane}")
            if lane not in lanes:
                lanes.append(lane)
        clean_assignments[plot_id] = lanes
    if set(clean_assignments) != plot_ids:
        raise ValueError("请为全部剧情提交完整的时间线归属")

    def bounded_number(key, fallback, minimum, maximum):
        raw_value = config.get(key, fallback)
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"时间线参数 {key} 不合法") from error
        return max(minimum, min(maximum, value))

    return {
        "version": 2,
        "mainLine": main_line,
        "lineSpacing": bounded_number("lineSpacing", 72, 48, 180),
        "topPadding": bounded_number("topPadding", 64, 24, 180),
        "sidePadding": bounded_number("sidePadding", 36, 16, 120),
        "pixelsPerStoryUnit": bounded_number("pixelsPerStoryUnit", 760, 560, 1600),
        "lines": lines,
        "assignments": clean_assignments,
    }


def serialize_timeline_document(config):
    fields = [
        "---",
        "version: 2",
        f"mainLine: {json.dumps(config['mainLine'], ensure_ascii=False)}",
        f"lineSpacing: {config['lineSpacing']}",
        f"topPadding: {config['topPadding']}",
        f"sidePadding: {config['sidePadding']}",
        f"pixelsPerStoryUnit: {config['pixelsPerStoryUnit']}",
        "---",
        "",
        "## Lines",
        "",
    ]
    for line in config["lines"]:
        fields.extend([
            f"- name: {json.dumps(line['name'], ensure_ascii=False)}",
            f"  color: {json.dumps(line['color'], ensure_ascii=False)}",
            f"  side: {line['side']}",
            f"  order: {line['order']}",
        ])
        if line.get("startPlotId") is not None:
            fields.append(f"  startPlotId: {line['startPlotId']}")
        if line.get("endPlotId") is not None:
            fields.append(f"  endPlotId: {line['endPlotId']}")
        fields.append("")
    return "\n".join(fields).rstrip() + "\n"


def replace_name(text, old_name, new_name):
    if ASCII_NAME_PATTERN.fullmatch(old_name):
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_-]){re.escape(old_name)}(?![A-Za-z0-9_-])"
        )
        return pattern.sub(lambda _: new_name, text)
    return text.replace(old_name, new_name)


def atomic_write(path, content):
    mode = path.stat().st_mode if path.exists() else 0o644
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.chmod(temporary_path, mode)
    os.replace(temporary_path, path)


def build_content_index(project_root):
    project_root = project_root.resolve()
    collections = {}
    for key, directory_name in CONTENT_DIRECTORIES.items():
        directory = project_root / directory_name
        paths = []
        if directory.is_dir():
            for path in sorted(directory.rglob("*.md")):
                resolved_path = path.resolve()
                if project_root not in resolved_path.parents or not path.is_file():
                    continue
                paths.append(f"./{path.relative_to(project_root).as_posix()}")
        collections[key] = paths

    for key, file_name in CONTENT_CONFIG_FILES.items():
        path = project_root / file_name
        collections[key] = [f"./{file_name}"] if path.is_file() else []
    return collections


def write_content_index(project_root, collections):
    path = project_root / CONTENT_INDEX_NAME
    content = json.dumps(
        {"version": 1, "collections": collections},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == content:
        return
    atomic_write(path, content)


def canonical_character_filename(character_id, name):
    clean_id = str(character_id or "").strip()
    clean_name = str(name or "").strip()
    if not clean_id or not clean_name:
        raise ValueError("人物文件名缺少 id 或 name")
    if FORBIDDEN_FILENAME_PATTERN.search(clean_name) or clean_name.endswith((".", " ")):
        raise ValueError("人物名称包含不能用于文件名的字符")
    filename = f"{clean_id}-{clean_name}.md"
    if len(filename.encode("utf-8")) > 240:
        raise ValueError("人物名称过长，无法生成安全文件名")
    return filename


def relationship_character_ids(text):
    match = FRONTMATTER_PATTERN.match(text)
    if not match:
        return []
    meta = match.group("meta")
    people_match = re.search(
        r"(?ms)^people:\s*\n(?P<items>(?:[ \t]+.*(?:\n|$))*)",
        meta,
    )
    if people_match:
        return [
            value.strip().strip("\"'")
            for value in re.findall(
                r"(?m)^\s*-\s+id:\s*([^\n#]+?)\s*$",
                people_match.group("items"),
            )
        ]
    endpoints = [
        re.search(rf"(?m)^{field}:\s*([^\n#]+?)\s*$", meta)
        for field in ("from", "to")
    ]
    if not all(endpoints):
        return []
    return [endpoint.group(1).strip().strip("\"'") for endpoint in endpoints]


def canonical_relationship_filename(character_ids, character_names):
    if len(character_ids) != 2:
        raise ValueError("人物关系必须恰好包含两个端点")
    parts = []
    for character_id in character_ids:
        name = character_names.get(str(character_id))
        if not name:
            raise ValueError(f"人物关系引用了不存在的人物：{character_id}")
        parts.append(canonical_character_filename(character_id, name).removesuffix(".md"))
    filename = "__".join(parts) + ".md"
    if len(filename.encode("utf-8")) > 240:
        raise ValueError("关系双方名称过长，无法生成安全文件名")
    return filename


def canonical_plot_filename(plot_id, title):
    clean_id = str(plot_id or "").strip()
    clean_title = str(title or "").strip()
    if not clean_id or not clean_title:
        raise ValueError("剧情文件名缺少 id 或标题")
    if FORBIDDEN_FILENAME_PATTERN.search(clean_title) or clean_title.endswith((".", " ")):
        raise ValueError("剧情标题包含不能用于文件名的字符")
    filename = f"{int(clean_id):03d}-{clean_title}.md"
    if len(filename.encode("utf-8")) > 240:
        raise ValueError("剧情标题过长，无法生成安全文件名")
    return filename


def canonical_entry_filename(entry_id):
    clean_id = str(entry_id or "").strip()
    if not ASCII_NAME_PATTERN.fullmatch(clean_id):
        raise ValueError("设定 ID 只能包含英文字母、数字、横线和下划线")
    return f"{clean_id}.md"


def canonical_fragment_filename(fragment_id):
    clean_id = str(fragment_id or "").strip()
    if not ASCII_NAME_PATTERN.fullmatch(clean_id):
        raise ValueError("碎片 ID 只能包含英文字母、数字、横线和下划线")
    return f"{clean_id}.md"


def clean_text(value, label, maximum=120, required=False):
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise ValueError(f"请填写{label}")
    if len(cleaned) > maximum or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label}不能超过 {maximum} 个字符")
    return cleaned


def clean_values(value, label, maximum_items=60, maximum_length=80):
    if value in (None, ""):
        return []
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError(f"{label}格式不合法")
    cleaned = []
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > maximum_length or "\n" in text or "\r" in text:
            raise ValueError(f"{label}中的单项不能超过 {maximum_length} 个字符")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


def serialize_markdown(fields, body=""):
    lines = ["---"]
    for key, value in fields:
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for child_key, child_value in value.items():
                label = clean_text(child_key, "档案字段名", 60, required=True)
                lines.append(f"  {label}: {json.dumps(str(child_value), ensure_ascii=False)}")
        else:
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.extend(["---", str(body or "").strip(), ""])
    return "\n".join(lines)


def record_trash_records(project_root, now=None):
    current_time = time.time() if now is None else float(now)
    trash_root = project_root / ".trash" / "records"
    records = []
    if not trash_root.is_dir():
        return records
    for path in sorted(trash_root.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        deleted_at = int(payload.get("deletedAt", 0) or 0)
        expires_at = deleted_at + RECORD_TRASH_RETENTION_SECONDS
        remaining_seconds = max(0, expires_at - current_time)
        records.append({
            "trashId": path.name,
            "kind": str(payload.get("kind", "")),
            "id": str(payload.get("id", "")),
            "title": str(payload.get("title", "未命名档案")),
            "deletedAt": deleted_at,
            "expiresAt": expires_at,
            "daysRemaining": int(math.ceil(remaining_seconds / 86400)),
            "fileCount": len(payload.get("files", [])),
            "_path": path,
            "_payload": payload,
        })
    return records


def purge_expired_record_trash(project_root, now=None):
    current_time = time.time() if now is None else float(now)
    purged = 0
    for record in record_trash_records(project_root, current_time):
        if record["expiresAt"] > current_time:
            continue
        record["_path"].unlink()
        purged += 1
    return purged


def plot_trash_records(project_root, now=None):
    current_time = time.time() if now is None else float(now)
    trash_root = project_root / ".trash" / "plots"
    records = []
    if not trash_root.is_dir():
        return records
    for path in sorted(trash_root.glob("*.md")):
        timestamp_text, separator, original_filename = path.name.partition("-")
        if not separator or not timestamp_text.isdigit() or not original_filename.endswith(".md"):
            continue
        deleted_at = int(timestamp_text)
        expires_at = deleted_at + PLOT_TRASH_RETENTION_SECONDS
        text = path.read_text(encoding="utf-8")
        fields = parse_frontmatter(text)
        plot_id = str(fields.get("id", "")).strip()
        raw_sequence = str(fields.get("sequence", plot_id)).strip()
        if not plot_id.isdigit() or not raw_sequence.isdigit():
            continue
        remaining_seconds = max(0, expires_at - current_time)
        records.append(
            {
                "trashId": path.name,
                "id": int(plot_id),
                "title": str(fields.get("title", original_filename.removesuffix(".md"))),
                "sequence": int(raw_sequence),
                "originalFilename": original_filename,
                "deletedAt": deleted_at,
                "expiresAt": expires_at,
                "daysRemaining": int(math.ceil(remaining_seconds / 86400)),
                "_path": path,
                "_text": text,
            }
        )
    return records


def remove_plot_references_permanently(project_root, plot_id):
    written = []
    references_updated = 0
    try:
        for directory_name, key in (("characters", "events"), ("entries", "plots")):
            directory = project_root / directory_name
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                updated = remove_frontmatter_list_value(text, key, plot_id)
                if updated == text:
                    continue
                atomic_write(path, updated)
                written.append((path, text))
                references_updated += 1

        timeline_path = project_root / "timeline.md"
        if timeline_path.is_file():
            timeline_text = timeline_path.read_text(encoding="utf-8")
            node_pattern = re.compile(
                rf"(?m)^- plotId:\s*{re.escape(str(plot_id))}\s*$\n(?:^[ \t]+.*(?:\n|$))*"
            )
            updated_timeline = node_pattern.sub("", timeline_text, count=1)
            anchor_pattern = re.compile(
                rf"(?m)^[ \t]+(?:startPlotId|endPlotId):\s*{re.escape(str(plot_id))}\s*$\n?"
            )
            updated_timeline = anchor_pattern.sub("", updated_timeline)
            if updated_timeline != timeline_text:
                atomic_write(timeline_path, updated_timeline)
                written.append((timeline_path, timeline_text))
                references_updated += 1
    except (OSError, ValueError):
        for path, previous in reversed(written):
            atomic_write(path, previous)
        raise
    return written, references_updated


def purge_expired_plot_trash(project_root, now=None):
    current_time = time.time() if now is None else float(now)
    purged = 0
    for record in plot_trash_records(project_root, current_time):
        if record["expiresAt"] > current_time:
            continue
        written, _ = remove_plot_references_permanently(project_root, record["id"])
        try:
            record["_path"].unlink()
        except OSError:
            for path, previous in reversed(written):
                atomic_write(path, previous)
            raise
        purged += 1
    return purged


class StoryTellerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address,
        handler_class,
        content_root=CONTENT_ROOT,
        default_project="",
    ):
        resolved_content_root = Path(content_root).expanduser().resolve()
        if not resolved_content_root.is_dir():
            raise ValueError(f"内容目录不存在：{resolved_content_root}")
        if default_project and not PROJECT_PATTERN.fullmatch(default_project):
            raise ValueError("默认项目名称不合法")
        if default_project and not (resolved_content_root / default_project).is_dir():
            raise ValueError(f"找不到默认项目：{default_project}")
        self.content_root = resolved_content_root
        self.default_project = default_project
        super().__init__(server_address, handler_class)
        self.api_token = secrets.token_urlsafe(24)
        self.previews = {}

    def prune_previews(self):
        cutoff = time.time() - PREVIEW_TTL_SECONDS
        self.previews = {
            key: value
            for key, value in self.previews.items()
            if value["createdAt"] >= cutoff
        }


class StoryTellerHandler(SimpleHTTPRequestHandler):
    server_version = "StoryTellerLocal/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def translate_path(self, path):
        request_path = unquote(urlparse(path).path)
        if request_path == "/content" or request_path.startswith("/content/"):
            relative_path = request_path.removeprefix("/content").lstrip("/")
            candidate = (self.server.content_root / relative_path).resolve()
            content_root = self.server.content_root.resolve()
            if candidate == content_root or content_root in candidate.parents:
                return str(candidate)
            return str(content_root / ".invalid-path")
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_api_error(self, message, status=HTTPStatus.BAD_REQUEST):
        self.send_json({"ok": False, "error": message}, status)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("请求内容大小不合法") from error
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("请求内容大小不合法")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("请求内容不是有效 JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是对象")
        return payload

    def authorized(self):
        return secrets.compare_digest(
            self.headers.get("X-Story-Teller-Token", ""),
            self.server.api_token,
        )

    def local_host(self):
        host = self.headers.get("Host", "").split(":", 1)[0].lower()
        return host in {"127.0.0.1", "localhost"}

    def project_id(self, project):
        project = str(project or "").strip() or getattr(self.server, "default_project", "")
        if not PROJECT_PATTERN.fullmatch(project):
            raise ValueError("项目名称不合法")
        return project

    def project_root(self, project):
        project = self.project_id(project)
        content_root = self.server.content_root.resolve()
        root = (content_root / project).resolve()
        if content_root not in root.parents or not root.is_dir():
            raise ValueError("找不到当前内容包")
        return root

    def undo_metadata(self):
        if not UNDO_PATH.is_file():
            return None
        try:
            return json.loads(UNDO_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/content-index":
            return self.content_index(parsed)
        if parsed.path == "/api/projects":
            return self.projects_index()
        if parsed.path == "/api/records/trash":
            return self.record_trash(parsed)
        if parsed.path == "/api/records/trash/preview":
            return self.record_trash_preview(parsed)
        if parsed.path == "/api/plots/trash/preview":
            return self.plot_trash_preview(parsed)
        if parsed.path == "/api/plots/trash":
            return self.plot_trash(parsed)
        if parsed.path != "/api/capabilities":
            return super().do_GET()
        if not self.local_host():
            return self.send_api_error("只允许从本机访问写入服务", HTTPStatus.FORBIDDEN)
        project = parse_qs(parsed.query).get("project", [""])[0]
        try:
            project_root = self.project_root(project)
            purge_expired_plot_trash(project_root)
            purge_expired_record_trash(project_root)
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
        except OSError as error:
            return self.send_api_error(f"回收站清理失败：{error}", HTTPStatus.INTERNAL_SERVER_ERROR)
        undo = self.undo_metadata()
        trash_count = len(plot_trash_records(project_root)) + len(record_trash_records(project_root))
        self.send_json(
            {
                "ok": True,
                "writable": True,
                "features": ["content-management-v1"],
                "token": self.server.api_token,
                "trashCount": trash_count,
                "canUndo": bool(undo and undo.get("project") == project),
                "undoLabel": (
                    f"{undo.get('oldName')} → {undo.get('newName')}"
                    if undo and undo.get("project") == project
                    else ""
                ),
            }
        )

    def plot_trash(self, parsed):
        if not self.local_host():
            return self.send_api_error("只允许从本机读取回收站", HTTPStatus.FORBIDDEN)
        requested_project = parse_qs(parsed.query, keep_blank_values=True).get("project", [""])[0]
        try:
            project_root = self.project_root(requested_project)
            purge_expired_plot_trash(project_root)
            records = plot_trash_records(project_root)
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
        except OSError as error:
            return self.send_api_error(f"回收站读取失败：{error}", HTTPStatus.INTERNAL_SERVER_ERROR)
        items = [
            {key: value for key, value in record.items() if not key.startswith("_")}
            for record in sorted(records, key=lambda item: item["deletedAt"], reverse=True)
        ]
        self.send_json({"ok": True, "items": items, "retentionDays": 7})

    def plot_trash_preview(self, parsed):
        if not self.local_host():
            return self.send_api_error("只允许从本机预览回收站", HTTPStatus.FORBIDDEN)
        query = parse_qs(parsed.query, keep_blank_values=True)
        requested_project = query.get("project", [""])[0]
        trash_id = str(query.get("trashId", [""])[0]).strip()
        if not trash_id or Path(trash_id).name != trash_id:
            return self.send_api_error("请选择有效的回收站剧情")
        try:
            project_root = self.project_root(requested_project)
            purge_expired_plot_trash(project_root)
            record = next(
                (item for item in plot_trash_records(project_root) if item["trashId"] == trash_id),
                None,
            )
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
        except OSError as error:
            return self.send_api_error(f"回收站预览失败：{error}", HTTPStatus.INTERNAL_SERVER_ERROR)
        if not record:
            return self.send_api_error("这条剧情已不在回收站中", HTTPStatus.NOT_FOUND)
        frontmatter = FRONTMATTER_PATTERN.match(record["_text"])
        body = record["_text"][frontmatter.end() :].strip() if frontmatter else record["_text"].strip()
        fields = parse_frontmatter(record["_text"])
        self.send_json(
            {
                "ok": True,
                "trashId": record["trashId"],
                "id": record["id"],
                "title": record["title"],
                "sequence": record["sequence"],
                "daysRemaining": record["daysRemaining"],
                "status": str(fields.get("status", "")),
                "accent": str(fields.get("accent", "#3f7fc1")).strip("\"'"),
                "body": body,
            }
        )

    def projects_index(self):
        if not self.local_host():
            return self.send_api_error("只允许从本机读取项目列表", HTTPStatus.FORBIDDEN)
        projects = []
        for path in sorted(self.server.content_root.iterdir()):
            if not path.is_dir() or not PROJECT_PATTERN.fullmatch(path.name):
                continue
            manifest = path / "manifest.md"
            fields = parse_frontmatter(manifest.read_text(encoding="utf-8")) if manifest.is_file() else {}
            projects.append({"id": path.name, "title": str(fields.get("title", path.name)).strip("\"'")})
        self.send_json({"ok": True, "items": projects})

    def record_trash(self, parsed):
        if not self.local_host():
            return self.send_api_error("只允许从本机读取回收站", HTTPStatus.FORBIDDEN)
        project = parse_qs(parsed.query, keep_blank_values=True).get("project", [""])[0]
        try:
            project_root = self.project_root(project)
            purge_expired_record_trash(project_root)
            items = [
                {key: value for key, value in record.items() if not key.startswith("_")}
                for record in sorted(record_trash_records(project_root), key=lambda item: item["deletedAt"], reverse=True)
            ]
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
        self.send_json({"ok": True, "items": items, "retentionDays": 7})

    def record_trash_preview(self, parsed):
        if not self.local_host():
            return self.send_api_error("只允许从本机预览回收站", HTTPStatus.FORBIDDEN)
        query = parse_qs(parsed.query, keep_blank_values=True)
        project = query.get("project", [""])[0]
        trash_id = str(query.get("trashId", [""])[0]).strip()
        if not trash_id or Path(trash_id).name != trash_id:
            return self.send_api_error("请选择有效的回收站档案")
        try:
            project_root = self.project_root(project)
            record = next((item for item in record_trash_records(project_root) if item["trashId"] == trash_id), None)
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
        if not record:
            return self.send_api_error("这份档案已不在回收站中", HTTPStatus.NOT_FOUND)
        files = record["_payload"].get("files", [])
        content = str(files[0].get("content", "")) if files else ""
        match = FRONTMATTER_PATTERN.match(content)
        body = content[match.end():].strip() if match else content.strip()
        self.send_json({
            "ok": True,
            "trashId": trash_id,
            "kind": record["kind"],
            "id": record["id"],
            "title": record["title"],
            "daysRemaining": record["daysRemaining"],
            "body": body,
            "fileCount": record["fileCount"],
        })

    def content_index(self, parsed):
        if not self.local_host():
            return self.send_api_error("只允许从本机读取内容目录", HTTPStatus.FORBIDDEN)
        requested_project = parse_qs(parsed.query, keep_blank_values=True).get("project", [""])[0]
        try:
            project = self.project_id(requested_project)
            project_root = self.project_root(project)
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)

        collections = build_content_index(project_root)
        write_content_index(project_root, collections)
        self.send_json({"ok": True, "project": project, "collections": collections})

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in {
            "/api/refactor/preview",
            "/api/refactor/apply",
            "/api/refactor/undo",
            "/api/relationships/create",
            "/api/relationships/update",
            "/api/characters/create",
            "/api/characters/update",
            "/api/characters/scope",
            "/api/entries/save",
            "/api/fragments/save",
            "/api/records/delete",
            "/api/records/trash/restore",
            "/api/plots/create",
            "/api/plots/update",
            "/api/plots/delete",
            "/api/plots/trash/restore",
            "/api/timeline/update",
            "/api/project/update",
            "/api/projects/create",
            "/api/graph-layout/update",
            "/api/diagnostics/repair",
        }:
            return self.send_api_error("未知接口", HTTPStatus.NOT_FOUND)
        if not self.local_host():
            return self.send_api_error("只允许从本机访问写入服务", HTTPStatus.FORBIDDEN)
        if not self.authorized():
            return self.send_api_error("本地写入授权已失效，正在重新连接本地服务", HTTPStatus.FORBIDDEN)
        try:
            payload = self.read_json()
            if parsed.path == "/api/refactor/preview":
                return self.preview_refactor(payload)
            if parsed.path == "/api/refactor/apply":
                return self.apply_refactor(payload)
            if parsed.path == "/api/relationships/create":
                return self.create_relationship(payload)
            if parsed.path == "/api/relationships/update":
                return self.update_relationship(payload)
            if parsed.path == "/api/characters/create":
                return self.create_character(payload)
            if parsed.path == "/api/characters/update":
                return self.update_character(payload)
            if parsed.path == "/api/characters/scope":
                return self.update_character_scope(payload)
            if parsed.path == "/api/entries/save":
                return self.save_entry(payload)
            if parsed.path == "/api/fragments/save":
                return self.save_fragment(payload)
            if parsed.path == "/api/records/delete":
                return self.delete_record(payload)
            if parsed.path == "/api/records/trash/restore":
                return self.restore_record(payload)
            if parsed.path == "/api/plots/create":
                return self.create_plot(payload)
            if parsed.path == "/api/plots/update":
                return self.update_plot(payload)
            if parsed.path == "/api/plots/delete":
                return self.delete_plot(payload)
            if parsed.path == "/api/plots/trash/restore":
                return self.restore_plot(payload)
            if parsed.path == "/api/timeline/update":
                return self.update_timeline(payload)
            if parsed.path == "/api/project/update":
                return self.update_project(payload)
            if parsed.path == "/api/projects/create":
                return self.create_project(payload)
            if parsed.path == "/api/graph-layout/update":
                return self.update_graph_layout(payload)
            if parsed.path == "/api/diagnostics/repair":
                return self.repair_diagnostics(payload)
            return self.undo_refactor(payload)
        except ValueError as error:
            return self.send_api_error(str(error))
        except OSError as error:
            return self.send_api_error(f"文件操作失败：{error}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def locate_target(self, project_root, target_type, target_id):
        project_root = project_root.resolve()
        directory_name = {"character": "characters", "entry": "entries"}.get(target_type)
        if not directory_name:
            raise ValueError("只支持人物和设定名称重构")
        candidates = []
        target_directory = project_root / directory_name
        for path in sorted(target_directory.rglob("*.md")):
            resolved_path = path.resolve()
            if project_root not in resolved_path.parents or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            if fields.get("id") == str(target_id):
                candidates.append((path, fields, text))
        if not candidates:
            raise ValueError("找不到需要重命名的档案")
        if len(candidates) > 1:
            raise ValueError("目标 id 重复，请先修复配置问题")
        return candidates[0]

    def character_names(self, project_root):
        names = {}
        directory = project_root / "characters"
        for path in sorted(directory.rglob("*.md")):
            fields = parse_frontmatter(path.read_text(encoding="utf-8"))
            character_id = str(fields.get("id", "")).strip()
            name = str(fields.get("name", "")).strip()
            if character_id and name:
                names[character_id] = name
        return names

    def locate_record(self, project_root, kind, record_id):
        directory_name = {
            "character": "characters",
            "entry": "entries",
            "fragment": "fragments",
            "relationship": "relationships",
        }.get(kind)
        if not directory_name:
            raise ValueError("不支持的档案类型")
        candidates = []
        for path in sorted((project_root / directory_name).rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            if kind == "relationship":
                ids = relationship_character_ids(text)
                key = "__".join(ids)
                reverse_key = "__".join(reversed(ids))
                if str(record_id) not in {key, reverse_key, path.relative_to(project_root).as_posix()}:
                    continue
            elif str(fields.get("id", "")).strip() != str(record_id).strip():
                continue
            candidates.append((path, fields, text))
        if not candidates:
            raise ValueError("找不到需要操作的档案")
        if len(candidates) > 1:
            raise ValueError("档案 ID 重复，请先运行配置修复")
        return candidates[0]

    def create_character(self, payload):
        project = str(payload.get("project", ""))
        name = str(payload.get("name", "")).strip()
        narrative_role = str(payload.get("narrativeRole", "配角")).strip()
        scope = str(payload.get("characterScope", "常驻人物")).strip()
        group = str(payload.get("group", "")).strip()
        side = str(payload.get("side", "中立")).strip()
        intro = str(payload.get("intro", "")).strip()
        color = str(payload.get("color", "")).strip().lower()

        if not name or len(name) > 80 or "\n" in name or "\r" in name:
            raise ValueError("人物姓名长度需要在 1 到 80 个字符之间")
        if narrative_role not in {"主角", "配角"}:
            raise ValueError("人物定位不合法")
        if scope not in CHARACTER_SCOPES:
            raise ValueError("人物收纳状态不合法")
        if side not in {"主角方", "中立", "反派方"}:
            raise ValueError("人物阵营不合法")
        if len(group) > 80 or "\n" in group or "\r" in group:
            raise ValueError("人物分组不能超过 80 个字符")
        if len(intro) > 20000:
            raise ValueError("人物简介不能超过 20000 个字符")
        if not HEX_COLOR_PATTERN.fullmatch(color):
            raise ValueError("请选择有效的人物颜色")

        try:
            main_plot_impact = int(payload.get("mainPlotImpact", 50))
        except (TypeError, ValueError) as error:
            raise ValueError("主线影响必须是 0 到 100 的整数") from error
        if not 0 <= main_plot_impact <= 100:
            raise ValueError("主线影响必须是 0 到 100 的整数")

        def clean_list(key, label):
            values = payload.get(key, [])
            if not isinstance(values, list) or len(values) > 24:
                raise ValueError(f"{label}格式不合法")
            cleaned = []
            for item in values:
                value = str(item).strip()
                if not value:
                    continue
                if len(value) > 40 or "\n" in value or "\r" in value:
                    raise ValueError(f"{label}中的单项不能超过 40 个字符")
                if value not in cleaned:
                    cleaned.append(value)
            return cleaned

        aliases = clean_list("aliases", "人物别名")
        markers = clean_list("markers", "人物标识")
        avatar = clean_text(payload.get("avatar"), "头像路径", 500)
        facts = payload.get("facts", {})
        if not isinstance(facts, dict) or len(facts) > 30:
            raise ValueError("人物档案字段格式不合法")
        project_root = self.project_root(project)
        characters_root = project_root / "characters"
        existing_ids = []
        existing_names = set()
        if characters_root.is_dir():
            for path in sorted(characters_root.rglob("*.md")):
                fields = parse_frontmatter(path.read_text(encoding="utf-8"))
                character_id = str(fields.get("id", "")).strip()
                existing_name = str(fields.get("name", "")).strip()
                if character_id.isdigit():
                    existing_ids.append(int(character_id))
                if existing_name:
                    existing_names.add(existing_name)
        if name in existing_names:
            raise ValueError("已经存在同名人物，请使用别名或修改现有档案")

        character_id = str(max(existing_ids, default=0) + 1)
        filename = canonical_character_filename(character_id, name)
        target = characters_root / filename
        if target.exists():
            raise ValueError("目标人物文件已经存在")

        gradient = f"linear-gradient(135deg, {color}, #6676c7)"
        fields = [
            "---",
            f"id: {character_id}",
            f"name: {json.dumps(name, ensure_ascii=False)}",
            f"narrativeRole: {json.dumps(narrative_role, ensure_ascii=False)}",
            f"characterScope: {json.dumps(scope, ensure_ascii=False)}",
            f"color: {json.dumps(color, ensure_ascii=False)}",
            f"gradient: {json.dumps(gradient, ensure_ascii=False)}",
            f"mainPlotImpact: {main_plot_impact}",
            f"side: {json.dumps(side, ensure_ascii=False)}",
        ]
        if group:
            fields.append(f"group: {json.dumps(group, ensure_ascii=False)}")
        if markers:
            fields.append(f"markers: {json.dumps(markers, ensure_ascii=False)}")
        if aliases:
            fields.append(f"aliases: {json.dumps(aliases, ensure_ascii=False)}")
        if avatar:
            fields.append(f"avatar: {json.dumps(avatar, ensure_ascii=False)}")
        if payload.get("graphVisible") is False:
            fields.append("graphVisible: false")
        if facts:
            fields.append("facts:")
            for label, value in facts.items():
                clean_label = clean_text(label, "档案字段名", 60, required=True)
                fields.append(f"  {clean_label}: {json.dumps(str(value), ensure_ascii=False)}")
        content = "\n".join((*fields, "---", intro, ""))

        characters_root.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)
        write_content_index(project_root, build_content_index(project_root))
        self.send_json(
            {
                "ok": True,
                "id": character_id,
                "name": name,
                "path": target.relative_to(project_root).as_posix(),
            },
            HTTPStatus.CREATED,
        )

    def update_character(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        character_id = clean_text(payload.get("id"), "人物 ID", 40, required=True)
        path, fields, original = self.locate_record(project_root, "character", character_id)
        name = str(fields.get("name", "")).strip("\"'")
        if not name:
            raise ValueError("人物档案缺少姓名")
        narrative_role = clean_text(payload.get("narrativeRole", "配角"), "人物定位", 20, required=True)
        scope = clean_text(payload.get("characterScope", "常驻人物"), "收纳状态", 20, required=True)
        side = clean_text(payload.get("side", "中立"), "人物阵营", 20, required=True)
        if narrative_role not in {"主角", "配角"} or scope not in CHARACTER_SCOPES or side not in {"主角方", "中立", "反派方"}:
            raise ValueError("人物分类设置不合法")
        impact = int(payload.get("mainPlotImpact", 50))
        if not 0 <= impact <= 100:
            raise ValueError("主线影响必须是 0 到 100 的整数")
        color = clean_text(payload.get("color"), "人物颜色", 20, required=True).lower()
        if not HEX_COLOR_PATTERN.fullmatch(color):
            raise ValueError("请选择有效的人物颜色")
        facts = payload.get("facts", {})
        if not isinstance(facts, dict) or len(facts) > 30:
            raise ValueError("人物档案字段格式不合法")
        gradient = str(fields.get("gradient", "")).strip("\"'")
        if gradient:
            gradient = re.sub(r"#[0-9A-Fa-f]{6}", color, gradient, count=1)
        else:
            gradient = f"linear-gradient(135deg, {color}, #6676c7)"
        managed_values = {
            "id": int(character_id) if character_id.isdigit() else character_id,
            "name": name,
            "aliases": clean_values(payload.get("aliases"), "人物别名", 24, 40),
            "color": color,
            "gradient": gradient,
            "avatar": clean_text(payload.get("avatar"), "头像路径", 500),
            "group": clean_text(payload.get("group"), "人物分组", 80),
            "markers": clean_values(payload.get("markers"), "人物标识", 24, 40),
            "narrativeRole": narrative_role,
            "mainPlotImpact": impact,
            "side": side,
            "characterScope": scope,
            "graphVisible": False if payload.get("graphVisible") is False else None,
            "facts": {clean_text(label, "档案字段名", 60, True): clean_text(value, "档案字段值", 300) for label, value in facts.items()},
        }
        updated = original
        for key, value in managed_values.items():
            if value is None or value == "" or value == [] or value == {}:
                updated = remove_frontmatter_field(updated, key)
            else:
                updated = update_frontmatter_field(updated, key, value)
        updated = replace_markdown_body(updated, str(payload.get("intro", ""))[:20000])
        atomic_write(path, updated)
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "id": character_id, "name": name, "path": path.relative_to(project_root).as_posix()})

    def create_relationship(self, payload):
        project = str(payload.get("project", ""))
        first_id = str(payload.get("firstId", "")).strip()
        second_id = str(payload.get("secondId", "")).strip()
        if not first_id or not second_id:
            raise ValueError("请选择关系双方")
        if first_id == second_id:
            raise ValueError("关系双方不能是同一个人物")

        def clean_field(key, label, required=True):
            value = str(payload.get(key, "")).strip()
            if required and not value:
                raise ValueError(f"请填写{label}")
            if len(value) > 80 or "\n" in value or "\r" in value:
                raise ValueError(f"{label}长度需要在 1 到 80 个字符之间")
            return value

        first_role = clean_field("firstRole", "第一位人物的身份")
        second_role = clean_field("secondRole", "第二位人物的身份")
        label = clean_field("label", "关系名称")
        relationship_type = clean_field("type", "关系类型", required=False)
        color = str(payload.get("color", "")).strip()
        if not HEX_COLOR_PATTERN.fullmatch(color):
            raise ValueError("请选择有效的关系颜色")

        project_root = self.project_root(project)
        character_names = {}
        character_counts = {}
        characters_root = project_root / "characters"
        if characters_root.is_dir():
            for path in sorted(characters_root.rglob("*.md")):
                fields = parse_frontmatter(path.read_text(encoding="utf-8"))
                character_id = str(fields.get("id", "")).strip()
                name = str(fields.get("name", "")).strip()
                if not character_id or not name:
                    continue
                character_counts[character_id] = character_counts.get(character_id, 0) + 1
                character_names[character_id] = name

        for character_id in (first_id, second_id):
            count = character_counts.get(character_id, 0)
            if count == 0:
                raise ValueError(f"找不到人物 id：{character_id}")
            if count > 1:
                raise ValueError(f"人物 id 重复，请先修复：{character_id}")

        relationships_root = project_root / "relationships"
        pair = frozenset((first_id, second_id))
        if relationships_root.is_dir():
            for path in sorted(relationships_root.rglob("*.md")):
                endpoint_ids = relationship_character_ids(path.read_text(encoding="utf-8"))
                if len(endpoint_ids) == 2 and frozenset(endpoint_ids) == pair:
                    raise ValueError("这两个人物已经存在关系，请直接编辑原关系文件")

        filename = canonical_relationship_filename(
            [first_id, second_id],
            character_names,
        )
        target = relationships_root / filename
        if target.exists():
            raise ValueError("目标关系文件已经存在")

        fields = [
            "---",
            "people:",
            f"  - id: {json.dumps(first_id, ensure_ascii=False)}",
            f"    role: {json.dumps(first_role, ensure_ascii=False)}",
            f"  - id: {json.dumps(second_id, ensure_ascii=False)}",
            f"    role: {json.dumps(second_role, ensure_ascii=False)}",
            f"label: {json.dumps(label, ensure_ascii=False)}",
            f"color: {json.dumps(color.lower(), ensure_ascii=False)}",
        ]
        if relationship_type:
            fields.append(f"type: {json.dumps(relationship_type, ensure_ascii=False)}")
        content = "\n".join((*fields, "---", "")) + "\n"

        relationships_root.mkdir(parents=True, exist_ok=True)
        atomic_write(target, content)
        write_content_index(project_root, build_content_index(project_root))
        self.send_json(
            {
                "ok": True,
                "path": target.relative_to(project_root).as_posix(),
                "label": label,
            },
            HTTPStatus.CREATED,
        )

    def update_relationship(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        relationship_id = clean_text(payload.get("id"), "关系 ID", 500, required=True)
        path, _, original = self.locate_record(project_root, "relationship", relationship_id)
        endpoint_ids = relationship_character_ids(original)
        if len(endpoint_ids) != 2:
            raise ValueError("人物关系必须恰好包含两个端点")
        first_role = clean_text(payload.get("firstRole"), "第一位人物的身份", 80, required=True)
        second_role = clean_text(payload.get("secondRole"), "第二位人物的身份", 80, required=True)
        label = clean_text(payload.get("label"), "关系名称", 80, required=True)
        relationship_type = clean_text(payload.get("type"), "关系类型", 80)
        color = clean_text(payload.get("color"), "关系颜色", 20, required=True).lower()
        if not HEX_COLOR_PATTERN.fullmatch(color):
            raise ValueError("请选择有效的关系颜色")
        content = "\n".join([
            "---",
            "people:",
            f"  - id: {json.dumps(endpoint_ids[0], ensure_ascii=False)}",
            f"    role: {json.dumps(first_role, ensure_ascii=False)}",
            f"  - id: {json.dumps(endpoint_ids[1], ensure_ascii=False)}",
            f"    role: {json.dumps(second_role, ensure_ascii=False)}",
            f"label: {json.dumps(label, ensure_ascii=False)}",
            f"color: {json.dumps(color, ensure_ascii=False)}",
            *([f"type: {json.dumps(relationship_type, ensure_ascii=False)}"] if relationship_type else []),
            "---",
            "",
        ])
        atomic_write(path, content)
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "id": "__".join(endpoint_ids), "label": label})

    def save_entry(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        entry_id = clean_text(payload.get("id"), "设定 ID", 80, required=True)
        filename = canonical_entry_filename(entry_id)
        name = clean_text(payload.get("name"), "设定名称", 120, required=True)
        fields = [
            ("id", entry_id),
            ("name", name),
            ("type", clean_text(payload.get("type", "设定"), "设定类型", 40, required=True)),
            ("subtype", clean_text(payload.get("subtype"), "设定子类型", 60)),
            ("area", clean_text(payload.get("area"), "所属区域", 100)),
            ("accent", clean_text(payload.get("accent", "#3f7fc1"), "设定颜色", 20, required=True).lower()),
            ("aliases", clean_values(payload.get("aliases"), "设定别名", 30, 60)),
            ("tags", clean_values(payload.get("tags"), "设定标签", 40, 60)),
            ("people", clean_values(payload.get("people"), "相关人物", 100, 40)),
            ("plots", [int(value) for value in clean_values(payload.get("plots"), "相关剧情", 200, 20) if str(value).isdigit()]),
            ("status", clean_text(payload.get("status"), "设定状态", 40)),
        ]
        if not HEX_COLOR_PATTERN.fullmatch(fields[5][1]):
            raise ValueError("请选择有效的设定颜色")
        target = project_root / "entries" / filename
        creating = bool(payload.get("create"))
        if creating:
            if target.exists() or any(str(parse_frontmatter(path.read_text(encoding="utf-8")).get("id", "")) == entry_id for path in (project_root / "entries").glob("*.md")):
                raise ValueError("已经存在相同 ID 的设定")
        else:
            target, old_fields, _ = self.locate_record(project_root, "entry", entry_id)
            old_name = str(old_fields.get("name", "")).strip("\"'")
            if old_name and old_name != name:
                raise ValueError("修改设定名称请使用检查页的安全重命名")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, serialize_markdown(fields, str(payload.get("body", ""))[:40000]))
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "id": entry_id, "name": name, "path": target.relative_to(project_root).as_posix()}, HTTPStatus.CREATED if creating else HTTPStatus.OK)

    def save_fragment(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        fragment_id = clean_text(payload.get("id"), "碎片 ID", 80, required=True)
        filename = canonical_fragment_filename(fragment_id)
        title = clean_text(payload.get("title"), "碎片标题", 120, required=True)
        accent = clean_text(payload.get("accent", "#7d6bd6"), "碎片颜色", 20, required=True).lower()
        if not HEX_COLOR_PATTERN.fullmatch(accent):
            raise ValueError("请选择有效的碎片颜色")
        fields = [
            ("id", fragment_id),
            ("title", title),
            ("status", clean_text(payload.get("status", "灵感"), "碎片状态", 40, required=True)),
            ("tags", clean_values(payload.get("tags"), "碎片标签", 40, 60)),
            ("accent", accent),
        ]
        target = project_root / "fragments" / filename
        creating = bool(payload.get("create"))
        if creating:
            if target.exists() or any(str(parse_frontmatter(path.read_text(encoding="utf-8")).get("id", "")) == fragment_id for path in (project_root / "fragments").glob("*.md")):
                raise ValueError("已经存在相同 ID 的碎片")
        else:
            target, _, _ = self.locate_record(project_root, "fragment", fragment_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(target, serialize_markdown(fields, str(payload.get("body", ""))[:40000]))
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "id": fragment_id, "title": title, "path": target.relative_to(project_root).as_posix()}, HTTPStatus.CREATED if creating else HTTPStatus.OK)

    def record_delete_files_and_patches(self, project_root, kind, record_id):
        path, fields, text = self.locate_record(project_root, kind, record_id)
        title = str(fields.get("name") or fields.get("title") or fields.get("label") or record_id).strip("\"'")
        files = [{"path": path.relative_to(project_root).as_posix(), "content": text}]
        patches = []
        if kind == "character":
            for relationship_path in sorted((project_root / "relationships").glob("*.md")):
                relationship_text = relationship_path.read_text(encoding="utf-8")
                if str(record_id) in relationship_character_ids(relationship_text):
                    files.append({"path": relationship_path.relative_to(project_root).as_posix(), "content": relationship_text})
            patch_targets = [("plots", "people"), ("entries", "people")]
        elif kind == "entry":
            patch_targets = [("plots", "entries")]
        else:
            patch_targets = []
        for directory_name, key in patch_targets:
            directory = project_root / directory_name
            if not directory.is_dir():
                continue
            for target in sorted(directory.glob("*.md")):
                before = target.read_text(encoding="utf-8")
                after = remove_frontmatter_list_value(before, key, record_id)
                if after != before:
                    patches.append({"path": target.relative_to(project_root).as_posix(), "before": before, "after": after})
        return title, files, patches

    def delete_record(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        kind = clean_text(payload.get("kind"), "档案类型", 30, required=True)
        record_id = clean_text(payload.get("id"), "档案 ID", 500, required=True)
        if kind not in {"character", "entry", "fragment", "relationship"}:
            raise ValueError("不支持的档案类型")
        purge_expired_record_trash(project_root)
        title, files, patches = self.record_delete_files_and_patches(project_root, kind, record_id)
        deleted_at = int(time.time())
        trash_id = f"{deleted_at}-{kind}-{secrets.token_hex(5)}.json"
        trash_path = project_root / ".trash" / "records" / trash_id
        bundle = {"version": 1, "kind": kind, "id": record_id, "title": title, "deletedAt": deleted_at, "files": files, "patches": patches}
        trash_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(trash_path, json.dumps(bundle, ensure_ascii=False, indent=2) + "\n")
        changed = []
        removed = []
        try:
            for patch in patches:
                target = project_root / patch["path"]
                atomic_write(target, patch["after"])
                changed.append(patch)
            for file in files:
                target = project_root / file["path"]
                target.unlink()
                removed.append(file)
            write_content_index(project_root, build_content_index(project_root))
        except OSError:
            for file in removed:
                atomic_write(project_root / file["path"], file["content"])
            for patch in reversed(changed):
                atomic_write(project_root / patch["path"], patch["before"])
            trash_path.unlink(missing_ok=True)
            write_content_index(project_root, build_content_index(project_root))
            raise
        self.send_json({"ok": True, "trashId": trash_id, "kind": kind, "id": record_id, "title": title, "expiresAt": deleted_at + RECORD_TRASH_RETENTION_SECONDS})

    def restore_record(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        trash_id = clean_text(payload.get("trashId"), "回收站档案", 300, required=True)
        record = next((item for item in record_trash_records(project_root) if item["trashId"] == trash_id), None)
        if not record:
            raise ValueError("这份档案已不在回收站中")
        bundle = record["_payload"]
        for file in bundle.get("files", []):
            if (project_root / file["path"]).exists():
                raise ValueError(f"恢复位置已被占用：{file['path']}")
        for patch in bundle.get("patches", []):
            target = project_root / patch["path"]
            if target.is_file() and target.read_text(encoding="utf-8") != patch["after"]:
                raise ValueError(f"{patch['path']} 在删除后已被修改，无法安全恢复引用")
        written = []
        try:
            for file in bundle.get("files", []):
                target = project_root / file["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(target, file["content"])
                written.append(target)
            for patch in bundle.get("patches", []):
                atomic_write(project_root / patch["path"], patch["before"])
            record["_path"].unlink()
            write_content_index(project_root, build_content_index(project_root))
        except OSError:
            for target in written:
                target.unlink(missing_ok=True)
            raise
        self.send_json({"ok": True, "kind": record["kind"], "id": record["id"], "title": record["title"]})

    def create_plot(self, payload):
        project = str(payload.get("project", ""))
        values = validate_plot_payload(payload)
        title = values["title"]
        summary = values["summary"]
        body = values["body"]
        chapter = values["chapter"]
        status = values["status"]
        accent = values["accent"]
        tags = values["tags"]
        lanes = values["lanes"]
        project_root = self.project_root(project)
        purge_expired_plot_trash(project_root)
        reserved_plot_ids = [record["id"] for record in plot_trash_records(project_root)]
        plots_root = project_root / "plots"
        records = []
        if plots_root.is_dir():
            for path in sorted(plots_root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                fields = parse_frontmatter(text)
                plot_id = str(fields.get("id", "")).strip()
                if not plot_id.isdigit():
                    raise ValueError(f"剧情文件缺少数字 id：{path.relative_to(project_root).as_posix()}")
                raw_sequence = str(fields.get("sequence", plot_id)).strip()
                if not raw_sequence.isdigit() or int(raw_sequence) < 1:
                    raise ValueError(f"剧情顺序不合法：{path.relative_to(project_root).as_posix()}")
                records.append({
                    "path": path,
                    "text": text,
                    "id": int(plot_id),
                    "sequence": int(raw_sequence),
                })

        sequences = [record["sequence"] for record in records]
        if len(sequences) != len(set(sequences)):
            raise ValueError("剧情顺序存在重复，请先修复配置")
        plot_ids = [record["id"] for record in records]
        if len(plot_ids) != len(set(plot_ids)):
            raise ValueError("剧情 id 存在重复，请先修复配置")
        max_sequence = max(sequences, default=0)
        raw_insert_at = payload.get("insertAt")
        if raw_insert_at in (None, ""):
            insert_at = max_sequence + 1
        else:
            try:
                insert_at = int(raw_insert_at)
            except (TypeError, ValueError) as error:
                raise ValueError("插入位置必须是有效章节号") from error
            if insert_at < 1 or insert_at > max_sequence + 1:
                raise ValueError(f"插入位置需要在 1 到 {max_sequence + 1} 之间")

        new_id = max([*(record["id"] for record in records), *reserved_plot_ids], default=0) + 1
        filename = canonical_plot_filename(new_id, title)
        target = plots_root / filename
        if target.exists():
            raise ValueError("目标剧情文件已经存在")

        fields = [
            "---",
            f"id: {new_id}",
            f"sequence: {insert_at}",
            f"chapter: {json.dumps(chapter, ensure_ascii=False)}",
            f"title: {json.dumps(title, ensure_ascii=False)}",
        ]
        if summary:
            fields.append(f"summary: {json.dumps(summary, ensure_ascii=False)}")
        fields.extend([
            f"accent: {json.dumps(accent, ensure_ascii=False)}",
            f"status: {json.dumps(status, ensure_ascii=False)}",
        ])
        if lanes:
            fields.append(f"lanes: {json.dumps(lanes, ensure_ascii=False)}")
        if tags:
            fields.append(f"tags: {json.dumps(tags, ensure_ascii=False)}")
        if values["people"]:
            fields.append(f"people: {json.dumps(values['people'], ensure_ascii=False)}")
        if values["entries"]:
            fields.append(f"entries: {json.dumps(values['entries'], ensure_ascii=False)}")
        if values["key"]:
            fields.append("key: true")
        if values["climax"]:
            fields.append("climax: true")
        content = "\n".join((*fields, "---", body, ""))

        shifted = [record for record in records if record["sequence"] >= insert_at]
        written = []
        created = False
        try:
            for record in sorted(shifted, key=lambda item: item["sequence"], reverse=True):
                updated = update_frontmatter_field(
                    record["text"],
                    "sequence",
                    record["sequence"] + 1,
                )
                atomic_write(record["path"], updated)
                written.append((record["path"], record["text"]))
            plots_root.mkdir(parents=True, exist_ok=True)
            atomic_write(target, content)
            created = True
            write_content_index(project_root, build_content_index(project_root))
        except OSError:
            if created:
                target.unlink(missing_ok=True)
            for path, original in reversed(written):
                atomic_write(path, original)
            write_content_index(project_root, build_content_index(project_root))
            raise

        self.send_json(
            {
                "ok": True,
                "id": new_id,
                "sequence": insert_at,
                "title": title,
                "shiftedCount": len(shifted),
                "path": target.relative_to(project_root).as_posix(),
            },
            HTTPStatus.CREATED,
        )

    def locate_plot(self, project_root, plot_id):
        clean_id = str(plot_id or "").strip()
        if not clean_id.isdigit():
            raise ValueError("请选择有效的剧情")
        candidates = []
        plots_root = project_root / "plots"
        if plots_root.is_dir():
            for path in sorted(plots_root.rglob("*.md")):
                resolved_path = path.resolve()
                if project_root.resolve() not in resolved_path.parents or not path.is_file():
                    continue
                text = path.read_text(encoding="utf-8")
                fields = parse_frontmatter(text)
                if str(fields.get("id", "")).strip() == clean_id:
                    candidates.append((path, fields, text))
        if not candidates:
            raise ValueError("找不到需要操作的剧情")
        if len(candidates) > 1:
            raise ValueError("剧情 id 重复，请先修复配置问题")
        return candidates[0]

    def update_timeline(self, payload):
        project = str(payload.get("project", ""))
        project_root = self.project_root(project)
        plots_root = project_root / "plots"
        plot_records = []
        if plots_root.is_dir():
            for path in sorted(plots_root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                fields = parse_frontmatter(text)
                raw_id = str(fields.get("id", "")).strip()
                raw_sequence = str(fields.get("sequence", raw_id)).strip()
                if not raw_id.isdigit() or not raw_sequence.isdigit():
                    raise ValueError(f"剧情编号或顺序不合法：{path.relative_to(project_root).as_posix()}")
                plot_records.append({
                    "path": path,
                    "text": text,
                    "id": int(raw_id),
                    "sequence": int(raw_sequence),
                })
        if not plot_records:
            raise ValueError("当前项目没有可编排的剧情")
        plot_ids = [record["id"] for record in plot_records]
        if len(plot_ids) != len(set(plot_ids)):
            raise ValueError("剧情 id 存在重复，请先修复配置")

        config = validate_timeline_payload(payload, plot_records)
        timeline_path = project_root / "timeline.md"
        previous_timeline = timeline_path.read_text(encoding="utf-8") if timeline_path.is_file() else None
        written = []
        try:
            for record in plot_records:
                lanes = config["assignments"][record["id"]]
                updated = (
                    update_frontmatter_field(record["text"], "lanes", lanes)
                    if lanes
                    else remove_frontmatter_field(record["text"], "lanes")
                )
                if updated == record["text"]:
                    continue
                atomic_write(record["path"], updated)
                written.append((record["path"], record["text"]))
            atomic_write(timeline_path, serialize_timeline_document(config))
            write_content_index(project_root, build_content_index(project_root))
        except (OSError, ValueError):
            if previous_timeline is None:
                timeline_path.unlink(missing_ok=True)
            else:
                atomic_write(timeline_path, previous_timeline)
            for path, previous in reversed(written):
                atomic_write(path, previous)
            write_content_index(project_root, build_content_index(project_root))
            raise

        self.send_json({
            "ok": True,
            "lineCount": len(config["lines"]),
            "plotCount": len(plot_records),
            "updatedPlotCount": len(written),
        })

    def update_plot(self, payload):
        project = str(payload.get("project", ""))
        plot_id = str(payload.get("id", "")).strip()
        values = validate_plot_payload(payload)
        project_root = self.project_root(project)
        target, _, original = self.locate_plot(project_root, plot_id)
        destination = target.with_name(canonical_plot_filename(plot_id, values["title"]))
        if destination != target and destination.exists():
            raise ValueError("修改后的剧情文件名已经存在")

        if "sequence" not in payload:
            updated = update_plot_document(original, values)
            moved = False
            try:
                atomic_write(target, updated)
                if destination != target:
                    os.replace(target, destination)
                    moved = True
                write_content_index(project_root, build_content_index(project_root))
            except OSError:
                if moved and destination.exists():
                    os.replace(destination, target)
                atomic_write(target, original)
                write_content_index(project_root, build_content_index(project_root))
                raise
            self.send_json({
                "ok": True,
                "id": int(plot_id),
                "title": values["title"],
                "sequence": int(parse_frontmatter(original).get("sequence", plot_id)),
                "reorderedCount": 0,
                "path": destination.relative_to(project_root).as_posix(),
            })
            return

        records = []
        for path in sorted((project_root / "plots").rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            raw_id = str(fields.get("id", "")).strip()
            raw_sequence = str(fields.get("sequence", raw_id)).strip()
            if not raw_id.isdigit() or not raw_sequence.isdigit():
                raise ValueError("剧情编号或顺序不合法")
            records.append({"id": int(raw_id), "sequence": int(raw_sequence), "path": path, "text": text})
        records.sort(key=lambda item: (item["sequence"], item["id"]))
        target_record = next((item for item in records if item["id"] == int(plot_id)), None)
        if not target_record:
            raise ValueError("找不到需要修改的剧情")
        raw_sequence = payload.get("sequence", target_record["sequence"])
        try:
            requested_sequence = int(raw_sequence)
        except (TypeError, ValueError) as error:
            raise ValueError("章节顺序必须是有效数字") from error
        if requested_sequence < 1 or requested_sequence > len(records):
            raise ValueError(f"章节顺序需要在 1 到 {len(records)} 之间")
        records.remove(target_record)
        records.insert(requested_sequence - 1, target_record)

        updated_documents = []
        for sequence, record in enumerate(records, start=1):
            content = record["text"]
            if record is target_record:
                content = update_plot_document(content, values)
            content = update_frontmatter_field(content, "sequence", sequence)
            updated_documents.append((record["path"], record["text"], content))
        moved = False
        written = []
        try:
            for path, before, after in updated_documents:
                if before == after:
                    continue
                atomic_write(path, after)
                written.append((path, before))
            if destination != target:
                os.replace(target, destination)
                moved = True
            write_content_index(project_root, build_content_index(project_root))
        except OSError:
            if moved and destination.exists():
                os.replace(destination, target)
            for path, before in reversed(written):
                atomic_write(path, before)
            write_content_index(project_root, build_content_index(project_root))
            raise

        self.send_json(
            {
                "ok": True,
                "id": int(plot_id),
                "title": values["title"],
                "sequence": requested_sequence,
                "reorderedCount": sum(1 for path, before, after in updated_documents if before != after),
                "path": destination.relative_to(project_root).as_posix(),
            }
        )

    def delete_plot(self, payload):
        project = str(payload.get("project", ""))
        plot_id = str(payload.get("id", "")).strip()
        project_root = self.project_root(project)
        purge_expired_plot_trash(project_root)
        target, fields, original = self.locate_plot(project_root, plot_id)
        raw_sequence = str(fields.get("sequence", plot_id)).strip()
        if not raw_sequence.isdigit() or int(raw_sequence) < 1:
            raise ValueError("目标剧情的章节顺序不合法")
        target_sequence = int(raw_sequence)
        written = []
        moved = False
        shifted_count = 0
        deleted_at = int(time.time())
        trash_root = project_root / ".trash" / "plots"
        trash_target = trash_root / f"{deleted_at}-{target.name}"
        if trash_target.exists():
            raise ValueError("回收站中已经存在同名剧情，请稍后重试")

        try:
            remaining = []
            for path in sorted((project_root / "plots").rglob("*.md")):
                if path == target:
                    continue
                text = path.read_text(encoding="utf-8")
                plot_fields = parse_frontmatter(text)
                raw_other_id = str(plot_fields.get("id", "")).strip()
                raw_other_sequence = str(plot_fields.get("sequence", plot_fields.get("id", ""))).strip()
                if not raw_other_id.isdigit() or not raw_other_sequence.isdigit():
                    raise ValueError(f"剧情编号或顺序不合法：{path.relative_to(project_root).as_posix()}")
                remaining.append(
                    {
                        "path": path,
                        "text": text,
                        "id": int(raw_other_id),
                        "sequence": int(raw_other_sequence),
                    }
                )
            remaining.sort(key=lambda item: (item["sequence"], item["id"]))
            for next_sequence, record in enumerate(remaining, start=1):
                if record["sequence"] == next_sequence and "sequence" in parse_frontmatter(record["text"]):
                    continue
                updated = update_frontmatter_field(record["text"], "sequence", next_sequence)
                atomic_write(record["path"], updated)
                written.append((record["path"], record["text"]))
                shifted_count += 1
            trash_root.mkdir(parents=True, exist_ok=True)
            os.replace(target, trash_target)
            moved = True
            write_content_index(project_root, build_content_index(project_root))
        except (OSError, ValueError):
            if moved and trash_target.exists():
                os.replace(trash_target, target)
            for path, previous in reversed(written):
                atomic_write(path, previous)
            write_content_index(project_root, build_content_index(project_root))
            raise

        self.send_json(
            {
                "ok": True,
                "id": int(plot_id),
                "title": str(fields.get("title", "")),
                "shiftedCount": shifted_count,
                "trashId": trash_target.name,
                "expiresAt": deleted_at + PLOT_TRASH_RETENTION_SECONDS,
            }
        )

    def restore_plot(self, payload):
        project = str(payload.get("project", ""))
        trash_id = str(payload.get("trashId", "")).strip()
        if not trash_id or Path(trash_id).name != trash_id:
            raise ValueError("请选择有效的回收站剧情")
        project_root = self.project_root(project)
        purge_expired_plot_trash(project_root)
        record = next(
            (item for item in plot_trash_records(project_root) if item["trashId"] == trash_id),
            None,
        )
        if not record:
            raise ValueError("这条剧情已不在回收站中")

        plots_root = project_root / "plots"
        destination = plots_root / record["originalFilename"]
        if destination.exists():
            raise ValueError("原剧情文件位置已被占用，无法恢复")

        active_records = []
        for path in (sorted(plots_root.rglob("*.md")) if plots_root.is_dir() else []):
            text = path.read_text(encoding="utf-8")
            fields = parse_frontmatter(text)
            active_id = str(fields.get("id", "")).strip()
            raw_sequence = str(fields.get("sequence", active_id)).strip()
            if active_id == str(record["id"]):
                raise ValueError("当前剧情列表中已经存在相同 ID，无法恢复")
            if not raw_sequence.isdigit():
                raise ValueError(f"剧情顺序不合法：{path.relative_to(project_root).as_posix()}")
            active_records.append(
                {"path": path, "text": text, "sequence": int(raw_sequence)}
            )

        restore_sequence = min(
            record["sequence"],
            max((item["sequence"] for item in active_records), default=0) + 1,
        )
        shifted = [item for item in active_records if item["sequence"] >= restore_sequence]
        written = []
        moved = False
        try:
            for item in sorted(shifted, key=lambda value: value["sequence"], reverse=True):
                updated = update_frontmatter_field(item["text"], "sequence", item["sequence"] + 1)
                atomic_write(item["path"], updated)
                written.append((item["path"], item["text"]))
            restored = update_frontmatter_field(record["_text"], "sequence", restore_sequence)
            atomic_write(record["_path"], restored)
            plots_root.mkdir(parents=True, exist_ok=True)
            os.replace(record["_path"], destination)
            moved = True
            write_content_index(project_root, build_content_index(project_root))
        except (OSError, ValueError):
            if moved and destination.exists():
                os.replace(destination, record["_path"])
                atomic_write(record["_path"], record["_text"])
            elif record["_path"].exists():
                atomic_write(record["_path"], record["_text"])
            for path, previous in reversed(written):
                atomic_write(path, previous)
            write_content_index(project_root, build_content_index(project_root))
            raise

        self.send_json(
            {
                "ok": True,
                "id": record["id"],
                "title": record["title"],
                "sequence": restore_sequence,
                "shiftedCount": len(shifted),
            }
        )

    def update_character_scope(self, payload):
        project = str(payload.get("project", ""))
        target_id = str(payload.get("id", "")).strip()
        scope = str(payload.get("scope", "")).strip()
        if not target_id:
            raise ValueError("请选择人物")
        if scope not in CHARACTER_SCOPES:
            raise ValueError("人物收纳状态不合法")

        project_root = self.project_root(project)
        target_path, fields, text = self.locate_target(project_root, "character", target_id)
        name = str(fields.get("name", "")).strip()
        updated = update_frontmatter_field(text, "characterScope", scope)
        if updated != text:
            atomic_write(target_path, updated)
        self.send_json(
            {
                "ok": True,
                "id": target_id,
                "name": name,
                "scope": scope,
                "path": target_path.relative_to(project_root).as_posix(),
            }
        )

    def update_project(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        title = clean_text(payload.get("title"), "作品名称", 120, required=True)
        eyebrow = clean_text(payload.get("eyebrow", "Story Teller"), "顶部名称", 80, required=True)
        raw_chapters = payload.get("chapters", [])
        if not isinstance(raw_chapters, list) or not 1 <= len(raw_chapters) <= 30:
            raise ValueError("作品需要包含 1 到 30 个篇章")
        chapters = []
        used = set()
        for item in raw_chapters:
            if not isinstance(item, dict):
                raise ValueError("篇章数据格式不合法")
            chapter_id = clean_text(item.get("id"), "篇章 ID", 40, required=True)
            if not ASCII_NAME_PATTERN.fullmatch(chapter_id) or chapter_id in used:
                raise ValueError("篇章 ID 必须唯一，且只能包含英文字母、数字、横线和下划线")
            label = clean_text(item.get("label"), "篇章名称", 80, required=True)
            chapters.append((chapter_id, label))
            used.add(chapter_id)
        active_chapters = set()
        plots_root = project_root / "plots"
        if plots_root.is_dir():
            for path in plots_root.rglob("*.md"):
                active_chapters.add(str(parse_frontmatter(path.read_text(encoding="utf-8")).get("chapter", "")).strip("\"'"))
        removed_in_use = active_chapters - used
        if removed_in_use:
            raise ValueError(f"以下篇章仍有文章，不能删除：{'、'.join(sorted(removed_in_use))}")
        fields = [("title", title), ("eyebrow", eyebrow), ("chapters", [item[0] for item in chapters])]
        fields.extend((f"chapter{chapter_id[:1].upper()}{chapter_id[1:]}", label) for chapter_id, label in chapters)
        atomic_write(project_root / "manifest.md", serialize_markdown(fields, "# Story Data Manifest\n\n项目内容由网页管理，Markdown 仅用于持久化。"))
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "title": title, "chapterCount": len(chapters)})

    def create_project(self, payload):
        project_id = clean_text(payload.get("id"), "项目 ID", 60, required=True)
        if not PROJECT_PATTERN.fullmatch(project_id):
            raise ValueError("项目 ID 只能包含英文字母、数字、横线和下划线")
        root = (self.server.content_root / project_id).resolve()
        if self.server.content_root.resolve() not in root.parents or root.exists():
            raise ValueError("项目已经存在或项目路径不合法")
        title = clean_text(payload.get("title"), "作品名称", 120, required=True)
        root.mkdir(parents=True)
        try:
            for directory in CONTENT_DIRECTORIES.values():
                (root / directory).mkdir()
            atomic_write(root / "manifest.md", serialize_markdown([
                ("title", title), ("eyebrow", "Story Teller"), ("chapters", ["act1"]), ("chapterAct1", "第一篇")
            ], "# Story Data Manifest\n\n项目内容由网页管理，Markdown 仅用于持久化。"))
            atomic_write(root / "timeline.md", serialize_markdown([
                ("version", 2), ("mainLine", "主线"), ("lineSpacing", 72), ("topPadding", 54), ("sidePadding", 34)
            ], "# Timeline Layout\n\n## Lines\n\n- name: 主线\n  color: \"#d65f8f\"\n  side: center\n  order: 1"))
            atomic_write(root / "graph-layout.md", serialize_markdown([
                ("nodeSpacing", 116), ("relationshipDistance", 250), ("leafDistanceExtra", 48),
                ("centerStrength", 1), ("groupStrength", 1), ("leafStrength", 1)
            ], ""))
            write_content_index(root, build_content_index(root))
        except OSError:
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    path.rmdir()
            root.rmdir()
            raise
        self.send_json({"ok": True, "id": project_id, "title": title}, HTTPStatus.CREATED)

    def update_graph_layout(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        path = project_root / "graph-layout.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else "---\ndescription: \"人物图谱布局由网页管理\"\n---\n"
        numeric_fields = {
            "nodeSpacing": (80, 260),
            "relationshipDistance": (120, 600),
            "leafDistanceExtra": (0, 300),
            "centerStrength": (0, 3),
            "groupStrength": (0, 3),
            "leafStrength": (0, 3),
        }
        for key, (minimum, maximum) in numeric_fields.items():
            value = float(payload.get(key, parse_frontmatter(text).get(key, minimum)))
            if not minimum <= value <= maximum:
                raise ValueError(f"图谱参数 {key} 超出允许范围")
            text = update_frontmatter_field(text, key, int(value) if value.is_integer() else value)
        anchors = payload.get("anchors", [])
        if not isinstance(anchors, list) or len(anchors) > 500:
            raise ValueError("图谱位置数据格式不合法")
        character_ids = set(self.character_names(project_root))
        anchor_lines = ["## Saved Positions", ""]
        for item in anchors:
            character_id = str(item.get("id", "")).strip()
            if character_id not in character_ids:
                continue
            x = float(item.get("x"))
            y = float(item.get("y"))
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("人物位置包含无效坐标")
            anchor_lines.extend([f"- id: {json.dumps(character_id, ensure_ascii=False)}", f"  x: {round(x, 2)}", f"  y: {round(y, 2)}"])
        match = FRONTMATTER_PATTERN.match(text)
        body = text[match.end():].strip() if match else ""
        body = re.sub(r"(?ms)^## Saved Positions\s*\n.*?(?=^## |\Z)", "", body).strip()
        body = "\n\n".join(part for part in [body, "\n".join(anchor_lines).strip()] if part)
        atomic_write(path, replace_markdown_body(text, body))
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "anchorCount": len(anchors)})

    def repair_diagnostics(self, payload):
        project_root = self.project_root(str(payload.get("project", "")))
        changes = 0
        plots_root = project_root / "plots"
        records = []
        if plots_root.is_dir():
            for path in plots_root.rglob("*.md"):
                text = path.read_text(encoding="utf-8")
                fields = parse_frontmatter(text)
                raw_id = str(fields.get("id", "")).strip()
                raw_sequence = str(fields.get("sequence", raw_id)).strip()
                records.append((int(raw_sequence) if raw_sequence.isdigit() else 10**9, int(raw_id) if raw_id.isdigit() else 10**9, path, text))
        for sequence, (_, _, path, text) in enumerate(sorted(records), start=1):
            updated = update_frontmatter_field(text, "sequence", sequence)
            if updated != text:
                atomic_write(path, updated)
                changes += 1
        character_names = self.character_names(project_root)
        for path in sorted((project_root / "characters").glob("*.md")):
            fields = parse_frontmatter(path.read_text(encoding="utf-8"))
            character_id = str(fields.get("id", "")).strip()
            name = str(fields.get("name", "")).strip("\"'")
            if not character_id or not name:
                continue
            destination = path.with_name(canonical_character_filename(character_id, name))
            if destination != path and not destination.exists():
                os.replace(path, destination)
                changes += 1
        character_names = self.character_names(project_root)
        for path in sorted((project_root / "relationships").glob("*.md")):
            ids = relationship_character_ids(path.read_text(encoding="utf-8"))
            if len(ids) != 2 or any(item not in character_names for item in ids):
                continue
            destination = path.with_name(canonical_relationship_filename(ids, character_names))
            if destination != path and not destination.exists():
                os.replace(path, destination)
                changes += 1
        active_character_ids = set(character_names)
        active_entry_ids = {
            str(parse_frontmatter(path.read_text(encoding="utf-8")).get("id", "")).strip()
            for path in (project_root / "entries").glob("*.md")
        }
        active_plot_ids = {
            str(parse_frontmatter(path.read_text(encoding="utf-8")).get("id", "")).strip()
            for path in (project_root / "plots").glob("*.md")
        }
        reference_rules = [
            ("plots", "people", active_character_ids),
            ("plots", "entries", active_entry_ids),
            ("characters", "events", active_plot_ids),
            ("entries", "people", active_character_ids),
            ("entries", "plots", active_plot_ids),
        ]
        for directory, key, valid_ids in reference_rules:
            for path in sorted((project_root / directory).glob("*.md")):
                before = path.read_text(encoding="utf-8")
                after = before
                for value in frontmatter_list_values(before, key):
                    if value not in valid_ids:
                        after = remove_frontmatter_list_value(after, key, value)
                if after != before:
                    atomic_write(path, after)
                    changes += 1
        write_content_index(project_root, build_content_index(project_root))
        self.send_json({"ok": True, "changeCount": changes})

    def character_filename_moves(
        self,
        project_root,
        target_path,
        target_id,
        new_name,
    ):
        character_names = self.character_names(project_root)
        character_names[target_id] = new_name
        moves = []
        target_relative = target_path.relative_to(project_root).as_posix()
        canonical_target = (
            Path("characters") / canonical_character_filename(target_id, new_name)
        ).as_posix()
        if target_relative != canonical_target:
            moves.append({"from": target_relative, "to": canonical_target})

        relationships_root = project_root / "relationships"
        if relationships_root.is_dir():
            for path in sorted(relationships_root.rglob("*.md")):
                text = path.read_text(encoding="utf-8")
                endpoint_ids = relationship_character_ids(text)
                if target_id not in endpoint_ids:
                    continue
                relative_path = path.relative_to(project_root).as_posix()
                canonical_path = (
                    Path("relationships")
                    / canonical_relationship_filename(endpoint_ids, character_names)
                ).as_posix()
                if relative_path != canonical_path:
                    moves.append({"from": relative_path, "to": canonical_path})
        return moves

    def resolve_operation_path(self, project_root, relative_path):
        path = (project_root / relative_path).resolve()
        if project_root not in path.parents:
            raise ValueError("文件路径超出当前内容包")
        return path

    def validate_moves(self, project_root, moves):
        for move in moves:
            source = self.resolve_operation_path(project_root, move["from"])
            target = self.resolve_operation_path(project_root, move["to"])
            if not source.is_file():
                raise ValueError(f"{move['from']} 已不存在，请重新预览")
            if target.exists():
                try:
                    same_file = os.path.samefile(source, target)
                except OSError:
                    same_file = False
                if not same_file:
                    raise ValueError(f"目标文件已存在：{move['to']}")

    def preview_refactor(self, payload):
        project = str(payload.get("project", ""))
        target_type = str(payload.get("type", ""))
        target_id = str(payload.get("id", "")).strip()
        new_name = str(payload.get("newName", "")).strip()
        if not target_id:
            raise ValueError("请选择需要重命名的档案")
        if not new_name or len(new_name) > 80 or "\n" in new_name or "\r" in new_name:
            raise ValueError("新名称长度需要在 1 到 80 个字符之间")

        project_root = self.project_root(project)
        target_path, fields, _ = self.locate_target(project_root, target_type, target_id)
        old_name = str(fields.get("name", "")).strip()
        if not old_name:
            raise ValueError("目标档案没有 name 字段")
        if old_name == new_name:
            raise ValueError("新名称与当前名称相同")
        if target_type == "character":
            canonical_character_filename(target_id, new_name)

        replacements = {}
        samples = []
        total_matches = 0
        for path in sorted(project_root.rglob("*.md")):
            resolved_path = path.resolve()
            if project_root not in resolved_path.parents:
                continue
            original = path.read_text(encoding="utf-8")
            updated = replace_name(original, old_name, new_name)
            if updated == original:
                continue
            match_count = original.count(old_name)
            if ASCII_NAME_PATTERN.fullmatch(old_name):
                match_count = len(
                    re.findall(
                        rf"(?<![A-Za-z0-9_-]){re.escape(old_name)}(?![A-Za-z0-9_-])",
                        original,
                    )
                )
            total_matches += match_count
            relative_path = path.relative_to(project_root).as_posix()
            replacements[relative_path] = {"before": original, "after": updated}
            for line_number, line in enumerate(original.splitlines(), start=1):
                if old_name not in line or len(samples) >= 60:
                    continue
                samples.append(
                    {
                        "file": relative_path,
                        "line": line_number,
                        "before": line.strip(),
                        "after": replace_name(line, old_name, new_name).strip(),
                    }
                )

        if target_path.relative_to(project_root).as_posix() not in replacements:
            raise ValueError("目标档案中没有找到当前名称")

        moves = (
            self.character_filename_moves(
                project_root,
                target_path,
                target_id,
                new_name,
            )
            if target_type == "character"
            else []
        )
        self.validate_moves(project_root, moves)

        operation_id = secrets.token_urlsafe(18)
        self.server.prune_previews()
        self.server.previews[operation_id] = {
            "createdAt": time.time(),
            "project": project,
            "type": target_type,
            "id": target_id,
            "oldName": old_name,
            "newName": new_name,
            "files": replacements,
            "moves": moves,
        }
        affected_files = set(replacements)
        affected_files.update(move["from"] for move in moves)
        self.send_json(
            {
                "ok": True,
                "operationId": operation_id,
                "oldName": old_name,
                "newName": new_name,
                "fileCount": len(affected_files),
                "matchCount": total_matches,
                "samples": samples,
                "moves": moves,
            }
        )

    def apply_refactor(self, payload):
        operation_id = str(payload.get("operationId", ""))
        operation = self.server.previews.get(operation_id)
        if not operation:
            raise ValueError("预览已失效，请重新生成")
        project_root = self.project_root(operation["project"])
        moves = operation.get("moves", [])

        for relative_path, contents in operation["files"].items():
            path = self.resolve_operation_path(project_root, relative_path)
            if project_root not in path.parents or path.read_text(encoding="utf-8") != contents["before"]:
                raise ValueError(f"{relative_path} 已发生变化，请重新预览")
        self.validate_moves(project_root, moves)

        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        backup = {
            "project": operation["project"],
            "oldName": operation["oldName"],
            "newName": operation["newName"],
            "createdAt": time.time(),
            "files": operation["files"],
            "moves": moves,
        }
        backup_text = json.dumps(backup, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=STATE_ROOT,
            delete=False,
        ) as handle:
            handle.write(backup_text)
            temporary_backup = Path(handle.name)
        os.replace(temporary_backup, UNDO_PATH)

        written = []
        completed_moves = []
        try:
            for relative_path, contents in operation["files"].items():
                path = project_root / relative_path
                atomic_write(path, contents["after"])
                written.append((path, contents["before"]))
            for move in moves:
                source = project_root / move["from"]
                target = project_root / move["to"]
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
                completed_moves.append((source, target))
            write_content_index(project_root, build_content_index(project_root))
        except OSError:
            for source, target in reversed(completed_moves):
                if target.exists():
                    os.replace(target, source)
            for path, original in reversed(written):
                atomic_write(path, original)
            write_content_index(project_root, build_content_index(project_root))
            UNDO_PATH.unlink(missing_ok=True)
            raise

        self.server.previews.pop(operation_id, None)
        affected_files = set(operation["files"])
        affected_files.update(move["from"] for move in moves)
        self.send_json(
            {
                "ok": True,
                "fileCount": len(affected_files),
                "oldName": operation["oldName"],
                "newName": operation["newName"],
            }
        )

    def undo_refactor(self, payload):
        project = str(payload.get("project", ""))
        project_root = self.project_root(project)
        backup = self.undo_metadata()
        if not backup or backup.get("project") != project:
            raise ValueError("当前项目没有可以撤销的重命名")
        moves = backup.get("moves", [])
        moved_paths = {move["from"]: move["to"] for move in moves}

        for relative_path, contents in backup["files"].items():
            current_relative_path = moved_paths.get(relative_path, relative_path)
            path = self.resolve_operation_path(project_root, current_relative_path)
            if project_root not in path.parents or path.read_text(encoding="utf-8") != contents["after"]:
                raise ValueError(f"{current_relative_path} 在重命名后又被修改，无法安全撤销")
        for move in moves:
            source = self.resolve_operation_path(project_root, move["from"])
            target = self.resolve_operation_path(project_root, move["to"])
            same_file = False
            if source.exists() and target.exists():
                try:
                    same_file = os.path.samefile(source, target)
                except OSError:
                    same_file = False
            if not target.is_file() or (source.exists() and not same_file):
                raise ValueError(f"{move['to']} 已发生变化，无法安全撤销")

        written = []
        completed_moves = []
        try:
            for move in reversed(moves):
                source = project_root / move["from"]
                target = project_root / move["to"]
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, source)
                completed_moves.append((source, target))
            for relative_path, contents in backup["files"].items():
                path = project_root / relative_path
                atomic_write(path, contents["before"])
                written.append((path, contents["after"]))
            write_content_index(project_root, build_content_index(project_root))
        except OSError:
            for path, updated in reversed(written):
                atomic_write(path, updated)
            for source, target in reversed(completed_moves):
                if source.exists():
                    os.replace(source, target)
            write_content_index(project_root, build_content_index(project_root))
            raise

        UNDO_PATH.unlink(missing_ok=True)
        affected_files = set(backup["files"])
        affected_files.update(move["from"] for move in moves)
        self.send_json(
            {
                "ok": True,
                "fileCount": len(affected_files),
                "oldName": backup["oldName"],
                "newName": backup["newName"],
            }
        )


def main():
    parser = argparse.ArgumentParser(description="Story Teller local content server")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--content-root", default=str(CONTENT_ROOT))
    parser.add_argument("--default-project", default="")
    args = parser.parse_args()
    server = StoryTellerServer(
        (args.bind, args.port),
        StoryTellerHandler,
        content_root=args.content_root,
        default_project=args.default_project,
    )
    print(f"Story Teller: http://{args.bind}:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
