from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from storyteller.rag.config import EmbeddingConfig
from storyteller.rag.documents import RagDocument, RagEdge, chunk_document, lexical_tokens
from storyteller.rag.embeddings import bytes_vector, cosine_similarity, embed_texts, vector_bytes
from storyteller.domain.world_schema import registry_fingerprint


RAG_SCHEMA_VERSION = 3
RAG_DATABASE_NAME = "rag.db"


SCHEMA_SQL = r"""
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE documents (
    document_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL UNIQUE,
    stable_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    revision INTEGER NOT NULL,
    canonical INTEGER NOT NULL CHECK(canonical IN (0, 1)),
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX documents_kind ON documents(kind, canonical, title);
CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    lexical_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(document_id, position)
);
CREATE INDEX chunks_document ON chunks(document_id, position);
CREATE VIRTUAL TABLE chunk_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    lexical_text,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TABLE embeddings (
    chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,
    content_hash TEXT NOT NULL,
    PRIMARY KEY(chunk_id, model_key)
);
CREATE INDEX embeddings_model ON embeddings(model_key, chunk_id);
CREATE TABLE edges (
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(source_entity_id, target_entity_id, relation_type, label)
);
CREATE INDEX edges_target ON edges(target_entity_id, relation_type);
"""


def rag_path(project_root: Path) -> Path:
    return Path(project_root) / RAG_DATABASE_NAME


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    else:
        connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=10000")
    return connection


def build_index(
    project_root: Path,
    project_id: str,
    documents: list[RagDocument],
    edges: list[RagEdge],
    source_revision: int,
    source_mtime_ns: int,
    config: EmbeddingConfig,
) -> dict[str, Any]:
    target = rag_path(project_root)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    embedding_error = ""
    chunk_count = 0
    try:
        connection = _connect(temporary)
        try:
            connection.executescript(SCHEMA_SQL)
            all_chunks: list[tuple[str, str, str, str]] = []
            for document in documents:
                document_id = f"doc:{document.entity_id}"
                connection.execute(
                    """
                    INSERT INTO documents(
                        document_id, entity_id, stable_id, kind, title, aliases_json,
                        revision, canonical, content, content_hash, metadata_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id, document.entity_id, document.stable_id, document.kind,
                        document.title, json.dumps(document.aliases, ensure_ascii=False),
                        document.revision, int(document.canonical), document.content,
                        document.content_hash, json.dumps(document.metadata, ensure_ascii=False),
                    ),
                )
                for position, text in enumerate(chunk_document(document)):
                    chunk_id = f"{document_id}:{position}"
                    content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    lexical = lexical_tokens(f"{document.title} {' '.join(document.aliases)} {text}")
                    connection.execute(
                        "INSERT INTO chunks(chunk_id, document_id, position, text, lexical_text, content_hash) VALUES(?, ?, ?, ?, ?, ?)",
                        (chunk_id, document_id, position, text, lexical, content_hash),
                    )
                    connection.execute(
                        "INSERT INTO chunk_fts(chunk_id, title, lexical_text) VALUES(?, ?, ?)",
                        (chunk_id, lexical_tokens(f"{document.title} {' '.join(document.aliases)}"), lexical),
                    )
                    all_chunks.append((chunk_id, text, document.title, content_hash))
            chunk_count = len(all_chunks)
            for edge in edges:
                connection.execute(
                    "INSERT OR IGNORE INTO edges(source_entity_id, target_entity_id, relation_type, label, metadata_json) VALUES(?, ?, ?, ?, ?)",
                    (edge.source, edge.target, edge.relation_type, edge.label, json.dumps(edge.metadata, ensure_ascii=False)),
                )
            if config.provider != "disabled" and all_chunks:
                try:
                    vectors = embed_texts([item[1] for item in all_chunks], config)
                    for item, vector in zip(all_chunks, vectors):
                        connection.execute(
                            "INSERT INTO embeddings(chunk_id, model_key, dimensions, vector, content_hash) VALUES(?, ?, ?, ?, ?)",
                            (item[0], config.model_key, len(vector), vector_bytes(vector), item[3]),
                        )
                except Exception as error:  # lexical RAG remains usable if an optional provider is offline
                    embedding_error = str(error)
            now = int(time.time())
            meta = {
                "rag_schema_version": str(RAG_SCHEMA_VERSION),
                "project_id": project_id,
                "source_revision": str(source_revision),
                "source_mtime_ns": str(source_mtime_ns),
                "embedding_model_key": config.model_key,
                "world_schema_hash": registry_fingerprint(),
                "embedding_status": "disabled" if config.provider == "disabled" else "failed" if embedding_error else "ready",
                "embedding_error": embedding_error,
                "built_at": str(now),
                "document_count": str(len(documents)),
                "chunk_count": str(chunk_count),
                "last_sync_mode": "full",
                "last_changed_documents": str(len(documents)),
                "last_removed_documents": "0",
            }
            connection.executemany("INSERT INTO meta(key, value) VALUES(?, ?)", meta.items())
            connection.commit()
            connection.execute("PRAGMA optimize")
        finally:
            connection.close()
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "path": str(target), "sourceRevision": source_revision,
        "documents": len(documents), "chunks": chunk_count,
        "embeddingStatus": "disabled" if config.provider == "disabled" else "failed" if embedding_error else "ready",
        "embeddingError": embedding_error,
    }


def sync_index(
    project_root: Path,
    project_id: str,
    documents: list[RagDocument],
    edges: list[RagEdge],
    source_revision: int,
    source_mtime_ns: int,
    config: EmbeddingConfig,
) -> dict[str, Any]:
    """Incrementally refresh changed documents while committing one atomic index revision."""
    target = rag_path(project_root)
    if not target.exists():
        return build_index(
            project_root, project_id, documents, edges,
            source_revision, source_mtime_ns, config,
        )
    with _connect(target, readonly=True) as connection:
        existing = {
            str(row["entity_id"]): {
                "contentHash": str(row["content_hash"]),
                "revision": int(row["revision"]),
                "metadata": str(row["metadata_json"]),
                "aliases": str(row["aliases_json"]),
                "title": str(row["title"]),
                "canonical": int(row["canonical"]),
            }
            for row in connection.execute(
                "SELECT entity_id, content_hash, revision, metadata_json, aliases_json, title, canonical FROM documents"
            )
        }
        previous_meta = read_meta(target)
    current = {document.entity_id: document for document in documents}
    removed = sorted(set(existing) - set(current))
    changed: list[RagDocument] = []
    for document in documents:
        previous = existing.get(document.entity_id)
        aliases_json = json.dumps(document.aliases, ensure_ascii=False)
        metadata_json = json.dumps(document.metadata, ensure_ascii=False)
        if previous is None or any((
            previous["contentHash"] != document.content_hash,
            previous["revision"] != document.revision,
            previous["metadata"] != metadata_json,
            previous["aliases"] != aliases_json,
            previous["title"] != document.title,
            previous["canonical"] != int(document.canonical),
        )):
            changed.append(document)

    prepared: dict[str, list[tuple[str, str, str, str, list[float] | None]]] = {}
    embedding_error = ""
    changed_chunks: list[tuple[str, str, str, str]] = []
    for document in changed:
        records = []
        document_id = f"doc:{document.entity_id}"
        for position, chunk_text in enumerate(chunk_document(document)):
            chunk_id = f"{document_id}:{position}"
            content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
            records.append((chunk_id, chunk_text, lexical_tokens(
                f"{document.title} {' '.join(document.aliases)} {chunk_text}"
            ), content_hash, None))
            changed_chunks.append((chunk_id, chunk_text, document.entity_id, content_hash))
        prepared[document.entity_id] = records
    if config.provider != "disabled" and changed_chunks:
        try:
            vectors = embed_texts([item[1] for item in changed_chunks], config)
            by_chunk = {item[0]: vector for item, vector in zip(changed_chunks, vectors)}
            for entity_id, records in prepared.items():
                prepared[entity_id] = [
                    (chunk_id, text, lexical, content_hash, by_chunk.get(chunk_id))
                    for chunk_id, text, lexical, content_hash, _vector in records
                ]
        except Exception as error:  # lexical search remains available
            embedding_error = str(error)

    connection = _connect(target)
    try:
        connection.execute("BEGIN IMMEDIATE")
        replaced = [*removed, *(document.entity_id for document in changed)]
        for entity_id in replaced:
            chunk_ids = [str(row[0]) for row in connection.execute(
                "SELECT chunk_id FROM chunks WHERE document_id=?", (f"doc:{entity_id}",)
            )]
            if chunk_ids:
                placeholders = ",".join("?" for _ in chunk_ids)
                connection.execute(f"DELETE FROM chunk_fts WHERE chunk_id IN ({placeholders})", chunk_ids)
            connection.execute("DELETE FROM documents WHERE entity_id=?", (entity_id,))
        for document in changed:
            document_id = f"doc:{document.entity_id}"
            connection.execute(
                """
                INSERT INTO documents(
                    document_id, entity_id, stable_id, kind, title, aliases_json,
                    revision, canonical, content, content_hash, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id, document.entity_id, document.stable_id, document.kind,
                    document.title, json.dumps(document.aliases, ensure_ascii=False),
                    document.revision, int(document.canonical), document.content,
                    document.content_hash, json.dumps(document.metadata, ensure_ascii=False),
                ),
            )
            for position, (chunk_id, text, lexical, content_hash, vector) in enumerate(prepared[document.entity_id]):
                connection.execute(
                    "INSERT INTO chunks(chunk_id, document_id, position, text, lexical_text, content_hash) VALUES(?, ?, ?, ?, ?, ?)",
                    (chunk_id, document_id, position, text, lexical, content_hash),
                )
                connection.execute(
                    "INSERT INTO chunk_fts(chunk_id, title, lexical_text) VALUES(?, ?, ?)",
                    (chunk_id, lexical_tokens(f"{document.title} {' '.join(document.aliases)}"), lexical),
                )
                if vector is not None:
                    connection.execute(
                        "INSERT INTO embeddings(chunk_id, model_key, dimensions, vector, content_hash) VALUES(?, ?, ?, ?, ?)",
                        (chunk_id, config.model_key, len(vector), vector_bytes(vector), content_hash),
                    )
        connection.execute("DELETE FROM edges")
        connection.executemany(
            "INSERT OR IGNORE INTO edges(source_entity_id, target_entity_id, relation_type, label, metadata_json) VALUES(?, ?, ?, ?, ?)",
            [
                (edge.source, edge.target, edge.relation_type, edge.label, json.dumps(edge.metadata, ensure_ascii=False))
                for edge in edges
            ],
        )
        document_count = int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
        chunk_count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
        previous_embedding_status = previous_meta.get("embedding_status", "unknown")
        embedding_status = (
            "disabled" if config.provider == "disabled"
            else "failed" if embedding_error
            else "ready" if changed_chunks
            else previous_embedding_status
        )
        meta = {
            "rag_schema_version": str(RAG_SCHEMA_VERSION),
            "project_id": project_id,
            "source_revision": str(source_revision),
            "source_mtime_ns": str(source_mtime_ns),
            "embedding_model_key": config.model_key,
            "world_schema_hash": registry_fingerprint(),
            "embedding_status": embedding_status,
            "embedding_error": embedding_error,
            "built_at": str(int(time.time())),
            "document_count": str(document_count),
            "chunk_count": str(chunk_count),
            "last_sync_mode": "incremental",
            "last_changed_documents": str(len(changed)),
            "last_removed_documents": str(len(removed)),
        }
        connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            meta.items(),
        )
        connection.commit()
        connection.execute("PRAGMA optimize")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "path": str(target), "sourceRevision": source_revision,
        "documents": len(documents), "changedDocuments": len(changed),
        "removedDocuments": len(removed), "chunks": chunk_count,
        "embeddingStatus": embedding_status, "embeddingError": embedding_error,
        "mode": "incremental",
    }


def read_meta(path: Path) -> dict[str, str]:
    with _connect(path, readonly=True) as connection:
        return {str(row["key"]): str(row["value"]) for row in connection.execute("SELECT key, value FROM meta")}


def _query_terms(query: str) -> list[str]:
    ignored = {"什么", "哪个", "哪些", "怎么", "如何", "为何", "是否", "一个", "这个", "那个", "知道"}
    raw = lexical_tokens(query).split()
    terms = [term for term in raw if term not in ignored and len(term) >= 2]
    return list(dict.fromkeys(terms))[:24]


def _excerpt(text: str, terms: list[str], length: int = 520) -> str:
    normalized = text.strip()
    positions = [normalized.find(term) for term in terms if normalized.find(term) >= 0]
    center = min(positions) if positions else 0
    start = max(0, center - length // 3)
    end = min(len(normalized), start + length)
    prefix = "…" if start else ""
    suffix = "…" if end < len(normalized) else ""
    return f"{prefix}{normalized[start:end].strip()}{suffix}"


def search_index(
    path: Path,
    query: str,
    config: EmbeddingConfig,
    *,
    limit: int = 8,
    kinds: list[str] | None = None,
    include_fragments: bool = False,
) -> list[dict[str, Any]]:
    clean_query = str(query or "").strip()
    if not clean_query:
        return []
    lowered = clean_query.lower()
    terms = _query_terms(clean_query)
    candidates: dict[str, dict[str, Any]] = {}
    mentioned_ids: set[str] = set()
    related_mentions: dict[str, set[str]] = defaultdict(set)
    with _connect(path, readonly=True) as connection:
        for document in connection.execute("SELECT entity_id, title, aliases_json FROM documents"):
            variants = [str(document["title"]), *json.loads(document["aliases_json"])]
            expanded: list[str] = []
            for variant in variants:
                clean_variant = str(variant).strip()
                if len(clean_variant) >= 2:
                    expanded.append(clean_variant)
                expanded.extend(
                    part for part in re.split(r"[·“”\"'（）()\s]+", clean_variant)
                    if len(part) >= 2
                )
            if any(variant.lower() in lowered for variant in expanded):
                mentioned_ids.add(str(document["entity_id"]))
        if mentioned_ids:
            for edge in connection.execute(
                "SELECT source_entity_id, target_entity_id FROM edges"
            ):
                target = str(edge["target_entity_id"])
                if target in mentioned_ids:
                    related_mentions[str(edge["source_entity_id"])].add(target)
        kind_sql = ""
        params: list[Any] = []
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            kind_sql = f" AND d.kind IN ({placeholders})"
            params.extend(kinds)
        canonical_sql = "" if include_fragments else " AND d.canonical=1"
        if terms:
            match_query = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
            rows = connection.execute(
                f"""
                SELECT d.*, c.chunk_id, c.text, bm25(chunk_fts, 0.4, 1.0) AS lexical_rank
                FROM chunk_fts
                JOIN chunks c ON c.chunk_id=chunk_fts.chunk_id
                JOIN documents d ON d.document_id=c.document_id
                WHERE chunk_fts MATCH ? {canonical_sql} {kind_sql}
                ORDER BY lexical_rank LIMIT 160
                """,
                [match_query, *params],
            )
            lexical_rows = list(rows)
        else:
            lexical_rows = []
        if not lexical_rows:
            like_terms = terms or [clean_query]
            clauses = " OR ".join("c.text LIKE ?" for _ in like_terms)
            lexical_rows = list(connection.execute(
                f"""
                SELECT d.*, c.chunk_id, c.text, 0.0 AS lexical_rank
                FROM chunks c JOIN documents d ON d.document_id=c.document_id
                WHERE ({clauses}) {canonical_sql} {kind_sql} LIMIT 160
                """,
                [*(f"%{term}%" for term in like_terms), *params],
            ))
        ranks = [float(row["lexical_rank"]) for row in lexical_rows]
        best_rank = min(ranks) if ranks else 0.0
        worst_rank = max(ranks) if ranks else 1.0
        rank_span = max(1e-9, worst_rank - best_rank)
        for row in lexical_rows:
            document_id = str(row["document_id"])
            lexical_score = 1.0 - ((float(row["lexical_rank"]) - best_rank) / rank_span) if len(ranks) > 1 else 1.0
            item = candidates.setdefault(document_id, {"row": row, "lexical": 0.0, "vector": 0.0})
            if lexical_score > item["lexical"]:
                item.update(row=row, lexical=lexical_score)

        if config.provider != "disabled":
            try:
                query_vectors = embed_texts([clean_query], config)
                query_vector = query_vectors[0] if query_vectors else []
            except Exception:
                query_vector = []
            if query_vector:
                vector_rows = connection.execute(
                    f"""
                    SELECT d.*, c.chunk_id, c.text, e.vector
                    FROM embeddings e
                    JOIN chunks c ON c.chunk_id=e.chunk_id
                    JOIN documents d ON d.document_id=c.document_id
                    WHERE e.model_key=? {canonical_sql} {kind_sql}
                    """,
                    [config.model_key, *params],
                )
                vector_candidates = []
                for row in vector_rows:
                    similarity = cosine_similarity(query_vector, bytes_vector(row["vector"]))
                    vector_candidates.append((similarity, row))
                for similarity, row in sorted(vector_candidates, key=lambda item: item[0], reverse=True)[:160]:
                    document_id = str(row["document_id"])
                    item = candidates.setdefault(document_id, {"row": row, "lexical": 0.0, "vector": 0.0})
                    if similarity > item["vector"]:
                        item.update(row=row, vector=similarity)

    results: list[dict[str, Any]] = []
    for item in candidates.values():
        row = item["row"]
        aliases = json.loads(row["aliases_json"])
        title = str(row["title"])
        entity_id = str(row["entity_id"])
        direct = 0.0
        if entity_id in mentioned_ids:
            direct = 0.42 if len(mentioned_ids) == 1 else 0.22
        elif title.lower() in lowered or lowered in title.lower():
            direct = 0.22
        elif any(alias.lower() in lowered for alias in aliases):
            direct = 0.18
        relation_boost = 0.0
        if mentioned_ids:
            coverage = len(related_mentions.get(entity_id, set())) / len(mentioned_ids)
            relation_boost = (0.1 if len(mentioned_ids) == 1 else 0.3) * coverage
            if len(mentioned_ids) >= 2 and coverage == 1.0:
                relation_boost += 0.18
            if coverage and str(row["kind"]) == "entry" and any(word in clean_query for word in ("组织", "势力", "团体", "家族", "属于")):
                relation_boost += 0.22
            if coverage and str(row["kind"]) == "relationship" and any(word in clean_query for word in ("关系", "看法", "怎么看", "印象")):
                relation_boost += 0.16
        vector_score = max(0.0, min(1.0, (float(item["vector"]) + 1.0) / 2.0)) if item["vector"] else 0.0
        score = min(1.0, 0.58 * float(item["lexical"]) + 0.34 * vector_score + direct + relation_boost)
        results.append({
            "entityId": str(row["entity_id"]), "stableId": str(row["stable_id"]),
            "kind": str(row["kind"]), "title": title, "canonical": bool(row["canonical"]),
            "revision": int(row["revision"]), "score": round(score, 6),
            "certainty": str(json.loads(row["metadata_json"]).get("certainty") or "confirmed"),
            "timelineStatus": str(json.loads(row["metadata_json"]).get("timelineStatus") or "independent"),
            "excerpt": _excerpt(str(row["text"]), terms),
            "citation": f"story://{row['entity_id']}",
            "matchedBy": {
                "lexical": round(float(item["lexical"]), 6),
                "embedding": round(float(item["vector"]), 6) if item["vector"] else None,
            },
        })
    return sorted(results, key=lambda item: (item["score"], item["revision"]), reverse=True)[:max(1, min(limit, 50))]


def get_document(path: Path, entity_id: str) -> dict[str, Any] | None:
    with _connect(path, readonly=True) as connection:
        row = connection.execute("SELECT * FROM documents WHERE entity_id=?", (entity_id,)).fetchone()
        if not row:
            return None
        related = list(connection.execute(
            """
            SELECT edge.*, target.title AS target_title, target.kind AS target_kind
            FROM edges edge LEFT JOIN documents target ON target.entity_id=edge.target_entity_id
            WHERE edge.source_entity_id=? ORDER BY edge.relation_type, target.title
            """, (entity_id,),
        ))
        return {
            "entityId": str(row["entity_id"]), "stableId": str(row["stable_id"]),
            "kind": str(row["kind"]), "title": str(row["title"]),
            "aliases": json.loads(row["aliases_json"]), "revision": int(row["revision"]),
            "canonical": bool(row["canonical"]), "content": str(row["content"]),
            "metadata": json.loads(row["metadata_json"]),
            "certainty": str(json.loads(row["metadata_json"]).get("certainty") or "confirmed"),
            "timelineStatus": str(json.loads(row["metadata_json"]).get("timelineStatus") or "independent"),
            "related": [{
                "entityId": str(item["target_entity_id"]),
                "title": str(item["target_title"] or item["target_entity_id"]),
                "kind": str(item["target_kind"] or ""),
                "relationType": str(item["relation_type"]), "label": str(item["label"]),
                "metadata": json.loads(item["metadata_json"]),
            } for item in related],
            "citation": f"story://{row['entity_id']}",
        }


def catalog(path: Path) -> dict[str, Any]:
    meta = read_meta(path)
    with _connect(path, readonly=True) as connection:
        counts = {str(row["kind"]): int(row["count"]) for row in connection.execute(
            "SELECT kind, COUNT(*) AS count FROM documents GROUP BY kind ORDER BY kind"
        )}
        items = [{
            "entityId": str(row["entity_id"]), "stableId": str(row["stable_id"]),
            "kind": str(row["kind"]), "title": str(row["title"]),
            "canonical": bool(row["canonical"]), "revision": int(row["revision"]),
            "certainty": str(json.loads(row["metadata_json"]).get("certainty") or "confirmed"),
            "timelineStatus": str(json.loads(row["metadata_json"]).get("timelineStatus") or "independent"),
        } for row in connection.execute(
            "SELECT entity_id, stable_id, kind, title, canonical, revision, metadata_json FROM documents ORDER BY kind, title"
        )]
    return {"project": meta.get("project_id", ""), "sourceRevision": int(meta.get("source_revision", 0)), "counts": counts, "items": items}
