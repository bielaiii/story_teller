from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

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
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertFalse(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone())
            self.assertEqual(list(connection.execute("PRAGMA foreign_key_check")), [])

        migrated_digest = digest(self.project_root / "story.db")
        second = prepare_project(self.project_root)
        self.assertFalse(second["migrated"])
        self.assertTrue(second["export"]["skipped"])
        self.assertEqual(digest(self.project_root / "story.db"), migrated_digest)

    def test_prepare_rejects_a_newer_database_without_replacing_it(self) -> None:
        database = self.project_root / "story.db"
        with sqlite3.connect(database) as connection:
            connection.execute("PRAGMA user_version=99")
            connection.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        before = digest(database)
        with self.assertRaisesRegex(ValueError, "只支持迁移 Schema V1/V2"):
            prepare_project(self.project_root)
        self.assertEqual(digest(database), before)


if __name__ == "__main__":
    unittest.main()
