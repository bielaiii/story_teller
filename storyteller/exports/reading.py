"""Human-readable, disposable Markdown copies. SQLite remains authoritative."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from storyteller.domain.merge_conflicts import has_open_merge
from storyteller.domain.uow import UnitOfWork
from storyteller.exports.coordinator import ExportCoordinator
from storyteller.exports.markdown import safe_filename
from storyteller.storage.connection import Database, SnapshotDatabase
from storyteller.storage.repositories import ProjectRepository

FORMAT = 1
KINDS = {"entries": "设定", "characters": "人物", "fragments": "碎片", "plots": "篇章"}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def safe_target(root: Path, relative: str) -> Path:
    target = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("生成路径越界")
    if root.is_symlink() or any(p.is_symlink() for p in [target, *target.parents] if p != root.parent):
        # In particular, never follow a user-created symlink while publishing.
        raise ValueError("生成目录不允许符号链接")
    if root.resolve() not in target.resolve().parents:
        raise ValueError("生成路径越界")
    return target


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == data:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def filename(title: str, identifier: str) -> str:
    # Byte limits work on Linux and macOS; digest also disambiguates case-folding.
    name = safe_filename(title, "未命名").encode()[:140].decode("utf-8", errors="ignore")
    identity = safe_filename(identifier, "item")[:40]
    return f"{name}--{identity}-{hashlib.sha256(identifier.encode()).hexdigest()[:8]}.md"


def md_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("\n", " ")


def section(title: str, value) -> str:
    if not value:
        return ""
    if isinstance(value, dict):
        value = "\n".join(f"- {k}：{v}" for k, v in value.items())
    elif isinstance(value, list):
        value = "\n".join(
            f"- {v.get('key', '')}：{v.get('value', '')}" if isinstance(v, dict) else f"- {v}"
            for v in value
        )
    return f"\n## {title}\n\n{str(value).strip()}\n"


class ReadingCopies:
    def __init__(self, database: Database, project: str):
        self.database, self.project = database, project
        self.root = database.project_root / "markdown"

    def project_state(self):
        with self.database.read() as connection:
            row = connection.execute("SELECT revision, extra_json FROM projects WHERE id=?", (self.project,)).fetchone()
        extra = json.loads(row["extra_json"])
        return int(row["revision"]), extra.get("readingCopies", {}).get("enabled", True)

    def status(self) -> dict:
        revision, enabled = self.project_state()
        index = read_json(self.root / ".index.json")
        error = read_json(self.root / ".error.json")
        ready = index.get("revision") == revision and index.get("format") == FORMAT
        return {
            "enabled": enabled, "directory": str(self.root), "revision": revision,
            "exportedRevision": index.get("revision"), "lastSuccessAt": index.get("generatedAt"),
            "status": "failed" if error.get("message") else ("ready" if ready else "pending"),
            "lastError": error.get("message", ""), "intervalSeconds": 60,
        }

    def configure(self, enabled: bool, base_revision: int):
        def update(connection):
            row = connection.execute("SELECT extra_json FROM projects WHERE id=?", (self.project,)).fetchone()
            extra = json.loads(row[0])
            extra["readingCopies"] = {**extra.get("readingCopies", {}), "enabled": enabled}
            connection.execute("UPDATE projects SET extra_json=? WHERE id=?",
                               (json.dumps(extra, ensure_ascii=False), self.project))
        return UnitOfWork(self.database, self.project).mutate(
            base_revision=base_revision, label="设置 Markdown 自动生成", action="update",
            entity_kind="project", callback=update,
        )

    def generate(self, *, force: bool = False) -> dict:
        if has_open_merge(self.database, self.project):
            return {**self.status(), "status": "blocked", "lastError": "请先解决数据库合并冲突"}
        with ExportCoordinator(self.database, self.project)._publication_lock():
            try:
                return self._generate(force=force)
            except Exception as error:
                try:
                    atomic_write(safe_target(self.root, ".error.json"), json_bytes({"message": str(error)}))
                except OSError:
                    pass
                raise

    def _generate(self, *, force: bool) -> dict:
        old = read_json(self.root / ".index.json")
        with self.database.read() as connection:
            db = SnapshotDatabase(self.database, connection)
            repository = ProjectRepository(db, self.project)
            row = connection.execute("SELECT revision, extra_json FROM projects WHERE id=?", (self.project,)).fetchone()
            if not force and not json.loads(row["extra_json"]).get("readingCopies", {}).get("enabled", True):
                return self.status()
            if not force and old.get("format") == FORMAT and old.get("revision") == row["revision"] and all(
                safe_target(self.root, path).is_file() for path in old.get("files", [])
            ):
                return self.status()
            snapshot = repository.snapshot()
            files: dict[str, bytes] = {}
            owned: set[str] = set()
            records = {}
            assets = list(connection.execute("SELECT id, filename, content_hash FROM assets WHERE project_id=?", (self.project,)))
            asset_paths = {}
            for asset in assets:
                suffix = Path(asset["filename"]).suffix[:15]
                path = f"附件/{hashlib.sha256(asset['id'].encode()).hexdigest()}{suffix}"
                asset_paths[asset["filename"]] = path
                owned.add(path)
                if old.get("assets", {}).get(asset["id"]) != asset["content_hash"] or not safe_target(self.root, path).exists():
                    files[path] = bytes(connection.execute("SELECT content FROM assets WHERE id=?", (asset["id"],)).fetchone()[0])
            chapters = {c["entityId"]: c["label"] for c in snapshot["chapters"]}
            assets_signature = hashlib.sha256(json_bytes(asset_paths)).hexdigest()
            parents = {f["entityId"]: f["title"] for f in snapshot["fragments"]}
            total_index = [f"# {snapshot['project']['title']}\n",
                           "> 自动生成的阅读副本；修改这些文件不会写回应用，重新生成可能覆盖修改。\n"]
            for kind, folder in KINDS.items():
                total_index.append(f"- [{folder}]({quote(folder)}/README.md)\n")
                entries = list(snapshot[kind])
                if kind == "fragments":
                    entries.sort(key=lambda x: (parents.get(x.get("parentFragmentId"), ""), x.get("fragmentOrder", 0), x["entityId"]))
                toc = [f"# {folder}\n"]
                previous_group = None
                for item in entries:
                    identifier = item["entityId"]
                    title = item.get("name") or item.get("title") or item["id"]
                    path = f"{folder}/{filename(title, identifier)}"
                    owned.add(path)
                    group = chapters.get(item.get("chapterId"), "主线") if kind == "plots" else (
                        parents.get(item.get("parentFragmentId"), "独立碎片") if kind == "fragments" else ""
                    )
                    if group and group != previous_group:
                        toc.append(f"\n## {group}\n\n")
                        previous_group = group
                    prefix = f"第 {item['chapterNumber']} 章 · " if kind == "plots" and item.get("chapterNumber") is not None else ""
                    toc.append(f"- [{md_label(prefix + title)}]({quote(Path(path).name)})\n")
                    signature = hashlib.sha256(json_bytes({"item": item, "group": group, "assets": assets_signature})).hexdigest()
                    records[identifier] = {"signature": signature, "path": path}
                    if old.get("format") == FORMAT and old.get("records", {}).get(identifier) == records[identifier] and safe_target(self.root, path).is_file():
                        continue
                    detail = repository.entity_detail(identifier)["data"]
                    document = f"# {prefix}{title}\n\n"
                    if group:
                        document += f"所属：{group}\n\n"
                    metadata = {label: detail.get(key) for key, label in (
                        ("aliases", "别名"), ("status", "状态"), ("narrativeRole", "人物定位"),
                        ("characterScope", "人物范围"), ("side", "阵营"), ("area", "区域"),
                    ) if detail.get(key)}
                    if metadata:
                        document += section("资料", {key: "、".join(value) if isinstance(value, list) else value
                                                     for key, value in metadata.items()})
                    if kind == "characters":
                        document += section("人物简介", detail.get("intro"))
                        document += section("人物档案", detail.get("facts"))
                        document += section("补充档案", detail.get("supplements"))
                        document += section("核心人设", detail.get("corePersona"))
                        document += section("补充人设", detail.get("supplementPersona"))
                        document += section("人物大纲", detail.get("destinyOutline"))
                    else:
                        if kind == "entries":
                            document += f"类型：{detail.get('type', '')} · {detail.get('subtype', '')}\n\n"
                        document += section("标签", detail.get("tags"))
                        document += section("摘要", detail.get("summary"))
                        document += "\n" + str(detail.get("body") or "").strip() + "\n"
                    for source, target in asset_paths.items():
                        # Markdown destinations, including existing ../assets paths.
                        destination = "../" + quote(target)
                        for candidate in (source, quote(source), f"../{source}", f"/content/{self.project}/{source}"):
                            document = document.replace(f"]({candidate})", f"]({destination})")
                    attached = [a for a in connection.execute(
                        "SELECT filename FROM assets WHERE entity_id=? ORDER BY filename", (identifier,)
                    )]
                    if attached:
                        document += "\n## 附件\n\n" + "".join(
                            f"- [{md_label(a['filename'])}](../{quote(asset_paths[a['filename']])})\n" for a in attached
                        )
                    files[path] = document.encode()
                files[f"{folder}/README.md"] = "".join(toc).encode()
            files["README.md"] = "".join(total_index).encode()
            owned.update(files)
            index = {
                "format": FORMAT, "revision": row["revision"], "generatedAt": int(time.time()),
                "files": sorted(owned), "records": records,
                "assets": {a["id"]: a["content_hash"] for a in assets},
            }
        # Validate every path before publishing or cleaning up.
        for path in owned | set(old.get("files", [])):
            safe_target(self.root, path)
        for path, content in files.items():
            atomic_write(safe_target(self.root, path), content)
        for path in set(old.get("files", [])) - owned:
            safe_target(self.root, path).unlink(missing_ok=True)
        atomic_write(safe_target(self.root, ".index.json"), json_bytes(index))
        safe_target(self.root, ".error.json").unlink(missing_ok=True)
        return self.status()
