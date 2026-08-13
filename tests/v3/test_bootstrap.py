from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from storyteller import SCHEMA_VERSION
from storyteller.bootstrap import create_empty_project, prepare_project
from storyteller.deployment_lock import ContentDeploymentLock
from storyteller.exports.version import EXPORT_FORMAT_VERSION
from storyteller.storage.schema import migrate_v4_to_v5


ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary.name) / "demo"
        self.project_root.mkdir()
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.project_root / "story.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_migrates_atomically_exports_and_is_idempotent(self) -> None:
        source_digest = digest(self.project_root / "story.db")
        result = prepare_project(self.project_root)
        self.assertTrue(result["migrated"])
        backup = Path(result["backup"])
        self.assertTrue(backup.is_file())
        self.assertEqual(digest(backup), source_digest)
        snapshot = json.loads((self.project_root / "project.snapshot.json").read_text("utf-8"))
        self.assertTrue(snapshot["readonly"])
        self.assertEqual(len(snapshot["characters"]), 7)
        with sqlite3.connect(self.project_root / "story.db") as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertFalse(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone())
            self.assertEqual(list(connection.execute("PRAGMA foreign_key_check")), [])
            first_revision = connection.execute("SELECT revision FROM projects WHERE id='demo'").fetchone()[0]
            first_checked_at = int(connection.execute(
                "SELECT value FROM metadata WHERE key='maintenance_last_checked_at'"
            ).fetchone()[0])

        second = prepare_project(self.project_root)
        self.assertFalse(second["migrated"])
        self.assertTrue(second["export"]["skipped"])
        with sqlite3.connect(self.project_root / "story.db") as connection:
            self.assertEqual(first_revision, connection.execute(
                "SELECT revision FROM projects WHERE id='demo'"
            ).fetchone()[0])
            second_checked_at = int(connection.execute(
                "SELECT value FROM metadata WHERE key='maintenance_last_checked_at'"
            ).fetchone()[0])
        self.assertEqual(second["maintenance"]["checkedAt"], second_checked_at)
        self.assertGreaterEqual(second_checked_at, first_checked_at)

        content_index_path = self.project_root / "content-index.json"
        content_index = json.loads(content_index_path.read_text(encoding="utf-8"))
        content_index.pop("exportFormatVersion")
        content_index_path.write_text(json.dumps(content_index), encoding="utf-8")
        refreshed = prepare_project(self.project_root)
        self.assertFalse(refreshed["export"].get("skipped", False))
        self.assertEqual(
            EXPORT_FORMAT_VERSION,
            json.loads(content_index_path.read_text(encoding="utf-8"))["exportFormatVersion"],
        )

    def test_create_empty_project_builds_a_current_writable_database_and_exports(self) -> None:
        root = Path(self.temporary.name) / "new-project"
        result = create_empty_project(root, title="新的故事")
        self.assertEqual("new-project", result["project"])
        self.assertTrue((root / "story.db").is_file())
        self.assertTrue((root / "project.snapshot.json").is_file())
        with sqlite3.connect(root / "story.db") as connection:
            self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual(
                ("new-project", "新的故事", 0),
                connection.execute("SELECT id, title, revision FROM projects").fetchone(),
            )
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))
        with self.assertRaisesRegex(FileExistsError, "已经存在"):
            create_empty_project(root, title="重复")

    def test_content_deployment_lock_rejects_a_second_web_owner(self) -> None:
        first = ContentDeploymentLock(self.project_root.parent)
        second = ContentDeploymentLock(self.project_root.parent)
        first.acquire()
        try:
            with self.assertRaisesRegex(RuntimeError, "另一个 Web 服务"):
                second.acquire()
        finally:
            first.close()
        second.acquire()
        second.close()

    def test_prepare_rejects_a_newer_database_without_replacing_it(self) -> None:
        database = self.project_root / "story.db"
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version=99")
            connection.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        before = digest(database)
        with self.assertRaisesRegex(ValueError, "只支持迁移 Schema V1/V2/V3"):
            prepare_project(self.project_root)
        self.assertEqual(digest(database), before)

    def test_prepare_upgrades_schema_v3_with_a_recoverable_backup(self) -> None:
        prepare_project(self.project_root)
        database = self.project_root / "story.db"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                DROP TABLE merge_conflicts;
                DROP TABLE merge_sessions;
                UPDATE metadata SET value='3' WHERE key='schema_version';
                PRAGMA user_version=3;
                """
            )
        result = prepare_project(self.project_root)

        self.assertTrue(result["migrated"])
        self.assertEqual(3, result["sourceSchemaVersion"])
        backup = Path(result["backup"])
        self.assertTrue(backup.name.endswith(".v3-backup.db"))
        self.assertTrue(backup.is_file())
        with sqlite3.connect(backup) as backup_connection:
            self.assertEqual(3, backup_connection.execute("PRAGMA user_version").fetchone()[0])
            backup_count = backup_connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        with sqlite3.connect(database) as connection:
            self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
            self.assertTrue(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_sessions'"
            ).fetchone())
            self.assertGreaterEqual(
                connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                backup_count,
            )
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_prepare_upgrades_schema_v5_with_directional_relationship_impressions(self) -> None:
        database = self.project_root / "story.db"
        shutil.copy2(ROOT / "content" / "demo" / "story.db", database)
        with sqlite3.connect(database) as connection:
            # The checked-in demo database tracks the current schema. Rewind only
            # the columns introduced after V4 so this migration test does not
            # depend on keeping a second stale binary database in the repository.
            connection.executescript(
                """
                ALTER TABLE plots DROP COLUMN story_anchor_side;
                ALTER TABLE plots DROP COLUMN story_anchor_plot_id;
                ALTER TABLE plots DROP COLUMN story_order_mode;
                ALTER TABLE plots DROP COLUMN story_sort_key;
                ALTER TABLE relationships DROP COLUMN graph_line_mode;
                ALTER TABLE relationships DROP COLUMN graph_scope;
                ALTER TABLE relationships DROP COLUMN to_impression;
                ALTER TABLE relationships DROP COLUMN from_impression;
                ALTER TABLE entry_characters DROP COLUMN sort_key;
                ALTER TABLE entry_characters DROP COLUMN status;
                ALTER TABLE entry_characters DROP COLUMN role;
                UPDATE metadata SET value='4' WHERE key='schema_version';
                PRAGMA user_version=4;
                """
            )
            self.assertEqual(4, connection.execute("PRAGMA user_version").fetchone()[0])
            migrate_v4_to_v5(connection)
            self.assertEqual(5, connection.execute("PRAGMA user_version").fetchone()[0])

        result = prepare_project(self.project_root)

        self.assertTrue(result["migrated"])
        self.assertEqual(5, result["sourceSchemaVersion"])
        self.assertTrue(Path(result["backup"]).name.endswith(".v5-backup.db"))
        with sqlite3.connect(database) as connection:
            self.assertEqual(SCHEMA_VERSION, connection.execute("PRAGMA user_version").fetchone()[0])
            columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(relationships)")
            }
            self.assertTrue({"from_impression", "to_impression", "graph_scope", "graph_line_mode"}.issubset(columns))
            member_columns = {
                str(row[1]) for row in connection.execute("PRAGMA table_info(entry_characters)")
            }
            self.assertTrue({"role", "status", "sort_key"}.issubset(member_columns))
            self.assertEqual(
                [("", "")],
                list(connection.execute(
                    "SELECT DISTINCT from_impression, to_impression FROM relationships"
                )),
            )


if __name__ == "__main__":
    unittest.main()
