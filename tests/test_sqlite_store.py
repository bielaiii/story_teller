import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlite_store import SQLiteProjectStore


class SQLiteProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name) / "novel"
        (self.project_root / "characters").mkdir(parents=True)
        (self.project_root / "plots").mkdir()
        (self.project_root / "characters" / "1-沈清妙.md").write_text(
            "---\nid: 1\nname: 沈清妙\n---\n初始档案\n",
            encoding="utf-8",
        )
        (self.project_root / "plots" / "001.md").write_text(
            "---\nid: 1\nsequence: 1\ntitle: 开始\n---\n初始正文\n",
            encoding="utf-8",
        )
        (self.project_root / "manifest.md").write_text(
            "---\ntitle: 测试项目\nchapters: [act1]\n---\n",
            encoding="utf-8",
        )
        self.store = SQLiteProjectStore(self.project_root)
        self.store.initialize()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_initial_import_creates_database_and_snapshot(self):
        self.assertTrue((self.project_root / "story.db").is_file())
        snapshot = self.store.snapshot()
        self.assertEqual(["./characters/1-沈清妙.md"], snapshot["collections"]["characters"])
        self.assertIn("初始正文", snapshot["documents"]["plots/001.md"])
        self.assertEqual("sqlite", "sqlite")

    def test_reopening_database_does_not_modify_database_bytes(self):
        before = self.store.database_path.read_bytes()
        self.store.initialize()
        self.assertEqual(before, self.store.database_path.read_bytes())

    def test_database_restores_exports_and_ignores_manual_source_edit(self):
        character_path = self.project_root / "characters" / "1-沈清妙.md"
        original_modified_time = character_path.stat().st_mtime_ns
        self.store.materialize_exports(clean=True)
        self.assertEqual(original_modified_time, character_path.stat().st_mtime_ns)
        character_path.write_text("手工篡改", encoding="utf-8")
        extra_path = self.project_root / "characters" / "2-手工添加.md"
        extra_path.write_text("不会进入数据库", encoding="utf-8")
        self.store.initialize()
        self.assertIn("初始档案", character_path.read_text(encoding="utf-8"))
        self.assertFalse(extra_path.exists())
        self.assertNotIn("characters/2-手工添加.md", self.store.snapshot()["documents"])

    def test_capture_is_atomic_when_unique_stable_id_is_violated(self):
        duplicate = self.project_root / "characters" / "duplicate.md"
        duplicate.write_text("---\nid: 1\nname: 另一个人物\n---\n重复\n", encoding="utf-8")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.capture_from_exports("invalid-duplicate")
        self.store.materialize_exports(clean=True)
        self.assertFalse(duplicate.exists())
        self.assertEqual(3, self.store.document_count())

    def test_successful_capture_updates_database_and_transaction_history(self):
        plot_path = self.project_root / "plots" / "001.md"
        plot_path.write_text("---\nid: 1\nsequence: 1\ntitle: 开始\n---\n数据库正文\n", encoding="utf-8")
        changed = self.store.capture_from_exports("plot-update")
        self.assertIn("plots/001.md", changed)
        self.assertIn("数据库正文", self.store.snapshot()["documents"]["plots/001.md"])
        self.assertEqual("plot-update", self.store.info()["lastOperation"])

    def test_renaming_export_path_keeps_the_same_stable_id(self):
        old_path = self.project_root / "characters" / "1-沈清妙.md"
        new_path = self.project_root / "characters" / "1-沈清妍.md"
        old_path.replace(new_path)
        new_path.write_text("---\nid: 1\nname: 沈清妍\n---\n改名后的档案\n", encoding="utf-8")
        self.store.capture_from_exports("character-rename")
        snapshot = self.store.snapshot()
        self.assertEqual(["./characters/1-沈清妍.md"], snapshot["collections"]["characters"])
        self.assertIn("改名后的档案", snapshot["documents"]["characters/1-沈清妍.md"])

    def test_newer_database_schema_is_rejected_without_rewriting_it(self):
        with self.store.connect() as connection:
            connection.execute("PRAGMA user_version = 999")
        with self.assertRaisesRegex(RuntimeError, "请先更新 Story Teller"):
            self.store.initialize()
        with sqlite3.connect(self.store.database_path) as connection:
            self.assertEqual(999, connection.execute("PRAGMA user_version").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
