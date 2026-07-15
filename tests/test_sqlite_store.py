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

    def test_operation_history_can_undo_and_redo_a_write(self):
        plot_path = self.project_root / "plots" / "001.md"
        original = plot_path.read_text(encoding="utf-8")
        plot_path.write_text(
            "---\nid: 1\nsequence: 1\ntitle: 修改后\n---\n新的正文\n",
            encoding="utf-8",
        )
        self.store.capture_from_exports("/api/plots/update", {
            "label": "编辑剧情：修改后", "entityType": "plot", "action": "update",
        })

        history = self.store.history()
        self.assertEqual("编辑剧情：修改后", history[0]["label"])
        self.assertTrue(history[0]["canUndo"])
        undone = self.store.undo_transaction(history[0]["id"])
        self.assertTrue(undone["ok"])
        self.assertEqual(original, plot_path.read_text(encoding="utf-8"))

        inverse = self.store.history()[0]
        self.assertTrue(inverse["label"].startswith("撤销："))
        self.store.undo_transaction(inverse["id"])
        self.assertIn("新的正文", plot_path.read_text(encoding="utf-8"))

    def test_older_overlapping_operation_requires_newer_change_to_be_undone_first(self):
        plot_path = self.project_root / "plots" / "001.md"
        plot_path.write_text("---\nid: 1\nsequence: 1\ntitle: 第一次\n---\n第一次\n", encoding="utf-8")
        self.store.capture_from_exports("first", {"label": "第一次", "entityType": "plot"})
        first_id = self.store.history()[0]["id"]
        plot_path.write_text("---\nid: 1\nsequence: 1\ntitle: 第二次\n---\n第二次\n", encoding="utf-8")
        self.store.capture_from_exports("second", {"label": "第二次", "entityType": "plot"})

        with self.assertRaisesRegex(ValueError, "后来又被修改"):
            self.store.undo_transaction(first_id)
        second_id = self.store.history()[0]["id"]
        self.store.undo_transaction(second_id)
        self.store.undo_transaction(first_id)
        self.assertIn("初始正文", plot_path.read_text(encoding="utf-8"))

    def test_redone_structural_delete_returns_to_typed_trash_history(self):
        timeline = self.project_root / "timeline.md"
        timeline.write_text("---\nmainLine: 主线\n---\n\n- name: 主线\n- name: 支线\n", encoding="utf-8")
        self.store.capture_from_exports("seed-timeline", {
            "label": "建立时间线", "entityType": "timeline", "action": "system",
        })
        timeline.write_text("---\nmainLine: 主线\n---\n\n- name: 主线\n", encoding="utf-8")
        self.store.capture_from_exports("delete-line", {
            "label": "删除剧情线：支线", "entityType": "timeline", "action": "delete",
            "details": {"deletedItems": [{"type": "timeline", "id": "支线", "title": "支线"}]},
        })
        deletion = self.store.history(deletion_only=True)[0]
        self.store.undo_transaction(deletion["id"])
        self.assertEqual([], [item for item in self.store.history(deletion_only=True) if not item["undone"]])
        inverse = self.store.history()[0]
        self.store.undo_transaction(inverse["id"])
        redone = [item for item in self.store.history(deletion_only=True) if not item["undone"]]
        self.assertEqual("支线", redone[0]["deletedItems"][0]["title"])

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

    def test_version_one_database_is_migrated_with_undo_snapshot_tables(self):
        legacy_root = Path(self.temporary_directory.name) / "legacy"
        legacy_root.mkdir()
        database = legacy_root / "story.db"
        with sqlite3.connect(database) as connection:
            connection.executescript("""
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO metadata(key, value) VALUES('schema_version', '1');
                CREATE TABLE documents (
                    path TEXT PRIMARY KEY, collection TEXT NOT NULL,
                    stable_id TEXT NOT NULL DEFAULT '', display_name TEXT NOT NULL DEFAULT '',
                    sequence INTEGER, content BLOB NOT NULL, content_hash TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL,
                    operation TEXT NOT NULL, changed_paths TEXT NOT NULL
                );
                PRAGMA user_version = 1;
            """)
        legacy_store = SQLiteProjectStore(legacy_root)
        legacy_store.initialize()
        with legacy_store.connect() as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(transactions)")}
            self.assertIn("expires_at", columns)
            self.assertIn("undone_by", columns)
            self.assertIsNotNone(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='transaction_changes'"
            ).fetchone())
            self.assertEqual(2, connection.execute("PRAGMA user_version").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
