from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from storyteller.rag.app import create_rag_app
from storyteller.settings import Settings


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Story Teller standalone RAG server")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4181)
    parser.add_argument("--content-root", type=Path, default=root / "content")
    parser.add_argument("--default-project", default="")
    args = parser.parse_args()
    settings = Settings.create(
        root=root,
        content_root=args.content_root,
        frontend_root=root / "dist",
        default_project=args.default_project,
        host=args.bind,
        port=args.port,
    )
    uvicorn.run(create_rag_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
