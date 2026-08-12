from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import yaml

from storyteller import SCHEMA_VERSION
from storyteller.storage.schema import initialize_schema


REGISTRY_PATH = Path(__file__).with_name("world_schema.yaml")
STORAGE_REGISTRY_PATH = Path(__file__).with_name("world_schema.storage.yaml")
PRIMARY_ENTITY_TABLES = {
    "character": "characters",
    "plot": "plots",
    "entry": "entries",
    "fragment": "fragments",
    "relationship": "relationships",
    "chapter": "chapters",
    "timeline_line": "timeline_lines",
}
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


@lru_cache(maxsize=1)
def load_world_schema() -> dict[str, Any]:
    value = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("entityKinds"), dict):
        raise ValueError("世界领域注册表格式不合法")
    return value


def entity_schema(kind: str) -> dict[str, Any]:
    value = load_world_schema()["entityKinds"].get(kind)
    if not isinstance(value, dict):
        raise ValueError(f"领域注册表没有实体类型：{kind}")
    return value


def visible_fields(kind: str, purpose: str = "aiVisible") -> dict[str, dict[str, Any]]:
    fields = entity_schema(kind).get("fields", {})
    return {
        str(name): dict(spec)
        for name, spec in fields.items()
        if isinstance(spec, dict) and bool(spec.get(purpose))
    }


def public_world_schema() -> dict[str, Any]:
    registry = load_world_schema()
    entities: dict[str, Any] = {}
    for kind, spec in registry["entityKinds"].items():
        fields = {
            name: {
                key: value
                for key, value in field.items()
                if key not in {"source", "derived"}
            }
            for name, field in spec.get("fields", {}).items()
            if field.get("aiVisible")
        }
        entities[kind] = {
            key: value
            for key, value in spec.items()
            if key != "fields"
        }
        entities[kind]["fields"] = fields
    return {
        "version": int(registry.get("version", 1)),
        "databaseSchemaVersion": SCHEMA_VERSION,
        "description": str(registry.get("description") or ""),
        "entityKinds": entities,
    }


def filter_entity_data(kind: str, data: dict[str, Any], *, purpose: str = "aiVisible") -> dict[str, Any]:
    allowed = visible_fields(kind, purpose)
    result = {
        key: data[key]
        for key in allowed
        if key in data
    }
    for key in ("entityId", "id", "revision"):
        if key in data:
            result[key] = data[key]
    return result


def hydrate_registered_fields(database, kind: str, entity_id: str, data: dict[str, Any]) -> dict[str, Any]:
    """Fill ordinary main-table fields declared by the registry without repository hand mapping."""
    result = dict(data)
    main_table = PRIMARY_ENTITY_TABLES.get(kind)
    if not main_table:
        return result
    missing: dict[str, tuple[str, dict[str, Any]]] = {}
    for field_name, spec in entity_schema(kind).get("fields", {}).items():
        if field_name in result or spec.get("derived"):
            continue
        source = str(spec.get("source") or "")
        if "." not in source:
            continue
        table, column = source.split(".", 1)
        if table not in {main_table, "entities"} or not IDENTIFIER.fullmatch(column):
            continue
        missing[field_name] = (source, spec)
    if not missing:
        return result
    with database.read() as connection:
        rows: dict[str, sqlite3.Row | None] = {}
        for table in {source.split(".", 1)[0] for source, _spec in missing.values()}:
            if table == "entities":
                rows[table] = connection.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
            else:
                rows[table] = connection.execute(f'SELECT * FROM "{table}" WHERE entity_id=?', (entity_id,)).fetchone()
        for field_name, (source, spec) in missing.items():
            table, column = source.split(".", 1)
            row = rows.get(table)
            if not row or column not in row.keys():
                continue
            value: Any = row[column]
            field_type = str(spec.get("type") or "")
            if value is None:
                result[field_name] = None
            elif field_type in {"integer", "number"}:
                result[field_name] = int(value)
            elif field_type == "boolean":
                result[field_name] = bool(value)
            else:
                result[field_name] = str(value)
    return result


def exportable_metadata(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    fields = visible_fields(kind, "exportable")
    return {
        name: data[name]
        for name, spec in fields.items()
        if name in data
        and spec.get("type") != "markdown"
        and data[name] not in (None, "", [], {})
    }


def semantic_lines(kind: str, data: dict[str, Any], *, purpose: str = "searchable") -> list[tuple[str, Any]]:
    return [
        (str(spec.get("label") or name), data.get(name))
        for name, spec in visible_fields(kind, purpose).items()
        if data.get(name) not in (None, "", [], {})
    ]


def _memory_schema() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    initialize_schema(connection)
    return connection


def inspect_storage_schema() -> dict[str, Any]:
    connection = _memory_schema()
    try:
        tables: dict[str, Any] = {}
        rows = connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        for row in rows:
            table = str(row["name"])
            foreign_keys: dict[str, dict[str, str]] = {}
            for foreign in connection.execute(f'PRAGMA foreign_key_list("{table}")'):
                foreign_keys[str(foreign["from"])] = {
                    "table": str(foreign["table"]),
                    "column": str(foreign["to"]),
                }
            columns = {}
            for column in connection.execute(f'PRAGMA table_info("{table}")'):
                name = str(column["name"])
                spec: dict[str, Any] = {
                    "storageType": str(column["type"] or ""),
                    "required": bool(column["notnull"]),
                    "primaryKey": bool(column["pk"]),
                }
                if column["dflt_value"] is not None:
                    spec["default"] = str(column["dflt_value"])
                if name in foreign_keys:
                    spec["references"] = foreign_keys[name]
                columns[name] = spec
            tables[table] = {"columns": columns}
        return {"databaseSchemaVersion": SCHEMA_VERSION, "tables": tables}
    finally:
        connection.close()


def semantic_sources() -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = {}
    for kind, entity in load_world_schema()["entityKinds"].items():
        for field_name, field in entity.get("fields", {}).items():
            source = str(field.get("source") or "")
            if "." not in source:
                continue
            table, column = source.split(".", 1)
            result.setdefault((table, column), []).append(f"{kind}.{field_name}")
    return result


def sync_storage_registry(*, bootstrap: bool = False) -> dict[str, Any]:
    if bootstrap and STORAGE_REGISTRY_PATH.exists():
        raise ValueError("领域存储注册表已经存在，--bootstrap 只能用于首次建立基线")
    actual = inspect_storage_schema()
    previous: dict[str, Any] = {}
    if STORAGE_REGISTRY_PATH.exists():
        loaded = yaml.safe_load(STORAGE_REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            previous = loaded
    old_tables = previous.get("tables", {}) if isinstance(previous.get("tables"), dict) else {}
    sources = semantic_sources()
    internal_tables = set(load_world_schema().get("internalTables", []))
    result = {"databaseSchemaVersion": SCHEMA_VERSION, "tables": {}}
    for table, table_spec in actual["tables"].items():
        columns = {}
        old_columns = old_tables.get(table, {}).get("columns", {}) if isinstance(old_tables.get(table), dict) else {}
        for column, physical in table_spec["columns"].items():
            prior = old_columns.get(column, {}) if isinstance(old_columns, dict) else {}
            semantics = sources.get((table, column), [])
            if semantics:
                review = "domain"
            elif table in internal_tables:
                review = "internal"
            else:
                prior_review = str(prior.get("review") or "")
                review = "internal" if prior_review == "internal" or bootstrap else "TODO"
            columns[column] = {**physical, "review": review}
            if semantics:
                columns[column]["fields"] = semantics
        result["tables"][table] = {"columns": columns}
    return result


def storage_registry_text(value: dict[str, Any]) -> str:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=100000)


def validate_world_schema(storage_registry: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    registry = load_world_schema()
    actual = inspect_storage_schema()
    for kind, entity in registry["entityKinds"].items():
        if not entity.get("label") or not entity.get("description"):
            errors.append(f"{kind} 缺少 label 或 description")
        for name, field in entity.get("fields", {}).items():
            for required in ("label", "type", "aiVisible", "searchable", "exportable"):
                if required not in field:
                    errors.append(f"{kind}.{name} 缺少 {required}")
            source = str(field.get("source") or "")
            if source and "." in source:
                table, column = source.split(".", 1)
                if table not in actual["tables"] or column not in actual["tables"][table]["columns"]:
                    errors.append(f"{kind}.{name} 指向不存在的 SQLite 字段：{source}")
    current = storage_registry or sync_storage_registry()
    for table, table_spec in current.get("tables", {}).items():
        for column, field in table_spec.get("columns", {}).items():
            if field.get("review") == "TODO":
                errors.append(f"SQLite 字段尚未登记语义：{table}.{column}")
    expected = sync_storage_registry()
    if current != expected:
        errors.append("world_schema.storage.yaml 与当前 SQLite Schema 不一致")
    return errors


def load_storage_registry() -> dict[str, Any]:
    if not STORAGE_REGISTRY_PATH.exists():
        return {}
    value = yaml.safe_load(STORAGE_REGISTRY_PATH.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def registry_json_bytes() -> bytes:
    return (json.dumps(public_world_schema(), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def registry_fingerprint() -> str:
    return hashlib.sha256(registry_json_bytes()).hexdigest()


def searchable_entity_kinds() -> Iterable[str]:
    return (
        kind for kind, spec in load_world_schema()["entityKinds"].items()
        if any(field.get("searchable") for field in spec.get("fields", {}).values())
    )
