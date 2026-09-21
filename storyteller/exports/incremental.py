"""Versioned export checkpoints and bounded incremental journals.

Only explicit exports, missing/expired checkpoints and journal compaction read
all bodies. Published journals are immutable and shared by static/recovery reads.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

from storyteller.exports.recovery import EXCLUDED_TABLES, _encode
from storyteller.exports.version import EXPORT_FORMAT_VERSION
from storyteller.storage.repositories import ProjectRepository

INDEX_FILE = "export-index.json"
DATA_DIRECTORY = "export-data"
MAX_PATCHES = 64
COLLECTIONS = ("characters", "plots", "entries", "fragments", "relationships", "chapters")


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def blob(files, content):
    path = f"{DATA_DIRECTORY}/{hashlib.sha256(content).hexdigest()}.json"
    files[path] = content
    return path


def read_blob(root: Path, relative: str):
    # Manifests are external recovery inputs, never permit arbitrary file reads.
    if not isinstance(relative, str) or not re.fullmatch(r"export-data/[a-f0-9]{64}\.json", relative):
        raise ValueError("导出数据路径无效")
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or path.suffix != ".json":
        raise ValueError("导出数据路径越界")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != path.stem:
        raise ValueError("导出数据校验失败")
    return json.loads(raw)


def load_index(root, project, revision, *, bounded=True):
    try:
        index = json.loads((root / INDEX_FILE).read_text())
        if (index["formatVersion"] != EXPORT_FORMAT_VERSION or index["project"] != project
                or not 0 <= index["revision"] <= revision or (bounded and len(index["patches"]) >= MAX_PATCHES)):
            return None
        for relative in [index["staticBase"], index["recoveryBase"], *[ref for pair in index["patches"] for ref in pair.values()]]:
            # Contents are checked by readers; normal saving only checks existence.
            if not isinstance(relative, str) or not re.fullmatch(r"export-data/[a-f0-9]{64}\.json", relative) or not (root / relative).is_file():
                return None
        return index
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def checkpoint(files, snapshot, paths, project):
    static_base = blob(files, files["project.snapshot.json"])
    recovery_base = blob(files, files["recovery.snapshot.json"])
    index = {"formatVersion": EXPORT_FORMAT_VERSION, "project": project,
             "revision": snapshot["project"]["revision"], "summary": summary(snapshot),
             "paths": paths, "staticBase": static_base, "recoveryBase": recovery_base, "patches": []}
    files[INDEX_FILE] = json_bytes(index)
    return index


def summary(snapshot):
    result = copy.deepcopy(snapshot)
    for collection in COLLECTIONS:
        for item in result[collection]:
            item.pop("body", None)
            item.pop("intro", None)
    return result


def plan(database, project, index):
    repository = ProjectRepository(database, project)
    delta = repository.changes_since(index["revision"])
    current = copy.deepcopy(index["summary"])
    with database.read() as connection:
        row = connection.execute("SELECT * FROM projects WHERE id=?", (project,)).fetchone()
        current["project"] = {"id": project, "revision": row["revision"], "title": row["title"],
                              "eyebrow": row["eyebrow"], "extra": json.loads(row["extra_json"])}
        # Include physically removed rows as well as soft deletions.
        active = {row[0] for row in connection.execute("SELECT id FROM entities WHERE deleted_at IS NULL")}
    dirty = {identifier for identifier, paths in index["paths"].items()
             if any(not (database.project_root / path).is_file() for path in paths)}
    for collection in COLLECTIONS:
        changes = {item["entityId"]: item for item in delta["changed"].get(collection, [])}
        dirty.update(changes)
        dirty.update(delta["removed"].get(collection, []))
        values = {item["entityId"]: item for item in current[collection] if item["entityId"] in active}
        values.update(changes)
        current[collection] = list(values.values())
    current.update(delta["structures"])
    if delta["changed"].get("timelineLines") or delta["removed"].get("timelineLines"):
        with database.read() as connection:
            current["timeline"] = repository._timeline(connection)
    # Export paths/content depend on names of parents, characters and story lines.
    old_names = {item["entityId"]: item["name"] for item in index["summary"]["characters"]}
    changed_characters = {item["entityId"] for item in delta["changed"].get("characters", [])
                          if item["name"] != old_names.get(item["entityId"])}
    dirty.update(item["entityId"] for item in current["relationships"]
                 if item["from"] in changed_characters or item["to"] in changed_characters)
    dirty.update(item["entityId"] for item in current["fragments"] if item.get("parentFragmentId") in dirty)
    old_lines = {item["entityId"]: item["name"] for item in index["summary"]["timeline"]["lines"]}
    renamed_lines = {item["entityId"] for item in current["timeline"]["lines"] if old_lines.get(item["entityId"]) != item["name"]}
    dirty.update(item["entityId"] for item in current["plots"] if renamed_lines.intersection(item.get("stories", [])))
    dirty.update(set(index["paths"]) - active)
    current["characters"].sort(key=lambda item: (-item["mainPlotImpact"], item["id"]))
    current["plots"].sort(key=lambda item: (item["chapterNumber"] is None, item["chapterNumber"] or 0, item["sortKey"], item["id"]))
    for position, item in enumerate(current["plots"]):
        item["sequence"] = position + 1
    current["entries"].sort(key=lambda item: (item["type"], item["id"]))
    current["fragments"].sort(key=lambda item: (item.get("updatedAt", 0), item.get("createdAt", 0), item["entityId"]), reverse=True)
    current["relationships"].sort(key=lambda item: item["id"])
    current["chapters"].sort(key=lambda item: item["sortKey"])
    details = {}
    for identifier in dirty & active:
        detail = repository.entity_detail(identifier)
        if detail and detail["kind"] in {"character", "plot", "entry", "fragment", "relationship"}:
            details[identifier] = detail["data"]
    return summary(current), dirty, details


def recovery_patch(database, project, revision):
    with database.read() as connection:
        changed = {}
        for row in connection.execute("""
            SELECT c.table_name, c.primary_key_json FROM operation_changes c
            JOIN operations o ON o.id=c.operation_id
            WHERE o.project_id=? AND o.result_revision>?
        """, (project, revision)):
            changed.setdefault(row[0], set()).add(row[1])
        changed.setdefault("projects", set()).add(json.dumps({"id": project}))
        tables = {}
        for name, keys in changed.items():
            if name in EXCLUDED_TABLES:
                continue
            info = list(connection.execute(f'PRAGMA table_info("{name}")'))
            if not info:
                raise ValueError("增量恢复包含未知数据表")
            columns = [item[1] for item in info]
            primary = [item[1] for item in sorted(info, key=lambda item: item[5]) if item[5]]
            rows = []
            for raw_key in sorted(keys):
                key = json.loads(raw_key)
                values = [key[column] for column in primary]
                where = " AND ".join(f'"{column}"=?' for column in primary)
                row = connection.execute(f'SELECT * FROM "{name}" WHERE {where}', values).fetchone()
                rows.append({"key": values, "row": [_encode(row[column]) for column in columns] if row else None})
            tables[name] = {"columns": columns, "primaryKeys": primary, "changes": rows}
        # These records are not audited by the content transaction. Their small
        # metadata is refreshed; historical before/after bodies are never scanned.
        replacements = {}
        for name in ("operations", "merge_sessions", "merge_conflicts"):
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')]
            replacements[name] = {"columns": columns, "rows": [[_encode(value) for value in row]
                                     for row in connection.execute(f'SELECT * FROM "{name}" ORDER BY 1')]}
        columns = [row[1] for row in connection.execute('PRAGMA table_info("operation_changes")')]
        new_changes = [[_encode(row[column]) for column in columns] for row in connection.execute("""
            SELECT c.* FROM operation_changes c JOIN operations o ON o.id=c.operation_id
            WHERE o.project_id=? AND o.result_revision>? ORDER BY c.operation_id,c.table_name,c.primary_key_json
        """, (project, revision))]
        return {"tables": tables, "replaceTables": replacements,
                "operationChanges": {"columns": columns, "rows": new_changes}}


def publish_patch(files, database, project, index, current, details, paths):
    revision = current["project"]["revision"]
    overrides = {}
    for collection in COLLECTIONS:
        previous = {item["entityId"]: item for item in index["summary"][collection]}
        for item in current[collection]:
            old = previous.get(item["entityId"], {})
            overrides[item["entityId"]] = {key: value for key, value in item.items() if old.get(key) != value}
    header = {"fromRevision": index["revision"], "revision": revision, "project": project}
    patches = [*index["patches"], {
        "static": blob(files, json_bytes({**header, "static": {"summary": current, "details": details, "overrides": overrides}})),
        "recovery": blob(files, json_bytes({**header, "recovery": recovery_patch(database, project, index["revision"])})),
    }]
    for filename, base, kind in (("project.snapshot.json", index["staticBase"], "static"),
                                 ("recovery.snapshot.json", index["recoveryBase"], "recovery")):
        files[filename] = json_bytes({"format": "story-teller-export-journal", "version": 1,
                                     "kind": kind, "project": current["project"], "base": base, "patches": [pair[kind] for pair in patches]})
    files[INDEX_FILE] = json_bytes({**index, "revision": revision, "summary": current, "paths": paths, "patches": patches})


def load_snapshot(path):
    path = Path(path)
    payload = json.loads(path.read_text())
    if payload.get("format") != "story-teller-export-journal":
        return payload
    if payload.get("version") != 1 or payload.get("kind") != "static":
        raise ValueError("静态快照格式不受支持")
    result = read_blob(path.parent, payload["base"])
    for reference in payload["patches"]:
        patch = read_blob(path.parent, reference)
        if patch["fromRevision"] != result["project"]["revision"] or patch["project"] != result["project"]["id"]:
            raise ValueError("静态快照增量不连续")
        current = patch["static"]["summary"]
        details = patch["static"]["details"]
        for collection in COLLECTIONS:
            previous = {item["entityId"]: item for item in result[collection]}
            result[collection] = [{**previous.get(item["entityId"], item), **patch["static"]["overrides"].get(item["entityId"], {}), **details.get(item["entityId"], {})}
                                  for item in current[collection]]
        for key in ("project", "timeline", "graph"):
            result[key] = current[key]
    if result["project"] != payload["project"]:
        raise ValueError("静态快照版本不匹配")
    result["readonly"] = True
    return result


def load_recovery(path):
    path = Path(path)
    payload = json.loads(path.read_text())
    if payload.get("format") != "story-teller-export-journal":
        return payload
    if payload.get("version") != 1 or payload.get("kind") != "recovery":
        raise ValueError("恢复快照格式不受支持")
    result = read_blob(path.parent, payload["base"])
    project_table = result["tables"]["projects"]
    revision = next(row[project_table["columns"].index("revision")] for row in project_table["rows"]
                    if row[project_table["columns"].index("id")] == result["project"])
    for reference in payload["patches"]:
        patch = read_blob(path.parent, reference)
        if patch["fromRevision"] != revision or patch["project"] != result["project"]:
            raise ValueError("恢复快照增量不连续")
        data = patch["recovery"]
        for name, changes in data["tables"].items():
            table = result["tables"][name]
            if table["columns"] != changes["columns"]:
                raise ValueError("恢复快照数据表结构不匹配")
            positions = [table["columns"].index(key) for key in changes["primaryKeys"]]
            rows = {tuple(row[pos] for pos in positions): row for row in table["rows"]}
            for change in changes["changes"]:
                key = tuple(change["key"])
                if change["row"] is None:
                    rows.pop(key, None)
                else:
                    rows[key] = change["row"]
            table["rows"] = [row for _, row in sorted(rows.items())]
        result["tables"].update(data["replaceTables"])
        table = result["tables"]["operation_changes"]
        valid = {row[0] for row in result["tables"]["operations"]["rows"]}
        table["rows"] = [row for row in table["rows"] if row[0] in valid] + data["operationChanges"]["rows"]
        revision = patch["revision"]
    if revision != payload["project"]["revision"] or result["project"] != payload["project"]["id"]:
        raise ValueError("恢复快照版本不匹配")
    return result
