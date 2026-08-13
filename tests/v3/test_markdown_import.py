import shutil
import tempfile
import unittest
from pathlib import Path

from storyteller.domain.errors import DomainError
from storyteller.domain.maintenance import MaintenanceService
from storyteller.imports.markdown import MarkdownFile, MarkdownImportService, parse_markdown_file
from storyteller.storage.repositories.project import ProjectRepository
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class MarkdownImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "demo"
        self.root.mkdir()
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.root / "legacy.db")
        V3Migrator(self.root / "legacy.db", "demo").migrate_to(self.root / "story.db")
        self.database = Database(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def revision(self):
        with self.database.read() as connection:
            return int(connection.execute("SELECT revision FROM projects").fetchone()[0])

    def test_parser_rejects_unknown_keys_and_string_booleans(self):
        with self.assertRaisesRegex(DomainError, "不接受 title"):
            parse_markdown_file(MarkdownFile("plots/a.md", "---\nchapterNumber: 1\ntitle: nope\n---\nbody"))
        with self.assertRaisesRegex(DomainError, "必须是 true 或 false"):
            parse_markdown_file(MarkdownFile("plots/a.md", "---\nchapterNumber: 1\nkey: 'true'\n---\nbody"))

    def test_fragment_chapter_number_is_optional_and_status_is_not_an_import_key(self):
        parsed = parse_markdown_file(MarkdownFile("fragments/东港/未编号.md", "---\ntags: [悬念]\n---\n片段"))
        self.assertIsNone(parsed.metadata.get("chapterNumber"))
        with self.assertRaisesRegex(DomainError, "不支持的 key"):
            parse_markdown_file(MarkdownFile("fragments/东港/状态.md", "---\nstatus: 草稿\n---\n片段"))
        with self.assertRaisesRegex(DomainError, "所在故事目录一致"):
            parse_markdown_file(MarkdownFile("fragments/东港/冲突.md", "---\nstory: 西港\n---\n片段"))

    def test_preview_and_apply_create_plot_story_and_fragment_atomically(self):
        files = [
            MarkdownFile("plots/归港.md", "---\nchapterNumber: 42\nstories: [主线, 东港]\nsummary: 摘要\ntags: [回归]\nkey: true\n---\n正文", 1_700_000_000),
            MarkdownFile("fragments/东港/_story.md", "---\n---\n故事总览", 1_700_000_001),
            MarkdownFile("fragments/东港/未决.md", "---\nchapterNumber: 2\ntags: [悬念]\nkey: true\n---\n片段", 1_700_000_002),
        ]
        service = MarkdownImportService(self.database, "demo")
        revision = self.revision()
        preview = service.preview(revision, files)
        self.assertFalse(preview["requiresResolution"])
        result = service.apply(revision, files, preview_fingerprint=preview["fingerprint"])
        self.assertEqual(3, result.callback_result["count"])
        with self.database.read() as connection:
            plot = connection.execute(
                "SELECT e.title, p.chapter_number, p.summary FROM plots p JOIN entities e ON e.id=p.entity_id WHERE e.title='归港'"
            ).fetchone()
            self.assertEqual(("归港", 42, "摘要"), tuple(plot))
            fragment = connection.execute(
                "SELECT f.is_key FROM fragments f JOIN entities e ON e.id=f.entity_id WHERE e.title='未决'"
            ).fetchone()
            self.assertEqual(1, fragment[0])
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM operations WHERE action='import'").fetchone()[0])

        snapshot = ProjectRepository(self.database, "demo").snapshot()
        child = next(item for item in snapshot["fragments"] if item["title"] == "未决")
        self.assertEqual(2, child["chapterNumber"])

    def test_apply_rejects_changed_files_and_batch_chapter_duplicates(self):
        service = MarkdownImportService(self.database, "demo")
        revision = self.revision()
        original = MarkdownFile("plots/a.md", "---\nchapterNumber: 901\n---\na")
        preview = service.preview(revision, [original])
        changed = MarkdownFile(original.path, original.text[:-1] + "b")
        with self.assertRaisesRegex(Exception, "文件已变化"):
            service.apply(revision, [changed], preview_fingerprint=preview["fingerprint"])
        duplicates = [
            MarkdownFile("plots/b.md", "---\nchapterNumber: 902\n---\nb"),
            MarkdownFile("plots/c.md", "---\nchapterNumber: 902\n---\nc"),
        ]
        with self.assertRaisesRegex(DomainError, "重复 chapterNumber"):
            service.apply(revision, duplicates, allow_conflicts=True)

    def test_import_second_phase_links_people_and_entries_from_text(self):
        service = MarkdownImportService(self.database, "demo")
        revision = self.revision()
        files = [MarkdownFile("plots/自动引用.md", "---\nchapterNumber: 903\n---\n林秋走进海雾电台，查看旧港档案馆。")]
        result = service.apply(revision, files)
        identifier = result.callback_result["created"][0]["entityId"]
        with self.database.read() as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM plot_characters WHERE plot_id=?", (identifier,)).fetchone()[0])
            self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM plot_entries WHERE plot_id=?", (identifier,)).fetchone()[0], 2)

    def test_exact_duplicate_is_preview_skip_and_not_written_twice(self):
        service = MarkdownImportService(self.database, "demo")
        revision = self.revision()
        files = [
            MarkdownFile("plots/甲/重复.md", "---\nchapterNumber: 904\n---\n同一正文"),
            MarkdownFile("plots/乙/重复.md", "---\nchapterNumber: 905\n---\n同一正文"),
        ]
        preview = service.preview(revision, files)
        self.assertEqual("skip", preview["items"][1]["action"])
        result = service.apply(revision, files, preview_fingerprint=preview["fingerprint"])
        self.assertEqual(1, result.callback_result["count"])
        self.assertEqual(1, result.callback_result["skipped"])

    def test_plot_title_review_preview_and_confirm_are_explicit(self):
        with self.database.write() as connection:
            connection.execute("UPDATE entities SET title='第 1 章' WHERE id='plot:1'")
        service = MaintenanceService(self.database, "demo")
        preview = service.preview_plot_titles()
        item = next(value for value in preview["items"] if value["entityId"] == "plot:1")
        self.assertIn("stories", item)
        with self.database.read() as connection:
            revision = int(connection.execute("SELECT revision FROM projects").fetchone()[0])
        result = service.apply_plot_title_candidates(revision, [{"plot_id": "plot:1", "title": "港口回声"}])
        self.assertEqual(["plot:1"], result.callback_result["updated"])
        with self.database.read() as connection:
            self.assertEqual("港口回声", connection.execute("SELECT title FROM entities WHERE id='plot:1'").fetchone()[0])

    def test_unresolved_plot_can_be_explicitly_moved_to_fragment(self):
        with self.database.write() as connection:
            connection.execute("UPDATE entities SET title='第 1 章' WHERE id='plot:1'")
            revision = int(connection.execute("SELECT revision FROM projects").fetchone()[0])
        result = MaintenanceService(self.database, "demo").move_unresolved_plots_to_fragments(revision, ["plot:1"])
        self.assertEqual(1, result.callback_result["count"])
        with self.database.read() as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM active_plots WHERE entity_id='plot:1'").fetchone())
            moved = connection.execute("SELECT entity_id FROM active_fragments f JOIN entities e ON e.id=f.entity_id WHERE e.title=?", ("待整理 · 原第 1 章",)).fetchone()
            self.assertTrue(moved)
            self.assertEqual("待整理 · 原第 1 章", connection.execute("SELECT title FROM entities WHERE id=?", (moved[0],)).fetchone()[0])

    def test_apply_rejects_stale_revision_without_writing(self):
        service = MarkdownImportService(self.database, "demo")
        files = [MarkdownFile("plots/过期.md", "---\nchapterNumber: 77\n---\n正文")]
        with self.assertRaisesRegex(Exception, "当前版本"):
            service.apply(self.revision() + 1, files)
        with self.database.read() as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM entities WHERE title='过期'").fetchone())

    def test_story_migration_previews_warnings_and_is_atomic(self):
        service = MaintenanceService(self.database, "demo")
        preview = service.preview_stories()
        self.assertIn("warnings", preview)
        revision = self.revision()
        if preview["requiresAcknowledgement"]:
            with self.assertRaisesRegex(DomainError, "先预览并确认"):
                service.migrate_stories(revision)
            self.assertEqual(revision, self.revision())
        result = service.migrate_stories(revision, acknowledge_warnings=True)
        self.assertEqual(3, result.callback_result["migrated"])
        with self.database.read() as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM active_chapters").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM active_plots WHERE chapter_id IS NOT NULL").fetchone()[0])
            self.assertGreater(connection.execute("SELECT COUNT(*) FROM active_timeline_lines").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
