import http.server
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from storyteller.domain.uow import UnitOfWork
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

    # Exercise the same immutable journal a local background save publishes.
    database = Database(project_root)
    with database.read() as connection:
        revision = connection.execute("SELECT revision FROM projects").fetchone()[0]
    UnitOfWork(database, "novel").mutate(
        base_revision=revision, label="static incremental fixture", action="update", entity_kind="plot",
        callback=lambda connection: connection.execute("UPDATE plots SET body_markdown='增量静态正文：恢复后可完整阅读。' WHERE entity_id='plot:1'"),
    )
    ExportCoordinator(database, "novel").export(incremental=True)
    journal_root = site_root / "journal"
    shutil.copytree(ROOT / "dist", journal_root)
    shutil.copy2(project_root / "project.snapshot.json", journal_root / "project.snapshot.json")
    import json
    manifest = json.loads((project_root / "project.snapshot.json").read_text())
    (journal_root / "export-data").mkdir()
    for relative in [manifest["base"], *manifest["patches"]]:
        shutil.copy2(project_root / relative, journal_root / relative)

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

    handler = lambda *args, **kwargs: QuietHandler(*args, directory=site_root, **kwargs)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 4193), handler)
    server.serve_forever()
