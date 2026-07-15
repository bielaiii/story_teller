import hashlib
import json
import os
import re
import sqlite3
import tempfile
import threading
import time
from pathlib import Path


SCHEMA_VERSION = 2
HISTORY_RETENTION_SECONDS = 7 * 24 * 60 * 60
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
                        changed_paths TEXT NOT NULL,
                        label TEXT NOT NULL DEFAULT '',
                        entity_type TEXT NOT NULL DEFAULT 'content',
                        action TEXT NOT NULL DEFAULT 'update',
                        details TEXT NOT NULL DEFAULT '{}',
                        expires_at INTEGER NOT NULL DEFAULT 0,
                        undone_by INTEGER
                    );
                    CREATE TABLE IF NOT EXISTS transaction_changes (
                        transaction_id INTEGER NOT NULL,
                        path TEXT NOT NULL,
                        before_content BLOB,
                        after_content BLOB,
                        PRIMARY KEY(transaction_id, path),
                        FOREIGN KEY(transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
                    );
                    CREATE INDEX IF NOT EXISTS transactions_created_at
                        ON transactions(created_at DESC, id DESC);
                    """
                )
                transaction_columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(transactions)")
                }
                for column, definition in (
                    ("label", "TEXT NOT NULL DEFAULT ''"),
                    ("entity_type", "TEXT NOT NULL DEFAULT 'content'"),
                    ("action", "TEXT NOT NULL DEFAULT 'update'"),
                    ("details", "TEXT NOT NULL DEFAULT '{}'"),
                    ("expires_at", "INTEGER NOT NULL DEFAULT 0"),
                    ("undone_by", "INTEGER"),
                ):
                    if column not in transaction_columns:
                        connection.execute(f"ALTER TABLE transactions ADD COLUMN {column} {definition}")
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
                self.capture_from_exports("initial-markdown-import", {
                    "label": "初始化项目数据库",
                    "entityType": "project",
                    "action": "system",
                })
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

    def capture_from_exports(self, operation="content-write", metadata=None):
        with self._lock:
            files = self.scan_exports()
            now = int(time.time())
            metadata = metadata if isinstance(metadata, dict) else {}
            with self.connect() as connection:
                previous = {
                    row["path"]: {"hash": row["content_hash"], "content": bytes(row["content"])}
                    for row in connection.execute("SELECT path, content_hash, content FROM documents")
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
                    if previous.get(relative_path, {}).get("hash") == digest:
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
                if changed_paths:
                    details = metadata.get("details") if isinstance(metadata.get("details"), dict) else {}
                    cursor = connection.execute(
                        """
                        INSERT INTO transactions(
                            created_at, operation, changed_paths, label, entity_type,
                            action, details, expires_at
                        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            now,
                            str(operation or "content-write"),
                            json.dumps(changed_paths, ensure_ascii=False),
                            str(metadata.get("label") or operation or "内容修改"),
                            str(metadata.get("entityType") or "content"),
                            str(metadata.get("action") or "update"),
                            json.dumps(details, ensure_ascii=False),
                            now + HISTORY_RETENTION_SECONDS,
                        ),
                    )
                    transaction_id = int(cursor.lastrowid)
                    connection.executemany(
                        """
                        INSERT INTO transaction_changes(
                            transaction_id, path, before_content, after_content
                        ) VALUES(?, ?, ?, ?)
                        """,
                        [
                            (
                                transaction_id,
                                path,
                                previous.get(path, {}).get("content"),
                                files.get(path),
                            )
                            for path in changed_paths
                        ],
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

    @staticmethod
    def _history_details(raw_details):
        try:
            value = json.loads(raw_details or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _transaction_can_undo(self, connection, transaction, changes, now=None):
        current_time = int(time.time()) if now is None else int(now)
        if str(transaction["action"]) == "system":
            return False, "系统初始化记录不能撤销"
        if transaction["undone_by"] is not None:
            return False, "这项操作已经撤销"
        if int(transaction["expires_at"] or 0) <= current_time:
            return False, "这项操作已超过 7 天"
        current = {
            row["path"]: bytes(row["content"])
            for row in connection.execute(
                f"SELECT path, content FROM documents WHERE path IN ({','.join('?' for _ in changes)})",
                tuple(change["path"] for change in changes),
            )
        } if changes else {}
        for change in changes:
            expected = bytes(change["after_content"]) if change["after_content"] is not None else None
            if current.get(change["path"]) != expected:
                return False, f"{change['path']} 后来又被修改，不能安全撤销"
        return True, ""

    def history(self, limit=100, deletion_only=False):
        safe_limit = max(1, min(int(limit or 100), 300))
        now = int(time.time())
        with self._lock, self.connect() as connection:
            transactions = list(connection.execute(
                """
                SELECT * FROM transactions
                WHERE expires_at > ? AND action <> 'system'
                ORDER BY id DESC LIMIT ?
                """,
                (now, safe_limit),
            ))
            items = []
            for transaction in transactions:
                details = self._history_details(transaction["details"])
                deleted_items = details.get("deletedItems", [])
                if deletion_only and not deleted_items:
                    continue
                changes = list(connection.execute(
                    "SELECT * FROM transaction_changes WHERE transaction_id = ? ORDER BY path",
                    (transaction["id"],),
                ))
                if not changes:
                    continue
                can_undo, blocked_reason = self._transaction_can_undo(
                    connection, transaction, changes, now
                )
                remaining_seconds = max(0, int(transaction["expires_at"]) - now)
                items.append({
                    "id": int(transaction["id"]),
                    "createdAt": int(transaction["created_at"]),
                    "operation": str(transaction["operation"]),
                    "label": str(transaction["label"] or transaction["operation"]),
                    "entityType": str(transaction["entity_type"] or "content"),
                    "action": str(transaction["action"] or "update"),
                    "changedPaths": json.loads(transaction["changed_paths"] or "[]"),
                    "changedCount": len(changes),
                    "details": details,
                    "deletedItems": deleted_items if isinstance(deleted_items, list) else [],
                    "expiresAt": int(transaction["expires_at"]),
                    "daysRemaining": int((remaining_seconds + 86399) // 86400),
                    "undone": transaction["undone_by"] is not None,
                    "canUndo": can_undo,
                    "undoBlockedReason": blocked_reason,
                })
            return items

    def undo_transaction(self, transaction_id):
        try:
            target_id = int(transaction_id)
        except (TypeError, ValueError) as error:
            raise ValueError("请选择有效的操作记录") from error
        now = int(time.time())
        with self._lock, self.connect() as connection:
            transaction = connection.execute(
                "SELECT * FROM transactions WHERE id = ?", (target_id,)
            ).fetchone()
            if not transaction:
                raise ValueError("这项操作记录不存在")
            changes = list(connection.execute(
                "SELECT * FROM transaction_changes WHERE transaction_id = ? ORDER BY path",
                (target_id,),
            ))
            if not changes:
                raise ValueError("这项旧操作没有可用的撤销快照")
            can_undo, blocked_reason = self._transaction_can_undo(
                connection, transaction, changes, now
            )
            if not can_undo:
                raise ValueError(blocked_reason)

            for change in changes:
                if change["before_content"] is None:
                    connection.execute("DELETE FROM documents WHERE path = ?", (change["path"],))
            for change in changes:
                if change["before_content"] is None:
                    continue
                content = bytes(change["before_content"])
                digest = hashlib.sha256(content).hexdigest()
                collection, stable_id, display_name, sequence = classify_path(change["path"], content)
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
                    (
                        change["path"], collection, stable_id, display_name, sequence,
                        content, digest, now,
                    ),
                )

            target_details = self._history_details(transaction["details"])
            inverse_details = {"targetTransactionId": target_id}
            target_deleted_items = target_details.get("deletedItems", [])
            target_redo_deleted_items = target_details.get("redoDeletedItems", [])
            if isinstance(target_deleted_items, list) and target_deleted_items:
                inverse_details["redoDeletedItems"] = target_deleted_items
            elif isinstance(target_redo_deleted_items, list) and target_redo_deleted_items:
                inverse_details["deletedItems"] = target_redo_deleted_items
            inverse_action = "delete" if inverse_details.get("deletedItems") else "undo"
            inverse_label = (
                f"重新执行：{transaction['label']}"
                if inverse_action == "delete"
                else f"撤销：{transaction['label'] or transaction['operation']}"
            )
            inverse_cursor = connection.execute(
                """
                INSERT INTO transactions(
                    created_at, operation, changed_paths, label, entity_type,
                    action, details, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    "/api/history/undo",
                    transaction["changed_paths"],
                    inverse_label,
                    transaction["entity_type"],
                    inverse_action,
                    json.dumps(inverse_details, ensure_ascii=False),
                    now + HISTORY_RETENTION_SECONDS,
                ),
            )
            inverse_id = int(inverse_cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO transaction_changes(
                    transaction_id, path, before_content, after_content
                ) VALUES(?, ?, ?, ?)
                """,
                [
                    (
                        inverse_id,
                        change["path"],
                        change["after_content"],
                        change["before_content"],
                    )
                    for change in changes
                ],
            )
            connection.execute(
                "UPDATE transactions SET undone_by = ? WHERE id = ?",
                (inverse_id, target_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('last_operation', ?)",
                ("/api/history/undo",),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('updated_at', ?)",
                (str(now),),
            )
        self.materialize_exports(clean=True)
        return {
            "ok": True,
            "transactionId": target_id,
            "undoTransactionId": inverse_id,
            "label": str(transaction["label"] or transaction["operation"]),
        }

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
