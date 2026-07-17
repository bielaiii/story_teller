from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from storyteller.storage.connection import Database, schema_version
from storyteller.storage.schema import initialize_schema


FRONTMATTER = re.compile(r"^---\n(?P<meta>[\s\S]*?)\n---(?:\n|$)")
HEX_FIELD = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:color|accent)\s*:\s*)(?P<value>#[0-9a-fA-F]{6})\s*$"
)
GRADIENT_FIELD = re.compile(r"(?m)^(?P<prefix>[ \t]*gradient\s*:\s*)(?P<value>[^\n]+)$")
RETENTION_SECONDS = 7 * 24 * 60 * 60
RANK_STEP = 10**12


def entity_id(kind: str, stable_id: object) -> str:
    return f"{kind}:{str(stable_id).strip()}"


def sort_key(value: object, fallback: int = 0) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(fallback)
    return f"{number:024d}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        clean = str(item).strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def clean_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip()}


def clean_persona_items(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        content = str(item.get("value") or "").strip()
        if key and content:
            result.append({"key": key, "value": content})
    return result


def normalize_color(value: Any, fallback: str = "#7d6bd6") -> str:
    clean = str(value or "").strip()
    return clean.lower() if re.fullmatch(r"#[0-9a-fA-F]{6}", clean) else fallback


def prepare_yaml(source: str) -> str:
    quoted_colors = HEX_FIELD.sub(
        lambda item: f"{item.group('prefix')}\"{item.group('value')}\"", source
    )

    def quote_gradient(item: re.Match[str]) -> str:
        raw = item.group("value").strip()
        if raw.startswith(("\"", "'")):
            return item.group(0)
        return f"{item.group('prefix')}{json.dumps(raw, ensure_ascii=False)}"

    return GRADIENT_FIELD.sub(quote_gradient, quoted_colors)


@dataclass(frozen=True, slots=True)
class MarkdownDocument:
    path: str
    metadata: dict[str, Any]
    body: str
    raw: str
    deleted_at: int | None = None
    root_delete_kind: str = ""

    @property
    def stable_id(self) -> str:
        return str(self.metadata.get("id", "")).strip()


def parse_markdown(path: str, raw: str, *, deleted_at: int | None = None, root_delete_kind: str = "") -> MarkdownDocument:
    match = FRONTMATTER.match(raw)
    if not match:
        return MarkdownDocument(path, {}, raw, raw, deleted_at, root_delete_kind)
    metadata_source = prepare_yaml(match.group("meta"))
    loaded = yaml.safe_load(metadata_source) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} 的 frontmatter 必须是键值对象")
    return MarkdownDocument(
        path=path,
        metadata={str(key): value for key, value in loaded.items()},
        body=raw[match.end() :].rstrip("\n"),
        raw=raw,
        deleted_at=deleted_at,
        root_delete_kind=root_delete_kind,
    )


def parse_yaml_list_section(body: str, heading: str) -> list[dict[str, Any]]:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*\n(?P<body>.*?)(?=^## |\Z)", body
    )
    if not match:
        return []
    source = match.group("body").strip()
    if not source:
        return []
    loaded = yaml.safe_load(prepare_yaml(source)) or []
    return [item for item in loaded if isinstance(item, dict)] if isinstance(loaded, list) else []


def document_kind(path: str) -> str:
    root = Path(path).parts[0] if Path(path).parts else ""
    return {
        "characters": "character",
        "plots": "plot",
        "entries": "entry",
        "fragments": "fragment",
        "relationships": "relationship",
    }.get(root, "")


class LegacySnapshot:
    """Read-only, fully parsed view of a legacy document database."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path).resolve()
        connection = sqlite3.connect(
            f"file:{self.database_path.as_posix()}?mode=ro", uri=True
        )
        try:
            connection.row_factory = sqlite3.Row
            self.version = schema_version(connection)
            if self.version not in {1, 2}:
                raise ValueError(f"只支持迁移 Schema V1/V2，当前为 V{self.version}")
            self.metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            self.documents = {
                str(row["path"]): bytes(row["content"]).decode("utf-8")
                for row in connection.execute("SELECT path, content FROM documents ORDER BY path")
            }
            self.transactions = self._read_transactions(connection)
        finally:
            connection.close()

    @staticmethod
    def _read_transactions(connection: sqlite3.Connection) -> list[dict[str, Any]]:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transaction_changes'"
        ).fetchone()
        if not table:
            return []
        columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
        if "expires_at" not in columns:
            return []
        result = []
        for row in connection.execute("SELECT * FROM transactions ORDER BY id"):
            item = dict(row)
            item["changes"] = [
                {
                    "path": str(change["path"]),
                    "before": bytes(change["before_content"]).decode("utf-8")
                    if change["before_content"] is not None else None,
                    "after": bytes(change["after_content"]).decode("utf-8")
                    if change["after_content"] is not None else None,
                }
                for change in connection.execute(
                    "SELECT * FROM transaction_changes WHERE transaction_id=? ORDER BY path",
                    (row["id"],),
                )
            ]
            result.append(item)
        return result

    def active_documents(self) -> dict[str, MarkdownDocument]:
        return {
            path: parse_markdown(path, raw)
            for path, raw in self.documents.items()
            if path.endswith(".md") and not path.startswith(".trash/")
        }

    def deleted_documents(self) -> tuple[list[MarkdownDocument], list[MarkdownDocument]]:
        roots: list[MarkdownDocument] = []
        dependencies: list[MarkdownDocument] = []
        for path, raw in self.documents.items():
            if path.startswith(".trash/plots/") and path.endswith(".md"):
                timestamp = Path(path).name.split("-", 1)[0]
                if timestamp.isdigit():
                    roots.append(parse_markdown(path, raw, deleted_at=int(timestamp), root_delete_kind="plot"))
                continue
            if not path.startswith(".trash/records/") or not path.endswith(".json"):
                continue
            try:
                bundle = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError(f"回收站记录损坏：{path}") from error
            kind = str(bundle.get("kind", "")).strip()
            deleted_at = int(bundle.get("deletedAt", 0) or 0)
            files = bundle.get("files", []) if isinstance(bundle.get("files"), list) else []
            root_found = False
            for file_item in files:
                if not isinstance(file_item, dict):
                    continue
                file_path = str(file_item.get("path", ""))
                content = str(file_item.get("content", ""))
                file_kind = document_kind(file_path)
                is_root = not root_found and file_kind == kind
                parsed = parse_markdown(
                    file_path,
                    content,
                    deleted_at=deleted_at if is_root else None,
                    root_delete_kind=kind if is_root else "",
                )
                (roots if is_root else dependencies).append(parsed)
                root_found = root_found or is_root
            if not root_found:
                raise ValueError(f"回收站记录缺少根实体：{path}")
        return roots, dependencies

    def reference_sources_before_deletion(self) -> list[MarkdownDocument]:
        result: list[MarkdownDocument] = []
        for path, raw in self.documents.items():
            if not path.startswith(".trash/records/") or not path.endswith(".json"):
                continue
            bundle = json.loads(raw)
            for patch in bundle.get("patches", []):
                if not isinstance(patch, dict) or not str(patch.get("path", "")).endswith(".md"):
                    continue
                before = patch.get("before")
                if isinstance(before, str):
                    result.append(parse_markdown(str(patch["path"]), before))
        return result


class V3Migrator:
    def __init__(self, source_database: Path, project_id: str):
        self.source = LegacySnapshot(source_database)
        self.project_id = str(project_id).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", self.project_id):
            raise ValueError("项目 ID 不合法")
        self.now = int(time.time())
        self.body_hashes: dict[str, str] = {}
        self.body_records: dict[str, tuple[str, str, str]] = {}
        self.plot_sort_keys: dict[str, str] = {}
        self.warnings: list[str] = []

    def migrate_to(self, target_database: Path) -> dict[str, Any]:
        target = Path(target_database).resolve()
        if target.exists():
            raise FileExistsError(f"目标数据库已经存在：{target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            initialize_schema(connection)
            connection.commit()
            connection.execute("BEGIN IMMEDIATE")
            active = self.source.active_documents()
            deleted_roots, dependency_documents = self.source.deleted_documents()
            self._insert_project(connection, active.get("manifest.md"))
            self._insert_chapters(connection, active.get("manifest.md"))

            all_documents = list(active.values()) + deleted_roots + dependency_documents
            by_kind = {
                kind: [doc for doc in all_documents if (doc.root_delete_kind or document_kind(doc.path)) == kind]
                for kind in ("character", "entry", "fragment", "plot", "relationship")
            }
            ordered_plots = sorted(
                by_kind["plot"],
                key=lambda document: (
                    int(document.metadata.get("sequence", document.metadata.get("id", 0)) or 0),
                    0 if document.deleted_at else 1,
                    int(document.deleted_at or 0),
                    str(document.metadata.get("id", "")),
                ),
            )
            self.plot_sort_keys = {
                document.path: sort_key(index * RANK_STEP)
                for index, document in enumerate(ordered_plots, start=1)
            }
            for document in by_kind["character"]:
                self._insert_character(connection, document)
            for document in by_kind["entry"]:
                self._insert_entry(connection, document)
            for document in by_kind["fragment"]:
                self._insert_fragment(connection, document)
            for index, document in enumerate(by_kind["plot"], start=1):
                self._insert_plot(connection, document, index)

            reference_documents = list(active.values()) + self.source.reference_sources_before_deletion()
            self._insert_plot_references(connection, reference_documents)
            self._insert_entry_references(connection, reference_documents)
            self._insert_stable_references(connection, reference_documents)
            for document in by_kind["relationship"]:
                self._insert_relationship(connection, document)

            self._insert_timeline(connection, active.get("timeline.md"), by_kind["plot"])
            self._insert_graph(connection, active.get("graph-layout.md"), by_kind["character"])
            self._insert_legacy_operations(connection)
            revision = int(connection.execute(
                "SELECT revision FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()[0])
            connection.execute(
                "INSERT INTO export_state(project_id, requested_revision, exported_revision, status, updated_at) VALUES(?, ?, 0, 'pending', ?)",
                (self.project_id, revision, self.now),
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('migrated_from_sha256', ?)",
                (file_sha256(self.source.database_path),),
            )
            violations = [tuple(row) for row in connection.execute("PRAGMA foreign_key_check")]
            if violations:
                raise ValueError(f"迁移后的数据库存在外键错误：{violations[:5]}")
            connection.commit()
            report = self._report(connection, target)
        except Exception:
            connection.rollback()
            connection.close()
            target.unlink(missing_ok=True)
            raise
        connection.close()
        return report

    def _insert_project(self, connection: sqlite3.Connection, manifest: MarkdownDocument | None) -> None:
        metadata = manifest.metadata if manifest else {}
        title = str(metadata.get("title") or self.project_id)
        eyebrow = str(metadata.get("eyebrow") or "Story Teller")
        extra = {key: value for key, value in metadata.items() if key not in {"title", "eyebrow", "chapters"} and not key.startswith("chapter")}
        connection.execute(
            "INSERT INTO projects(id, title, eyebrow, extra_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
            (self.project_id, title, eyebrow, json_text(extra), self.now, self.now),
        )

    def _insert_entity(
        self,
        connection: sqlite3.Connection,
        kind: str,
        stable_id: object,
        title: object,
        document: MarkdownDocument,
        extra: dict[str, Any],
    ) -> str:
        stable = str(stable_id).strip()
        if not stable:
            raise ValueError(f"{document.path} 缺少稳定 ID")
        identifier = entity_id(kind, stable)
        deleted_at = document.deleted_at
        purge_at = deleted_at + RETENTION_SECONDS if deleted_at else None
        connection.execute(
            """
            INSERT INTO entities(
                id, project_id, kind, stable_id, title, deleted_at, purge_at,
                extra_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier, self.project_id, kind, stable, str(title or stable),
                deleted_at, purge_at, json_text(extra), self.now, self.now,
            ),
        )
        return identifier

    def _insert_chapters(self, connection: sqlite3.Connection, manifest: MarkdownDocument | None) -> None:
        metadata = manifest.metadata if manifest else {}
        chapters = clean_list(metadata.get("chapters")) or ["act1"]
        for index, stable in enumerate(chapters, start=1):
            label = str(metadata.get(f"chapter{stable[:1].upper()}{stable[1:]}") or stable)
            doc = manifest or MarkdownDocument("manifest.md", {}, "", "")
            identifier = self._insert_entity(connection, "chapter", stable, label, doc, {})
            connection.execute(
                "INSERT INTO chapters(entity_id, label, sort_key) VALUES(?, ?, ?)",
                (identifier, label, sort_key(index * RANK_STEP)),
            )

    def _insert_character(self, connection: sqlite3.Connection, document: MarkdownDocument) -> None:
        data = document.metadata
        known = {
            "id", "name", "aliases", "color", "gradient", "group", "markers", "mainPlotImpact",
            "side", "facts", "supplements", "events", "characterScope", "narrativeRole", "graphVisible", "x", "y",
            "references", "corePersona", "supplementPersona",
        }
        markers = clean_list(data.get("markers"))
        narrative_role = str(data.get("narrativeRole") or ("主角" if any(item in {"主角", "男主", "女主"} for item in markers) else "配角"))
        scope = str(data.get("characterScope") or "常驻人物")
        side = str(data.get("side") or ("反派方" if "反派" in markers else "主角方" if any(item in {"主角", "主角团", "正派"} for item in markers) else "中立"))
        if narrative_role not in {"主角", "配角"}:
            narrative_role = "配角"
        if scope not in {"主线人物", "常驻人物", "待定角色", "一次性角色"}:
            scope = "常驻人物"
        if side not in {"主角方", "中立", "反派方"}:
            side = "中立"
        extra = {key: value for key, value in data.items() if key not in known}
        core_persona = clean_persona_items(data.get("corePersona"))
        supplement_persona = clean_persona_items(data.get("supplementPersona"))
        if core_persona or supplement_persona:
            extra["characterPersona"] = {
                "core": core_persona,
                "supplement": supplement_persona,
            }
        identifier = self._insert_entity(
            connection, "character", data.get("id"), data.get("name"), document,
            extra,
        )
        impact = max(0, min(100, int(data.get("mainPlotImpact", 0) or 0)))
        connection.execute(
            """
            INSERT INTO characters(
                entity_id, name, intro_markdown, narrative_role, character_scope,
                side, main_plot_impact, color, gradient, group_name, graph_visible
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier, str(data.get("name") or data.get("id")), document.body,
                narrative_role, scope, side, impact, normalize_color(data.get("color")),
                str(data.get("gradient") or ""), str(data.get("group") or ""),
                None if data.get("graphVisible") is None else int(bool(data.get("graphVisible"))),
            ),
        )
        self._insert_values(connection, "character_aliases", "character_id", identifier, "alias", clean_list(data.get("aliases")))
        self._insert_values(connection, "character_markers", "character_id", identifier, "marker", markers)
        for position, (key, value) in enumerate(clean_mapping(data.get("facts")).items()):
            connection.execute(
                "INSERT INTO character_facts(character_id, fact_key, fact_value, position) VALUES(?, ?, ?, ?)",
                (identifier, key, value, position),
            )
        supplements = data.get("supplements", [])
        if isinstance(supplements, str):
            supplements = [line for line in supplements.splitlines() if line.strip()]
        for position, value in enumerate(clean_list(supplements)):
            connection.execute(
                "INSERT INTO character_supplements(character_id, content, position) VALUES(?, ?, ?)",
                (identifier, value, position),
            )
        self._remember_body(document, "characters", "intro_markdown", identifier)

    def _insert_entry(self, connection: sqlite3.Connection, document: MarkdownDocument) -> None:
        data = document.metadata
        known = {"id", "name", "type", "subtype", "area", "accent", "aliases", "tags", "people", "plots", "status", "references"}
        identifier = self._insert_entity(
            connection, "entry", data.get("id"), data.get("name"), document,
            {key: value for key, value in data.items() if key not in known},
        )
        connection.execute(
            "INSERT INTO entries(entity_id, name, type, subtype, area, body_markdown, status, accent) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identifier, str(data.get("name") or data.get("id")), str(data.get("type") or "其他"),
                str(data.get("subtype") or ""), str(data.get("area") or ""), document.body,
                str(data.get("status") or ""), normalize_color(data.get("accent")),
            ),
        )
        self._insert_values(connection, "entry_aliases", "entry_id", identifier, "alias", clean_list(data.get("aliases")))
        self._insert_values(connection, "entry_tags", "entry_id", identifier, "tag", clean_list(data.get("tags")))
        self._remember_body(document, "entries", "body_markdown", identifier)

    def _insert_fragment(self, connection: sqlite3.Connection, document: MarkdownDocument) -> None:
        data = document.metadata
        known = {"id", "title", "status", "accent", "tags", "references"}
        identifier = self._insert_entity(
            connection, "fragment", data.get("id"), data.get("title"), document,
            {key: value for key, value in data.items() if key not in known},
        )
        connection.execute(
            "INSERT INTO fragments(entity_id, body_markdown, status, accent) VALUES(?, ?, ?, ?)",
            (identifier, document.body, str(data.get("status") or ""), normalize_color(data.get("accent"))),
        )
        self._insert_values(connection, "fragment_tags", "fragment_id", identifier, "tag", clean_list(data.get("tags")))
        self._remember_body(document, "fragments", "body_markdown", identifier)

    def _insert_plot(self, connection: sqlite3.Connection, document: MarkdownDocument, fallback: int) -> None:
        data = document.metadata
        known = {"id", "sequence", "chapter", "title", "summary", "people", "entries", "accent", "lanes", "status", "tags", "key", "climax", "references"}
        identifier = self._insert_entity(
            connection, "plot", data.get("id"), data.get("title"), document,
            {key: value for key, value in data.items() if key not in known},
        )
        chapter = entity_id("chapter", data.get("chapter") or "act1")
        if not connection.execute("SELECT 1 FROM chapters WHERE entity_id=?", (chapter,)).fetchone():
            chapter = None
            self.warnings.append(f"{document.path} 引用的篇章不存在，已迁入未安排区域")
        connection.execute(
            """
            INSERT INTO plots(entity_id, chapter_id, sort_key, summary, body_markdown, status, accent, is_key, is_climax)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier, chapter, self.plot_sort_keys.get(document.path, sort_key(fallback * RANK_STEP)),
                str(data.get("summary") or ""), document.body, str(data.get("status") or "草稿"),
                normalize_color(data.get("accent")), int(bool(data.get("key"))), int(bool(data.get("climax"))),
            ),
        )
        self._insert_values(connection, "plot_tags", "plot_id", identifier, "tag", clean_list(data.get("tags")))
        self._remember_body(document, "plots", "body_markdown", identifier)

    @staticmethod
    def _insert_values(
        connection: sqlite3.Connection,
        table: str,
        owner_column: str,
        owner_id: str,
        value_column: str,
        values: Iterable[str],
    ) -> None:
        for position, value in enumerate(values):
            connection.execute(
                f"INSERT OR IGNORE INTO {table}({owner_column}, {value_column}, position) VALUES(?, ?, ?)",
                (owner_id, value, position),
            )

    def _insert_plot_references(self, connection: sqlite3.Connection, documents: list[MarkdownDocument]) -> None:
        for document in documents:
            if document_kind(document.path) != "plot":
                continue
            plot_id = entity_id("plot", document.metadata.get("id"))
            if not connection.execute("SELECT 1 FROM plots WHERE entity_id=?", (plot_id,)).fetchone():
                continue
            for stable in clean_list(document.metadata.get("people")):
                character_id = entity_id("character", stable)
                if connection.execute("SELECT 1 FROM characters WHERE entity_id=?", (character_id,)).fetchone():
                    connection.execute(
                        "INSERT OR IGNORE INTO plot_characters(plot_id, character_id) VALUES(?, ?)",
                        (plot_id, character_id),
                    )
            for stable in clean_list(document.metadata.get("entries")):
                entry_id = entity_id("entry", stable)
                if connection.execute("SELECT 1 FROM entries WHERE entity_id=?", (entry_id,)).fetchone():
                    connection.execute(
                        "INSERT OR IGNORE INTO plot_entries(plot_id, entry_id) VALUES(?, ?)",
                        (plot_id, entry_id),
                    )

    def _insert_entry_references(self, connection: sqlite3.Connection, documents: list[MarkdownDocument]) -> None:
        for document in documents:
            if document_kind(document.path) != "entry":
                continue
            entry_id = entity_id("entry", document.metadata.get("id"))
            if not connection.execute("SELECT 1 FROM entries WHERE entity_id=?", (entry_id,)).fetchone():
                continue
            for stable in clean_list(document.metadata.get("people")):
                character_id = entity_id("character", stable)
                if connection.execute("SELECT 1 FROM characters WHERE entity_id=?", (character_id,)).fetchone():
                    connection.execute(
                        "INSERT OR IGNORE INTO entry_characters(entry_id, character_id) VALUES(?, ?)",
                        (entry_id, character_id),
                    )

    def _insert_stable_references(
        self, connection: sqlite3.Connection, documents: list[MarkdownDocument]
    ) -> None:
        """Preserve legacy metadata links as normalized stable references."""
        for document in documents:
            kind = document.root_delete_kind or document_kind(document.path)
            if kind not in {"character", "plot", "entry", "fragment", "relationship"}:
                continue
            source_id = entity_id(kind, document.metadata.get("id"))
            if not connection.execute("SELECT 1 FROM entities WHERE id=?", (source_id,)).fetchone():
                continue
            targets: list[str] = []
            if kind == "character":
                targets.extend(entity_id("plot", value) for value in clean_list(document.metadata.get("events")))
            elif kind == "plot":
                targets.extend(entity_id("character", value) for value in clean_list(document.metadata.get("people")))
                targets.extend(entity_id("entry", value) for value in clean_list(document.metadata.get("entries")))
            elif kind == "entry":
                targets.extend(entity_id("character", value) for value in clean_list(document.metadata.get("people")))
                targets.extend(entity_id("plot", value) for value in clean_list(document.metadata.get("plots")))
            targets.extend(
                value for value in clean_list(document.metadata.get("references"))
                if ":" in value
            )
            for target_id in dict.fromkeys(targets):
                if target_id == source_id or not connection.execute(
                    "SELECT 1 FROM entities WHERE id=?", (target_id,)
                ).fetchone():
                    continue
                if connection.execute(
                    """
                    SELECT 1 FROM entity_references
                    WHERE source_entity_id=? AND target_entity_id=? AND context='body' AND marker=?
                    """,
                    (source_id, target_id, target_id),
                ).fetchone():
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO entity_references(
                        source_entity_id, target_entity_id, context, marker, source
                    ) VALUES(?, ?, 'body', ?, 'migration')
                    """,
                    (source_id, target_id, target_id),
                )

                # Some old packages kept reverse character/entry plot lists even
                # when the plot frontmatter was incomplete. Keep the normalized
                # relation authoritative in both directions after migration.
                if kind == "character" and target_id.startswith("plot:"):
                    connection.execute(
                        "INSERT OR IGNORE INTO plot_characters(plot_id, character_id) VALUES(?, ?)",
                        (target_id, source_id),
                    )
                elif kind == "entry" and target_id.startswith("plot:"):
                    connection.execute(
                        "INSERT OR IGNORE INTO plot_entries(plot_id, entry_id) VALUES(?, ?)",
                        (target_id, source_id),
                    )

    def _insert_relationship(self, connection: sqlite3.Connection, document: MarkdownDocument) -> None:
        data = document.metadata
        people = data.get("people")
        if isinstance(people, list) and len(people) == 2 and all(isinstance(item, dict) for item in people):
            endpoints = [str(item.get("id", "")).strip() for item in people]
            roles = [str(item.get("role", "")) for item in people]
        else:
            endpoints = [str(data.get("from", "")).strip(), str(data.get("to", "")).strip()]
            roles = [str(data.get("fromRole", "")), str(data.get("toRole", ""))]
        if len(endpoints) != 2 or not all(endpoints):
            raise ValueError(f"{document.path} 的人物关系端点不完整")
        from_id, to_id = (entity_id("character", value) for value in endpoints)
        if not all(connection.execute("SELECT 1 FROM characters WHERE entity_id=?", (value,)).fetchone() for value in (from_id, to_id)):
            raise ValueError(f"{document.path} 引用了不存在的人物")
        stable = "__".join(endpoints)
        known = {"id", "people", "from", "to", "fromRole", "toRole", "label", "color", "type", "references"}
        identifier = self._insert_entity(
            connection, "relationship", stable, data.get("label") or stable, document,
            {key: value for key, value in data.items() if key not in known},
        )
        connection.execute(
            """
            INSERT INTO relationships(
                entity_id, from_character_id, to_character_id, from_role, to_role,
                label, type, color, body_markdown
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier, from_id, to_id, roles[0], roles[1], str(data.get("label") or ""),
                str(data.get("type") or ""), normalize_color(data.get("color"), "#8b95a7"), document.body,
            ),
        )
        self._remember_body(document, "relationships", "body_markdown", identifier)

    def _insert_timeline(
        self,
        connection: sqlite3.Connection,
        timeline: MarkdownDocument | None,
        plots: list[MarkdownDocument],
    ) -> None:
        metadata = timeline.metadata if timeline else {}
        configured_lines = parse_yaml_list_section(timeline.body, "Lines") if timeline else []
        lane_names: list[str] = []
        for document in plots:
            for lane in clean_list(document.metadata.get("lanes")):
                if lane not in lane_names:
                    lane_names.append(lane)
        main_line = str(metadata.get("mainLine") or (lane_names[0] if lane_names else "主线"))
        if main_line not in lane_names:
            lane_names.insert(0, main_line)
        palette = clean_list(metadata.get("palette")) or ["#3f7fc1", "#d65f8f", "#3ba878", "#df8d35"]
        line_by_name = {str(item.get("name", "")): item for item in configured_lines}
        for item in configured_lines:
            name = str(item.get("name", "")).strip()
            if name and name not in lane_names:
                lane_names.append(name)
        for index, name in enumerate(lane_names, start=1):
            item = line_by_name.get(name, {})
            document = timeline or MarkdownDocument("timeline.md", {}, "", "")
            identifier = self._insert_entity(connection, "timeline_line", name, name, document, {})
            side = "center" if name == main_line else str(item.get("side") or ("right" if index % 2 == 0 else "left"))
            start = self._existing_plot_id(connection, item.get("startPlotId"))
            end = self._existing_plot_id(connection, item.get("endPlotId"))
            connection.execute(
                "INSERT INTO timeline_lines(entity_id, color, side, sort_key, start_plot_id, end_plot_id) VALUES(?, ?, ?, ?, ?, ?)",
                (identifier, normalize_color(item.get("color"), palette[(index - 1) % len(palette)]), side, sort_key(int(item.get("order", index) or index) * RANK_STEP), start, end),
            )
        settings_extra = {key: value for key, value in metadata.items() if key not in {"version", "mainLine", "lineSpacing", "topPadding", "sidePadding", "pixelsPerStoryUnit", "palette"}}
        connection.execute(
            """
            INSERT INTO timeline_settings(
                project_id, main_line_id, line_spacing, top_padding, side_padding,
                pixels_per_story_unit, extra_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.project_id, entity_id("timeline_line", main_line), int(metadata.get("lineSpacing", 72) or 72),
                int(metadata.get("topPadding", 64) or 64), int(metadata.get("sidePadding", 36) or 36),
                int(metadata.get("pixelsPerStoryUnit", 760) or 760), json_text(settings_extra),
            ),
        )
        for fallback, document in enumerate(plots, start=1):
            plot_id = entity_id("plot", document.metadata.get("id"))
            row = connection.execute("SELECT sort_key FROM plots WHERE entity_id=?", (plot_id,)).fetchone()
            story_key = str(row[0]) if row else sort_key(fallback * RANK_STEP)
            for lane in clean_list(document.metadata.get("lanes")):
                line_id = entity_id("timeline_line", lane)
                if connection.execute("SELECT 1 FROM timeline_lines WHERE entity_id=?", (line_id,)).fetchone():
                    connection.execute(
                        "INSERT OR IGNORE INTO plot_timeline_lines(plot_id, line_id, story_sort_key) VALUES(?, ?, ?)",
                        (plot_id, line_id, story_key),
                    )

    @staticmethod
    def _existing_plot_id(connection: sqlite3.Connection, value: Any) -> str | None:
        if value in (None, ""):
            return None
        identifier = entity_id("plot", value)
        return identifier if connection.execute("SELECT 1 FROM plots WHERE entity_id=?", (identifier,)).fetchone() else None

    def _insert_graph(
        self,
        connection: sqlite3.Connection,
        graph: MarkdownDocument | None,
        characters: list[MarkdownDocument],
    ) -> None:
        metadata = graph.metadata if graph else {}
        known = {"description", "nodeSpacing", "initialJitter", "relationshipDistance", "leafDistanceExtra", "centerStrength", "groupStrength", "leafStrength"}
        connection.execute(
            """
            INSERT INTO graph_settings(
                project_id, node_spacing, initial_jitter, relationship_distance,
                leaf_distance_extra, center_strength, group_strength, leaf_strength, extra_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.project_id, float(metadata.get("nodeSpacing", 116) or 116),
                float(metadata.get("initialJitter", 38) or 38), float(metadata.get("relationshipDistance", 250) or 250),
                float(metadata.get("leafDistanceExtra", 48) or 48), float(metadata.get("centerStrength", 1) or 1),
                float(metadata.get("groupStrength", 1) or 1), float(metadata.get("leafStrength", 1) or 1),
                json_text({key: value for key, value in metadata.items() if key not in known}),
            ),
        )
        for index, item in enumerate(parse_yaml_list_section(graph.body, "Clusters") if graph else []):
            cluster_id = str(item.get("id") or f"cluster-{index + 1}")
            connection.execute(
                "INSERT INTO graph_clusters(id, project_id, label, center_x, center_y, radius, strength, sort_key) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (cluster_id, self.project_id, str(item.get("label") or cluster_id), item.get("centerX"), item.get("centerY"), item.get("radius"), item.get("strength"), sort_key((index + 1) * RANK_STEP)),
            )
            for stable in clean_list(item.get("members")):
                character_id = entity_id("character", stable)
                if connection.execute("SELECT 1 FROM characters WHERE entity_id=?", (character_id,)).fetchone():
                    connection.execute("INSERT OR IGNORE INTO graph_cluster_members(cluster_id, character_id) VALUES(?, ?)", (cluster_id, character_id))
        for item in parse_yaml_list_section(graph.body, "Distances") if graph else []:
            from_id, to_id = entity_id("character", item.get("from")), entity_id("character", item.get("to"))
            if all(connection.execute("SELECT 1 FROM characters WHERE entity_id=?", (value,)).fetchone() for value in (from_id, to_id)):
                connection.execute(
                    "INSERT OR IGNORE INTO graph_distances(from_character_id, to_character_id, distance, strength) VALUES(?, ?, ?, ?)",
                    (from_id, to_id, float(item.get("distance", 250)), float(item.get("strength", 1))),
                )
        node_items = parse_yaml_list_section(graph.body, "Nodes") if graph else []
        positions = {str(item.get("id")): item for item in (parse_yaml_list_section(graph.body, "Saved Positions") if graph else [])}
        explicit_nodes = {str(item.get("id")): item for item in node_items}
        for document in characters:
            stable = str(document.metadata.get("id"))
            item = explicit_nodes.get(stable, {})
            position = positions.get(stable, {})
            x = position.get("x", document.metadata.get("x"))
            y = position.get("y", document.metadata.get("y"))
            orbit = item.get("orbitOf")
            if not item and x is None and y is None:
                continue
            connection.execute(
                """
                INSERT INTO graph_nodes(character_id, orbit_of, orbit_distance, orbit_angle, strength, anchor_x, anchor_y)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id("character", stable), entity_id("character", orbit) if orbit not in (None, "") else None,
                    item.get("orbitDistance"), item.get("orbitAngle"), item.get("strength"), x, y,
                ),
            )

    def _insert_legacy_operations(self, connection: sqlite3.Connection) -> None:
        # Preserve recent audit labels and expiry boundaries. Legacy document snapshots are
        # intentionally not made executable against normalized rows.
        for item in self.source.transactions:
            expires_at = int(item.get("expires_at", 0) or 0)
            if expires_at <= self.now:
                continue
            base_revision = int(connection.execute("SELECT revision FROM projects WHERE id=?", (self.project_id,)).fetchone()[0])
            result_revision = base_revision + 1
            details: dict[str, Any] = {}
            try:
                loaded_details = json.loads(item.get("details") or "{}")
                if isinstance(loaded_details, dict):
                    details = loaded_details
            except (TypeError, json.JSONDecodeError):
                pass
            details["legacyTransactionId"] = int(item["id"])
            details["legacySnapshotArchived"] = True
            connection.execute(
                """
                INSERT INTO operations(
                    project_id, label, action, entity_kind, base_revision, result_revision,
                    details_json, created_at, expires_at, undone_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.project_id, str(item.get("label") or item.get("operation") or "旧版操作"),
                    "legacy", str(item.get("entity_type") or "content"), base_revision,
                    result_revision, json_text(details), int(item.get("created_at", self.now)),
                    expires_at, self.now if item.get("undone_by") is not None else None,
                ),
            )
            connection.execute("UPDATE projects SET revision=?, updated_at=? WHERE id=?", (result_revision, self.now, self.project_id))

    def _remember_body(
        self,
        document: MarkdownDocument,
        table: str,
        column: str,
        identifier: str,
    ) -> None:
        self.body_hashes[document.path] = hashlib.sha256(document.body.encode("utf-8")).hexdigest()
        self.body_records[document.path] = (table, column, identifier)

    def _report(self, connection: sqlite3.Connection, target: Path) -> dict[str, Any]:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("characters", "plots", "entries", "fragments", "relationships", "timeline_lines", "chapters")
        }
        target_hashes: dict[str, str] = {}
        for path, (table, column, identifier) in self.body_records.items():
            row = connection.execute(
                f"SELECT {column} FROM {table} WHERE entity_id=?", (identifier,)
            ).fetchone()
            if row:
                target_hashes[path] = hashlib.sha256(str(row[0]).encode("utf-8")).hexdigest()
        mismatches = sorted(
            path for path, digest in self.body_hashes.items() if target_hashes.get(path) != digest
        )
        if mismatches:
            raise ValueError(f"正文哈希校验失败：{mismatches[:5]}")
        return {
            "source": str(self.source.database_path),
            "target": str(target),
            "sourceSchemaVersion": self.source.version,
            "targetSchemaVersion": 3,
            "sourceSha256": file_sha256(self.source.database_path),
            "targetSha256": file_sha256(target),
            "counts": counts,
            "bodyHashCount": len(self.body_hashes),
            "bodyHashesVerified": len(target_hashes),
            "foreignKeyCheck": "ok",
            "warnings": self.warnings,
        }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate_database_atomic(project_root: Path, *, keep_backup: bool = True) -> dict[str, Any]:
    root = Path(project_root).resolve()
    database = root / "story.db"
    if not database.is_file():
        raise FileNotFoundError(f"数据库不存在：{database}")
    with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as source:
        current_version = schema_version(source)
    if current_version == 3:
        Database(root).require_v3()
        return {"ok": True, "alreadyMigrated": True, "database": str(database)}
    if current_version not in {1, 2}:
        raise ValueError(f"只支持迁移 Schema V1/V2，当前为 V{current_version}")
    source_digest = file_sha256(database)
    # A content package may have gone through an earlier preview or failed cutover.
    # Name the backup from the exact source bytes so an existing stale backup can
    # never be mistaken for the database that is about to be replaced.
    backup = database.with_name(f"story.{source_digest[:12]}.v2-backup.db")
    if keep_backup and not backup.exists():
        shutil.copy2(database, backup)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".story-v3-", suffix=".db", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    try:
        report = V3Migrator(database, root.name).migrate_to(temporary)
        with sqlite3.connect(temporary) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or foreign_keys:
            raise ValueError("迁移数据库未通过最终完整性检查")
        os.chmod(temporary, database.stat().st_mode)
        os.replace(temporary, database)
        report.update({"ok": True, "backup": str(backup) if keep_backup else ""})
        return report
    finally:
        temporary.unlink(missing_ok=True)
