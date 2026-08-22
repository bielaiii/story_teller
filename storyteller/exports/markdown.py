from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from storyteller.domain.world_schema import exportable_metadata, hydrate_registered_fields, registry_json_bytes
from storyteller.exports.version import EXPORT_FORMAT_VERSION
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
            "# Story Data Manifest\n\n本文件由 Story Teller 从当前 SQLite 结构化数据确定性导出。",
        ).encode("utf-8")

        character_names = {item["entityId"]: item["name"] for item in snapshot["characters"]}
        for item in snapshot["characters"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            detail = hydrate_registered_fields(self.database, "character", item["entityId"], detail)
            metadata = {
                "id": detail["id"], "name": detail["name"], "aliases": detail["aliases"],
                "color": detail["color"], "gradient": detail["gradient"], "group": detail["group"],
                "markers": detail["markers"], "mainPlotImpact": detail["mainPlotImpact"],
                "side": detail["side"], "facts": detail["facts"], "supplements": detail["supplements"],
                "corePersona": detail["corePersona"], "supplementPersona": detail["supplementPersona"],
                "destinyOutline": detail["destinyOutline"],
                "characterScope": detail["characterScope"], "narrativeRole": detail["narrativeRole"],
                "references": detail.get("references", []),
            }
            metadata.update(detail.get("extra", {}))
            for key, value in exportable_metadata("character", detail).items():
                metadata.setdefault(key, value)
            name = safe_filename(detail["name"], detail["id"])
            files[f"characters/{detail['id']}-{name}.md"] = markdown_document(metadata, detail["intro"]).encode("utf-8")

        line_names = {item["entityId"]: item["name"] for item in snapshot["timeline"]["lines"]}
        for item in snapshot["plots"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            detail = hydrate_registered_fields(self.database, "plot", item["entityId"], detail)
            metadata = {
                "chapterNumber": detail.get("chapterNumber"),
                "stories": [line_names.get(value, value.removeprefix("timeline_line:")) for value in (detail.get("stories") or detail.get("lanes", []))],
                "summary": detail["summary"],
                "status": detail["status"], "tags": detail["tags"],
                "key": detail["key"], "climax": detail["climax"],
            }
            metadata.update(detail.get("extra", {}))
            for key, value in exportable_metadata("plot", detail).items():
                metadata.setdefault(key, value)
            title = safe_filename(detail["title"], detail["id"])
            files[f"plots/{title}.md"] = markdown_document(metadata, detail["body"]).encode("utf-8")

        for item in snapshot["entries"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            detail = hydrate_registered_fields(self.database, "entry", item["entityId"], detail)
            metadata = {
                "id": detail["id"], "name": detail["name"], "type": detail["type"],
                "subtype": detail["subtype"], "area": detail["area"], "accent": detail["accent"],
                "aliases": detail["aliases"], "tags": detail["tags"],
                "people": [value.removeprefix("character:") for value in detail["people"]],
                "members": [
                    {
                        "id": member["characterId"].removeprefix("character:"),
                        "role": member["role"],
                        "status": member["status"],
                    }
                    for member in detail.get("members", [])
                ],
                "status": detail["status"],
                "references": detail.get("references", []),
            }
            metadata.update(detail.get("extra", {}))
            for key, value in exportable_metadata("entry", detail).items():
                metadata.setdefault(key, value)
            files[f"entries/{safe_filename(detail['id'], 'entry')}.md"] = markdown_document(metadata, detail["body"]).encode("utf-8")

        fragment_details = {
            item["entityId"]: hydrate_registered_fields(
                self.database,
                "fragment",
                item["entityId"],
                self.repository.entity_detail(item["entityId"])["data"],
            )
            for item in snapshot["fragments"]
        }
        for detail in fragment_details.values():
            if detail.get("fragmentType") == "line":
                directory = safe_filename(detail["title"], detail["id"])
                files[f"fragments/{directory}/_story.md"] = markdown_document(
                    {"tags": detail["tags"], "key": detail["key"], "climax": detail["climax"]},
                    detail.get("body", ""),
                ).encode("utf-8")
                continue
            parent = fragment_details.get(str(detail.get("parentFragmentId"))) if detail.get("parentFragmentId") else None
            metadata = {
                "story": parent["title"] if parent else None,
                "order": detail.get("fragmentOrder", 0),
                "chapterNumber": detail.get("chapterNumber"),
                "tags": detail["tags"], "key": detail["key"], "climax": detail["climax"],
            }
            metadata.update(detail.get("extra", {}))
            for key, value in exportable_metadata("fragment", detail).items():
                metadata.setdefault(key, value)
            directory = f"{safe_filename(parent['title'], parent['id'])}/" if parent else ""
            files[f"fragments/{directory}{safe_filename(detail['title'], detail['id'])}.md"] = markdown_document(metadata, detail.get("body", "")).encode("utf-8")

        for item in snapshot["relationships"]:
            detail = self.repository.entity_detail(item["entityId"])["data"]
            detail = hydrate_registered_fields(self.database, "relationship", item["entityId"], detail)
            from_id = detail["from"].removeprefix("character:")
            to_id = detail["to"].removeprefix("character:")
            metadata = {
                "id": detail["id"],
                "people": [
                    {
                        "id": int(from_id) if from_id.isdigit() else from_id,
                        "role": detail["fromRole"],
                        "impression": detail["fromImpression"],
                    },
                    {
                        "id": int(to_id) if to_id.isdigit() else to_id,
                        "role": detail["toRole"],
                        "impression": detail["toImpression"],
                    },
                ],
                "graphScope": detail["graphScope"],
                "graphLineMode": detail["graphLineMode"],
                "label": detail["label"], "color": detail["color"], "type": detail["type"],
                "references": detail.get("references", []),
            }
            for key, value in exportable_metadata("relationship", detail).items():
                metadata.setdefault(key, value)
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
            "description": "人物图谱由当前 SQLite 结构化数据生成。",
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
        files["world-schema.json"] = registry_json_bytes()
        ai_manifest = {
            "version": EXPORT_FORMAT_VERSION,
            "project": project["id"],
            "title": project["title"],
            "sourceRevision": project["revision"],
            "sourceOfTruth": "./story.db",
            "readOnlyExports": {
                "schema": "./world-schema.json",
                "snapshot": "./project.snapshot.json",
                "recovery": "./recovery.snapshot.json",
                "characters": "./characters/",
                "plots": "./plots/",
                "entries": "./entries/",
                "fragments": "./fragments/",
                "relationships": "./relationships/",
            },
            "aiGateway": {
                "stdioCommand": ["story-world-mcp"],
                "hubMcp": "http://127.0.0.1:4188/mcp/",
                "workspaceSelection": "Hub 工具会动态提供 workspace 与 project 选项；project 省略时优先匹配同名 workspace，否则单项目自动选中",
                "recommendedFlow": [
                    "list_world_workspaces", "list_world_projects", "describe_world", "world_catalog", "resolve_world_entity",
                    "query_world", "get_world_entity", "get_related_world",
                    "search_world", "build_world_context",
                ],
            },
            "contentPolicy": {
                "fragment": {
                    "certainty": "confirmed",
                    "timelineStatus": "unplaced",
                    "searchByDefault": True,
                    "description": "已确定会进入故事，但尚未正式编入时间线。",
                }
            },
            "entityCounts": {
                "character": len(snapshot["characters"]),
                "plot": len(snapshot["plots"]),
                "entry": len(snapshot["entries"]),
                "fragment": len(snapshot["fragments"]),
                "relationship": len(snapshot["relationships"]),
                "chapter": len(snapshot["chapters"]),
            },
        }
        files["ai-manifest.json"] = (
            json.dumps(ai_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        files["AI_CONTEXT.md"] = (
            f"# {project['title']} · AI 数据入口\n\n"
            f"当前数据 revision：{project['revision']}。`story.db` 是唯一可写事实来源；本目录 Markdown 与 JSON 均为只读导出。\n\n"
            "读取顺序：先读 `world-schema.json` 理解实体语义，再读 `ai-manifest.json` 和 "
            "`project.snapshot.json`；本地 AI 可使用 stdio 命令 `story-world-mcp`，也可连接统一 Hub "
            "`http://127.0.0.1:4188/mcp/`。使用 Hub 时先调用 `list_world_workspaces` 选择当前仓库。\n\n"
            "组织归属、双方印象和剧情出场等精确事实应优先使用 MCP 的结构化工具；需要联想或按语义找资料时再使用 RAG。\n\n"
            "碎片是已确定但尚未编入时间线的剧情，默认应参与检索和创作上下文，不要把它解释为废弃或非正史。\n"
        ).encode("utf-8")
        files["content-index.json"] = (json.dumps(
            {
                "version": 4,
                "exportFormatVersion": EXPORT_FORMAT_VERSION,
                "snapshot": "./project.snapshot.json",
                "worldSchema": "./world-schema.json",
                "aiManifest": "./ai-manifest.json",
                "aiContext": "./AI_CONTEXT.md",
            },
            ensure_ascii=False, sort_keys=True, indent=2,
        ) + "\n").encode("utf-8")
        return files
