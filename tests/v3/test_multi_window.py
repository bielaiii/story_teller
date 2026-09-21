import unittest
from unittest.mock import patch

from storyteller.domain.errors import ConflictError
from storyteller.storage.repositories.project import ProjectRepository
from tests.v3 import test_incremental_audit as audit


class MultiWindowTests(unittest.TestCase):
    setUp = audit.IncrementalAuditTests.setUp
    mutate = audit.IncrementalAuditTests.mutate

    def test_entity_baseline_is_checked_even_when_project_revision_is_current(self):
        with self.db.read() as c:
            original = c.execute("SELECT revision FROM entities WHERE id='plot:1'").fetchone()[0]
        result = self.mutate(lambda c: c.execute("UPDATE entities SET title='remote',revision=revision+1 WHERE id='plot:1'"))
        with self.assertRaises(ConflictError):
            self.uow.mutate(base_revision=result.project_revision, label='stale editor', action='update',
                            entity_kind='plot', expected_entity_id='plot:1', expected_entity_revision=original,
                            callback=lambda c: c.execute("UPDATE entities SET title='stale' WHERE id='plot:1'"))
        with self.db.read() as c:
            self.assertEqual('remote', c.execute("SELECT title FROM entities WHERE id='plot:1'").fetchone()[0])

    def test_delta_entity_reads_remain_at_the_advertised_revision(self):
        repository = ProjectRepository(self.db, 'demo')
        initial = repository.snapshot()['project']['revision']
        result = self.mutate(lambda c: c.execute("UPDATE entities SET title='first' WHERE id='plot:1'"))
        detail = ProjectRepository.entity_detail
        advanced = False
        def concurrent_read(repo, *args, **kwargs):
            nonlocal advanced
            if not advanced:
                advanced = True
                self.mutate(lambda c: c.execute("UPDATE entities SET title='second' WHERE id='plot:1'"))
            return detail(repo, *args, **kwargs)
        with patch.object(ProjectRepository, 'entity_detail', concurrent_read):
            delta = repository.changes_since(initial)
        self.assertTrue(advanced)
        self.assertEqual(result.project_revision, delta['projectRevision'])
        self.assertEqual('first', delta['changed']['plots'][0]['title'])
        self.assertEqual('second', repository.entity_detail('plot:1')['data']['title'])
