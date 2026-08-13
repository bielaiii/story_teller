from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from storyteller.rag.hub_registry import default_hub_state_dir
from storyteller.settings import require_loopback
from storyteller.web_hub_app import create_web_hub_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Story Teller multi-content Web gateway")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    parser.add_argument("--hub-port", type=int, default=4181)
    parser.add_argument("--state-dir", type=Path, default=default_hub_state_dir())
    args = parser.parse_args()
    host = require_loopback(args.bind)
    if not 1 <= args.port <= 65535 or not 1 <= args.hub_port <= 65535:
        raise ValueError("端口不合法")
    state_dir = args.state_dir.expanduser().resolve()
    token_path = state_dir / "token"
    if not token_path.is_file():
        raise RuntimeError(f"Hub token 不存在：{token_path}")
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("Hub token 为空")
    uvicorn.run(
        create_web_hub_app(f"http://127.0.0.1:{args.hub_port}", token),
        host=host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
