import shutil
import sys
import tempfile
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storyteller.app import create_app  # noqa: E402
from storyteller.settings import Settings  # noqa: E402
from storyteller.storage.legacy import V3Migrator  # noqa: E402


with tempfile.TemporaryDirectory(prefix="story-teller-v3-e2e-") as temporary:
    content_root = Path(temporary) / "content"
    project_root = content_root / "novel"
    project_root.mkdir(parents=True)
    legacy = project_root / "legacy.db"
    shutil.copy2(ROOT / "tests" / "fixtures" / "schema-v1-demo.db", legacy)
    V3Migrator(legacy, "novel").migrate_to(project_root / "story.db")
    settings = Settings.create(
        ROOT,
        content_root=content_root,
        frontend_root=ROOT / "dist",
        default_project="novel",
    )
    uvicorn.run(create_app(settings), host="127.0.0.1", port=4192, log_level="warning")
