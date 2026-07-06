import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import (
    StoryTellerHandler,
    build_content_index,
    canonical_character_filename,
    canonical_relationship_filename,
    relationship_character_ids,
    write_content_index,
)


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

    def test_project_lookup_uses_configured_default(self):
        project = self.project_root / "private-novel"
        project.mkdir()
        handler = object.__new__(StoryTellerHandler)
        handler.server = SimpleNamespace(
            content_root=self.project_root,
            default_project="private-novel",
        )

        self.assertEqual(handler.project_id(""), "private-novel")
        self.assertEqual(handler.project_root(""), project)

    def test_canonical_character_and_relationship_filenames(self):
        relationship = """---
people:
  - id: 9
    role: 母亲
  - id: 3
    role: 儿子
label: 母子
---
"""

        self.assertEqual(canonical_character_filename("3", "林越"), "3-林越.md")
        self.assertEqual(relationship_character_ids(relationship), ["9", "3"])
        self.assertEqual(
            canonical_relationship_filename(
                ["9", "3"],
                {"9": "沈清妙", "3": "林越"},
            ),
            "9-沈清妙__3-林越.md",
        )

    def test_character_refactor_moves_files_and_undoes_safely(self):
        content_root = self.project_root / "content"
        project_root = content_root / "novel"
        character_path = project_root / "characters" / "3-林越.md"
        relationship_path = project_root / "relationships" / "9-沈清妙__3-林越.md"
        plot_path = project_root / "plots" / "001.md"
        self.write_markdown_at(
            character_path,
            "---\nid: 3\nname: 林越\n---\n林越的人物设定",
        )
        self.write_markdown_at(
            project_root / "characters" / "9-沈清妙.md",
            "---\nid: 9\nname: 沈清妙\n---\n人物设定",
        )
        self.write_markdown_at(
            relationship_path,
            """---
people:
  - id: 9
    role: 母亲
  - id: 3
    role: 儿子
label: 母子
---
""",
        )
        self.write_markdown_at(
            plot_path,
            "---\nid: 1\ntitle: 测试\n---\n林越回到家。",
        )
        write_content_index(project_root, build_content_index(project_root))

        handler = object.__new__(StoryTellerHandler)
        handler.server = SimpleNamespace(
            content_root=content_root,
            default_project="",
            previews={},
            prune_previews=lambda: None,
        )
        responses = []
        handler.send_json = lambda payload, status=None: responses.append(payload)
        state_root = self.project_root / "state"

        with (
            patch("server.STATE_ROOT", state_root),
            patch("server.UNDO_PATH", state_root / "last-refactor.json"),
        ):
            handler.preview_refactor(
                {
                    "project": "novel",
                    "type": "character",
                    "id": "3",
                    "newName": "林澈",
                }
            )
            preview = responses[-1]
            self.assertEqual(
                preview["moves"],
                [
                    {"from": "characters/3-林越.md", "to": "characters/3-林澈.md"},
                    {
                        "from": "relationships/9-沈清妙__3-林越.md",
                        "to": "relationships/9-沈清妙__3-林澈.md",
                    },
                ],
            )

            handler.apply_refactor({"operationId": preview["operationId"]})
            renamed_character = project_root / "characters" / "3-林澈.md"
            renamed_relationship = project_root / "relationships" / "9-沈清妙__3-林澈.md"
            self.assertTrue(renamed_character.is_file())
            self.assertTrue(renamed_relationship.is_file())
            self.assertFalse(character_path.exists())
            self.assertIn("林澈", renamed_character.read_text(encoding="utf-8"))
            self.assertIn("林澈回到家", plot_path.read_text(encoding="utf-8"))
            self.assertIn(
                "./characters/3-林澈.md",
                (project_root / "content-index.json").read_text(encoding="utf-8"),
            )

            handler.undo_refactor({"project": "novel"})
            self.assertTrue(character_path.is_file())
            self.assertTrue(relationship_path.is_file())
            self.assertFalse(renamed_character.exists())
            self.assertIn("林越回到家", plot_path.read_text(encoding="utf-8"))

    def test_create_relationship_writes_one_shared_file_and_refreshes_index(self):
        handler, project_root, responses = self.relationship_handler()

        handler.create_relationship(
            {
                "project": "novel",
                "firstId": "9",
                "firstRole": "母亲",
                "secondId": "3",
                "secondRole": "儿子",
                "label": "母子",
                "type": "亲属",
                "color": "#2A9D8F",
            }
        )

        relationship_path = project_root / "relationships" / "9-沈清妙__3-林越.md"
        self.assertTrue(relationship_path.is_file())
        relationship_text = relationship_path.read_text(encoding="utf-8")
        self.assertEqual(relationship_character_ids(relationship_text), ["9", "3"])
        self.assertIn('role: "母亲"', relationship_text)
        self.assertIn('label: "母子"', relationship_text)
        self.assertIn('color: "#2a9d8f"', relationship_text)
        self.assertEqual(responses[-1][1], 201)
        index = json.loads((project_root / "content-index.json").read_text(encoding="utf-8"))
        self.assertEqual(
            index["collections"]["relationships"],
            ["./relationships/9-沈清妙__3-林越.md"],
        )

    def test_create_relationship_rejects_duplicate_pair_in_reverse_order(self):
        handler, project_root, _ = self.relationship_handler()
        self.write_markdown_at(
            project_root / "relationships" / "9-沈清妙__3-林越.md",
            """---
people:
  - id: 9
    role: 母亲
  - id: 3
    role: 儿子
label: 母子
---
""",
        )

        with self.assertRaisesRegex(ValueError, "已经存在关系"):
            handler.create_relationship(
                {
                    "project": "novel",
                    "firstId": "3",
                    "firstRole": "儿子",
                    "secondId": "9",
                    "secondRole": "母亲",
                    "label": "家人",
                    "color": "#2a9d8f",
                }
            )

    def test_create_relationship_rejects_same_person(self):
        handler, _, _ = self.relationship_handler()

        with self.assertRaisesRegex(ValueError, "不能是同一个人物"):
            handler.create_relationship(
                {
                    "project": "novel",
                    "firstId": "3",
                    "firstRole": "自己",
                    "secondId": "3",
                    "secondRole": "自己",
                    "label": "自我",
                    "color": "#2a9d8f",
                }
            )

    def relationship_handler(self):
        content_root = self.project_root / "content"
        project_root = content_root / "novel"
        self.write_markdown_at(
            project_root / "characters" / "3-林越.md",
            "---\nid: 3\nname: 林越\n---\n人物设定",
        )
        self.write_markdown_at(
            project_root / "characters" / "9-沈清妙.md",
            "---\nid: 9\nname: 沈清妙\n---\n人物设定",
        )
        handler = object.__new__(StoryTellerHandler)
        handler.server = SimpleNamespace(
            content_root=content_root,
            default_project="",
        )
        responses = []
        handler.send_json = lambda payload, status=None: responses.append(
            (payload, int(status) if status is not None else 200)
        )
        return handler, project_root, responses

    @staticmethod
    def write_markdown_at(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
