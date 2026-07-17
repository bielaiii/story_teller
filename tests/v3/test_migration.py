import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from storyteller.domain.services import EntityService
from storyteller.exports import ExportCoordinator
from storyteller.exports.recovery import EXCLUDED_TABLES, RecoveryImporter
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator, parse_markdown


ROOT = Path(__file__).resolve().parents[2]


class V3MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "demo"
        self.root.mkdir()
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.root / "legacy.db")
        self.report = V3Migrator(self.root / "legacy.db", "demo").migrate_to(self.root / "story.db")
        self.database = Database(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_migration_normalizes_every_collection_and_preserves_all_bodies(self):
        self.assertEqual(3, self.report["targetSchemaVersion"])
        self.assertEqual(self.report["bodyHashCount"], self.report["bodyHashesVerified"])
        self.assertEqual("ok", self.report["foreignKeyCheck"])
        self.assertEqual(
            {"characters": 7, "plots": 9, "entries": 8, "fragments": 3, "relationships": 9, "timeline_lines": 5, "chapters": 3},
            self.report["counts"],
        )
        with self.database.read() as connection:
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))
            self.assertFalse(connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='documents'"
            ).fetchone())
            gradient = connection.execute(
                "SELECT gradient FROM characters WHERE entity_id='character:1'"
            ).fetchone()[0]
            self.assertEqual("linear-gradient(135deg, #2aa79b, #3867b7)", gradient)
            character_references = {
                str(row[0]) for row in connection.execute(
                    "SELECT target_entity_id FROM entity_references WHERE source_entity_id='character:1'"
                )
            }
            self.assertTrue({"plot:1", "plot:3", "plot:6"}.issubset(character_references))
            entry_references = {
                str(row[0]) for row in connection.execute(
                    "SELECT target_entity_id FROM entity_references WHERE source_entity_id='entry:archive'"
                )
            }
            self.assertTrue({"plot:1", "plot:6"}.issubset(entry_references))
            self.assertTrue(connection.execute(
                "SELECT 1 FROM plot_characters WHERE plot_id='plot:3' AND character_id='character:1'"
            ).fetchone())
            self.assertTrue(connection.execute(
                "SELECT 1 FROM plot_entries WHERE plot_id='plot:6' AND entry_id='entry:archive'"
            ).fetchone())

    def test_export_is_deterministic_and_static_snapshot_contains_full_bodies(self):
        coordinator = ExportCoordinator(self.database, "demo")
        coordinator.export()
        first = {
            path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.root.rglob("*")
            if path.is_file() and path.name not in {"story.db", "legacy.db"}
        }
        coordinator.export()
        second = {
            path.relative_to(self.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.root.rglob("*")
            if path.is_file() and path.name not in {"story.db", "legacy.db"}
        }
        self.assertEqual(first, second)
        snapshot = json.loads((self.root / "project.snapshot.json").read_text(encoding="utf-8"))
        self.assertTrue(snapshot["readonly"])
        self.assertIn("午夜求救", snapshot["plots"][0]["body"])
        self.assertNotIn("documents", snapshot)

    def test_recovery_snapshot_rebuilds_trash_history_and_stable_references(self):
        with self.database.read() as connection:
            revision = int(connection.execute(
                "SELECT revision FROM projects WHERE id='demo'"
            ).fetchone()[0])
            deleted_id = str(connection.execute(
                "SELECT entity_id FROM active_fragments ORDER BY entity_id LIMIT 1"
            ).fetchone()[0])
        EntityService(self.database, "demo").delete(deleted_id, revision, now=1_900_000_000)

        ExportCoordinator(self.database, "demo").export()
        restored_root = Path(self.temporary.name) / "restored"
        restored_database_path = restored_root / "story.db"
        result = RecoveryImporter(self.root, "demo").import_to(restored_database_path)
        self.assertTrue(result["ok"])
        restored = Database(restored_root)

        with self.database.read() as source, restored.read() as target:
            tables = [
                str(row[0]) for row in source.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                ) if str(row[0]) not in EXCLUDED_TABLES
            ]
            for table in tables:
                columns = [str(row[1]) for row in source.execute(f'PRAGMA table_info("{table}")')]
                primary_keys = [
                    str(row[1]) for row in sorted(
                        (item for item in source.execute(f'PRAGMA table_info("{table}")') if int(item[5]) > 0),
                        key=lambda item: int(item[5]),
                    )
                ]
                order = primary_keys or columns
                order_sql = ", ".join(f'"{column}"' for column in order)
                source_rows = [tuple(row) for row in source.execute(f'SELECT * FROM "{table}" ORDER BY {order_sql}')]
                target_rows = [tuple(row) for row in target.execute(f'SELECT * FROM "{table}" ORDER BY {order_sql}')]
                self.assertEqual(source_rows, target_rows, table)
            self.assertTrue(target.execute(
                "SELECT 1 FROM entities WHERE id=? AND deleted_at IS NOT NULL", (deleted_id,)
            ).fetchone())
            self.assertTrue(target.execute(
                "SELECT 1 FROM operations WHERE action='delete' AND entity_kind='fragment'"
            ).fetchone())
            self.assertGreater(int(target.execute(
                "SELECT COUNT(*) FROM entity_references"
            ).fetchone()[0]), 0)

    def test_schema_v2_history_is_migrated_without_becoming_an_executable_legacy_undo(self):
        v2_source = Path(self.temporary.name) / "schema-v2.db"
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", v2_source)
        with sqlite3.connect(v2_source) as connection:
            for statement in (
                "ALTER TABLE transactions ADD COLUMN label TEXT NOT NULL DEFAULT ''",
                "ALTER TABLE transactions ADD COLUMN entity_type TEXT NOT NULL DEFAULT 'content'",
                "ALTER TABLE transactions ADD COLUMN action TEXT NOT NULL DEFAULT 'update'",
                "ALTER TABLE transactions ADD COLUMN details TEXT NOT NULL DEFAULT '{}'",
                "ALTER TABLE transactions ADD COLUMN expires_at INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE transactions ADD COLUMN undone_by INTEGER",
            ):
                connection.execute(statement)
            connection.executescript(
                """
                CREATE TABLE transaction_changes (
                    transaction_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    before_content BLOB,
                    after_content BLOB,
                    PRIMARY KEY(transaction_id, path),
                    FOREIGN KEY(transaction_id) REFERENCES transactions(id) ON DELETE CASCADE
                );
                UPDATE transactions SET
                    label='V2 示例历史', entity_type='project', action='system',
                    details='{}', expires_at=4000000000;
                UPDATE metadata SET value='2' WHERE key='schema_version';
                PRAGMA user_version=2;
                """
            )
        v2_target = Path(self.temporary.name) / "v2-migrated.db"
        report = V3Migrator(v2_source, "demo").migrate_to(v2_target)
        self.assertEqual(2, report["sourceSchemaVersion"])
        with sqlite3.connect(v2_target) as connection:
            connection.row_factory = sqlite3.Row
            operation = connection.execute(
                "SELECT * FROM operations WHERE label='V2 示例历史'"
            ).fetchone()
            self.assertIsNotNone(operation)
            self.assertEqual("legacy", operation["action"])
            details = json.loads(operation["details_json"])
            self.assertTrue(details["legacySnapshotArchived"])
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))


if __name__ == "__main__":
    unittest.main()
