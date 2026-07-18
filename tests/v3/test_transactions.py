import shutil
import tempfile
import time
import unittest
from pathlib import Path

from storyteller.domain.errors import ConflictError
from storyteller.domain.maintenance import MaintenanceService
from storyteller.domain.services import EntityService
from storyteller.domain.uow import UnitOfWork
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator
from storyteller.storage.repositories import ProjectRepository


ROOT = Path(__file__).resolve().parents[2]


class V3TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "demo"
        self.root.mkdir()
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.root / "legacy.db")
        V3Migrator(self.root / "legacy.db", "demo").migrate_to(self.root / "story.db")
        self.database = Database(self.root)
        self.repository = ProjectRepository(self.database, "demo")
        self.service = EntityService(self.database, "demo")

    def tearDown(self):
        self.temporary.cleanup()

    def revision(self):
        return self.repository.snapshot()["project"]["revision"]

    def test_soft_delete_hides_character_graph_and_edges_then_restore_recovers_them(self):
        before = self.repository.snapshot()
        now = int(time.time())
        result = self.service.delete("character:7", self.revision(), now=now)
        deleted = self.repository.snapshot()
        self.assertNotIn("character:7", {item["entityId"] for item in deleted["characters"]})
        self.assertNotIn("relationship:7__4", {item["entityId"] for item in deleted["relationships"]})
        self.assertEqual(1, len(self.repository.trash()))
        restored = self.service.restore("character:7", result.project_revision, now=now + 1)
        after = self.repository.snapshot()
        self.assertEqual(len(before["characters"]), len(after["characters"]))
        self.assertEqual(len(before["relationships"]), len(after["relationships"]))
        self.assertEqual([], self.repository.trash())
        self.assertEqual(result.project_revision + 1, restored.project_revision)

    def test_plot_delete_keeps_other_sort_keys_and_display_sequence_is_contiguous(self):
        before = {item["entityId"]: item["sortKey"] for item in self.repository.snapshot()["plots"]}
        deleted = self.service.delete("plot:4", self.revision(), now=2_000_000)
        active = self.repository.snapshot()["plots"]
        self.assertEqual(list(range(1, len(active) + 1)), [item["sequence"] for item in active])
        self.assertEqual(
            {key: value for key, value in before.items() if key != "plot:4"},
            {item["entityId"]: item["sortKey"] for item in active},
        )
        self.service.restore("plot:4", deleted.project_revision, now=2_000_001)
        restored = self.repository.snapshot()["plots"]
        self.assertEqual(list(before), [item["entityId"] for item in restored])

    def test_transaction_failure_rolls_back_every_row_and_revision(self):
        revision = self.revision()

        def fail(connection):
            connection.execute("UPDATE entities SET title='不应保存' WHERE id='character:1'")
            raise RuntimeError("injected")

        with self.assertRaisesRegex(RuntimeError, "injected"):
            UnitOfWork(self.database, "demo").mutate(
                base_revision=revision, label="失败注入", action="update",
                entity_kind="character", callback=fail,
            )
        self.assertEqual(revision, self.revision())
        self.assertEqual("林秋", self.repository.entity_detail("character:1")["title"])

    def test_undo_rejects_a_row_changed_by_a_newer_operation(self):
        deleted = self.service.delete("character:7", self.revision(), now=3_000_000)
        self.service.restore("character:7", deleted.project_revision, now=3_000_001)
        with self.assertRaises(ConflictError):
            UnitOfWork(self.database, "demo").undo(deleted.operation_id, self.revision(), now=3_000_002)

    def test_hard_purge_uses_foreign_key_cascade_and_vacuum(self):
        deleted = self.service.delete("character:7", self.revision(), now=4_000_000)
        result = MaintenanceService(self.database, "demo").purge_expired(now=4_000_000 + 8 * 24 * 60 * 60)
        self.assertEqual(2, result["purgedEntities"])
        self.assertEqual(1, result["purgedRelationships"])
        self.assertEqual(4_000_000 + 8 * 24 * 60 * 60, result["checkedAt"])
        with self.database.read() as connection:
            self.assertEqual(
                str(result["checkedAt"]),
                connection.execute(
                    "SELECT value FROM metadata WHERE key='maintenance_last_checked_at'"
                ).fetchone()[0],
            )
        self.assertTrue(result["vacuumed"])
        with self.database.read() as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM characters WHERE entity_id='character:7'").fetchone())
            self.assertFalse(connection.execute("SELECT 1 FROM relationships WHERE from_character_id='character:7' OR to_character_id='character:7'").fetchone())
            self.assertFalse(connection.execute("SELECT 1 FROM entities WHERE id='relationship:7__4'").fetchone())
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))


if __name__ == "__main__":
    unittest.main()
