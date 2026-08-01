from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storyteller import SCHEMA_VERSION
from storyteller.domain.uow import (
    UnitOfWork,
    canonical_json,
    decode_value,
    encode_value,
)
from storyteller.storage.connection import Database, schema_version
from storyteller.storage.schema import migrate_v3_to_v4, migrate_v4_to_v5


TRANSIENT_COLUMNS = {
    "projects": {"revision", "updated_at"},
    "entities": {"revision", "updated_at"},
}
TEXT_MERGE_COLUMNS = {
    "body_markdown",
    "intro_markdown",
    "summary",
    "content",
    "fact_value",
    "extra_json",
}
TABLE_LABELS = {
    "projects": "项目信息",
    "entities": "内容档案",
    "chapters": "篇章",
    "characters": "人物",
    "character_aliases": "人物别名",
    "character_markers": "人物标签",
    "character_facts": "人物事实",
    "character_supplements": "人物补充",
    "entries": "设定",
    "entry_aliases": "设定别名",
    "entry_tags": "设定标签",
    "fragments": "碎片",
    "fragment_tags": "碎片标签",
    "plots": "剧情",
    "plot_tags": "剧情标签",
    "plot_characters": "剧情人物",
    "plot_entries": "剧情设定",
    "entry_characters": "设定人物",
    "relationships": "人物关系",
    "timeline_settings": "时间线设置",
    "timeline_lines": "时间线",
    "plot_timeline_lines": "时间线节点",
    "timeline_connections": "时间线连接",
    "graph_settings": "图谱设置",
    "graph_nodes": "图谱节点",
    "graph_distances": "图谱距离",
    "graph_clusters": "图谱分组",
    "graph_cluster_members": "图谱分组成员",
    "entity_references": "内容引用",
    "assets": "附件",
}
ENTITY_COLUMNS = (
    "entity_id",
    "plot_id",
    "character_id",
    "entry_id",
    "fragment_id",
    "line_id",
    "source_entity_id",
    "target_entity_id",
    "from_character_id",
    "to_character_id",
)


@dataclass(slots=True)
class RowConflict:
    table: str
    primary_key: str
    base: str | None
    ours: str | None
    theirs: str | None
    merged: str | None
    columns: list[str]
    entity_id: str | None = None
    title: str = ""


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def copy_database(source: Path, target: Path) -> None:
    target.unlink(missing_ok=True)
    target.with_name(target.name + "-wal").unlink(missing_ok=True)
    target.with_name(target.name + "-shm").unlink(missing_ok=True)
    with sqlite3.connect(
        f"{source.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    ) as source_db:
        with sqlite3.connect(target) as target_db:
            source_db.backup(target_db)
            target_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    target.with_name(target.name + "-wal").unlink(missing_ok=True)
    target.with_name(target.name + "-shm").unlink(missing_ok=True)


def ensure_current_schema(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        version = schema_version(connection)
        if version == 3:
            connection.execute("PRAGMA foreign_keys=ON")
            migrate_v3_to_v4(connection)
            version = schema_version(connection)
        if version == 4:
            connection.execute("PRAGMA foreign_keys=ON")
            migrate_v4_to_v5(connection)
            version = schema_version(connection)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"数据库 Schema V{version} 无法由当前合并驱动处理（需要 V{SCHEMA_VERSION}）"
            )


def project_state(connection: sqlite3.Connection) -> tuple[str, int]:
    row = connection.execute("SELECT id, revision FROM projects ORDER BY id LIMIT 1").fetchone()
    if not row:
        raise ValueError("数据库缺少项目记录")
    return str(row["id"]), int(row["revision"])


def table_snapshot(
    connection: sqlite3.Connection,
    tables: dict[str, Any],
) -> dict[tuple[str, str], str]:
    snapshot: dict[tuple[str, str], str] = {}
    for table, info in tables.items():
        for raw_row in connection.execute(f'SELECT * FROM "{table}"'):
            row = {column: encode_value(raw_row[column]) for column in info.columns}
            primary_key = {column: row[column] for column in info.primary_keys}
            snapshot[(table, canonical_json(primary_key))] = canonical_json(row)
    return snapshot


def decoded_row(raw: str | None) -> dict[str, Any] | None:
    return json.loads(raw) if raw is not None else None


def semantic_row(table: str, row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    ignored = TRANSIENT_COLUMNS.get(table, set())
    return {key: value for key, value in row.items() if key not in ignored}


def rows_equal(table: str, left: str | None, right: str | None) -> bool:
    return semantic_row(table, decoded_row(left)) == semantic_row(table, decoded_row(right))


def _transient_value(
    table: str,
    column: str,
    base: dict[str, Any],
    ours: dict[str, Any],
    theirs: dict[str, Any],
    both_semantically_changed: bool,
) -> Any:
    if column == "revision":
        ours_value = int(ours.get(column, 0) or 0)
        theirs_value = int(theirs.get(column, 0) or 0)
        if table == "entities" and both_semantically_changed:
            return max(ours_value, theirs_value) + 1
        return max(ours_value, theirs_value)
    if column == "updated_at":
        return max(int(ours.get(column, 0) or 0), int(theirs.get(column, 0) or 0))
    return ours.get(column, theirs.get(column, base.get(column)))


def merge_text_value(base: str, ours: str, theirs: str) -> str | None:
    """Ask Git's native text merge engine to combine non-overlapping edits."""
    with tempfile.TemporaryDirectory(prefix="story-text-merge-") as temporary:
        root = Path(temporary)
        base_path = root / "base.txt"
        ours_path = root / "ours.txt"
        theirs_path = root / "theirs.txt"
        base_path.write_text(base, encoding="utf-8")
        ours_path.write_text(ours, encoding="utf-8")
        theirs_path.write_text(theirs, encoding="utf-8")
        process = subprocess.run(
            [
                "git",
                "merge-file",
                "-p",
                str(ours_path),
                str(base_path),
                str(theirs_path),
            ],
            check=False,
            capture_output=True,
        )
        if process.returncode == 0:
            return process.stdout.decode("utf-8")
        if process.returncode == 1:
            return None
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git 文本三方合并失败：{message or process.returncode}")


def merge_row(
    table: str,
    primary_key: str,
    base_raw: str | None,
    ours_raw: str | None,
    theirs_raw: str | None,
) -> tuple[str | None, RowConflict | None]:
    if rows_equal(table, ours_raw, theirs_raw):
        return ours_raw if ours_raw is not None else theirs_raw, None
    if rows_equal(table, ours_raw, base_raw):
        return theirs_raw, None
    if rows_equal(table, theirs_raw, base_raw):
        return ours_raw, None

    base = decoded_row(base_raw)
    ours = decoded_row(ours_raw)
    theirs = decoded_row(theirs_raw)
    if base is None or ours is None or theirs is None:
        return ours_raw, RowConflict(
            table, primary_key, base_raw, ours_raw, theirs_raw, ours_raw, ["__row__"]
        )

    ignored = TRANSIENT_COLUMNS.get(table, set())
    merged: dict[str, Any] = {}
    conflicting: list[str] = []
    all_columns = list(dict.fromkeys([*ours, *theirs, *base]))
    ours_changed = semantic_row(table, ours) != semantic_row(table, base)
    theirs_changed = semantic_row(table, theirs) != semantic_row(table, base)
    for column in all_columns:
        if column in ignored:
            merged[column] = _transient_value(
                table, column, base, ours, theirs, ours_changed and theirs_changed
            )
            continue
        before = base.get(column)
        current = ours.get(column)
        incoming = theirs.get(column)
        if current == incoming:
            merged[column] = current
        elif current == before:
            merged[column] = incoming
        elif incoming == before:
            merged[column] = current
        elif (
            column in TEXT_MERGE_COLUMNS
            and isinstance(before, str)
            and isinstance(current, str)
            and isinstance(incoming, str)
        ):
            text_result = merge_text_value(before, current, incoming)
            if text_result is None:
                merged[column] = current
                conflicting.append(column)
            else:
                merged[column] = text_result
        else:
            merged[column] = current
            conflicting.append(column)
    merged_raw = canonical_json(merged)
    if not conflicting:
        return merged_raw, None
    return merged_raw, RowConflict(
        table, primary_key, base_raw, ours_raw, theirs_raw, merged_raw, conflicting
    )


def infer_entity_id(table: str, *rows: str | None) -> str | None:
    for raw in rows:
        row = decoded_row(raw)
        if not row:
            continue
        if table == "entities" and isinstance(row.get("id"), str):
            return str(row["id"])
        for column in ENTITY_COLUMNS:
            value = row.get(column)
            if isinstance(value, str) and ":" in value:
                return value
    return None


def describe_conflicts(
    conflicts: list[RowConflict],
    snapshots: tuple[dict[tuple[str, str], str], ...],
) -> None:
    entity_titles: dict[str, str] = {}
    for snapshot in snapshots:
        for (table, _primary_key), raw in snapshot.items():
            if table != "entities":
                continue
            row = decoded_row(raw)
            if row and isinstance(row.get("id"), str):
                entity_titles[str(row["id"])] = str(row.get("title") or row["id"])
    for conflict in conflicts:
        conflict.entity_id = infer_entity_id(
            conflict.table, conflict.ours, conflict.theirs, conflict.base
        )
        table_label = TABLE_LABELS.get(conflict.table, conflict.table)
        entity_title = entity_titles.get(conflict.entity_id or "")
        conflict.title = f"{table_label} · {entity_title}" if entity_title else table_label


def apply_targets(
    database: Database,
    project_id: str,
    ours_revision: int,
    ours_snapshot: dict[tuple[str, str], str],
    targets: dict[tuple[str, str], str | None],
) -> None:
    pending = [
        (table, primary_key, target)
        for (table, primary_key), target in targets.items()
        if not rows_equal(table, ours_snapshot.get((table, primary_key)), target)
    ]
    if not pending:
        return

    def apply(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA defer_foreign_keys=ON")
        tables = UnitOfWork._tables(connection)
        depths = UnitOfWork._dependency_depths(tables)
        deletions = sorted(
            (item for item in pending if item[2] is None),
            key=lambda item: depths.get(item[0], 0),
            reverse=True,
        )
        upserts = sorted(
            (item for item in pending if item[2] is not None),
            key=lambda item: depths.get(item[0], 0),
        )
        for table, primary_key, target in [*deletions, *upserts]:
            info = tables.get(table)
            if info is None:
                raise ValueError(f"合并结果包含未知数据表：{table}")
            UnitOfWork._apply_row(connection, info, primary_key, target)

    UnitOfWork(database, project_id).mutate(
        base_revision=ours_revision,
        label="合并另一台电脑的更新",
        action="merge",
        entity_kind="project",
        callback=apply,
        details={"source": "git-merge-driver"},
    )


def persist_conflicts(
    database: Database,
    project_id: str,
    source_path: str,
    hashes: tuple[str, str, str],
    revisions: tuple[int, int, int],
    conflicts: list[RowConflict],
) -> str | None:
    if not conflicts:
        return None
    timestamp = int(time.time())
    session_id = str(uuid.uuid4())
    with database.write() as connection:
        connection.execute(
            """
            INSERT INTO merge_sessions(
                id, project_id, source_path, base_hash, ours_hash, theirs_hash,
                base_revision, ours_revision, theirs_revision, status,
                conflict_count, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
            """,
            (
                session_id,
                project_id,
                source_path,
                *hashes,
                *revisions,
                len(conflicts),
                timestamp,
            ),
        )
        connection.executemany(
            """
            INSERT INTO merge_conflicts(
                id, session_id, table_name, primary_key_json, entity_id, title,
                base_json, ours_json, theirs_json, merged_json,
                conflict_columns_json, resolution_json, status, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', 'open', ?)
            """,
            [
                (
                    str(uuid.uuid4()),
                    session_id,
                    conflict.table,
                    conflict.primary_key,
                    conflict.entity_id,
                    conflict.title,
                    conflict.base,
                    conflict.ours,
                    conflict.theirs,
                    conflict.merged,
                    canonical_json(conflict.columns),
                    timestamp,
                )
                for conflict in conflicts
            ],
        )
    return session_id


def build_merge(
    base_path: Path,
    ours_path: Path,
    theirs_path: Path,
    output_path: Path,
    source_path: str = "",
) -> tuple[int, str | None]:
    for path, label in (
        (base_path, "共同祖先"),
        (ours_path, "当前电脑"),
        (theirs_path, "另一台电脑"),
    ):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"{label}数据库不存在或为空：{path}")

    hashes = (file_hash(base_path), file_hash(ours_path), file_hash(theirs_path))
    temporary_root = Path(tempfile.mkdtemp(prefix="story-db-merge-"))
    candidate = temporary_root / "story.db"
    try:
        copy_database(ours_path, candidate)
        ensure_current_schema(candidate)
        connections = [open_readonly(path) for path in (base_path, ours_path, theirs_path)]
        try:
            states = [project_state(connection) for connection in connections]
            project_ids = {state[0] for state in states}
            if len(project_ids) != 1:
                raise ValueError("三个数据库不属于同一个项目")
            project_id = states[0][0]
            revisions = tuple(state[1] for state in states)
            table_sets = [UnitOfWork._tables(connection) for connection in connections]
            table_names = set(table_sets[1])
            if not table_names.issubset(table_sets[0]) or not table_names.issubset(table_sets[2]):
                missing = sorted(
                    (table_names - set(table_sets[0])) | (table_names - set(table_sets[2]))
                )
                raise ValueError(f"数据库结构不一致，缺少数据表：{', '.join(missing)}")
            snapshots = tuple(
                table_snapshot(connection, {name: tables[name] for name in sorted(table_names)})
                for connection, tables in zip(connections, table_sets)
            )
        finally:
            for connection in connections:
                connection.close()

        base_snapshot, ours_snapshot, theirs_snapshot = snapshots
        targets: dict[tuple[str, str], str | None] = {}
        conflicts: list[RowConflict] = []
        for table, primary_key in sorted(
            set(base_snapshot) | set(ours_snapshot) | set(theirs_snapshot)
        ):
            target, conflict = merge_row(
                table,
                primary_key,
                base_snapshot.get((table, primary_key)),
                ours_snapshot.get((table, primary_key)),
                theirs_snapshot.get((table, primary_key)),
            )
            targets[(table, primary_key)] = target
            if conflict:
                conflicts.append(conflict)
        describe_conflicts(conflicts, snapshots)

        database = Database(temporary_root)
        try:
            apply_targets(database, project_id, revisions[1], ours_snapshot, targets)
        except (sqlite3.IntegrityError, ValueError) as error:
            # Cross-row UNIQUE/FK constraints can reveal a conflict that is invisible
            # when rows are compared independently. Preserve the current database and
            # turn every incoming difference into an explicit whole-row decision.
            copy_database(ours_path, candidate)
            ensure_current_schema(candidate)
            conflict_keys = {(item.table, item.primary_key) for item in conflicts}
            for key, target in sorted(targets.items()):
                if rows_equal(key[0], ours_snapshot.get(key), target) or key in conflict_keys:
                    continue
                conflicts.append(
                    RowConflict(
                        key[0],
                        key[1],
                        base_snapshot.get(key),
                        ours_snapshot.get(key),
                        theirs_snapshot.get(key),
                        ours_snapshot.get(key),
                        ["__row__"],
                        title=f"{TABLE_LABELS.get(key[0], key[0])}（需要确认）",
                    )
                )
            describe_conflicts(conflicts, snapshots)
            print(f"自动合并触发约束冲突，已改为保留选择项：{error}", file=sys.stderr)

        session_id = persist_conflicts(
            Database(temporary_root),
            project_id,
            source_path,
            hashes,
            revisions,
            conflicts,
        )
        with sqlite3.connect(candidate) as check:
            check.execute("PRAGMA foreign_keys=ON")
            integrity = str(check.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = list(check.execute("PRAGMA foreign_key_check"))
            if integrity != "ok" or foreign_keys:
                raise ValueError("合并结果未通过数据库完整性检查")
            check.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        copy_database(candidate, output_path)
        try:
            os.chmod(output_path, ours_path.stat().st_mode)
        except OSError:
            pass
        return len(conflicts), session_id
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Story Teller SQLite 三方 Git 合并驱动")
    parser.add_argument("base", type=Path)
    parser.add_argument("ours", type=Path)
    parser.add_argument("theirs", type=Path)
    parser.add_argument("path", nargs="?", default="")
    args = parser.parse_args()
    temporary = args.ours.with_name(f".{args.ours.name}.merged-{uuid.uuid4().hex}.db")
    try:
        count, session_id = build_merge(
            args.base, args.ours, args.theirs, temporary, str(args.path or "")
        )
        os.replace(temporary, args.ours)
        if count:
            print(
                f"Story Teller 已自动合入无冲突内容，并保留 {count} 项待网页确认"
                f"（会话 {session_id}）。"
            )
        else:
            print("Story Teller 数据库已完成无冲突三方合并。")
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"Story Teller 数据库合并失败：{error}", file=sys.stderr)
        return 1
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
