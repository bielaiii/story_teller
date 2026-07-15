import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path


SCHEMA_VERSION = 1
DATABASE_NAME = "story.db"
MANAGED_ROOTS = {"characters", "plots", "entries", "fragments", "relationships", ".trash"}
MANAGED_FILES = {"manifest.md", "timeline.md", "graph-layout.md", "content-index.json"}
FRONTMATTER_PATTERN = re.compile(rb"^---\n(?P<meta>[\s\S]*?)\n---(?:\n|$)")


def _frontmatter_scalar(content, key):
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return ""
    field = re.search(
        rb"(?m)^" + re.escape(key.encode("utf-8")) + rb"\s*:\s*([^\n#]+?)\s*$",
        match.group("meta"),
    )
    if not field:
        return ""
    return field.group(1).decode("utf-8", errors="replace").strip().strip("\"'")


def _relationship_id(content):
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        return ""
    meta = match.group("meta")
    nested = re.findall(rb"(?m)^\s*-\s+id:\s*([^\n#]+?)\s*$", meta)
    if len(nested) == 2:
        return "__".join(item.decode("utf-8").strip().strip("\"'") for item in nested)
    endpoints = []
    for key in (b"from", b"to"):
        field = re.search(rb"(?m)^" + key + rb"\s*:\s*([^\n#]+?)\s*$", meta)
        if field:
            endpoints.append(field.group(1).decode("utf-8").strip().strip("\"'"))
    return "__".join(endpoints) if len(endpoints) == 2 else ""


def classify_path(relative_path, content):
    path = Path(relative_path)
    root = path.parts[0] if path.parts else ""
    if root in {"characters", "plots", "entries", "fragments", "relationships"} and path.suffix.lower() == ".md":
        collection = root
    elif relative_path == "manifest.md":
        collection = "manifest"
    elif relative_path == "timeline.md":
        collection = "timeline"
    elif relative_path == "graph-layout.md":
        collection = "graphLayout"
    elif relative_path.startswith(".trash/"):
        collection = "trash"
    else:
        collection = "asset"
    stable_id = _relationship_id(content) if collection == "relationships" else _frontmatter_scalar(content, "id")
    display_name = ""
    for key in ("name", "title", "label"):
        display_name = _frontmatter_scalar(content, key)
        if display_name:
            break
    raw_sequence = _frontmatter_scalar(content, "sequence") or stable_id
    sequence = int(raw_sequence) if raw_sequence.isdigit() else None
    return collection, stable_id, display_name, sequence


def is_managed_relative_path(relative_path):
    path = Path(relative_path)
    if relative_path in MANAGED_FILES:
        return True
    if not path.parts or any(part.startswith(".") for part in path.parts if part != ".trash"):
        return False
    return True


def atomic_write_bytes(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else 0o644
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary_path = Path(handle.name)
    os.chmod(temporary_path, mode)
    os.replace(temporary_path, path)


class SQLiteProjectStore:
    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.database_path = self.project_root / DATABASE_NAME
        self._lock = threading.RLock()

    def connect(self):
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def existing_schema_version(self, connection):
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        has_metadata = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'metadata'"
        ).fetchone()
        if not has_metadata:
            return user_version
        row = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
        metadata_version = int(row[0]) if row and str(row[0]).isdigit() else 0
        return max(user_version, metadata_version)

    def initialize(self):
        with self._lock:
            database_exists = self.database_path.is_file()
            self.project_root.mkdir(parents=True, exist_ok=True)
            with self.connect() as connection:
                existing_version = self.existing_schema_version(connection)
                if existing_version > SCHEMA_VERSION:
                    raise RuntimeError(
                        f"数据库版本 {existing_version} 高于当前程序支持的版本 {SCHEMA_VERSION}，请先更新 Story Teller"
                    )
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS documents (
                        path TEXT PRIMARY KEY,
                        collection TEXT NOT NULL,
                        stable_id TEXT NOT NULL DEFAULT '',
                        display_name TEXT NOT NULL DEFAULT '',
                        sequence INTEGER,
                        content BLOB NOT NULL,
                        content_hash TEXT NOT NULL,
                        updated_at INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS documents_collection_sequence
                        ON documents(collection, sequence, stable_id);
                    CREATE UNIQUE INDEX IF NOT EXISTS documents_stable_id
                        ON documents(collection, stable_id)
                        WHERE stable_id <> '' AND collection IN ('characters', 'plots', 'entries', 'fragments');
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at INTEGER NOT NULL,
                        operation TEXT NOT NULL,
                        changed_paths TEXT NOT NULL
                    );
                    """
                )
                metadata_version = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()
                if not metadata_version or metadata_version[0] != str(SCHEMA_VERSION):
                    connection.execute(
                        "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if user_version != SCHEMA_VERSION:
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            if not database_exists or self.document_count() == 0:
                self.capture_from_exports("initial-markdown-import")
            else:
                self.materialize_exports(clean=True)

    def document_count(self):
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    def scan_exports(self):
        files = {}
        for path in sorted(self.project_root.rglob("*")):
            if not path.is_file():
                continue
            if path == self.database_path or path.name in {f"{DATABASE_NAME}-journal", f"{DATABASE_NAME}-wal", f"{DATABASE_NAME}-shm"}:
                continue
            relative_path = path.relative_to(self.project_root).as_posix()
            if not is_managed_relative_path(relative_path):
                continue
            files[relative_path] = path.read_bytes()
        return files

    def capture_from_exports(self, operation="content-write"):
        with self._lock:
            files = self.scan_exports()
            now = int(time.time())
            with self.connect() as connection:
                previous = {
                    row["path"]: row["content_hash"]
                    for row in connection.execute("SELECT path, content_hash FROM documents")
                }
                current_paths = set(files)
                changed_paths = sorted(set(previous) ^ current_paths)
                if current_paths:
                    placeholders = ",".join("?" for _ in current_paths)
                    connection.execute(
                        f"DELETE FROM documents WHERE path NOT IN ({placeholders})",
                        tuple(sorted(current_paths)),
                    )
                else:
                    connection.execute("DELETE FROM documents")
                for relative_path, content in files.items():
                    digest = hashlib.sha256(content).hexdigest()
                    if previous.get(relative_path) == digest:
                        continue
                    changed_paths.append(relative_path)
                    collection, stable_id, display_name, sequence = classify_path(relative_path, content)
                    connection.execute(
                        """
                        INSERT INTO documents(path, collection, stable_id, display_name, sequence, content, content_hash, updated_at)
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET
                            collection=excluded.collection,
                            stable_id=excluded.stable_id,
                            display_name=excluded.display_name,
                            sequence=excluded.sequence,
                            content=excluded.content,
                            content_hash=excluded.content_hash,
                            updated_at=excluded.updated_at
                        """,
                        (relative_path, collection, stable_id, display_name, sequence, content, digest, now),
                    )
                changed_paths = sorted(set(changed_paths))
                connection.execute(
                    "INSERT INTO transactions(created_at, operation, changed_paths) VALUES(?, ?, ?)",
                    (now, str(operation or "content-write"), json.dumps(changed_paths, ensure_ascii=False)),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('last_operation', ?)",
                    (str(operation or "content-write"),),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('updated_at', ?)",
                    (str(now),),
                )
            return changed_paths

    def materialize_exports(self, clean=True):
        with self._lock:
            with self.connect() as connection:
                records = list(connection.execute("SELECT path, content FROM documents ORDER BY path"))
            database_paths = {record["path"] for record in records}
            if clean:
                for relative_path in sorted(self.scan_exports()):
                    if relative_path not in database_paths:
                        (self.project_root / relative_path).unlink(missing_ok=True)
            for record in records:
                target = self.project_root / record["path"]
                content = bytes(record["content"])
                if target.is_file() and target.read_bytes() == content:
                    continue
                atomic_write_bytes(target, content)

    def snapshot(self):
        with self._lock, self.connect() as connection:
            records = list(
                connection.execute(
                    "SELECT path, collection, stable_id, display_name, sequence, content FROM documents ORDER BY path"
                )
            )
            collections = {
                "characters": [],
                "plots": [],
                "fragments": [],
                "entries": [],
                "relationships": [],
                "timeline": [],
                "graphLayout": [],
            }
            documents = {}
            for record in records:
                path = record["path"]
                collection = record["collection"]
                if collection in collections:
                    collections[collection].append(f"./{path}")
                if collection in {*collections, "manifest"}:
                    documents[path] = bytes(record["content"]).decode("utf-8")
            return {"collections": collections, "documents": documents}

    def info(self):
        with self.connect() as connection:
            metadata = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
            counts = {
                row["collection"]: row["count"]
                for row in connection.execute("SELECT collection, COUNT(*) AS count FROM documents GROUP BY collection")
            }
        return {
            "database": self.database_path.name,
            "schemaVersion": int(metadata.get("schema_version", SCHEMA_VERSION)),
            "updatedAt": int(metadata.get("updated_at", 0) or 0),
            "lastOperation": metadata.get("last_operation", ""),
            "counts": counts,
        }


class SQLiteContentManager:
    def __init__(self, content_root):
        self.content_root = Path(content_root).resolve()
        self._stores = {}
        self.write_lock = threading.RLock()

    def initialize_existing_projects(self):
        for path in sorted(self.content_root.iterdir()):
            if path.is_dir() and re.fullmatch(r"[A-Za-z0-9_-]+", path.name):
                self.store(path.name).initialize()

    def store(self, project):
        project_id = str(project or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", project_id):
            raise ValueError("项目名称不合法")
        root = (self.content_root / project_id).resolve()
        if self.content_root not in root.parents:
            raise ValueError("项目路径超出内容目录")
        store = self._stores.get(project_id)
        if store is None:
            store = SQLiteProjectStore(root)
            self._stores[project_id] = store
        return store

    def initialize_project(self, project):
        store = self.store(project)
        store.initialize()
        return store
