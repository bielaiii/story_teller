from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CONFIG_NAME = "rag.config.json"


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    provider: str = "builtin"
    model: str = "hash-char-2-3-v1"
    dimensions: int = 384
    base_url: str = "http://127.0.0.1:11434/v1"
    api_key_env: str = "OPENAI_API_KEY"
    batch_size: int = 32

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "EmbeddingConfig":
        raw = value or {}
        provider = str(raw.get("provider") or "builtin").strip().lower()
        if provider not in {"builtin", "openai-compatible", "sentence-transformers", "disabled"}:
            raise ValueError("embedding provider 仅支持 builtin、openai-compatible、sentence-transformers 或 disabled")
        model = str(raw.get("model") or ("none" if provider == "disabled" else "hash-char-2-3-v1")).strip()
        if not model:
            raise ValueError("embedding model 不能为空")
        if provider == "builtin" and model not in {"hash-char-2-3-v1", "hash-char-3-v1"}:
            raise ValueError("builtin provider 仅支持 hash-char-2-3-v1 或 hash-char-3-v1")
        dimensions = int(raw.get("dimensions") or 384)
        if not 32 <= dimensions <= 8192:
            raise ValueError("embedding dimensions 必须在 32 到 8192 之间")
        batch_size = int(raw.get("batchSize", raw.get("batch_size", 32)) or 32)
        if not 1 <= batch_size <= 256:
            raise ValueError("embedding batchSize 必须在 1 到 256 之间")
        base_url = str(raw.get("baseUrl", raw.get("base_url", "http://127.0.0.1:11434/v1"))).strip().rstrip("/")
        api_key_env = str(raw.get("apiKeyEnv", raw.get("api_key_env", "OPENAI_API_KEY"))).strip()
        if provider == "openai-compatible" and not base_url:
            raise ValueError("openai-compatible provider 需要 baseUrl")
        return cls(
            provider=provider,
            model=model,
            dimensions=dimensions,
            base_url=base_url,
            api_key_env=api_key_env,
            batch_size=batch_size,
        )

    @property
    def model_key(self) -> str:
        return f"{self.provider}:{self.model}:{self.dimensions}"

    def public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "baseUrl": self.base_url,
            "apiKeyEnv": self.api_key_env,
            "batchSize": self.batch_size,
            "apiKeyAvailable": bool(self.api_key_env and os.environ.get(self.api_key_env)),
        }

    def stored_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return {
            "provider": value["provider"],
            "model": value["model"],
            "dimensions": value["dimensions"],
            "baseUrl": value["base_url"],
            "apiKeyEnv": value["api_key_env"],
            "batchSize": value["batch_size"],
        }


def config_path(project_root: Path) -> Path:
    return Path(project_root) / CONFIG_NAME


def load_config(project_root: Path) -> EmbeddingConfig:
    path = config_path(project_root)
    if not path.exists():
        return EmbeddingConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 {CONFIG_NAME}：{error}") from error
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_NAME} 必须是 JSON 对象")
    return EmbeddingConfig.from_dict(raw.get("embedding") if "embedding" in raw else raw)


def save_config(project_root: Path, config: EmbeddingConfig) -> Path:
    path = config_path(project_root)
    temporary = path.with_suffix(".json.tmp")
    payload = {"version": 1, "embedding": config.stored_dict()}
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path
