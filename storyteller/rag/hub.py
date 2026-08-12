from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from storyteller.rag.hub_app import create_hub_app
from storyteller.rag.hub_registry import default_hub_state_dir
from storyteller.settings import require_loopback


def main() -> None:
    parser = argparse.ArgumentParser(description="Story World central MCP hub")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4181)
    parser.add_argument("--state-dir", type=Path, default=default_hub_state_dir())
    args = parser.parse_args()
    host = require_loopback(args.bind)
    if not 1 <= args.port <= 65535:
        raise ValueError("端口不合法")
    state_dir = args.state_dir.expanduser().resolve()
    token_path = state_dir / "token"
    if not token_path.is_file():
        raise RuntimeError(f"Hub token 不存在：{token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("Hub token 为空")
    os.chdir(Path(__file__).resolve().parents[2])
    uvicorn.run(
        create_hub_app(state_dir / "registry.json", token, host=host),
        host=host, port=args.port, log_level="info",
    )


if __name__ == "__main__":
    main()
