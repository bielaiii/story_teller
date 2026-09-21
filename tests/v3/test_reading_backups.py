import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from storyteller.backups import Backups, restore_backup
from storyteller.exports.reading import ReadingCopies
from tests.v3 import test_incremental_audit as audit


class ReadingBackupTests(unittest.TestCase):
    setUp = audit.IncrementalAuditTests.setUp
    mutate = audit.IncrementalAuditTests.mutate

    def test_all_collections_and_noop_keeps_mtime(self):
        reader = ReadingCopies(self.db, "demo")
        result = reader.generate()
        self.assertEqual("ready", result["status"])
        for folder in ("设定", "人物", "碎片", "篇章"):
            self.assertTrue((reader.root / folder / "README.md").is_file())
        before = {p: p.stat().st_mtime_ns for p in reader.root.rglob("*") if p.is_file()}
        reader.generate()
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})

    def test_rename_delete_preserves_unmanaged_and_repairs_missing(self):
        reader = ReadingCopies(self.db, "demo")
        reader.generate()
        index = json.loads((reader.root / ".index.json").read_text())
        path = reader.root / index["records"]["plot:1"]["path"]
        path.unlink()
        reader.generate()
        self.assertTrue(path.is_file())
        note = reader.root / "我的笔记.md"
        note.write_text("keep")
        self.mutate(lambda c: c.execute("UPDATE entities SET title='新名字' WHERE id='plot:1'"))
        reader.generate()
        self.assertFalse(path.exists())
        self.mutate(lambda c: c.execute("UPDATE entities SET deleted_at=1,purge_at=100 WHERE id='plot:1'"))
        reader.generate()
        self.assertEqual("keep", note.read_text())
        self.assertNotIn("plot:1", json.loads((reader.root / ".index.json").read_text())["records"])

    def test_settings_are_audited_and_disabled_generation_can_be_forced(self):
        reader = ReadingCopies(self.db, "demo")
        with self.db.read() as c:
            revision = c.execute("SELECT revision FROM projects").fetchone()[0]
        result = reader.configure(False, revision)
        self.assertIsNotNone(result.operation_id)
        reader.generate()
        self.assertFalse((reader.root / "README.md").exists())
        reader.generate(force=True)
        self.assertTrue((reader.root / "README.md").exists())
        self.uow.undo(result.operation_id, result.project_revision)
        self.assertTrue(reader.status()["enabled"])

    def test_failure_does_not_advance_index_and_retry_succeeds(self):
        reader = ReadingCopies(self.db, "demo")
        reader.generate()
        old_revision = reader.status()["exportedRevision"]
        self.mutate(lambda c: c.execute("UPDATE entities SET title='after' WHERE id='plot:1'"))
        real = __import__("storyteller.exports.reading", fromlist=["atomic_write"]).atomic_write
        def failed(path, content):
            if path.suffix == ".md":
                raise OSError("disk full")
            return real(path, content)
        with patch("storyteller.exports.reading.atomic_write", side_effect=failed):
            with self.assertRaises(OSError):
                reader.generate()
        self.assertEqual(old_revision, reader.status()["exportedRevision"])
        self.assertEqual("failed", reader.status()["status"])
        reader.generate()
        self.assertEqual("ready", reader.status()["status"])

    def test_symlink_is_rejected(self):
        reader = ReadingCopies(self.db, "demo")
        outside = self.db.project_root / "outside"
        outside.mkdir()
        reader.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            reader.generate()
        self.assertEqual([], list(outside.iterdir()))

    def test_backup_contains_blob_and_restore_refuses_overwrite(self):
        self.mutate(lambda c: c.execute("INSERT INTO assets VALUES ('a','demo',NULL,'a.bin','application/octet-stream',?,'hash',0)", (b"test",)))
        backup = Backups(self.db, "demo")
        item = backup.create()
        destination = self.db.project_root / "restored" / "demo"
        restore_backup(backup.root / item["filename"], destination)
        with sqlite3.connect(destination / "story.db") as c:
            self.assertEqual(b"test", c.execute("SELECT content FROM assets").fetchone()[0])
        with self.assertRaises(FileExistsError):
            restore_backup(backup.root / item["filename"], destination)

    def test_retention_and_due_revision(self):
        backups = Backups(self.db, "demo")
        manual = backups.create("manual")
        for i in range(9):
            with patch("storyteller.backups.time.time", return_value=100000 + i):
                backups.create("daily")
        items = backups.status()["items"]
        self.assertEqual(7, len([i for i in items if i["kind"] == "daily"]))
        self.assertTrue((backups.root / manual["filename"]).is_file())
        self.assertFalse(backups.due())
        self.mutate(lambda c: c.execute("UPDATE entities SET title='changed' WHERE id='plot:1'"))
        self.assertTrue(backups.due())

    def test_same_names_and_long_titles_do_not_collide(self):
        reader = ReadingCopies(self.db, "demo")
        self.mutate(lambda c: c.execute("UPDATE entities SET title=? WHERE kind='plot'", ("同名/*" * 100,)))
        reader.generate()
        index = json.loads((reader.root / ".index.json").read_text())
        files = [value["path"] for key, value in index["records"].items() if key.startswith("plot:")]
        self.assertEqual(len(files), len(set(files)))
        self.assertTrue(all(len(Path(p).name.encode()) < 255 for p in files))
