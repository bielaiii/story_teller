from __future__ import annotations

import argparse
from pathlib import Path

from storyteller.rag.manager import RagManager
from storyteller.rag.mcp import create_mcp_server
from storyteller.settings import Settings


def main() -> None:
    framework_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Story Teller project-scoped stdio MCP server")
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--default-project", default="")
    args = parser.parse_args()
    settings = Settings.create(
        root=framework_root,
        content_root=args.content_root,
        frontend_root=framework_root / "dist",
        default_project=args.default_project,
    )
    server = create_mcp_server(RagManager(settings), settings)
    server.run("stdio")


if __name__ == "__main__":
    main()
