import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyteller.domain.uow import UnitOfWork
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator

ROOT = Path(__file__).resolve().parents[2]


class IncrementalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        shutil.copy2(ROOT / 'tests/fixtures/schema-v1-demo.db', root / 'legacy.db')
        V3Migrator(root / 'legacy.db', 'demo').migrate_to(root / 'story.db')
        self.db = Database(root)
        self.uow = UnitOfWork(self.db, 'demo')

    def mutate(self, callback):
        with self.db.read() as c:
            revision = c.execute('SELECT revision FROM projects').fetchone()[0]
        return self.uow.mutate(base_revision=revision, label='test', action='update',
                               entity_kind='plot', callback=callback)

    def test_journal_matches_full_snapshot_with_replace_cascade_and_savepoint(self):
        with self.db.write() as c:
            c.execute("INSERT INTO assets VALUES ('asset','demo','plot:1','a.bin','application/octet-stream',?,'hash',0)", (b'\x00\xff' * 100,))
        observed = {}

        def update(c):
            tables = self.uow._tables(c)
            before = self.uow._snapshot(c, tables)
            c.execute("SAVEPOINT discarded")
            c.execute("UPDATE entities SET title='discarded' WHERE id='plot:2'")
            c.execute("ROLLBACK TO discarded")
            c.execute("RELEASE discarded")
            c.execute("UPDATE entities SET title='first' WHERE id='plot:1'")
            c.execute("UPDATE entities SET title='second' WHERE id='plot:1'")
            c.execute("INSERT OR REPLACE INTO assets VALUES ('asset','demo','plot:1','a.bin','application/octet-stream',?,'new',0)", (b'new',))
            c.execute("UPDATE assets SET id='renamed' WHERE id='asset'")
            c.execute("DELETE FROM entities WHERE id='plot:2'")
            observed['changes'] = self.uow._changes(before, self.uow._snapshot(c, tables))
        result = self.mutate(update)
        with self.db.read() as c:
            actual = [dict(table=r['table_name'], primaryKey=r['primary_key_json'], before=r['before_json'], after=r['after_json'])
                      for r in c.execute('SELECT * FROM operation_changes WHERE operation_id=? ORDER BY table_name, primary_key_json', (result.operation_id,))]
        self.assertEqual(observed['changes'], actual)
        self.uow.undo(result.operation_id, result.project_revision)
        with self.db.read() as c:
            self.assertEqual(b'\x00\xff' * 100, c.execute("SELECT content FROM assets WHERE id='asset'").fetchone()[0])
            self.assertIsNotNone(c.execute("SELECT id FROM entities WHERE id='plot:2'").fetchone())

    def test_untouched_blob_never_enters_python_audit(self):
        with self.db.write() as c:
            c.execute("INSERT INTO assets VALUES ('asset','demo',NULL,'a.bin','application/octet-stream',?,'hash',0)", (b'x' * 4_000_000,))
        from storyteller.domain.uow import encode_value
        def encode(value):
            self.assertNotIsInstance(value, bytes)
            return encode_value(value)
        with patch('storyteller.domain.uow.encode_value', side_effect=encode), patch.object(UnitOfWork, '_snapshot', side_effect=AssertionError('full scan')):
            self.mutate(lambda c: c.execute("UPDATE entities SET title='new' WHERE id='plot:1'"))

    def test_noop_and_failure_leave_no_history_or_revision(self):
        def noop(c):
            c.execute("UPDATE entities SET revision=revision+1 WHERE id='plot:1'")
        self.assertIsNone(self.mutate(noop).operation_id)
        def fail(c):
            c.execute("UPDATE entities SET title='bad' WHERE id='plot:1'")
            raise ValueError('abort')
        with self.assertRaises(ValueError):
            self.mutate(fail)
        result = self.mutate(lambda c: c.execute("UPDATE entities SET title='good' WHERE id='plot:1'"))
        with self.db.read() as c:
            self.assertEqual(1, c.execute('SELECT count(*) FROM operations WHERE action=?', ('update',)).fetchone()[0])
            change = c.execute("SELECT before_json FROM operation_changes WHERE operation_id=? AND table_name='entities'", (result.operation_id,)).fetchone()
            self.assertNotEqual('bad', json.loads(change[0])['title'])
