from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from storyteller import SCHEMA_VERSION


DATABASE_NAME = "story.db"


def schema_version(connection: sqlite3.Connection) -> int:
    user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
    ).fetchone()
    if not table:
        return user_version
    row = connection.execute(
        "SELECT value FROM metadata WHERE key='schema_version'"
    ).fetchone()
    metadata_version = int(row[0]) if row and str(row[0]).isdigit() else 0
    return max(user_version, metadata_version)


class Database:
    _registry_guard = threading.Lock()
    _locks: dict[Path, threading.RLock] = {}

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.path = self.project_root / DATABASE_NAME
        with self._registry_guard:
            self._lock = self._locks.setdefault(self.path, threading.RLock())

    @contextmanager
    def locked(self) -> Iterator[None]:
        with self._lock:
            yield

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            connection = sqlite3.connect(
                f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=10
            )
        else:
            connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        if not readonly:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
        return connection

    def require_v3(self, connection: sqlite3.Connection | None = None) -> None:
        owns_connection = connection is None
        active = connection or self.connect(readonly=True)
        try:
            version = schema_version(active)
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库版本 {version} 高于当前程序支持的版本 {SCHEMA_VERSION}，请先更新 Story Teller"
                )
            if version < SCHEMA_VERSION:
                raise RuntimeError(
                    f"数据库仍是 Schema V{version}，请先执行一次性 V3 迁移"
                )
            violations = list(active.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError("数据库外键完整性检查失败")
        finally:
            if owns_connection:
                active.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect(readonly=True)
        try:
            self.require_v3(connection)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self.locked():
            connection = self.connect()
            try:
                self.require_v3(connection)
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
