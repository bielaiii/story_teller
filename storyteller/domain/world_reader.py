from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from storyteller.domain.world_schema import entity_schema, filter_entity_data, hydrate_registered_fields, public_world_schema
from storyteller.storage.connection import Database
from storyteller.storage.repositories import ProjectRepository


BUCKETS = {
    "character": "characters",
    "plot": "plots",
    "entry": "entries",
    "fragment": "fragments",
    "relationship": "relationships",
    "chapter": "chapters",
    "timeline_line": "timelineLines",
}


class WorldReader:
    """Read-only domain gateway over the canonical story.db."""

    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id
        self.repository = ProjectRepository(database, project_id)

    def _revision(self) -> int:
        with self.database.read() as connection:
            row = connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()
            if not row:
                raise ValueError(f"项目 {self.project_id} 不存在")
            return int(row[0])

    @staticmethod
    def _entity_meta(kind: str) -> dict[str, str]:
        schema = entity_schema(kind)
        return {
            "certainty": str(schema.get("certainty") or "confirmed"),
            "timelineStatus": str(schema.get("timelineStatus") or "independent"),
        }

    def schema(self) -> dict[str, Any]:
        return {
            "project": self.project_id,
            "sourceRevision": self._revision(),
            **public_world_schema(),
        }

    def _items(self, kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
        snapshot = self.repository.snapshot()
        allowed = set(kinds or BUCKETS)
        result: list[dict[str, Any]] = []
        for kind, bucket in BUCKETS.items():
            if kind not in allowed:
                continue
            if kind == "timeline_line":
                values = snapshot["timeline"]["lines"]
            else:
                values = snapshot.get(bucket, [])
            for value in values:
                title = str(value.get("name") or value.get("title") or value.get("label") or value.get("id") or "")
                result.append({
                    "entityId": str(value["entityId"]),
                    "stableId": str(value.get("id") or ""),
                    "kind": kind,
                    "title": title,
                    "revision": int(value.get("revision") or 0),
                    **self._entity_meta(kind),
                })
        return result

    def catalog(self) -> dict[str, Any]:
        items = self._items()
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            counts[item["kind"]] += 1
        return {
            "project": self.project_id,
            "sourceRevision": self._revision(),
            "counts": dict(sorted(counts.items())),
            "items": items,
        }

    def resolve(self, query: str, *, kinds: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
        clean = str(query or "").strip()
        if not clean:
            return {"project": self.project_id, "sourceRevision": self._revision(), "query": clean, "results": []}
        lowered = clean.casefold()
        candidates = []
        for item in self._items(kinds):
            detail = self.repository.entity_detail(item["entityId"])
            data = detail["data"] if detail else {}
            aliases = [str(value) for value in data.get("aliases", [])]
            variants = [item["entityId"], item["stableId"], item["title"], *aliases]
            normalized = [value.casefold() for value in variants if value]
            if lowered in normalized:
                score = 1.0
            elif any(lowered in value for value in normalized):
                score = 0.75
            elif any(value in lowered for value in normalized if len(value) >= 2):
                score = 0.65
            else:
                continue
            candidates.append({**item, "aliases": aliases, "score": score})
        candidates.sort(key=lambda item: (-item["score"], item["kind"], item["title"]))
        return {
            "project": self.project_id,
            "sourceRevision": self._revision(),
            "query": clean,
            "results": candidates[:max(1, min(int(limit), 50))],
        }

    @staticmethod
    def _matches(value: Any, expected: Any) -> bool:
        if isinstance(value, list):
            return any(WorldReader._matches(item, expected) for item in value)
        if isinstance(value, dict):
            return any(WorldReader._matches(item, expected) for item in value.values())
        if isinstance(expected, list):
            return any(WorldReader._matches(value, item) for item in expected)
        if isinstance(value, str) or isinstance(expected, str):
            return str(expected).casefold() in str(value).casefold()
        return value == expected

    def query(
        self,
        *,
        kinds: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        values = []
        for item in self._items(kinds):
            detail = self.repository.entity_detail(item["entityId"])
            if not detail:
                continue
            data = detail["data"]
            data = hydrate_registered_fields(self.database, item["kind"], item["entityId"], data)
            if filters and any(not self._matches(data.get(key), expected) for key, expected in filters.items()):
                continue
            values.append({
                **item,
                "data": filter_entity_data(item["kind"], data),
                "citation": f"story-db://{self.project_id}/{item['entityId']}",
            })
        return {
            "project": self.project_id,
            "sourceRevision": self._revision(),
            "results": values[:max(1, min(int(limit), 200))],
        }

    def relationships(self, character_id: str) -> list[dict[str, Any]]:
        snapshot = self.repository.snapshot()
        names = {item["entityId"]: item["name"] for item in snapshot["characters"]}
        result = []
        for relation in snapshot["relationships"]:
            if character_id not in {relation["from"], relation["to"]}:
                continue
            is_from = relation["from"] == character_id
            other_id = relation["to"] if is_from else relation["from"]
            result.append({
                "relationshipId": relation["entityId"],
                "otherCharacterId": other_id,
                "otherCharacter": names.get(other_id, other_id),
                "label": relation.get("label") or relation.get("type") or "",
                "role": relation.get("fromRole" if is_from else "toRole") or "",
                "otherRole": relation.get("toRole" if is_from else "fromRole") or "",
                "impression": relation.get("fromImpression" if is_from else "toImpression") or "",
                "otherImpression": relation.get("toImpression" if is_from else "fromImpression") or "",
            })
        return result

    def organizations(self, character_id: str) -> list[dict[str, Any]]:
        snapshot = self.repository.snapshot()
        result = []
        for entry in snapshot["entries"]:
            if entry.get("type") != "组织":
                continue
            for member in entry.get("members", []):
                if member.get("characterId") != character_id:
                    continue
                result.append({
                    "organizationId": entry["entityId"],
                    "organization": entry["name"],
                    "role": member.get("role") or "",
                    "status": member.get("status") or "",
                })
        return result

    def appearances(self, entity_id: str) -> list[dict[str, Any]]:
        snapshot = self.repository.snapshot()
        result = []
        for plot in snapshot["plots"]:
            relation = "character" if entity_id in plot.get("people", []) else "entry" if entity_id in plot.get("entries", []) else ""
            if relation:
                result.append({
                    "entityId": plot["entityId"], "kind": "plot", "title": plot["title"],
                    "sequence": plot["sequence"], "storySortKey": plot["storySortKey"], "via": relation,
                })
        for fragment in snapshot["fragments"]:
            if entity_id in fragment.get("references", []):
                result.append({
                    "entityId": fragment["entityId"], "kind": "fragment", "title": fragment["title"],
                    "timelineStatus": "unplaced", "via": "reference",
                })
        return result

    def related(self, entity_id: str) -> dict[str, Any]:
        detail = self.repository.entity_detail(entity_id)
        if not detail:
            raise ValueError(f"内容不存在：{entity_id}")
        kind = str(detail["kind"])
        detail["data"] = hydrate_registered_fields(self.database, kind, entity_id, detail["data"])
        result: dict[str, Any] = {
            "project": self.project_id,
            "sourceRevision": self._revision(),
            "entityId": entity_id,
            "kind": kind,
        }
        if kind == "character":
            result["organizations"] = self.organizations(entity_id)
            result["relationships"] = self.relationships(entity_id)
            result["appearances"] = self.appearances(entity_id)
        elif kind == "entry":
            result["members"] = detail["data"].get("members", [])
            result["appearances"] = self.appearances(entity_id)
        elif kind == "plot":
            result["people"] = detail["data"].get("people", [])
            result["entries"] = detail["data"].get("entries", [])
            result["chapterId"] = detail["data"].get("chapterId", "")
        elif kind == "relationship":
            result["participants"] = [detail["data"].get("from"), detail["data"].get("to")]
        return result

    def entity(self, entity_id: str) -> dict[str, Any] | None:
        detail = self.repository.entity_detail(entity_id)
        if not detail:
            return None
        kind = str(detail["kind"])
        data = hydrate_registered_fields(self.database, kind, entity_id, detail["data"])
        return {
            "project": self.project_id,
            "sourceRevision": self._revision(),
            "entityId": entity_id,
            "stableId": str(detail["id"]),
            "kind": kind,
            "title": str(detail["title"]),
            "revision": int(detail["revision"]),
            **self._entity_meta(kind),
            "data": filter_entity_data(kind, data),
            "related": self.related(entity_id),
            "citation": f"story-db://{self.project_id}/{entity_id}",
        }
