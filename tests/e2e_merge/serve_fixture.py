import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storyteller.app import create_app  # noqa: E402
from storyteller.merge_driver import build_merge  # noqa: E402
from storyteller.settings import Settings  # noqa: E402
from storyteller.storage.legacy import V3Migrator  # noqa: E402


def edit_summary(path: Path, summary: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'", (summary,)
        )
        connection.execute(
            "UPDATE entities SET revision=revision+1, updated_at=updated_at+1 WHERE id='plot:1'"
        )
        connection.execute(
            "UPDATE projects SET revision=revision+1, updated_at=updated_at+1 WHERE id='novel'"
        )


with tempfile.TemporaryDirectory(prefix="story-teller-merge-e2e-") as temporary:
    root = Path(temporary)
    content_root = root / "content"
    project_root = content_root / "novel"
    project_root.mkdir(parents=True)
    legacy = root / "legacy.db"
    base = root / "base.db"
    ours = root / "ours.db"
    theirs = root / "theirs.db"
    shutil.copy2(ROOT / "tests" / "fixtures" / "schema-v1-demo.db", legacy)
    V3Migrator(legacy, "novel").migrate_to(base)
    shutil.copy2(base, ours)
    shutil.copy2(base, theirs)
    edit_summary(ours, "当前电脑保留的摘要")
    edit_summary(theirs, "另一台电脑写下的新摘要")
    build_merge(
        base,
        ours,
        theirs,
        project_root / "story.db",
        "content/novel/story.db",
    )
    settings = Settings.create(
        ROOT,
        content_root=content_root,
        frontend_root=ROOT / "dist",
        default_project="novel",
    )
    uvicorn.run(create_app(settings), host="127.0.0.1", port=4194, log_level="warning")
