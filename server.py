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


class StoryTellerServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler_class, content_root=CONTENT_ROOT):
        resolved_content_root = Path(content_root).expanduser().resolve()
        if not resolved_content_root.is_dir():
            raise ValueError(f"内容目录不存在：{resolved_content_root}")
        self.content_root = resolved_content_root
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

    def project_root(self, project):
        if not PROJECT_PATTERN.fullmatch(str(project or "")):
            raise ValueError("项目名称不合法")
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
        project = parse_qs(parsed.query).get("project", [""])[0]
        try:
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
        }
        self.send_json(
            {
                "ok": True,
                "operationId": operation_id,
                "oldName": old_name,
                "newName": new_name,
                "fileCount": len(replacements),
                "matchCount": total_matches,
                "samples": samples,
            }
        )

    def apply_refactor(self, payload):
        operation_id = str(payload.get("operationId", ""))
        operation = self.server.previews.get(operation_id)
        if not operation:
            raise ValueError("预览已失效，请重新生成")
        project_root = self.project_root(operation["project"])

        for relative_path, contents in operation["files"].items():
            path = (project_root / relative_path).resolve()
            if project_root not in path.parents or path.read_text(encoding="utf-8") != contents["before"]:
                raise ValueError(f"{relative_path} 已发生变化，请重新预览")

        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        backup = {
            "project": operation["project"],
            "oldName": operation["oldName"],
            "newName": operation["newName"],
            "createdAt": time.time(),
            "files": operation["files"],
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
        try:
            for relative_path, contents in operation["files"].items():
                path = project_root / relative_path
                atomic_write(path, contents["after"])
                written.append((path, contents["before"]))
        except OSError:
            for path, original in reversed(written):
                atomic_write(path, original)
            UNDO_PATH.unlink(missing_ok=True)
            raise

        self.server.previews.pop(operation_id, None)
        self.send_json(
            {
                "ok": True,
                "fileCount": len(operation["files"]),
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

        for relative_path, contents in backup["files"].items():
            path = (project_root / relative_path).resolve()
            if project_root not in path.parents or path.read_text(encoding="utf-8") != contents["after"]:
                raise ValueError(f"{relative_path} 在重命名后又被修改，无法安全撤销")

        written = []
        try:
            for relative_path, contents in backup["files"].items():
                path = project_root / relative_path
                atomic_write(path, contents["before"])
                written.append((path, contents["after"]))
        except OSError:
            for path, updated in reversed(written):
                atomic_write(path, updated)
            raise

        UNDO_PATH.unlink(missing_ok=True)
        self.send_json(
            {
                "ok": True,
                "fileCount": len(backup["files"]),
                "oldName": backup["oldName"],
                "newName": backup["newName"],
            }
        )


def main():
    parser = argparse.ArgumentParser(description="Story Teller local content server")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--content-root", default=str(CONTENT_ROOT))
    args = parser.parse_args()
    server = StoryTellerServer(
        (args.bind, args.port),
        StoryTellerHandler,
        content_root=args.content_root,
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
