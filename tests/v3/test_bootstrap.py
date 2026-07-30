from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from storyteller import SCHEMA_VERSION
from storyteller.bootstrap import prepare_project


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
            self.assertEqual(
                backup_count,
                connection.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
            )
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))


if __name__ == "__main__":
    unittest.main()
