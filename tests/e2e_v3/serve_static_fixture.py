import http.server
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storyteller.exports import ExportCoordinator  # noqa: E402
from storyteller.storage.connection import Database  # noqa: E402
from storyteller.storage.legacy import V3Migrator  # noqa: E402


with tempfile.TemporaryDirectory(prefix="story-teller-static-e2e-") as temporary:
    site_root = Path(temporary) / "site"
    project_root = Path(temporary) / "novel"
    project_root.mkdir()
    legacy = project_root / "legacy.db"
    shutil.copy2(ROOT / "tests" / "fixtures" / "schema-v1-demo.db", legacy)
    V3Migrator(legacy, "novel").migrate_to(project_root / "story.db")
    ExportCoordinator(Database(project_root), "novel").export()
    shutil.copytree(ROOT / "dist", site_root)
    shutil.copy2(project_root / "project.snapshot.json", site_root / "project.snapshot.json")

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=site_root, **kwargs)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 4193), handler)
    server.serve_forever()
