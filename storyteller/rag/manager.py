from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import fcntl

from storyteller.domain.errors import ConflictError
from storyteller.domain.world_reader import WorldReader
from storyteller.domain.world_schema import registry_fingerprint
from storyteller.rag.config import EmbeddingConfig, load_config, save_config
from storyteller.rag.documents import build_documents
from storyteller.rag.index import RAG_SCHEMA_VERSION, build_index, catalog, get_document, rag_path, read_meta, search_index, sync_index
from storyteller.settings import Settings
from storyteller.storage.connection import Database
from storyteller.storage.repositories import ProjectRepository


class RagManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._guard = threading.Lock()
        self._project_locks: dict[str, threading.RLock] = {}

    def _lock(self, project: str) -> threading.RLock:
        with self._guard:
            return self._project_locks.setdefault(project, threading.RLock())

    def _root(self, project: str) -> Path:
        root = self.settings.project_root(project)
        if not (root / "story.db").is_file():
            raise ValueError(f"项目 {project} 没有 story.db")
        return root

    @staticmethod
    @contextmanager
    def _process_lock(root: Path) -> Iterator[None]:
        """Serialize index replacement across the web service and MCP workers."""
        digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:20]
        path = Path(tempfile.gettempdir()) / f"story-teller-rag-{digest}.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def projects(self) -> list[str]:
        if not self.settings.content_root.is_dir():
            return []
        allowed = set(self.settings.enabled_projects)
        return sorted(
            path.name for path in self.settings.content_root.iterdir()
            if path.is_dir() and (path / "story.db").is_file()
            and (not allowed or path.name in allowed)
        )

    def _source_state(self, project: str) -> tuple[int, int]:
        root = self._root(project)
        database = Database(root)
        with database.read() as connection:
            row = connection.execute("SELECT revision FROM projects WHERE id=?", (project,)).fetchone()
            if not row:
                raise ValueError(f"项目 {project} 不存在")
            revision = int(row[0])
        return revision, (root / "story.db").stat().st_mtime_ns

    def ensure_fresh(self, project: str, *, force_check: bool = False) -> dict[str, Any]:
        root = self._root(project)
        target = rag_path(root)
        with self._lock(project):
            with self._process_lock(root):
                for _attempt in range(5):
                    source_revision, _source_mtime_ns = self._source_state(project)
                    config = load_config(root)
                    rebuild = not target.exists()
                    incremental = False
                    meta: dict[str, str] = {}
                    if not rebuild:
                        try:
                            meta = read_meta(target)
                            rebuild = (
                                int(meta.get("rag_schema_version", 0)) != RAG_SCHEMA_VERSION
                                or meta.get("project_id") != project
                                or meta.get("embedding_model_key") != config.model_key
                                or meta.get("world_schema_hash") != registry_fingerprint()
                            )
                            incremental = int(meta.get("source_revision", -1)) != source_revision
                        except (OSError, sqlite3.DatabaseError, ValueError):
                            rebuild = True
                    if not rebuild and not incremental:
                        return self.status(project, check_source=False)

                    repository = ProjectRepository(Database(root), project)
                    documents, edges, captured_revision = build_documents(repository)
                    latest_revision, latest_mtime_ns = self._source_state(project)
                    if captured_revision != latest_revision:
                        continue
                    if rebuild:
                        build_index(root, project, documents, edges, captured_revision, latest_mtime_ns, config)
                    else:
                        try:
                            repository.changes_since(int(meta.get("source_revision", 0)))
                        except ConflictError:
                            build_index(root, project, documents, edges, captured_revision, latest_mtime_ns, config)
                        else:
                            sync_index(root, project, documents, edges, captured_revision, latest_mtime_ns, config)
                    final_revision, _final_mtime_ns = self._source_state(project)
                    if final_revision == captured_revision:
                        return self.status(project, check_source=False)
            raise ValueError("story.db 在索引同步期间持续变化，请稍后重试")

    def rebuild(self, project: str) -> dict[str, Any]:
        root = self._root(project)
        with self._lock(project):
            with self._process_lock(root):
                repository = ProjectRepository(Database(root), project)
                documents, edges, revision = build_documents(repository)
                _, source_mtime_ns = self._source_state(project)
                result = build_index(root, project, documents, edges, revision, source_mtime_ns, load_config(root))
                result["status"] = self.status(project, check_source=False)
                return result

    def status(self, project: str, *, check_source: bool = True) -> dict[str, Any]:
        root = self._root(project)
        target = rag_path(root)
        config = load_config(root)
        if not target.exists():
            return {"project": project, "exists": False, "fresh": False, "path": str(target), "embedding": config.public_dict()}
        meta = read_meta(target)
        source_revision = int(meta.get("source_revision", 0))
        source_mtime_ns = int(meta.get("source_mtime_ns", 0))
        schema_hash = str(meta.get("world_schema_hash") or "")
        current_schema_hash = registry_fingerprint()
        fresh = True
        current_revision = source_revision
        current_mtime_ns = source_mtime_ns
        if check_source:
            current_revision, current_mtime_ns = self._source_state(project)
            fresh = (
                current_revision == source_revision
                and meta.get("embedding_model_key") == config.model_key
                and schema_hash == current_schema_hash
            )
        return {
            "project": project, "exists": True, "fresh": fresh, "path": str(target),
            "sourceRevision": source_revision, "currentRevision": current_revision,
            "sourceMtimeNs": source_mtime_ns, "currentMtimeNs": current_mtime_ns,
            "worldSchemaHash": schema_hash, "currentWorldSchemaHash": current_schema_hash,
            "builtAt": int(meta.get("built_at", 0)),
            "documents": int(meta.get("document_count", 0)), "chunks": int(meta.get("chunk_count", 0)),
            "embeddingStatus": meta.get("embedding_status", "unknown"),
            "embeddingError": meta.get("embedding_error", ""), "embedding": config.public_dict(),
            "lastSyncMode": meta.get("last_sync_mode", "full"),
            "lastChangedDocuments": int(meta.get("last_changed_documents", 0)),
            "lastRemovedDocuments": int(meta.get("last_removed_documents", 0)),
            "syncMode": "background-incremental-with-request-fallback",
        }

    def configure(self, project: str, value: dict[str, Any]) -> dict[str, Any]:
        root = self._root(project)
        config = EmbeddingConfig.from_dict(value)
        save_config(root, config)
        result = self.rebuild(project)
        return {"ok": True, "embedding": config.public_dict(), "rebuild": result}

    def search(self, project: str, query: str, *, limit: int = 8, kinds: list[str] | None = None, include_fragments: bool = False) -> dict[str, Any]:
        status = self.ensure_fresh(project)
        config = load_config(self._root(project))
        results = search_index(rag_path(self._root(project)), query, config, limit=limit, kinds=kinds, include_fragments=include_fragments)
        return {
            "query": query, "project": project,
            "sourceRevision": status["sourceRevision"],
            "currentRevision": status["sourceRevision"],
            "results": results,
        }

    def entity(self, project: str, entity_id: str) -> dict[str, Any] | None:
        self.ensure_fresh(project)
        return get_document(rag_path(self._root(project)), entity_id)

    def catalog(self, project: str) -> dict[str, Any]:
        self.ensure_fresh(project)
        return catalog(rag_path(self._root(project)))

    def context(self, project: str, question: str, *, limit: int = 10, max_chars: int = 12000, include_fragments: bool = False) -> dict[str, Any]:
        search = self.search(project, question, limit=limit, include_fragments=include_fragments)
        sections: list[str] = []
        citations: list[dict[str, Any]] = []
        remaining = max(1000, min(int(max_chars), 50000))
        structured_ids: set[str] = set()
        resolved = self.resolve(project, question, limit=min(5, limit))
        for match in resolved["results"]:
            if float(match.get("score", 0)) < 0.65:
                continue
            entity = self.structured_entity(project, match["entityId"])
            if not entity:
                continue
            rendered = (
                f"<!-- source: {entity['citation']} revision: {entity['revision']} -->\n"
                f"# 结构化事实：{entity['title']}\n\n"
                + json.dumps({"data": entity["data"], "related": entity["related"]}, ensure_ascii=False, indent=2)
            )
            if len(rendered) > remaining:
                rendered = rendered[:remaining].rstrip() + "\n…"
            sections.append(rendered)
            citations.append({
                "entityId": entity["entityId"], "stableId": entity["stableId"],
                "kind": entity["kind"], "title": entity["title"],
                "revision": entity["revision"], "citation": entity["citation"],
                "retrieval": "structured",
            })
            structured_ids.add(entity["entityId"])
            remaining -= len(rendered)
            if remaining <= 0:
                break
        rag_count = 0
        for result in search["results"]:
            if result["entityId"] in structured_ids:
                continue
            document = self.entity(project, result["entityId"])
            if not document:
                continue
            content = document["content"]
            rendered = f"<!-- source: {document['citation']} revision: {document['revision']} -->\n{content}"
            if len(rendered) > remaining:
                rendered = rendered[:remaining].rstrip() + "\n…"
            sections.append(rendered)
            citation = {key: document[key] for key in ("entityId", "stableId", "kind", "title", "revision", "citation")}
            citation["retrieval"] = "rag"
            citations.append(citation)
            rag_count += 1
            remaining -= len(rendered)
            if remaining <= 0:
                break
        return {
            "project": project, "question": question, "sourceRevision": search["sourceRevision"],
            "contextMarkdown": "\n\n---\n\n".join(sections), "citations": citations,
            "retrieval": {"structured": len(structured_ids), "rag": rag_count},
        }

    def startup(self) -> None:
        projects = [self.settings.default_project] if self.settings.default_project else self.projects()
        if not projects:
            raise RuntimeError("内容目录中没有可同步的 story.db")
        for project in projects:
            self.ensure_fresh(project, force_check=True)

    def reader(self, project: str) -> WorldReader:
        return WorldReader(Database(self._root(project)), project)

    def world_schema(self, project: str) -> dict[str, Any]:
        return self.reader(project).schema()

    def live_catalog(self, project: str) -> dict[str, Any]:
        return self.reader(project).catalog()

    def resolve(self, project: str, query: str, *, kinds: list[str] | None = None, limit: int = 10) -> dict[str, Any]:
        return self.reader(project).resolve(query, kinds=kinds, limit=limit)

    def query_world(
        self, project: str, *, kinds: list[str] | None = None,
        filters: dict[str, Any] | None = None, limit: int = 50,
    ) -> dict[str, Any]:
        return self.reader(project).query(kinds=kinds, filters=filters, limit=limit)

    def structured_entity(self, project: str, entity_id: str) -> dict[str, Any] | None:
        return self.reader(project).entity(entity_id)

    def live_related(self, project: str, entity_id: str) -> dict[str, Any]:
        return self.reader(project).related(entity_id)
