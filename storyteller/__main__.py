from __future__ import annotations

import argparse
import os
import signal
import threading
import time
from pathlib import Path

import uvicorn

from storyteller.app import create_app
from storyteller.deployment_lock import ContentDeploymentLock
from storyteller.settings import Settings


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Story Teller local server")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4187)
    parser.add_argument("--content-root", type=Path, default=root / "content")
    parser.add_argument("--frontend-root", type=Path, default=root / "dist")
    parser.add_argument("--default-project", default="")
    parser.add_argument("--projects", default="")
    parser.add_argument("--parent-pid", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    settings = Settings.create(
        root=root,
        content_root=args.content_root,
        frontend_root=args.frontend_root,
        default_project=args.default_project,
        enabled_projects=tuple(item for item in args.projects.split(",") if item),
        host=args.bind,
        port=args.port,
    )
    if args.parent_pid:
        expected_parent = int(args.parent_pid)

        def watch_parent() -> None:
            while os.getppid() == expected_parent:
                time.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)

        if os.getppid() != expected_parent:
            raise RuntimeError("Web Worker 的 Hub 父进程已经退出")
        threading.Thread(target=watch_parent, name="story-hub-parent-watch", daemon=True).start()
    with ContentDeploymentLock(settings.content_root):
        uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
