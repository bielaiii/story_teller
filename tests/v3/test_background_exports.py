import json
import threading
import unittest
from unittest.mock import patch

from storyteller.exports.background import ExportScheduler
from storyteller.exports.coordinator import ExportCoordinator
from tests.v3 import test_incremental_audit as audit


class BackgroundExportTests(unittest.TestCase):
    setUp = audit.IncrementalAuditTests.setUp
    mutate = audit.IncrementalAuditTests.mutate

    def test_burst_is_coalesced_and_shutdown_flushes_latest_revision(self):
        scheduler = ExportScheduler(delay_seconds=60)
        self.addCleanup(scheduler.close)
        coordinator = ExportCoordinator.export
        with patch.object(ExportCoordinator, 'export', autospec=True, side_effect=coordinator) as export:
            for title in ('one', 'two', 'three'):
                result = self.mutate(lambda c: c.execute("UPDATE entities SET title=? WHERE id='plot:1'", (title,)))
                self.assertEqual('pending', scheduler.export(self.db, 'demo')['status'])
            self.assertEqual(0, export.call_count)
            scheduler.close()
            self.assertEqual(1, export.call_count)
        snapshot = json.loads((self.db.project_root / 'project.snapshot.json').read_text())
        self.assertEqual(result.project_revision, snapshot['project']['revision'])
        self.assertEqual('three', next(p['title'] for p in snapshot['plots'] if p['entityId'] == 'plot:1'))
        with self.db.read() as c:
            self.assertEqual('ready', c.execute('SELECT status FROM export_state').fetchone()[0])

    def test_late_request_does_not_export_an_already_published_revision(self):
        self.mutate(lambda c: c.execute("UPDATE entities SET title='one' WHERE id='plot:1'"))
        ExportCoordinator(self.db, 'demo').export()
        scheduler = ExportScheduler(delay_seconds=60)
        with patch.object(ExportCoordinator, 'export', side_effect=AssertionError('redundant export')) as export:
            scheduler.export(self.db, 'demo')
            scheduler.close()
            export.assert_not_called()

    def test_save_during_render_uses_consistent_snapshot_and_gets_followup(self):
        scheduler = ExportScheduler(delay_seconds=0)
        self.addCleanup(scheduler.close)
        started, resume = threading.Event(), threading.Event()
        from storyteller.exports.markdown import MarkdownExporter
        render = MarkdownExporter.render
        revisions = []
        def paused(exporter):
            files = render(exporter)
            revisions.append(exporter.repository.snapshot()['project']['revision'])
            if len(revisions) == 1:
                started.set()
                if not resume.wait(5):
                    raise RuntimeError('test timeout')
            return files
        with patch.object(MarkdownExporter, 'render', paused):
            first = self.mutate(lambda c: c.execute("UPDATE entities SET title='one' WHERE id='plot:1'"))
            scheduler.export(self.db, 'demo')
            self.assertTrue(started.wait(5))
            try:
                latest = self.mutate(lambda c: c.execute("UPDATE entities SET title='two' WHERE id='plot:1'"))
                scheduler.export(self.db, 'demo')
            finally:
                resume.set()
            scheduler.close()
        self.assertEqual([first.project_revision, latest.project_revision], revisions)
        snapshot = json.loads((self.db.project_root / 'project.snapshot.json').read_text())
        self.assertEqual(latest.project_revision, snapshot['project']['revision'])

    def test_render_failure_is_persisted_and_next_save_retries(self):
        scheduler = ExportScheduler(delay_seconds=60)
        self.mutate(lambda c: c.execute("UPDATE entities SET title='one' WHERE id='plot:1'"))
        with patch('storyteller.exports.coordinator.MarkdownExporter.render', side_effect=OSError('disk full')):
            scheduler.export(self.db, 'demo')
            scheduler.close()
        with self.db.read() as c:
            row = c.execute('SELECT status,last_error FROM export_state').fetchone()
            self.assertEqual(('failed', 'disk full'), tuple(row))
            self.assertEqual('one', c.execute("SELECT title FROM entities WHERE id='plot:1'").fetchone()[0])
        retry = ExportScheduler(delay_seconds=60)
        retry.export(self.db, 'demo')
        retry.close()
        with self.db.read() as c:
            self.assertEqual('ready', c.execute('SELECT status FROM export_state').fetchone()[0])

    def test_old_completion_keeps_new_revision_pending(self):
        first = self.mutate(lambda c: c.execute("UPDATE entities SET title='one' WHERE id='plot:1'"))
        latest = self.mutate(lambda c: c.execute("UPDATE entities SET title='two' WHERE id='plot:1'"))
        coordinator = ExportCoordinator(self.db, 'demo')
        coordinator._record_state(first.project_revision, 'ready', '')
        with self.db.read() as c:
            row = c.execute('SELECT status,requested_revision,exported_revision FROM export_state').fetchone()
            self.assertEqual(('pending', latest.project_revision, first.project_revision), tuple(row))
        coordinator.export()
        coordinator._record_state(first.project_revision, 'failed', 'late')
        with self.db.read() as c:
            row = c.execute('SELECT status,exported_revision FROM export_state').fetchone()
            self.assertEqual(('ready', latest.project_revision), tuple(row))


class BackgroundExportApiTests(unittest.TestCase):
    def setUp(self):
        from tests.v3 import test_api
        test_api.V3ApiTests.setUp(self)
        self.addCleanup(self.temporary.cleanup)

    def test_http_save_returns_pending_with_persisted_body_then_shutdown_flushes(self):
        scheduler = ExportScheduler(delay_seconds=60)
        with patch('storyteller.app.ExportScheduler', return_value=scheduler), self.client as client:
            revision = client.get('/api/v1/projects/demo/snapshot').json()['project']['revision']
            response = client.patch('/api/v1/projects/demo/plots/plot:1', headers=self.headers,
                                    json={'baseRevision': revision, 'body': 'background HTTP persisted'})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual('pending', response.json()['export']['status'])
            detail = client.get('/api/v1/projects/demo/entities/plot:1').json()
            self.assertEqual('background HTTP persisted', detail['data']['body'])
            status = client.get('/api/v1/projects/demo/exports').json()
            self.assertEqual('pending', status['status'])
            self.assertEqual(response.json()['projectRevision'], status['requestedRevision'])
            self.assertFalse((self.project_root / 'project.snapshot.json').exists())
        snapshot = json.loads((self.project_root / 'project.snapshot.json').read_text())
        self.assertEqual('background HTTP persisted', next(p['body'] for p in snapshot['plots'] if p['entityId'] == 'plot:1'))

    def test_noop_save_retries_failed_export_without_creating_history(self):
        from storyteller.storage.connection import Database
        from storyteller.domain.uow import MutationResult
        db = Database(self.project_root)
        with db.write() as c:
            revision = c.execute('SELECT revision FROM projects').fetchone()[0]
            c.execute("UPDATE export_state SET status='failed', last_error='disk full'")
        scheduler = ExportScheduler(delay_seconds=60)
        with patch('storyteller.app.ExportScheduler', return_value=scheduler), self.client:
            executor = self.client.app.state.application.mutations
            response = executor.finish(db, 'demo', MutationResult(None, revision, ()))
            self.assertEqual('pending', response['export']['status'])
            self.assertEqual('pending', self.client.get('/api/v1/projects/demo/exports').json()['status'])
        with db.read() as c:
            self.assertEqual('ready', c.execute('SELECT status FROM export_state').fetchone()[0])
