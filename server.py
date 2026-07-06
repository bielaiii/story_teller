#!/usr/bin/env python3

import argparse
import json
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
    replacement = f"{key}: {json.dumps(value, ensure_ascii=False)}"
    lines = match.group("meta").splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", line):
            lines[index] = replacement
            break
    else:
        insert_at = 0
        for index, line in enumerate(lines):
            if re.match(r"^(id|name)\s*:", line):
                insert_at = index + 1
        lines.insert(insert_at, replacement)
    return text[: match.start("meta")] + "\n".join(lines) + text[match.end("meta") :]


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
    people_match = re.search(
        r"(?ms)^people:\s*\n(?P<items>(?:[ \t]+.*(?:\n|$))*)",
        match.group("meta"),
    )
    if not people_match:
        return []
    return [
        value.strip().strip("\"'")
        for value in re.findall(
            r"(?m)^\s*-\s+id:\s*([^\n#]+?)\s*$",
            people_match.group("items"),
        )
    ]


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
        if parsed.path != "/api/capabilities":
            return super().do_GET()
        if not self.local_host():
            return self.send_api_error("只允许从本机访问写入服务", HTTPStatus.FORBIDDEN)
        project = parse_qs(parsed.query).get("project", [""])[0]
        try:
            self.project_root(project)
        except ValueError as error:
            return self.send_api_error(str(error), HTTPStatus.NOT_FOUND)
        undo = self.undo_metadata()
        self.send_json(
            {
                "ok": True,
                "writable": True,
                "token": self.server.api_token,
                "canUndo": bool(undo and undo.get("project") == project),
                "undoLabel": (
                    f"{undo.get('oldName')} → {undo.get('newName')}"
                    if undo and undo.get("project") == project
                    else ""
                ),
            }
        )

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
            "/api/characters/scope",
        }:
            return self.send_api_error("未知接口", HTTPStatus.NOT_FOUND)
        if not self.local_host():
            return self.send_api_error("只允许从本机访问写入服务", HTTPStatus.FORBIDDEN)
        if not self.authorized():
            return self.send_api_error("本地写入授权已失效，请刷新页面", HTTPStatus.FORBIDDEN)
        try:
            payload = self.read_json()
            if parsed.path == "/api/refactor/preview":
                return self.preview_refactor(payload)
            if parsed.path == "/api/refactor/apply":
                return self.apply_refactor(payload)
            if parsed.path == "/api/relationships/create":
                return self.create_relationship(payload)
            if parsed.path == "/api/characters/scope":
                return self.update_character_scope(payload)
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
