from __future__ import annotations

import base64
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable

from storyteller.domain.errors import ConflictError, DomainError, NotFoundError
from storyteller.storage.connection import Database


HISTORY_RETENTION_SECONDS = 7 * 24 * 60 * 60
EXCLUDED_TABLES = {"metadata", "operations", "operation_changes", "export_state", "sqlite_sequence"}
IGNORED_COLUMNS = {"projects": {"revision", "updated_at"}}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def encode_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"$blob": base64.b64encode(value).decode("ascii")}
    return value


def decode_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$blob"}:
        return base64.b64decode(value["$blob"])
    return value


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    columns: tuple[str, ...]
    primary_keys: tuple[str, ...]
    dependencies: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MutationResult:
    operation_id: int | None
    project_revision: int
    changed_entity_ids: tuple[str, ...]
    callback_result: Any = None


class UnitOfWork:
    """One transaction boundary with automatic normalized row auditing."""

    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id

    @staticmethod
    def _tables(connection: sqlite3.Connection) -> dict[str, TableInfo]:
        result: dict[str, TableInfo] = {}
        table_names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
            if str(row[0]) not in EXCLUDED_TABLES
        ]
        for table in table_names:
            columns_info = list(connection.execute(f'PRAGMA table_info("{table}")'))
            columns = tuple(str(row[1]) for row in columns_info)
            primary_keys = tuple(
                str(row[1]) for row in sorted((item for item in columns_info if int(item[5]) > 0), key=lambda item: int(item[5]))
            )
            dependencies = tuple(sorted({
                str(row[2]) for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
                if str(row[2]) not in EXCLUDED_TABLES
            }))
            if primary_keys:
                result[table] = TableInfo(table, columns, primary_keys, dependencies)
        return result

    @staticmethod
    def _snapshot(connection: sqlite3.Connection, tables: dict[str, TableInfo]) -> dict[tuple[str, str], str]:
        snapshot: dict[tuple[str, str], str] = {}
        for table, info in tables.items():
            ignored = IGNORED_COLUMNS.get(table, set())
            for raw_row in connection.execute(f'SELECT * FROM "{table}"'):
                row = {column: encode_value(raw_row[column]) for column in info.columns if column not in ignored}
                primary_key = {column: row[column] for column in info.primary_keys}
                snapshot[(table, canonical_json(primary_key))] = canonical_json(row)
        return snapshot

    @staticmethod
    def _changes(before: dict[tuple[str, str], str], after: dict[tuple[str, str], str]) -> list[dict[str, Any]]:
        result = []
        for table, primary_key in sorted(set(before) | set(after)):
            previous = before.get((table, primary_key))
            current = after.get((table, primary_key))
            if previous == current:
                continue
            result.append({
                "table": table,
                "primaryKey": primary_key,
                "before": previous,
                "after": current,
            })
        return result

    @staticmethod
    def _has_semantic_changes(changes: list[dict[str, Any]]) -> bool:
        for change in changes:
            if change["table"] != "entities" or not change["before"] or not change["after"]:
                return True
            before = json.loads(change["before"])
            after = json.loads(change["after"])
            for transient in ("revision", "updated_at"):
                before.pop(transient, None)
                after.pop(transient, None)
            if before != after:
                return True
        return False

    @staticmethod
    def _affected_entity_ids(connection: sqlite3.Connection, changes: list[dict[str, Any]]) -> tuple[str, ...]:
        candidates: set[str] = set()
        for change in changes:
            for raw in (change["before"], change["after"]):
                if not raw:
                    continue
                row = json.loads(raw)
                for column, value in row.items():
                    if column == "id" and change["table"] == "entities":
                        candidates.add(str(value))
                    elif column == "entity_id" or column.endswith("_entity_id") or column in {
                        "character_id", "plot_id", "entry_id", "fragment_id", "line_id",
                        "from_character_id", "to_character_id", "source_entity_id", "target_entity_id",
                    }:
                        if isinstance(value, str):
                            candidates.add(value)
        if not candidates:
            return ()
        placeholders = ",".join("?" for _ in candidates)
        return tuple(sorted(
            str(row[0]) for row in connection.execute(
                f"SELECT id FROM entities WHERE id IN ({placeholders})", tuple(sorted(candidates))
            )
        ))

    def mutate(
        self,
        *,
        base_revision: int,
        label: str,
        action: str,
        entity_kind: str,
        callback: Callable[[sqlite3.Connection], Any],
        details: dict[str, Any] | None = None,
        after_operation: Callable[[sqlite3.Connection, int], None] | None = None,
        now: int | None = None,
    ) -> MutationResult:
        timestamp = int(time.time()) if now is None else int(now)
        with self.database.locked():
            connection = self.database.connect()
            try:
                self.database.require_v3(connection)
                connection.execute("BEGIN IMMEDIATE")
                project = connection.execute(
                "SELECT revision FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()
                if not project:
                    raise NotFoundError("项目不存在")
                current_revision = int(project[0])
                if int(base_revision) != current_revision:
                    raise ConflictError(
                        f"内容已在别处更新；当前版本为 {current_revision}，请合并后重试"
                    )
                tables = self._tables(connection)
                before = self._snapshot(connection, tables)
                callback_result = callback(connection)
                after = self._snapshot(connection, tables)
                changes = self._changes(before, after)
                if not changes or not self._has_semantic_changes(changes):
                    # Services may optimistically touch an entity revision before
                    # the final row comparison is known. A semantic no-op must not
                    # consume a project revision or leave that touch behind.
                    connection.rollback()
                    return MutationResult(None, current_revision, (), callback_result)
                next_revision = current_revision + 1
                connection.execute(
                "UPDATE projects SET revision=?, updated_at=? WHERE id=?",
                (next_revision, timestamp, self.project_id),
            )
                cursor = connection.execute(
                """
                INSERT INTO operations(
                    project_id, label, action, entity_kind, base_revision, result_revision,
                    details_json, created_at, expires_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.project_id, label, action, entity_kind, current_revision, next_revision,
                    canonical_json(details or {}), timestamp, timestamp + HISTORY_RETENTION_SECONDS,
                ),
            )
                operation_id = int(cursor.lastrowid)
                connection.executemany(
                """
                INSERT INTO operation_changes(
                    operation_id, table_name, primary_key_json, before_json, after_json,
                    before_revision, after_revision
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        operation_id, change["table"], change["primaryKey"], change["before"],
                        change["after"], current_revision, next_revision,
                    )
                    for change in changes
                ],
            )
                if after_operation:
                    after_operation(connection, operation_id)
                connection.execute(
                """
                INSERT INTO export_state(project_id, requested_revision, exported_revision, status, last_error, updated_at)
                VALUES(?, ?, 0, 'pending', '', ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    requested_revision=excluded.requested_revision,
                    status='pending', last_error='', updated_at=excluded.updated_at
                """,
                (self.project_id, next_revision, timestamp),
            )
                affected = self._affected_entity_ids(connection, changes)
                connection.commit()
                return MutationResult(operation_id, next_revision, affected, callback_result)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _current_row_json(
        connection: sqlite3.Connection,
        info: TableInfo,
        primary_key_json: str,
    ) -> str | None:
        primary_key = json.loads(primary_key_json)
        where = " AND ".join(f'"{column}"=?' for column in info.primary_keys)
        values = tuple(decode_value(primary_key[column]) for column in info.primary_keys)
        row = connection.execute(f'SELECT * FROM "{info.name}" WHERE {where}', values).fetchone()
        if row is None:
            return None
        ignored = IGNORED_COLUMNS.get(info.name, set())
        return canonical_json({
            column: encode_value(row[column]) for column in info.columns if column not in ignored
        })

    @staticmethod
    def operation_can_undo(connection: sqlite3.Connection, operation: sqlite3.Row, now: int | None = None) -> tuple[bool, str]:
        timestamp = int(time.time()) if now is None else int(now)
        if str(operation["action"]) == "legacy":
            return False, "旧版操作仅保留审计记录，不能跨 Schema 撤销"
        if operation["undone_by"] is not None or operation["undone_at"] is not None:
            return False, "这项操作已经撤销"
        if int(operation["expires_at"]) <= timestamp:
            return False, "这项操作已超过 7 天"
        tables = UnitOfWork._tables(connection)
        changes = list(connection.execute(
            "SELECT * FROM operation_changes WHERE operation_id=? ORDER BY table_name, primary_key_json",
            (operation["id"],),
        ))
        if not changes:
            return False, "这项操作没有可用的行级快照"
        for change in changes:
            info = tables.get(str(change["table_name"]))
            if info is None:
                return False, f"数据表 {change['table_name']} 已不受当前版本支持"
            current = UnitOfWork._current_row_json(connection, info, str(change["primary_key_json"]))
            if current != change["after_json"]:
                return False, "相关内容后来又被修改，不能安全撤销"
        ordered_tables = {"plots", "chapters", "timeline_lines"}
        affected_keys = {
            (str(change["table_name"]), str(change["primary_key_json"]))
            for change in changes
        }
        for change in changes:
            table_name = str(change["table_name"])
            if table_name not in ordered_tables or not change["before_json"]:
                continue
            before = json.loads(str(change["before_json"]))
            desired_rank = before.get("sort_key")
            info = tables[table_name]
            if desired_rank is None:
                continue
            occupant = connection.execute(
                f'SELECT {", ".join(chr(34)+column+chr(34) for column in info.primary_keys)} '
                f'FROM "{table_name}" WHERE sort_key=?',
                (desired_rank,),
            ).fetchone()
            if not occupant:
                continue
            occupant_key = canonical_json({
                column: encode_value(occupant[column]) for column in info.primary_keys
            })
            if (table_name, occupant_key) not in affected_keys:
                return False, "相关内容的顺序后来已经调整，不能安全撤销"
        return True, ""

    @staticmethod
    def _dependency_depths(tables: dict[str, TableInfo]) -> dict[str, int]:
        cache: dict[str, int] = {}

        def depth(table: str, visiting: set[str]) -> int:
            if table in cache:
                return cache[table]
            if table in visiting:
                return 0
            visiting.add(table)
            value = 0
            for dependency in tables[table].dependencies:
                if dependency in tables:
                    value = max(value, depth(dependency, visiting) + 1)
            visiting.remove(table)
            cache[table] = value
            return value

        for table in tables:
            depth(table, set())
        return cache

    @staticmethod
    def _apply_row(connection: sqlite3.Connection, info: TableInfo, primary_key_json: str, target_json: str | None) -> None:
        primary_key = json.loads(primary_key_json)
        where = " AND ".join(f'"{column}"=?' for column in info.primary_keys)
        key_values = tuple(decode_value(primary_key[column]) for column in info.primary_keys)
        exists = connection.execute(f'SELECT 1 FROM "{info.name}" WHERE {where}', key_values).fetchone()
        if target_json is None:
            if exists:
                connection.execute(f'DELETE FROM "{info.name}" WHERE {where}', key_values)
            return
        target = {key: decode_value(value) for key, value in json.loads(target_json).items()}
        if exists:
            columns = [column for column in target if column not in info.primary_keys]
            if columns:
                assignments = ", ".join(f'"{column}"=?' for column in columns)
                connection.execute(
                    f'UPDATE "{info.name}" SET {assignments} WHERE {where}',
                    tuple(target[column] for column in columns) + key_values,
                )
        else:
            columns = list(target)
            placeholders = ",".join("?" for _ in columns)
            connection.execute(
                f'INSERT INTO "{info.name}" ({",".join(chr(34)+column+chr(34) for column in columns)}) VALUES({placeholders})',
                tuple(target[column] for column in columns),
            )

    def undo(self, operation_id: int, base_revision: int, now: int | None = None) -> MutationResult:
        timestamp = int(time.time()) if now is None else int(now)
        probe = self.database.connect()
        try:
            self.database.require_v3(probe)
            operation = probe.execute(
                "SELECT * FROM operations WHERE id=? AND project_id=?",
                (int(operation_id), self.project_id),
            ).fetchone()
            if not operation:
                raise NotFoundError("操作记录不存在")
            can_undo, reason = self.operation_can_undo(probe, operation, timestamp)
            if not can_undo:
                raise ConflictError(reason)
            raw_changes = [dict(row) for row in probe.execute(
                "SELECT * FROM operation_changes WHERE operation_id=?",
                (int(operation_id),),
            )]
            label = str(operation["label"])
            entity_kind = str(operation["entity_kind"])
        finally:
            probe.close()

        def apply_inverse(connection: sqlite3.Connection) -> None:
            # Row snapshots describe the final inverse state. Defer FK checks so
            # an existing child can be moved away from a newly-created parent
            # before that parent is removed, without depending on incidental row order.
            connection.execute("PRAGMA defer_foreign_keys=ON")
            tables = self._tables(connection)
            depths = self._dependency_depths(tables)
            deletions = [change for change in raw_changes if change["before_json"] is None]
            restorations = [change for change in raw_changes if change["before_json"] is not None]
            # SQLite UNIQUE constraints are immediate. Temporarily move every
            # changed ordered row out of the numeric rank space before restoring
            # a permutation such as a reversed plot or chapter order.
            ordered_tables = {"plots", "chapters", "timeline_lines"}
            for index, change in enumerate(
                (item for item in restorations if item["table_name"] in ordered_tables),
                start=1,
            ):
                info = tables[change["table_name"]]
                primary_key = json.loads(change["primary_key_json"])
                where = " AND ".join(f'"{column}"=?' for column in info.primary_keys)
                values = tuple(decode_value(primary_key[column]) for column in info.primary_keys)
                if connection.execute(
                    f'SELECT 1 FROM "{info.name}" WHERE {where}', values
                ).fetchone():
                    connection.execute(
                        f'UPDATE "{info.name}" SET sort_key=? WHERE {where}',
                        (f"~undo-{operation_id}-{index:06d}",) + values,
                    )
            for change in sorted(deletions, key=lambda item: depths.get(item["table_name"], 0), reverse=True):
                self._apply_row(connection, tables[change["table_name"]], change["primary_key_json"], None)
            for change in sorted(restorations, key=lambda item: depths.get(item["table_name"], 0)):
                self._apply_row(
                    connection, tables[change["table_name"]], change["primary_key_json"], change["before_json"]
                )

        return self.mutate(
            base_revision=base_revision,
            label=f"撤销：{label}",
            action="undo",
            entity_kind=entity_kind,
            callback=apply_inverse,
            details={"targetOperationId": int(operation_id)},
            after_operation=lambda connection, inverse_id: connection.execute(
                "UPDATE operations SET undone_at=?, undone_by=? WHERE id=?",
                (timestamp, inverse_id, int(operation_id)),
            ),
            now=timestamp,
        )
