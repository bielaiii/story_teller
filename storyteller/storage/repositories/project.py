from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from typing import Any, Iterable

from storyteller.domain.errors import ConflictError
from storyteller.domain.uow import UnitOfWork
from storyteller.storage.connection import Database


def json_value(raw: str | None, fallback: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return fallback
    return value


def preview(text: str, length: int = 420) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) <= length:
        return normalized
    clipped = normalized[:length].rstrip()
    last_line_break = clipped.rfind("\n")
    if last_line_break >= length // 2:
        clipped = clipped[:last_line_break].rstrip()
    return f"{clipped}\n\n…"


def persona_from_lines(values: str | Iterable[str], fallback_key: str) -> list[dict[str, str]]:
    lines = str(values or "").splitlines() if isinstance(values, str) else list(values)
    result: list[dict[str, str]] = []
    for index, raw in enumerate(lines):
        line = str(raw or "").strip().lstrip("-• ").strip()
        if not line:
            continue
        separator = "：" if "：" in line else ":" if ":" in line else ""
        if separator:
            key, value = (part.strip() for part in line.split(separator, 1))
        else:
            key = fallback_key if not result else f"{fallback_key} {index + 1}"
            value = line
        if key and value:
            result.append({"key": key, "value": value})
    return result


def stored_persona(extra: dict[str, Any], section: str, fallback: list[dict[str, str]]) -> list[dict[str, str]]:
    persona = extra.get("characterPersona")
    values = persona.get(section) if isinstance(persona, dict) else None
    if not isinstance(values, list):
        return fallback
    result = []
    for item in values:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        value = str(item.get("value") or "").strip()
        if key and value:
            result.append({"key": key, "value": value})
    return result


class ProjectRepository:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id

    @staticmethod
    def _values(
        connection: sqlite3.Connection,
        table: str,
        owner_column: str,
        value_column: str,
    ) -> dict[str, list[str]]:
        result: dict[str, list[str]] = defaultdict(list)
        for row in connection.execute(
            f"SELECT {owner_column}, {value_column} FROM {table} ORDER BY {owner_column}, position"
        ):
            result[str(row[0])].append(str(row[1]))
        return result

    def snapshot(self) -> dict[str, Any]:
        with self.database.read() as connection:
            project = connection.execute("SELECT * FROM projects WHERE id=?", (self.project_id,)).fetchone()
            if not project:
                raise ValueError("项目不存在")
            aliases = self._values(connection, "character_aliases", "character_id", "alias")
            markers = self._values(connection, "character_markers", "character_id", "marker")
            entry_aliases = self._values(connection, "entry_aliases", "entry_id", "alias")
            entry_tags = self._values(connection, "entry_tags", "entry_id", "tag")
            fragment_tags = self._values(connection, "fragment_tags", "fragment_id", "tag")
            plot_tags = self._values(connection, "plot_tags", "plot_id", "tag")
            facts: dict[str, dict[str, str]] = defaultdict(dict)
            for row in connection.execute(
                "SELECT character_id, fact_key, fact_value FROM character_facts ORDER BY character_id, position"
            ):
                facts[str(row[0])][str(row[1])] = str(row[2])
            supplements = self._values(connection, "character_supplements", "character_id", "content")
            plot_people: dict[str, list[str]] = defaultdict(list)
            for row in connection.execute("SELECT * FROM active_plot_characters ORDER BY plot_id, character_id"):
                plot_people[str(row["plot_id"])].append(str(row["character_id"]))
            plot_entries: dict[str, list[str]] = defaultdict(list)
            for row in connection.execute("SELECT * FROM active_plot_entries ORDER BY plot_id, entry_id"):
                plot_entries[str(row["plot_id"])].append(str(row["entry_id"]))
            entry_people: dict[str, list[str]] = defaultdict(list)
            for row in connection.execute(
                """
                SELECT ec.* FROM entry_characters ec
                JOIN active_entries e ON e.entity_id=ec.entry_id
                JOIN active_characters c ON c.entity_id=ec.character_id
                ORDER BY ec.entry_id, ec.character_id
                """
            ):
                entry_people[str(row["entry_id"])].append(str(row["character_id"]))
            lanes: dict[str, list[str]] = defaultdict(list)
            for row in connection.execute(
                """
                SELECT node.plot_id, node.line_id FROM active_timeline_nodes node
                JOIN timeline_lines line ON line.entity_id=node.line_id
                ORDER BY node.plot_id, line.sort_key
                """
            ):
                lanes[str(row["plot_id"])].append(str(row["line_id"]))

            characters = [self._character(row, aliases, markers, facts, supplements, include_body=False) for row in connection.execute(
                "SELECT * FROM active_characters ORDER BY main_plot_impact DESC, stable_id"
            )]
            plots = [self._plot(row, plot_tags, plot_people, plot_entries, lanes, include_body=False) for row in connection.execute(
                "SELECT * FROM active_plots ORDER BY sort_key, stable_id"
            )]
            entries = [self._entry(row, entry_aliases, entry_tags, entry_people, include_body=False) for row in connection.execute(
                "SELECT * FROM active_entries ORDER BY type, stable_id"
            )]
            fragments = [self._fragment(row, fragment_tags, include_body=False) for row in connection.execute(
                "SELECT * FROM active_fragments ORDER BY stable_id"
            )]
            relationships = [dict(self._relationship(row)) for row in connection.execute(
                "SELECT * FROM active_relationships ORDER BY stable_id"
            )]
            chapters = [dict(self._chapter(row)) for row in connection.execute(
                "SELECT * FROM active_chapters ORDER BY sort_key"
            )]
            timeline = self._timeline(connection)
            graph = self._graph(connection)
            return {
                "project": {
                    "id": str(project["id"]),
                    "title": str(project["title"]),
                    "eyebrow": str(project["eyebrow"]),
                    "revision": int(project["revision"]),
                    "extra": json_value(project["extra_json"], {}),
                },
                "characters": characters,
                "plots": plots,
                "entries": entries,
                "fragments": fragments,
                "relationships": relationships,
                "chapters": chapters,
                "timeline": timeline,
                "graph": graph,
            }

    @staticmethod
    def _character(row, aliases, markers, facts, supplements, *, include_body: bool) -> dict[str, Any]:
        identifier = str(row["entity_id"])
        extra = json_value(row["extra_json"], {})
        if not isinstance(extra, dict):
            extra = {}
        core_persona = stored_persona(
            extra, "core", persona_from_lines(str(row["intro_markdown"]), "人物定位")
        )
        supplement_persona = stored_persona(
            extra, "supplement", persona_from_lines(supplements.get(identifier, []), "补充设定")
        )
        public_extra = dict(extra)
        public_extra.pop("characterPersona", None)
        result = {
            "entityId": identifier,
            "id": str(row["stable_id"]),
            "name": str(row["name"]),
            "aliases": aliases.get(identifier, []),
            "markers": markers.get(identifier, []),
            "facts": facts.get(identifier, {}),
            "supplements": supplements.get(identifier, []),
            "corePersona": core_persona,
            "supplementPersona": supplement_persona,
            "narrativeRole": str(row["narrative_role"]),
            "characterScope": str(row["character_scope"]),
            "side": str(row["side"]),
            "mainPlotImpact": int(row["main_plot_impact"]),
            "color": str(row["color"]),
            "gradient": str(row["gradient"]),
            "group": str(row["group_name"]),
            "graphVisible": None if row["graph_visible"] is None else bool(row["graph_visible"]),
            "revision": int(row["revision"]),
            "introPreview": preview(row["intro_markdown"]),
            "extra": public_extra,
        }
        if include_body:
            result["intro"] = str(row["intro_markdown"])
        return result

    @staticmethod
    def _plot(row, tags, people, entries, lanes, *, include_body: bool) -> dict[str, Any]:
        identifier = str(row["entity_id"])
        result = {
            "entityId": identifier,
            "id": str(row["stable_id"]),
            "title": str(row["title"]),
            "chapterId": str(row["chapter_id"] or ""),
            "sortKey": str(row["sort_key"]),
            "sequence": int(row["display_sequence"]),
            "summary": str(row["summary"]),
            "bodyPreview": preview(row["body_markdown"]),
            "status": str(row["status"]),
            "accent": str(row["accent"]),
            "key": bool(row["is_key"]),
            "climax": bool(row["is_climax"]),
            "tags": tags.get(identifier, []),
            "people": people.get(identifier, []),
            "entries": entries.get(identifier, []),
            "lanes": lanes.get(identifier, []),
            "revision": int(row["revision"]),
            "extra": json_value(row["extra_json"], {}),
        }
        if include_body:
            result["body"] = str(row["body_markdown"])
        return result

    @staticmethod
    def _entry(row, aliases, tags, people, *, include_body: bool) -> dict[str, Any]:
        identifier = str(row["entity_id"])
        result = {
            "entityId": identifier,
            "id": str(row["stable_id"]),
            "name": str(row["name"]),
            "type": str(row["type"]),
            "subtype": str(row["subtype"]),
            "area": str(row["area"]),
            "status": str(row["status"]),
            "accent": str(row["accent"]),
            "aliases": aliases.get(identifier, []),
            "tags": tags.get(identifier, []),
            "people": people.get(identifier, []),
            "bodyPreview": preview(row["body_markdown"]),
            "revision": int(row["revision"]),
            "extra": json_value(row["extra_json"], {}),
        }
        if include_body:
            result["body"] = str(row["body_markdown"])
        return result

    @staticmethod
    def _fragment(row, tags, *, include_body: bool) -> dict[str, Any]:
        identifier = str(row["entity_id"])
        result = {
            "entityId": identifier,
            "id": str(row["stable_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "accent": str(row["accent"]),
            "tags": tags.get(identifier, []),
            "bodyPreview": preview(row["body_markdown"]),
            "revision": int(row["revision"]),
            "extra": json_value(row["extra_json"], {}),
        }
        if include_body:
            result["body"] = str(row["body_markdown"])
        return result

    @staticmethod
    def _relationship(row) -> dict[str, Any]:
        return {
            "entityId": str(row["entity_id"]),
            "id": str(row["stable_id"]),
            "from": str(row["from_character_id"]),
            "to": str(row["to_character_id"]),
            "fromRole": str(row["from_role"]),
            "toRole": str(row["to_role"]),
            "label": str(row["label"]),
            "type": str(row["type"]),
            "color": str(row["color"]),
            "revision": int(row["revision"]),
        }

    @staticmethod
    def _chapter(row) -> dict[str, Any]:
        return {
            "entityId": str(row["entity_id"]),
            "id": str(row["stable_id"]),
            "label": str(row["label"]),
            "sortKey": str(row["sort_key"]),
            "revision": int(row["revision"]),
        }

    def _timeline(self, connection: sqlite3.Connection) -> dict[str, Any]:
        settings = connection.execute(
            "SELECT * FROM timeline_settings WHERE project_id=?", (self.project_id,)
        ).fetchone()
        lines = [
            {
                "entityId": str(row["entity_id"]), "id": str(row["stable_id"]),
                "name": str(row["title"]), "color": str(row["color"]),
                "side": str(row["side"]), "sortKey": str(row["sort_key"]),
                "startPlotId": row["start_plot_id"], "endPlotId": row["end_plot_id"],
                "revision": int(row["revision"]),
            }
            for row in connection.execute("SELECT * FROM active_timeline_lines ORDER BY sort_key")
        ]
        nodes = [
            {"plotId": str(row["plot_id"]), "lineId": str(row["line_id"]), "storySortKey": str(row["story_sort_key"])}
            for row in connection.execute("SELECT * FROM active_timeline_nodes ORDER BY line_id, story_sort_key")
        ]
        return {
            "mainLineId": str(settings["main_line_id"] or "") if settings else "",
            "lineSpacing": int(settings["line_spacing"]) if settings else 72,
            "topPadding": int(settings["top_padding"]) if settings else 64,
            "sidePadding": int(settings["side_padding"]) if settings else 36,
            "pixelsPerStoryUnit": int(settings["pixels_per_story_unit"]) if settings else 760,
            "lines": lines,
            "nodes": nodes,
        }

    def _graph(self, connection: sqlite3.Connection) -> dict[str, Any]:
        settings = connection.execute("SELECT * FROM graph_settings WHERE project_id=?", (self.project_id,)).fetchone()
        clusters = []
        for cluster in connection.execute("SELECT * FROM graph_clusters WHERE project_id=? ORDER BY sort_key", (self.project_id,)):
            members = [str(row[0]) for row in connection.execute(
                """
                SELECT m.character_id FROM graph_cluster_members m
                JOIN active_characters c ON c.entity_id=m.character_id
                WHERE m.cluster_id=? ORDER BY m.character_id
                """, (cluster["id"],)
            )]
            clusters.append({
                "id": str(cluster["id"]), "label": str(cluster["label"]),
                "centerX": cluster["center_x"], "centerY": cluster["center_y"],
                "radius": cluster["radius"], "strength": cluster["strength"], "members": members,
            })
        return {
            "settings": dict(settings) if settings else {},
            "nodes": [dict(row) for row in connection.execute("SELECT * FROM active_graph_nodes ORDER BY character_id")],
            "distances": [dict(row) for row in connection.execute("SELECT * FROM active_graph_distances ORDER BY from_character_id, to_character_id")],
            "clusters": clusters,
        }

    def entity_detail(self, entity_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        with self.database.read() as connection:
            entity = connection.execute(
                "SELECT * FROM entities WHERE id=? AND project_id=?", (entity_id, self.project_id)
            ).fetchone()
            if not entity or (entity["deleted_at"] is not None and not include_deleted):
                return None
            kind = str(entity["kind"])
            if kind == "relationship" and not include_deleted and not connection.execute(
                "SELECT 1 FROM active_relationships WHERE entity_id=?", (entity_id,)
            ).fetchone():
                return None
            base = {
                "entityId": str(entity["id"]), "id": str(entity["stable_id"]),
                "kind": kind, "title": str(entity["title"]), "revision": int(entity["revision"]),
                "deletedAt": entity["deleted_at"], "purgeAt": entity["purge_at"],
            }
            if kind == "character":
                row = connection.execute("SELECT c.*, e.* FROM characters c JOIN entities e ON e.id=c.entity_id WHERE c.entity_id=?", (entity_id,)).fetchone()
                aliases = self._values(connection, "character_aliases", "character_id", "alias")
                markers = self._values(connection, "character_markers", "character_id", "marker")
                facts = defaultdict(dict)
                for item in connection.execute("SELECT * FROM character_facts WHERE character_id=? ORDER BY position", (entity_id,)):
                    facts[entity_id][str(item["fact_key"])] = str(item["fact_value"])
                supplements = self._values(connection, "character_supplements", "character_id", "content")
                base["data"] = self._character(row, aliases, markers, facts, supplements, include_body=True)
            elif kind == "plot":
                row = connection.execute(
                    """
                    SELECT p.*, e.project_id, e.stable_id, e.title, e.revision, e.extra_json,
                           (SELECT COUNT(*) FROM active_plots earlier WHERE earlier.sort_key <= p.sort_key) AS display_sequence
                    FROM plots p JOIN entities e ON e.id=p.entity_id WHERE p.entity_id=?
                    """, (entity_id,)
                ).fetchone()
                tags = self._values(connection, "plot_tags", "plot_id", "tag")
                people = defaultdict(list)
                people_table = "plot_characters" if include_deleted else "active_plot_characters"
                for item in connection.execute(f"SELECT character_id FROM {people_table} WHERE plot_id=?", (entity_id,)):
                    people[entity_id].append(str(item[0]))
                entries = defaultdict(list)
                entries_table = "plot_entries" if include_deleted else "active_plot_entries"
                for item in connection.execute(f"SELECT entry_id FROM {entries_table} WHERE plot_id=?", (entity_id,)):
                    entries[entity_id].append(str(item[0]))
                lanes = defaultdict(list)
                lanes_table = "plot_timeline_lines" if include_deleted else "active_timeline_nodes"
                for item in connection.execute(f"SELECT line_id FROM {lanes_table} WHERE plot_id=?", (entity_id,)):
                    lanes[entity_id].append(str(item[0]))
                base["data"] = self._plot(row, tags, people, entries, lanes, include_body=True)
            elif kind == "entry":
                row = connection.execute("SELECT d.*, e.* FROM entries d JOIN entities e ON e.id=d.entity_id WHERE d.entity_id=?", (entity_id,)).fetchone()
                aliases = self._values(connection, "entry_aliases", "entry_id", "alias")
                tags = self._values(connection, "entry_tags", "entry_id", "tag")
                people = defaultdict(list)
                people_source = """
                    SELECT ec.character_id FROM entry_characters ec
                    JOIN active_characters c ON c.entity_id=ec.character_id
                    WHERE ec.entry_id=?
                """ if not include_deleted else "SELECT character_id FROM entry_characters WHERE entry_id=?"
                for item in connection.execute(people_source, (entity_id,)):
                    people[entity_id].append(str(item[0]))
                base["data"] = self._entry(row, aliases, tags, people, include_body=True)
            elif kind == "fragment":
                row = connection.execute("SELECT f.*, e.* FROM fragments f JOIN entities e ON e.id=f.entity_id WHERE f.entity_id=?", (entity_id,)).fetchone()
                tags = self._values(connection, "fragment_tags", "fragment_id", "tag")
                base["data"] = self._fragment(row, tags, include_body=True)
            elif kind == "relationship":
                row = connection.execute("SELECT r.*, e.* FROM relationships r JOIN entities e ON e.id=r.entity_id WHERE r.entity_id=?", (entity_id,)).fetchone()
                base["data"] = self._relationship(row)
                base["data"]["body"] = str(row["body_markdown"])
            elif kind == "chapter":
                row = connection.execute("SELECT c.*, e.* FROM chapters c JOIN entities e ON e.id=c.entity_id WHERE c.entity_id=?", (entity_id,)).fetchone()
                base["data"] = self._chapter(row)
            elif kind == "timeline_line":
                row = connection.execute("SELECT l.*, e.* FROM timeline_lines l JOIN entities e ON e.id=l.entity_id WHERE l.entity_id=?", (entity_id,)).fetchone()
                base["data"] = dict(row)
            if kind in {"character", "plot", "entry", "fragment", "relationship"}:
                reference_table = "entity_references" if include_deleted else "active_entity_references"
                base["data"]["references"] = [
                    str(item[0]) for item in connection.execute(
                        f"""
                        SELECT target_entity_id FROM {reference_table}
                        WHERE source_entity_id=? AND context='body'
                        ORDER BY id
                        """,
                        (entity_id,),
                    )
                ]
            return base

    def trash(self, limit: int = 100) -> list[dict[str, Any]]:
        now = int(time.time())
        with self.database.read() as connection:
            rows = connection.execute(
                """
                SELECT * FROM trash_items
                WHERE project_id=? AND purge_at>?
                ORDER BY deleted_at DESC LIMIT ?
                """,
                (self.project_id, now, max(1, min(int(limit), 300))),
            )
            return [{
                "entityId": str(row["id"]), "id": str(row["stable_id"]),
                "kind": str(row["kind"]), "title": str(row["title"]),
                "deletedAt": int(row["deleted_at"]), "expiresAt": int(row["purge_at"]),
                "daysRemaining": max(0, (int(row["purge_at"]) - now + 86399) // 86400),
                "canRestore": True,
            } for row in rows]

    def operations(self, limit: int = 100) -> list[dict[str, Any]]:
        now = int(time.time())
        with self.database.read() as connection:
            rows = list(connection.execute(
                """
                SELECT * FROM operations WHERE project_id=? AND expires_at>?
                ORDER BY id DESC LIMIT ?
                """,
                (self.project_id, now, max(1, min(int(limit), 300))),
            ))
            result = []
            for row in rows:
                can_undo, reason = UnitOfWork.operation_can_undo(connection, row, now)
                result.append({
                    "id": int(row["id"]), "label": str(row["label"]),
                    "action": str(row["action"]), "entityKind": str(row["entity_kind"]),
                    "createdAt": int(row["created_at"]), "expiresAt": int(row["expires_at"]),
                    "baseRevision": int(row["base_revision"]), "resultRevision": int(row["result_revision"]),
                    "canUndo": can_undo, "undoBlockedReason": reason,
                    "undone": row["undone_by"] is not None,
                })
            return result

    def changes_since(self, revision: int) -> dict[str, Any]:
        with self.database.read() as connection:
            current = int(connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()[0])
            if revision > current:
                raise ConflictError("客户端版本高于当前项目版本，请重新读取项目快照")
            operations = list(connection.execute(
                "SELECT id, base_revision, result_revision FROM operations WHERE project_id=? AND result_revision>? ORDER BY result_revision",
                (self.project_id, int(revision)),
            ))
            expected_revision = int(revision)
            for operation in operations:
                if int(operation["base_revision"]) != expected_revision:
                    raise ConflictError("增量历史已经过期，请重新读取项目快照")
                expected_revision = int(operation["result_revision"])
            if expected_revision != current:
                raise ConflictError("增量历史已经过期，请重新读取项目快照")
            entity_ids: set[str] = set()
            changed_tables: set[str] = set()
            lifecycle_ids: set[str] = set()
            for operation in operations:
                changes = [{
                    "table": str(row["table_name"]),
                    "before": row["before_json"],
                    "after": row["after_json"],
                } for row in connection.execute(
                    "SELECT table_name, before_json, after_json FROM operation_changes WHERE operation_id=?",
                    (operation["id"],),
                )]
                changed_tables.update(item["table"] for item in changes)
                entity_ids.update(UnitOfWork._affected_entity_ids(connection, changes))
                for change in changes:
                    if change["table"] != "entities" or not change["before"] or not change["after"]:
                        continue
                    before = json.loads(change["before"])
                    after = json.loads(change["after"])
                    if before.get("deleted_at") != after.get("deleted_at"):
                        lifecycle_ids.add(str(after["id"]))

            structures: set[str] = set()
            if changed_tables & {"timeline_settings", "timeline_lines", "plot_timeline_lines", "timeline_connections"}:
                structures.add("timeline")
            if changed_tables & {"graph_settings", "graph_nodes", "graph_distances", "graph_clusters", "graph_cluster_members"}:
                structures.add("graph")
            for identifier in lifecycle_ids:
                entity = connection.execute(
                    "SELECT kind FROM entities WHERE id=?", (identifier,)
                ).fetchone()
                if not entity:
                    continue
                entity_ids.update(str(row[0]) for row in connection.execute(
                    "SELECT source_entity_id FROM entity_references WHERE target_entity_id=?",
                    (identifier,),
                ))
                kind = str(entity["kind"])
                if kind == "character":
                    structures.add("graph")
                    entity_ids.update(str(row[0]) for row in connection.execute(
                        "SELECT entity_id FROM relationships WHERE from_character_id=? OR to_character_id=?",
                        (identifier, identifier),
                    ))
                    entity_ids.update(str(row[0]) for row in connection.execute(
                        "SELECT plot_id FROM plot_characters WHERE character_id=?", (identifier,)
                    ))
                    entity_ids.update(str(row[0]) for row in connection.execute(
                        "SELECT entry_id FROM entry_characters WHERE character_id=?", (identifier,)
                    ))
                elif kind == "entry":
                    entity_ids.update(str(row[0]) for row in connection.execute(
                        "SELECT plot_id FROM plot_entries WHERE entry_id=?", (identifier,)
                    ))
                elif kind in {"plot", "timeline_line"}:
                    structures.add("timeline")
        changed: dict[str, list[dict[str, Any]]] = defaultdict(list)
        removed: dict[str, list[str]] = defaultdict(list)
        kind_names = {
            "character": "characters", "plot": "plots", "entry": "entries",
            "fragment": "fragments", "relationship": "relationships",
            "timeline_line": "timelineLines", "chapter": "chapters",
        }
        for identifier in sorted(entity_ids):
            detail = self.entity_detail(identifier, include_deleted=True)
            if not detail:
                continue
            bucket = kind_names.get(detail["kind"], detail["kind"])
            active_detail = self.entity_detail(identifier)
            if active_detail is None:
                removed[bucket].append(identifier)
            else:
                changed[bucket].append(active_detail["data"])
        structural_delta: dict[str, Any] = {}
        if structures:
            snapshot = self.snapshot()
            if "timeline" in structures:
                structural_delta["timeline"] = snapshot["timeline"]
            if "graph" in structures:
                structural_delta["graph"] = snapshot["graph"]
        return {
            "fromRevision": int(revision),
            "projectRevision": current,
            "changed": dict(changed),
            "removed": dict(removed),
            "structures": structural_delta,
        }

    def mutation_delta(self, result) -> dict[str, Any]:
        if result.operation_id is None:
            return {
                "fromRevision": int(result.project_revision),
                "projectRevision": int(result.project_revision),
                "changed": {},
                "removed": {},
                "structures": {},
                "ok": True,
                "operation": {"id": None, "canUndo": False, "expiresAt": None},
            }
        previous = max(0, int(result.project_revision) - 1)
        delta = self.changes_since(previous)
        delta["ok"] = True
        with self.database.read() as connection:
            operation = connection.execute(
                "SELECT expires_at FROM operations WHERE id=? AND project_id=?",
                (result.operation_id, self.project_id),
            ).fetchone()
        delta["operation"] = {
            "id": result.operation_id,
            "canUndo": True,
            "expiresAt": int(operation[0]) if operation else None,
        }
        return delta
