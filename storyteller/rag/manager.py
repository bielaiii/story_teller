from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from storyteller.rag.config import EmbeddingConfig, load_config, save_config
from storyteller.rag.documents import build_documents
from storyteller.rag.index import RAG_SCHEMA_VERSION, build_index, catalog, get_document, rag_path, read_meta, search_index
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

    def projects(self) -> list[str]:
        if not self.settings.content_root.is_dir():
            return []
        return sorted(path.name for path in self.settings.content_root.iterdir() if path.is_dir() and (path / "story.db").is_file())

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
            if target.exists() and not force_check:
                try:
                    return self.status(project, check_source=False)
                except (OSError, sqlite3.DatabaseError, ValueError):
                    pass
            source_revision, source_mtime_ns = self._source_state(project)
            config = load_config(root)
            rebuild = not target.exists()
            if not rebuild:
                try:
                    meta = read_meta(target)
                    rebuild = (
                        int(meta.get("rag_schema_version", 0)) != RAG_SCHEMA_VERSION
                        or meta.get("project_id") != project
                        or int(meta.get("source_revision", -1)) != source_revision
                        or int(meta.get("source_mtime_ns", -1)) != source_mtime_ns
                        or meta.get("embedding_model_key") != config.model_key
                    )
                except (OSError, sqlite3.DatabaseError, ValueError):
                    rebuild = True
            if rebuild:
                repository = ProjectRepository(Database(root), project)
                documents, edges, captured_revision = build_documents(repository)
                latest_revision, latest_mtime_ns = self._source_state(project)
                if captured_revision != latest_revision:
                    documents, edges, captured_revision = build_documents(repository)
                    latest_revision, latest_mtime_ns = self._source_state(project)
                build_index(root, project, documents, edges, captured_revision, latest_mtime_ns, config)
            return self.status(project, check_source=False)

    def rebuild(self, project: str) -> dict[str, Any]:
        root = self._root(project)
        with self._lock(project):
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
        fresh = True
        current_revision = source_revision
        current_mtime_ns = source_mtime_ns
        if check_source:
            current_revision, current_mtime_ns = self._source_state(project)
            fresh = current_revision == source_revision and current_mtime_ns == source_mtime_ns and meta.get("embedding_model_key") == config.model_key
        return {
            "project": project, "exists": True, "fresh": fresh, "path": str(target),
            "sourceRevision": source_revision, "currentRevision": current_revision,
            "sourceMtimeNs": source_mtime_ns, "currentMtimeNs": current_mtime_ns,
            "builtAt": int(meta.get("built_at", 0)),
            "documents": int(meta.get("document_count", 0)), "chunks": int(meta.get("chunk_count", 0)),
            "embeddingStatus": meta.get("embedding_status", "unknown"),
            "embeddingError": meta.get("embedding_error", ""), "embedding": config.public_dict(),
            "syncMode": "startup-once",
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
        return {"query": query, "project": project, "sourceRevision": status["sourceRevision"], "results": results}

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
        for result in search["results"]:
            document = self.entity(project, result["entityId"])
            if not document:
                continue
            content = document["content"]
            rendered = f"<!-- source: {document['citation']} revision: {document['revision']} -->\n{content}"
            if len(rendered) > remaining:
                rendered = rendered[:remaining].rstrip() + "\n…"
            sections.append(rendered)
            citations.append({key: document[key] for key in ("entityId", "stableId", "kind", "title", "revision", "citation")})
            remaining -= len(rendered)
            if remaining <= 0:
                break
        return {
            "project": project, "question": question, "sourceRevision": search["sourceRevision"],
            "contextMarkdown": "\n\n---\n\n".join(sections), "citations": citations,
        }

    def startup(self) -> None:
        projects = [self.settings.default_project] if self.settings.default_project else self.projects()
        if not projects:
            raise RuntimeError("内容目录中没有可同步的 story.db")
        for project in projects:
            self.ensure_fresh(project, force_check=True)
