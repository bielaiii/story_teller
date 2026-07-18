from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from storyteller.storage.connection import Database
from storyteller.storage.repositories import ProjectRepository


FORBIDDEN_FILENAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def safe_filename(value: str, fallback: str) -> str:
    cleaned = FORBIDDEN_FILENAME.sub("-", str(value or "").strip()).strip(". ")
    return cleaned or fallback


def markdown_document(metadata: dict[str, Any], body: str = "") -> str:
    clean = {key: value for key, value in metadata.items() if value not in (None, "", [], {})}
    frontmatter = yaml.safe_dump(
        clean,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100000,
    ).rstrip()
    content = str(body or "").rstrip()
    return f"---\n{frontmatter}\n---\n{content + chr(10) if content else ''}"


class MarkdownExporter:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id
        self.repository = ProjectRepository(database, project_id)

    def render(self) -> dict[str, bytes]:
        snapshot = self.repository.snapshot()
        files: dict[str, bytes] = {}
        project = snapshot["project"]
        chapters = snapshot["chapters"]
        manifest_meta: dict[str, Any] = {
            "title": project["title"],
            "eyebrow": project["eyebrow"],
            "chapters": [chapter["id"] for chapter in chapters],
        }
        for chapter in chapters:
            stable = chapter["id"]
            manifest_meta[f"chapter{stable[:1].upper()}{stable[1:]}"] = chapter["label"]
        manifest_meta.update(project.get("extra", {}))
        files["manifest.md"] = markdown_document(
            manifest_meta,
            "# Story Data Manifest\n\n本文件由 Story Teller Schema V3 从 SQLite 确定性导出。",
        ).encode("utf-8")

        character_names = {item["entityId"]: item["name"] for item in snapshot["characters"]}
        for item in snapshot["characters"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            metadata = {
                "id": detail["id"], "name": detail["name"], "aliases": detail["aliases"],
                "color": detail["color"], "gradient": detail["gradient"], "group": detail["group"],
                "markers": detail["markers"], "mainPlotImpact": detail["mainPlotImpact"],
                "side": detail["side"], "facts": detail["facts"], "supplements": detail["supplements"],
                "corePersona": detail["corePersona"], "supplementPersona": detail["supplementPersona"],
                "characterScope": detail["characterScope"], "narrativeRole": detail["narrativeRole"],
                "graphVisible": detail["graphVisible"],
                "references": detail.get("references", []),
            }
            metadata.update(detail.get("extra", {}))
            name = safe_filename(detail["name"], detail["id"])
            files[f"characters/{detail['id']}-{name}.md"] = markdown_document(metadata, detail["intro"]).encode("utf-8")

        chapter_stable = {item["entityId"]: item["id"] for item in chapters}
        line_names = {item["entityId"]: item["name"] for item in snapshot["timeline"]["lines"]}
        for item in snapshot["plots"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            metadata = {
                "id": int(detail["id"]) if detail["id"].isdigit() else detail["id"],
                "chapter": chapter_stable.get(detail["chapterId"], ""),
                "title": detail["title"], "summary": detail["summary"],
                "people": [value.removeprefix("character:") for value in detail["people"]],
                "entries": [value.removeprefix("entry:") for value in detail["entries"]],
                "accent": detail["accent"],
                "lanes": [line_names.get(value, value.removeprefix("timeline_line:")) for value in detail["lanes"]],
                "status": detail["status"], "tags": detail["tags"],
                "key": detail["key"], "climax": detail["climax"],
                "references": detail.get("references", []),
            }
            metadata.update(detail.get("extra", {}))
            title = safe_filename(detail["title"], detail["id"])
            prefix = f"{int(detail['id']):03d}" if detail["id"].isdigit() else safe_filename(detail["id"], "plot")
            files[f"plots/{prefix}-{title}.md"] = markdown_document(metadata, detail["body"]).encode("utf-8")

        for item in snapshot["entries"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            metadata = {
                "id": detail["id"], "name": detail["name"], "type": detail["type"],
                "subtype": detail["subtype"], "area": detail["area"], "accent": detail["accent"],
                "aliases": detail["aliases"], "tags": detail["tags"],
                "people": [value.removeprefix("character:") for value in detail["people"]],
                "status": detail["status"],
                "references": detail.get("references", []),
            }
            metadata.update(detail.get("extra", {}))
            files[f"entries/{safe_filename(detail['id'], 'entry')}.md"] = markdown_document(metadata, detail["body"]).encode("utf-8")

        for item in snapshot["fragments"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            metadata = {
                "id": detail["id"], "title": detail["title"], "status": detail["status"],
                "tags": detail["tags"], "accent": detail["accent"],
                "references": detail.get("references", []),
            }
            metadata.update(detail.get("extra", {}))
            files[f"fragments/{safe_filename(detail['id'], 'fragment')}.md"] = markdown_document(metadata, detail["body"]).encode("utf-8")

        for item in snapshot["relationships"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            from_id = detail["from"].removeprefix("character:")
            to_id = detail["to"].removeprefix("character:")
            metadata = {
                "id": detail["id"],
                "people": [
                    {"id": int(from_id) if from_id.isdigit() else from_id, "role": detail["fromRole"]},
                    {"id": int(to_id) if to_id.isdigit() else to_id, "role": detail["toRole"]},
                ],
                "label": detail["label"], "color": detail["color"], "type": detail["type"],
                "references": detail.get("references", []),
            }
            from_name = safe_filename(character_names.get(detail["from"], from_id), from_id)
            to_name = safe_filename(character_names.get(detail["to"], to_id), to_id)
            files[f"relationships/{from_id}-{from_name}__{to_id}-{to_name}.md"] = markdown_document(metadata, detail.get("body", "")).encode("utf-8")

        timeline = snapshot["timeline"]
        timeline_meta = {
            "version": 3,
            "mainLine": line_names.get(timeline["mainLineId"], timeline["mainLineId"]),
            "lineSpacing": timeline["lineSpacing"], "topPadding": timeline["topPadding"],
            "sidePadding": timeline["sidePadding"], "pixelsPerStoryUnit": timeline["pixelsPerStoryUnit"],
        }
        line_records = []
        for line in timeline["lines"]:
            record = {"name": line["name"], "color": line["color"], "side": line["side"]}
            if line["startPlotId"]:
                record["startPlotId"] = line["startPlotId"].removeprefix("plot:")
            if line["endPlotId"]:
                record["endPlotId"] = line["endPlotId"].removeprefix("plot:")
            line_records.append(record)
        timeline_body = "## Lines\n\n" + yaml.safe_dump(line_records, allow_unicode=True, sort_keys=False, width=100000).rstrip()
        files["timeline.md"] = markdown_document(timeline_meta, timeline_body).encode("utf-8")

        graph = snapshot["graph"]
        graph_settings = graph.get("settings", {})
        graph_meta = {
            "description": "人物图谱由 Schema V3 结构化数据生成。",
            "nodeSpacing": graph_settings.get("node_spacing", 116),
            "initialJitter": graph_settings.get("initial_jitter", 38),
            "relationshipDistance": graph_settings.get("relationship_distance", 250),
            "leafDistanceExtra": graph_settings.get("leaf_distance_extra", 48),
            "centerStrength": graph_settings.get("center_strength", 1),
            "groupStrength": graph_settings.get("group_strength", 1),
            "leafStrength": graph_settings.get("leaf_strength", 1),
        }
        character_stable = {item["entityId"]: item["id"] for item in snapshot["characters"]}
        graph_sections = []
        if graph["clusters"]:
            clusters = [{
                **{key: value for key, value in item.items() if key != "members"},
                "members": [character_stable.get(value, value.removeprefix("character:")) for value in item["members"]],
            } for item in graph["clusters"]]
            graph_sections.extend(["## Clusters", "", yaml.safe_dump(clusters, allow_unicode=True, sort_keys=False, width=100000).rstrip()])
        if graph["distances"]:
            distances = [{
                "from": item["from_character_id"].removeprefix("character:"),
                "to": item["to_character_id"].removeprefix("character:"),
                "distance": item["distance"], "strength": item["strength"],
            } for item in graph["distances"]]
            graph_sections.extend(["", "## Distances", "", yaml.safe_dump(distances, allow_unicode=True, sort_keys=False, width=100000).rstrip()])
        graph_nodes = []
        saved_positions = []
        for item in graph["nodes"]:
            stable = character_stable.get(item["character_id"], item["character_id"].removeprefix("character:"))
            node = {"id": stable}
            if item.get("orbit_of"):
                node["orbitOf"] = character_stable.get(item["orbit_of"], item["orbit_of"].removeprefix("character:"))
            if item.get("orbit_distance") is not None:
                node["orbitDistance"] = item["orbit_distance"]
            if item.get("orbit_angle") is not None:
                node["orbitAngle"] = item["orbit_angle"]
            if item.get("strength") is not None:
                node["strength"] = item["strength"]
            if len(node) > 1:
                graph_nodes.append(node)
            if item.get("anchor_x") is not None or item.get("anchor_y") is not None:
                saved_positions.append({"id": stable, "x": item.get("anchor_x"), "y": item.get("anchor_y")})
        if graph_nodes:
            graph_sections.extend(["", "## Nodes", "", yaml.safe_dump(graph_nodes, allow_unicode=True, sort_keys=False, width=100000).rstrip()])
        if saved_positions:
            graph_sections.extend(["", "## Saved Positions", "", yaml.safe_dump(saved_positions, allow_unicode=True, sort_keys=False, width=100000).rstrip()])
        files["graph-layout.md"] = markdown_document(graph_meta, "\n".join(graph_sections)).encode("utf-8")
        files["content-index.json"] = (json.dumps(
            {"version": 3, "snapshot": "./project.snapshot.json"},
            ensure_ascii=False, sort_keys=True, indent=2,
        ) + "\n").encode("utf-8")
        return files
