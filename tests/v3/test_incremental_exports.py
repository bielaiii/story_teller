import json
import sqlite3
from unittest.mock import patch
from pathlib import Path
import unittest

from tests.v3 import test_incremental_audit as audit
from storyteller.exports.coordinator import ExportCoordinator
from storyteller.exports.incremental import load_snapshot, load_recovery, MAX_PATCHES
from storyteller.exports.markdown import MarkdownExporter
from storyteller.exports.static_snapshot import render_static_snapshot
from storyteller.exports.recovery import render_recovery_snapshot, RecoveryImporter
from storyteller.storage.repositories import ProjectRepository


class IncrementalExportTests(unittest.TestCase):
    setUp = audit.IncrementalAuditTests.setUp
    mutate = audit.IncrementalAuditTests.mutate
    # Reuse only fixture helpers, without inheriting their test cases below.
    def checkpoint(self):
        ExportCoordinator(self.db, 'demo').export()

    def incremental(self):
        return ExportCoordinator(self.db, 'demo').export(incremental=True)

    def assert_equal_full(self):
        root = self.db.project_root
        actual = load_snapshot(root / 'project.snapshot.json')
        expected = json.loads(render_static_snapshot(self.db, 'demo'))
        self.assertEqual(expected, actual)
        for name, value in MarkdownExporter(self.db, 'demo').render().items():
            self.assertEqual(value, (root / name).read_bytes(), name)
        actual = load_recovery(root / 'recovery.snapshot.json')
        expected = json.loads(render_recovery_snapshot(self.db, 'demo'))
        for payload in (actual, expected):
            for table in payload['tables'].values():
                table['rows'].sort(key=lambda row: json.dumps(row, sort_keys=True))
        self.assertEqual(expected, actual)

    def test_small_edit_does_not_scan_other_bodies_or_blobs_and_keeps_files(self):
        with self.db.write() as c:
            c.execute("INSERT INTO assets VALUES ('asset','demo',NULL,'a.bin','application/octet-stream',?,'hash',0)", (b'x' * 2_000_000,))
        self.checkpoint()
        root = self.db.project_root
        untouched = next(path for path in (root / 'plots').glob('*.md') if '烧焦' not in path.name)
        before = untouched.stat()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='changed body' WHERE entity_id='plot:1'"))
        detail = ProjectRepository.entity_detail
        def only_changed(repository, identifier, **kwargs):
            self.assertEqual('plot:1', identifier)
            return detail(repository, identifier, **kwargs)
        with (patch.object(ProjectRepository, 'snapshot', side_effect=AssertionError('full snapshot')),
             patch.object(ProjectRepository, 'entity_detail', only_changed),
             patch('storyteller.exports.coordinator.render_recovery_snapshot', side_effect=AssertionError('full recovery'))):
            self.incremental()
        after = untouched.stat()
        self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
        self.assert_equal_full()
        target = root / 'restored.db'
        RecoveryImporter(root, 'demo').import_to(target)
        with sqlite3.connect(target) as c:
            self.assertEqual('changed body', c.execute("SELECT body_markdown FROM plots WHERE entity_id='plot:1'").fetchone()[0])
            self.assertEqual(2_000_000, c.execute('SELECT length(content) FROM assets').fetchone()[0])
            self.assertEqual(1, c.execute('SELECT count(*) FROM operations').fetchone()[0])

    def test_rename_delete_undo_and_binary_changes_match_full_export(self):
        self.checkpoint()
        def edits(c):
            c.execute("UPDATE characters SET name='新人物名' WHERE entity_id='character:1'")
            c.execute("UPDATE entities SET title='新剧情名' WHERE id='plot:1'")
            c.execute("UPDATE entities SET deleted_at=1, purge_at=2 WHERE id='plot:2'")
            c.execute("INSERT INTO assets VALUES ('asset','demo',NULL,'a.bin','application/octet-stream',?,'hash',0)", (b'\x00\xff',))
        result = self.mutate(edits)
        self.incremental()
        self.assert_equal_full()
        self.uow.undo(result.operation_id, result.project_revision)
        self.incremental()
        self.assert_equal_full()

    def test_publish_failure_rolls_back_files_and_retry_keeps_contiguous_journal(self):
        self.checkpoint()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='first' WHERE entity_id='plot:1'"))
        self.incremental()
        before = (self.db.project_root / 'project.snapshot.json').read_bytes()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='second' WHERE entity_id='plot:1'"))
        import os
        replace = os.replace
        def fail(source, target):
            if '/next/' in str(source) and str(target).endswith('project.snapshot.json'):
                raise OSError('injected')
            return replace(source, target)
        with patch('storyteller.exports.coordinator.os.replace', side_effect=fail):
            with self.assertRaises(OSError): self.incremental()
        self.assertEqual(before, (self.db.project_root / 'project.snapshot.json').read_bytes())
        self.incremental()
        self.assert_equal_full()

    def test_missing_checkpoint_or_expired_history_rebuilds_safely(self):
        self.checkpoint()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='first' WHERE entity_id='plot:1'"))
        with self.db.write() as c: c.execute('DELETE FROM operations')
        self.incremental()
        self.assert_equal_full()
        (self.db.project_root / 'export-index.json').unlink()
        self.incremental()
        self.assert_equal_full()

    def test_bounded_journal_compacts_and_explicit_export_remains_standalone(self):
        self.checkpoint()
        with patch('storyteller.exports.incremental.MAX_PATCHES', 2):
            for value in range(3):
                self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown=? WHERE entity_id='plot:1'", (str(value),)))
                self.incremental()
                self.assert_equal_full()
        self.assertNotIn('format', json.loads((self.db.project_root / 'project.snapshot.json').read_text()))
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='explicit' WHERE entity_id='plot:1'"))
        self.incremental()
        self.checkpoint()
        self.assertNotIn('format', json.loads((self.db.project_root / 'project.snapshot.json').read_text()))
        self.assert_equal_full()

    def test_structural_and_parent_changes_match_full_export(self):
        self.checkpoint()
        changes = [
            "UPDATE entities SET title=title||'改名' WHERE kind='timeline_line'",
            "UPDATE chapters SET label=label||'新篇章'",
            "UPDATE graph_settings SET node_spacing=node_spacing+1",
            "UPDATE entities SET title=title||'改名' WHERE kind='fragment'",
        ]
        for statement in changes:
            with self.subTest(statement=statement):
                self.mutate(lambda c: c.execute(statement))
                self.incremental()
                self.assert_equal_full()

    def test_missing_article_is_repaired_without_rebuilding_other_articles(self):
        self.checkpoint()
        index = json.loads((self.db.project_root / 'export-index.json').read_text())
        missing = self.db.project_root / index['paths']['plot:2'][0]
        missing.unlink()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='changed' WHERE entity_id='plot:1'"))
        with patch.object(ProjectRepository, 'snapshot', side_effect=AssertionError('full snapshot')):
            self.incremental()
        self.assertTrue(missing.exists())
        self.assert_equal_full()

    def test_static_packaging_materializes_a_standalone_snapshot(self):
        import subprocess
        from tests.v3.test_incremental_audit import ROOT
        self.checkpoint()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='static package' WHERE entity_id='plot:1'"))
        self.incremental()
        output = self.db.project_root / 'packaged.json'
        subprocess.run([str(ROOT / 'scripts/python.sh'), str(ROOT / 'scripts/materialize_static_snapshot.py'),
                        str(self.db.project_root), str(output)], check=True, capture_output=True)
        self.assertEqual(json.loads(render_static_snapshot(self.db, 'demo')), json.loads(output.read_text()))

    def test_corrupted_recovery_data_is_rejected_without_creating_database(self):
        self.checkpoint()
        self.mutate(lambda c: c.execute("UPDATE plots SET body_markdown='changed' WHERE entity_id='plot:1'"))
        self.incremental()
        manifest = json.loads((self.db.project_root / 'recovery.snapshot.json').read_text())
        (self.db.project_root / manifest['patches'][0]).write_text('{}')
        target = self.db.project_root / 'recovered.db'
        with self.assertRaisesRegex(ValueError, '校验失败'):
            RecoveryImporter(self.db.project_root, 'demo').import_to(target)
        self.assertFalse(target.exists())
