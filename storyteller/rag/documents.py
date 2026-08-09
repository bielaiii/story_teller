from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from storyteller.storage.repositories import ProjectRepository


@dataclass(frozen=True, slots=True)
class RagDocument:
    entity_id: str
    stable_id: str
    kind: str
    title: str
    revision: int
    canonical: bool
    aliases: tuple[str, ...]
    content: str
    metadata: dict[str, Any]

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RagEdge:
    source: str
    target: str
    relation_type: str
    label: str
    metadata: dict[str, Any]


def _line(label: str, value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return ""
    if isinstance(value, dict):
        rendered = "；".join(f"{key}：{item}" for key, item in value.items())
    elif isinstance(value, (list, tuple)):
        rendered = "、".join(str(item) for item in value if str(item).strip())
    else:
        rendered = str(value)
    return f"- {label}：{rendered}" if rendered else ""


def _document(title: str, kind_label: str, fields: list[str], body: str = "") -> str:
    values = [f"# {title}", "", f"- 内容类型：{kind_label}"]
    values.extend(item for item in fields if item)
    if body.strip():
        values.extend(["", body.strip()])
    return "\n".join(values).strip() + "\n"


def build_documents(repository: ProjectRepository) -> tuple[list[RagDocument], list[RagEdge], int]:
    snapshot = repository.snapshot()
    project_revision = int(snapshot["project"]["revision"])
    summaries = {
        item["entityId"]: item
        for bucket in ("characters", "plots", "entries", "fragments", "relationships", "chapters")
        for item in snapshot.get(bucket, [])
    }
    names = {
        identifier: str(item.get("name") or item.get("title") or item.get("label") or identifier)
        for identifier, item in summaries.items()
    }
    documents: list[RagDocument] = []
    edges: list[RagEdge] = []

    organization_by_character: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for entry in snapshot.get("entries", []):
        if entry.get("type") != "组织":
            continue
        for member in entry.get("members", []):
            character_id = str(member.get("characterId") or "")
            organization_by_character.setdefault(character_id, []).append((entry, member))
            metadata = {"role": member.get("role", ""), "status": member.get("status", "")}
            label = " / ".join(value for value in (str(member.get("role") or ""), str(member.get("status") or "")) if value)
            edges.append(RagEdge(character_id, entry["entityId"], "organization", label, metadata))
            edges.append(RagEdge(entry["entityId"], character_id, "member", label, metadata))

    relationships_by_character: dict[str, list[dict[str, Any]]] = {}
    for relationship in snapshot.get("relationships", []):
        from_id = relationship["from"]
        to_id = relationship["to"]
        relationships_by_character.setdefault(from_id, []).append(relationship)
        relationships_by_character.setdefault(to_id, []).append(relationship)
        label = str(relationship.get("label") or relationship.get("type") or "人物关系")
        edges.append(RagEdge(from_id, to_id, "relationship", label, {
            "role": relationship.get("fromRole", ""),
            "impression": relationship.get("fromImpression", ""),
        }))
        edges.append(RagEdge(to_id, from_id, "relationship", label, {
            "role": relationship.get("toRole", ""),
            "impression": relationship.get("toImpression", ""),
        }))
        relationship_id = str(relationship["entityId"])
        edges.extend([
            RagEdge(relationship_id, from_id, "participant", str(relationship.get("fromRole") or ""), {}),
            RagEdge(relationship_id, to_id, "participant", str(relationship.get("toRole") or ""), {}),
            RagEdge(from_id, relationship_id, "relationship_record", label, {}),
            RagEdge(to_id, relationship_id, "relationship_record", label, {}),
        ])

    for summary in summaries.values():
        identifier = str(summary["entityId"])
        detail = repository.entity_detail(identifier)
        if not detail:
            continue
        data = detail["data"]
        kind = str(detail["kind"])
        title = str(detail["title"])
        stable_id = str(detail["id"])
        revision = int(detail["revision"])
        aliases = tuple(str(item) for item in data.get("aliases", []) if str(item).strip())
        fields: list[str] = [_line("稳定 ID", stable_id)]
        body = ""
        kind_label = {
            "character": "人物", "plot": "剧情", "entry": "设定", "fragment": "碎片",
            "relationship": "人物关系", "chapter": "章节", "timeline_line": "时间线",
        }.get(kind, kind)
        metadata: dict[str, Any] = {"references": data.get("references", [])}

        if kind == "character":
            fields.extend([
                _line("别名", aliases), _line("人物定位", data.get("narrativeRole")),
                _line("人物范围", data.get("characterScope")), _line("阵营", data.get("side")),
                _line("标记", data.get("markers")), _line("人物资料", data.get("facts")),
                _line("命运大纲", data.get("destinyOutline")),
            ])
            organizations = organization_by_character.get(identifier, [])
            if organizations:
                fields.append("- 所属组织：\n" + "\n".join(
                    f"  - {entry['name']}（身份：{member.get('role') or '未填写'}；状态：{member.get('status') or '未填写'}）"
                    for entry, member in organizations
                ))
            relationships = relationships_by_character.get(identifier, [])
            if relationships:
                lines = []
                for relationship in relationships:
                    is_from = relationship["from"] == identifier
                    target = relationship["to"] if is_from else relationship["from"]
                    role = relationship.get("fromRole" if is_from else "toRole", "")
                    impression = relationship.get("fromImpression" if is_from else "toImpression", "")
                    values = "；".join(value for value in (
                        str(relationship.get("label") or relationship.get("type") or ""),
                        f"身份：{role}" if role else "",
                        f"对其看法：{impression}" if impression else "",
                    ) if value)
                    lines.append(f"  - {names.get(target, target)}：{values or '有剧情关系'}")
                fields.append("- 人物关系：\n" + "\n".join(lines))
            body_parts = [str(data.get("intro") or "")]
            body_parts.extend(str(item) for item in data.get("supplements", []))
            body = "\n\n".join(item for item in body_parts if item.strip())
        elif kind == "entry":
            fields.extend([
                _line("设定类型", data.get("type")), _line("子类型", data.get("subtype")),
                _line("区域", data.get("area")), _line("状态", data.get("status")),
                _line("别名", aliases), _line("标签", data.get("tags")),
            ])
            members = data.get("members", [])
            if members:
                fields.append("- 组织成员：\n" + "\n".join(
                    f"  - {names.get(member['characterId'], member['characterId'])}（身份：{member.get('role') or '未填写'}；状态：{member.get('status') or '未填写'}）"
                    for member in members
                ))
            body = str(data.get("body") or "")
        elif kind == "plot":
            people = [names.get(item, item) for item in data.get("people", [])]
            entries = [names.get(item, item) for item in data.get("entries", [])]
            fields.extend([
                _line("章节", names.get(str(data.get("chapterId") or ""), data.get("chapterId"))),
                _line("状态", data.get("status")), _line("概要", data.get("summary")),
                _line("出场人物", people), _line("相关设定", entries), _line("标签", data.get("tags")),
            ])
            body = str(data.get("body") or "")
            for character_id in data.get("people", []):
                edges.extend([
                    RagEdge(identifier, character_id, "appearance", "剧情出场", {}),
                    RagEdge(character_id, identifier, "plot", "相关剧情", {}),
                ])
            for entry_id in data.get("entries", []):
                edges.extend([
                    RagEdge(identifier, entry_id, "setting", "相关设定", {}),
                    RagEdge(entry_id, identifier, "plot", "相关剧情", {}),
                ])
        elif kind == "fragment":
            fields.extend([_line("状态", data.get("status")), _line("标签", data.get("tags")), _line("正式性", "灵感碎片，默认不作为正史")])
            body = str(data.get("body") or "")
        elif kind == "relationship":
            from_id, to_id = data.get("from"), data.get("to")
            fields.extend([
                _line("关系双方", [names.get(from_id, from_id), names.get(to_id, to_id)]),
                _line(f"{names.get(from_id, from_id)}的身份", data.get("fromRole")),
                _line(f"{names.get(from_id, from_id)}对对方的看法", data.get("fromImpression")),
                _line(f"{names.get(to_id, to_id)}的身份", data.get("toRole")),
                _line(f"{names.get(to_id, to_id)}对对方的看法", data.get("toImpression")),
                _line("关系名称", data.get("label")), _line("关系类型", data.get("type")),
            ])
            body = str(data.get("body") or "")
        elif kind == "chapter":
            fields.extend([_line("章节名称", data.get("label")), _line("排序键", data.get("sortKey"))])
        else:
            body = json.dumps(data, ensure_ascii=False, indent=2)

        references = [str(item) for item in data.get("references", [])]
        for target in references:
            fields.append(_line("正文引用", names.get(target, target)))
            edges.append(RagEdge(identifier, target, "reference", "正文引用", {}))
            edges.append(RagEdge(target, identifier, "referenced_by", "被正文引用", {}))
        content = _document(title, kind_label, fields, body)
        documents.append(RagDocument(
            entity_id=identifier, stable_id=stable_id, kind=kind, title=title,
            revision=revision, canonical=kind != "fragment", aliases=aliases,
            content=content, metadata=metadata,
        ))
    return documents, edges, project_revision


def chunk_document(document: RagDocument, max_chars: int = 1400, overlap: int = 160) -> list[str]:
    content = document.content.strip()
    if len(content) <= max_chars:
        return [content]
    header = f"# {document.title}\n\n"
    body = content[len(header):] if content.startswith(header) else content
    chunks: list[str] = []
    start = 0
    while start < len(body):
        end = min(len(body), start + max_chars - len(header))
        if end < len(body):
            boundary = max(body.rfind("\n\n", start, end), body.rfind("\n", start, end))
            if boundary > start + (max_chars // 2):
                end = boundary
        chunks.append((header + body[start:end].strip()).strip())
        if end >= len(body):
            break
        start = max(start + 1, end - overlap)
    return chunks


def lexical_tokens(text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").lower())
    tokens = re.findall(r"[a-z0-9_:-]{2,}|[\u3400-\u9fff]+", normalized)
    result: list[str] = []
    for token in tokens:
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            if len(token) == 1:
                result.append(token)
            else:
                result.extend(token[index:index + 2] for index in range(len(token) - 1))
                result.extend(token[index:index + 3] for index in range(max(0, len(token) - 2)))
        else:
            result.append(token)
    return " ".join(dict.fromkeys(result))
