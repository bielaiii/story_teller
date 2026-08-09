from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from array import array
from typing import Iterable

import httpx

from storyteller.rag.config import EmbeddingConfig


def _normalized_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"\s+", "", value)


def _hash_vectors(texts: Iterable[str], dimensions: int, model: str) -> list[list[float]]:
    ngram_sizes = (3,) if model == "hash-char-3-v1" else (2, 3)
    vectors: list[list[float]] = []
    for raw in texts:
        text = _normalized_text(raw)
        vector = [0.0] * dimensions
        for size in ngram_sizes:
            for index in range(max(0, len(text) - size + 1)):
                token = text[index:index + size].encode("utf-8")
                digest = hashlib.blake2b(token, digest_size=8, person=b"storyrag").digest()
                bucket = int.from_bytes(digest[:4], "little") % dimensions
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        vectors.append([value / norm for value in vector] if norm else vector)
    return vectors


def embed_texts(texts: list[str], config: EmbeddingConfig) -> list[list[float]]:
    if config.provider == "disabled":
        return []
    if config.provider == "builtin":
        if config.model not in {"hash-char-2-3-v1", "hash-char-3-v1"}:
            raise ValueError("builtin provider 仅支持 hash-char-2-3-v1 或 hash-char-3-v1")
        return _hash_vectors(texts, config.dimensions, config.model)
    if config.provider == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers 尚未安装；请运行 ./scripts/python.sh -m pip install sentence-transformers"
            ) from error
        model = SentenceTransformer(config.model, trust_remote_code=False)
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=config.batch_size)
        return [[float(value) for value in vector] for vector in vectors]
    headers = {"Content-Type": "application/json"}
    api_key = os.environ.get(config.api_key_env, "") if config.api_key_env else ""
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    result: list[list[float]] = []
    with httpx.Client(timeout=45.0) as client:
        for start in range(0, len(texts), config.batch_size):
            batch = texts[start:start + config.batch_size]
            payload: dict[str, object] = {"model": config.model, "input": batch}
            if config.dimensions:
                payload["dimensions"] = config.dimensions
            response = client.post(f"{config.base_url}/embeddings", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json().get("data", [])
            ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
            result.extend([[float(value) for value in item["embedding"]] for item in ordered])
    if len(result) != len(texts):
        raise RuntimeError("embedding 服务返回的向量数量不正确")
    return result


def vector_bytes(values: list[float]) -> bytes:
    packed = array("f", values)
    if packed.itemsize != 4:
        raise RuntimeError("当前平台不支持 32 位浮点向量")
    return packed.tobytes()


def bytes_vector(raw: bytes) -> list[float]:
    values = array("f")
    values.frombytes(raw)
    return [float(value) for value in values]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))
