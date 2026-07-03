import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from server import StoryTellerHandler, build_content_index, write_content_index


class ContentIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.project_root = Path(self.temporary_directory.name).resolve()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def write_markdown(self, relative_path, content="---\nid: 1\nname: 测试\n---\n正文"):
        path = self.project_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_content_index_scans_nested_markdown(self):
        self.write_markdown("characters/leads/hero.md")
        self.write_markdown("plots/001.md")
        self.write_markdown("timeline.md", "# Timeline")
        (self.project_root / "plots" / "ignore.txt").write_text("ignore", encoding="utf-8")

        index = build_content_index(self.project_root)

        self.assertEqual(index["characters"], ["./characters/leads/hero.md"])
        self.assertEqual(index["plots"], ["./plots/001.md"])
        self.assertEqual(index["timeline"], ["./timeline.md"])
        self.assertEqual(index["graphLayout"], [])

    def test_content_index_file_is_stable_and_static_ready(self):
        self.write_markdown("entries/place.md")
        index = build_content_index(self.project_root)

        write_content_index(self.project_root, index)
        payload = json.loads((self.project_root / "content-index.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["collections"], index)

    def test_refactor_target_lookup_matches_recursive_scan(self):
        self.write_markdown(
            "characters/leads/hero.md",
            "---\nid: 42\nname: 沈知微\n---\n正文",
        )

        path, fields, _ = StoryTellerHandler.locate_target(
            None,
            self.project_root,
            "character",
            "42",
        )

        self.assertEqual(path.relative_to(self.project_root).as_posix(), "characters/leads/hero.md")
        self.assertEqual(fields["name"], "沈知微")

    def test_project_lookup_uses_server_content_root(self):
        project = self.project_root / "private-novel"
        project.mkdir()
        handler = object.__new__(StoryTellerHandler)
        handler.server = SimpleNamespace(content_root=self.project_root)

        resolved = handler.project_root("private-novel")

        self.assertEqual(resolved, project)


if __name__ == "__main__":
    unittest.main()
