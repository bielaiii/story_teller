"""Consistent SQLite backups and non-overwriting recovery."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path

from storyteller import SCHEMA_VERSION
from storyteller.exports.reading import atomic_write, json_bytes, read_json, safe_target
from storyteller.storage.connection import Database, schema_version


def verify(connection):
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("备份数据库完整性检查失败")
    if connection.execute("PRAGMA foreign_key_check").fetchone():
        raise ValueError("备份数据库存在无效引用")
    version = schema_version(connection)
    if version > SCHEMA_VERSION:
        raise ValueError("备份来自更新版本的程序")
    return version


class Backups:
    def __init__(self, database: Database, project: str):
        self.database, self.project = database, project
        self.root = database.project_root / "backups"

    def status(self):
        items = []
        if self.root.is_dir() and not self.root.is_symlink():
            for path in self.root.glob("*.json"):
                value = read_json(path)
                if value.get("format") == 1 and value.get("project") == self.project:
                    items.append(value)
        return {"directory": str(self.root), "items": sorted(items, key=lambda x: x["createdAt"], reverse=True)}

    def create(self, kind="manual"):
        if kind not in {"manual", "daily", "migration"}:
            raise ValueError("未知备份类型")
        # Share the cross-process publication lock with exports.
        from storyteller.exports.coordinator import ExportCoordinator
        with ExportCoordinator(self.database, self.project)._publication_lock():
            timestamp = int(time.time())
            name = f"{timestamp}-{kind}-{uuid.uuid4().hex[:12]}.db"
            target = safe_target(self.root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            try:
                with closing(self.database.connect(readonly=True)) as source, closing(sqlite3.connect(temporary)) as destination:
                    source.backup(destination)
                    version = verify(destination)
                    has_projects = destination.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone()
                    row = destination.execute("SELECT id, revision FROM projects").fetchone() if has_projects else (self.project, 0)
                    if not row or row[0] != self.project:
                        raise ValueError("备份项目与请求不一致")
                    revision = int(row[1])
                with temporary.open("rb") as stream:
                    os.fsync(stream.fileno())
                digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                os.replace(temporary, target)
                value = {"format": 1, "filename": name, "project": self.project, "kind": kind,
                         "createdAt": timestamp, "revision": revision, "schemaVersion": version,
                         "sha256": digest, "bytes": target.stat().st_size}
                atomic_write(safe_target(self.root, name + ".json"), json_bytes(value))
                limit = {"daily": 7, "migration": 5}.get(kind)
                if limit:
                    matches = [i for i in self.status()["items"] if i["kind"] == kind]
                    for item in matches[limit:]:
                        safe_target(self.root, item["filename"]).unlink(missing_ok=True)
                        safe_target(self.root, item["filename"] + ".json").unlink(missing_ok=True)
                return value
            finally:
                temporary.unlink(missing_ok=True)

    def due(self):
        with self.database.read() as connection:
            revision = connection.execute("SELECT revision FROM projects WHERE id=?", (self.project,)).fetchone()[0]
        items = [i for i in self.status()["items"] if i["kind"] == "daily"]
        return not items or (time.time() - items[0]["createdAt"] >= 86400 and items[0]["revision"] != revision)


def restore_backup(source: Path, destination: Path) -> dict:
    source = source.resolve()
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("恢复目标必须是不存在的新项目目录")
    metadata = read_json(source.with_name(source.name + ".json"))
    if not metadata or hashlib.sha256(source.read_bytes()).hexdigest() != metadata.get("sha256"):
        raise ValueError("备份缺少校验记录或校验失败")
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as connection:
        verify(connection)
        has_projects = connection.execute("SELECT 1 FROM sqlite_master WHERE name='projects'").fetchone()
        project = connection.execute("SELECT id FROM projects").fetchone()[0] if has_projects else metadata["project"]
        if destination.name != project:
            raise ValueError(f"请保留项目 ID，使用一个新的父目录，例如 new-content/{project}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".restore-", dir=destination.parent))
    try:
        shutil.copyfile(source, temporary / "story.db")
        # mkdir is exclusive: concurrent recovery cannot overwrite a winner.
        destination.mkdir()
        try:
            os.replace(temporary / "story.db", destination / "story.db")
        except BaseException:
            destination.rmdir()
            raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {"ok": True, "project": project, "directory": str(destination)}


def main():
    parser = argparse.ArgumentParser(description="恢复完整备份到新的内容目录，不覆盖已有项目")
    parser.add_argument("backup", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(restore_backup(args.backup, args.destination), ensure_ascii=False))


if __name__ == "__main__":
    main()
