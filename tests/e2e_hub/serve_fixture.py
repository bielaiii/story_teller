from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HUB_ROOT = Path(
    os.environ.get("STORY_TELLER_HUB_ROOT", ROOT.parent.parent / "story_teller_hub")
).expanduser().resolve()
sys.path.insert(0, str(HUB_ROOT))
sys.path.insert(0, str(ROOT))

from storyteller_hub.cli import (  # noqa: E402
    acquire_web_lease,
    ensure_token,
    heartbeat_web_lease,
    register_workspace,
    release_web_lease,
    start_or_reuse_hub,
    start_or_reuse_web_hub,
)
from storyteller.storage.legacy import V3Migrator  # noqa: E402


HUB_PORT = 4193
WEB_PORT = 4194


def add_project(repository: Path, project: str) -> None:
    project_root = repository / "content" / project
    project_root.mkdir(parents=True)
    legacy = project_root / "legacy.db"
    shutil.copy2(ROOT / "tests" / "fixtures" / "schema-v1-demo.db", legacy)
    V3Migrator(legacy, project).migrate_to(project_root / "story.db")


def make_repository(base: Path, name: str, projects: list[str]) -> Path:
    repository = base / name
    (repository / "content").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (repository / "story_teller").symlink_to(ROOT, target_is_directory=True)
    for project in projects:
        add_project(repository, project)
    return repository


running = True


def stop(_signum, _frame) -> None:
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

with tempfile.TemporaryDirectory(prefix="story-teller-hub-e2e-") as temporary:
    base = Path(temporary)
    state_dir = base / "state"
    alpha = make_repository(base, "alpha-content", ["demo", "side-story"])
    beta = make_repository(base, "beta-content", ["demo"])
    token = ensure_token(state_dir)
    start_or_reuse_hub(
        host="127.0.0.1", port=HUB_PORT, state_dir=state_dir,
        hub_root=HUB_ROOT, timeout=20,
    )
    start_or_reuse_web_hub(
        host="127.0.0.1", port=WEB_PORT, hub_port=HUB_PORT,
        state_dir=state_dir, hub_root=HUB_ROOT, timeout=20,
    )
    leases: dict[str, str] = {}
    try:
        for repository, name in ((alpha, "Alpha Content"), (beta, "Beta Content")):
            registered = register_workspace(
                host="127.0.0.1", port=HUB_PORT, token=token,
                repository_root=repository, content_root=repository / "content",
                framework_root=repository / "story_teller", project="demo",
                display_name=name,
            )["workspace"]
            workspace_id = registered["workspaceId"]
            leases[workspace_id] = acquire_web_lease(
                host="127.0.0.1", port=HUB_PORT, token=token, workspace_id=workspace_id,
            )["lease"]
        while running:
            time.sleep(3)
            for workspace_id, lease in list(leases.items()):
                try:
                    heartbeat_web_lease(
                        host="127.0.0.1", port=HUB_PORT, token=token,
                        workspace_id=workspace_id, lease=lease,
                    )
                except RuntimeError:
                    leases.pop(workspace_id, None)
    finally:
        for workspace_id, lease in leases.items():
            try:
                release_web_lease(
                    host="127.0.0.1", port=HUB_PORT, token=token,
                    workspace_id=workspace_id, lease=lease,
                )
            except RuntimeError:
                pass
        for name in ("web-hub.pid", "hub.pid"):
            try:
                pid = int((state_dir / name).read_text().strip())
                os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ProcessLookupError, ValueError):
                pass
