import json
import multiprocessing
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from storyteller.exports.coordinator import ExportCoordinator
from storyteller.exports.markdown import MarkdownExporter
from storyteller.storage.connection import Database
from tests.v3 import test_incremental_audit as audit


def competing_export(root, started, finished):
    started.set()
    ExportCoordinator(Database(Path(root)), 'demo').export()
    finished.set()


class ExportConsistencyTests(unittest.TestCase):
    setUp = audit.IncrementalAuditTests.setUp
    mutate = audit.IncrementalAuditTests.mutate

    def test_all_formats_share_snapshot_while_another_process_waits_to_publish(self):
        first = self.mutate(lambda c: c.execute("UPDATE entities SET title='first' WHERE id='plot:1'"))
        ctx = multiprocessing.get_context('spawn')
        started, finished = ctx.Event(), ctx.Event()
        process = ctx.Process(target=competing_export, args=(str(self.db.project_root), started, finished))
        render = MarkdownExporter.render
        captured = {}
        replace = ExportCoordinator._replace_exports
        def paused(exporter):
            files = render(exporter)
            process.start()
            self.assertTrue(started.wait(10))
            self.assertFalse(finished.wait(0.2), 'another process published through the lock')
            self.mutate(lambda c: c.execute("UPDATE entities SET title='second' WHERE id='plot:1'"))
            return files
        def capture(coordinator, files):
            captured.update(files)
            replace(coordinator, files)
        try:
            with patch.object(MarkdownExporter, 'render', paused), patch.object(ExportCoordinator, '_replace_exports', capture):
                ExportCoordinator(self.db, 'demo').export()
            process.join(15)
            self.assertEqual(0, process.exitcode)
            self.assertTrue(finished.is_set())
        finally:
            if process.is_alive():
                process.terminate()
                process.join()
        static = json.loads(captured['project.snapshot.json'])
        self.assertEqual(first.project_revision, static['project']['revision'])
        self.assertEqual('first', next(p['title'] for p in static['plots'] if p['entityId'] == 'plot:1'))
        recovery = json.loads(captured['recovery.snapshot.json'])['tables']
        projects = recovery['projects']
        self.assertEqual(first.project_revision, projects['rows'][0][projects['columns'].index('revision')])
        entities = recovery['entities']
        row = next(r for r in entities['rows'] if r[entities['columns'].index('id')] == 'plot:1')
        self.assertEqual('first', row[entities['columns'].index('title')])
        self.assertTrue(any(b'first' in content for name, content in captured.items() if name.startswith('plots/')))
        latest = json.loads((self.db.project_root / 'project.snapshot.json').read_text())
        self.assertEqual(first.project_revision + 1, latest['project']['revision'])
        self.assertEqual('second', next(p['title'] for p in latest['plots'] if p['entityId'] == 'plot:1'))
        with self.db.read() as c:
            self.assertEqual(('ready', first.project_revision + 1, first.project_revision + 1),
                             tuple(c.execute('SELECT status,requested_revision,exported_revision FROM export_state').fetchone()))

    def test_late_success_and_failure_cannot_regress_ready_state(self):
        first = self.mutate(lambda c: c.execute("UPDATE entities SET title='first' WHERE id='plot:1'"))
        last = self.mutate(lambda c: c.execute("UPDATE entities SET title='second' WHERE id='plot:1'"))
        exporter = ExportCoordinator(self.db, 'demo')
        exporter.export()
        exporter._record_state(first.project_revision, 'ready', '')
        exporter._record_state(first.project_revision, 'failed', 'late failure')
        exporter._record_state(last.project_revision, 'failed', 'same version late failure')
        with self.db.read() as c:
            self.assertEqual((last.project_revision, last.project_revision, 'ready', ''),
                             tuple(c.execute('SELECT requested_revision,exported_revision,status,last_error FROM export_state').fetchone()))

    def test_failed_publication_restores_previous_files_then_retry_publishes(self):
        exporter = ExportCoordinator(self.db, 'demo')
        exporter.export()
        before = (self.db.project_root / 'project.snapshot.json').read_bytes()
        last = self.mutate(lambda c: c.execute("UPDATE entities SET title='second' WHERE id='plot:1'"))
        import os
        replace = os.replace
        def fail(source, target):
            if '/next/' in str(source) and str(target).endswith('project.snapshot.json'):
                raise OSError('publication failed')
            return replace(source, target)
        with patch('storyteller.exports.coordinator.os.replace', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'publication failed'):
                exporter.export()
        self.assertEqual(before, (self.db.project_root / 'project.snapshot.json').read_bytes())
        with self.db.read() as c:
            self.assertEqual('failed', c.execute('SELECT status FROM export_state').fetchone()[0])
        exporter.export()
        self.assertEqual(last.project_revision, json.loads((self.db.project_root / 'project.snapshot.json').read_text())['project']['revision'])

    def test_old_completion_preserves_a_newer_failure(self):
        first = self.mutate(lambda c: c.execute("UPDATE entities SET title='first' WHERE id='plot:1'"))
        last = self.mutate(lambda c: c.execute("UPDATE entities SET title='second' WHERE id='plot:1'"))
        exporter = ExportCoordinator(self.db, 'demo')
        exporter._record_state(last.project_revision, 'failed', 'newer failure')
        exporter._record_state(first.project_revision, 'ready', '')
        with self.db.read() as c:
            self.assertEqual((last.project_revision, first.project_revision, 'failed', 'newer failure'),
                             tuple(c.execute('SELECT requested_revision,exported_revision,status,last_error FROM export_state').fetchone()))
