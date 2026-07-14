import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlparse
from unittest.mock import patch

from server import (
    StoryTellerHandler,
    build_content_index,
    canonical_character_filename,
    canonical_plot_filename,
    canonical_relationship_filename,
    plot_trash_records,
    purge_expired_plot_trash,
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
        self.assertEqual(canonical_plot_filename("8", "新的章节"), "008-新的章节.md")
        self.assertEqual(relationship_character_ids(relationship), ["9", "3"])
        self.assertEqual(
            canonical_relationship_filename(
                ["9", "3"],
                {"9": "沈清妙", "3": "林越"},
            ),
            "9-沈清妙__3-林越.md",
        )

    def test_relationship_ids_support_from_to_frontmatter(self):
        relationship = """---
from: 11
to: 10
label: 旧案合谋
---
"""

        self.assertEqual(relationship_character_ids(relationship), ["11", "10"])

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

    def test_create_character_assigns_next_stable_id_and_refreshes_index(self):
        handler, project_root, responses = self.relationship_handler()

        handler.create_character(
            {
                "project": "novel",
                "name": "顾遥",
                "narrativeRole": "配角",
                "characterScope": "常驻人物",
                "group": "调查组",
                "side": "主角方",
                "mainPlotImpact": 64,
                "color": "#3f7fc1",
                "aliases": ["小顾"],
                "markers": ["记者"],
                "intro": "负责追踪旧港失踪案的记者。",
            }
        )

        character_path = project_root / "characters" / "10-顾遥.md"
        self.assertTrue(character_path.is_file())
        character_text = character_path.read_text(encoding="utf-8")
        self.assertIn("id: 10", character_text)
        self.assertIn('narrativeRole: "配角"', character_text)
        self.assertIn('aliases: ["小顾"]', character_text)
        self.assertIn("负责追踪旧港失踪案的记者。", character_text)
        self.assertEqual(responses[-1][1], 201)
        index = json.loads((project_root / "content-index.json").read_text(encoding="utf-8"))
        self.assertIn("./characters/10-顾遥.md", index["collections"]["characters"])

    def test_create_plot_inserts_sequence_without_changing_stable_ids(self):
        handler, project_root, responses = self.relationship_handler()
        plot_seven = project_root / "plots" / "007-old.md"
        plot_eight = project_root / "plots" / "008-later.md"
        self.write_markdown_at(
            plot_seven,
            "---\nid: 7\nchapter: act2\ntitle: 原第七章\n---\n正文七",
        )
        self.write_markdown_at(
            plot_eight,
            "---\nid: 8\nchapter: act3\ntitle: 原第八章\n---\n正文八",
        )

        handler.create_plot(
            {
                "project": "novel",
                "title": "插入的第八章",
                "summary": "在原第八章之前发生。",
                "body": "## 新章节\n\n这里是插入的剧情正文。",
                "chapter": "act3",
                "status": "草稿",
                "accent": "#3f7fc1",
                "tags": ["插入测试"],
                "lanes": ["主线"],
                "insertAt": 8,
            }
        )

        inserted = project_root / "plots" / "009-插入的第八章.md"
        self.assertTrue(inserted.is_file())
        self.assertIn("id: 9", inserted.read_text(encoding="utf-8"))
        self.assertIn("sequence: 8", inserted.read_text(encoding="utf-8"))
        self.assertNotIn("sequence:", plot_seven.read_text(encoding="utf-8"))
        shifted_text = plot_eight.read_text(encoding="utf-8")
        self.assertIn("id: 8", shifted_text)
        self.assertIn("sequence: 9", shifted_text)
        self.assertEqual(responses[-1][0]["shiftedCount"], 1)
        self.assertEqual(responses[-1][1], 201)

    def test_update_plot_preserves_stable_fields_and_renames_file(self):
        handler, project_root, responses = self.relationship_handler()
        original = project_root / "plots" / "007-old-title.md"
        self.write_markdown_at(
            original,
            """---
id: 7
sequence: 4
chapter: act2
title: 旧标题
people: [3]
entries: [dock]
customField: keep-me
accent: "#3f7fc1"
status: 草稿
---
旧正文
""",
        )
        write_content_index(project_root, build_content_index(project_root))

        handler.update_plot(
            {
                "project": "novel",
                "id": 7,
                "title": "新标题",
                "summary": "更新后的摘要",
                "body": "## 新正文\n\n修改已经保存。",
                "chapter": "act2",
                "status": "已接入",
                "accent": "#2A9D8F",
                "tags": ["修改"],
                "lanes": ["主线"],
                "key": True,
                "climax": False,
            }
        )

        updated = project_root / "plots" / "007-新标题.md"
        self.assertFalse(original.exists())
        self.assertTrue(updated.is_file())
        text = updated.read_text(encoding="utf-8")
        self.assertIn("id: 7", text)
        self.assertIn("sequence: 4", text)
        self.assertIn("people: [3]", text)
        self.assertIn("customField: keep-me", text)
        self.assertIn('title: "新标题"', text)
        self.assertIn('accent: "#2a9d8f"', text)
        self.assertIn("key: true", text)
        self.assertNotIn("climax:", text)
        self.assertIn("修改已经保存。", text)
        self.assertEqual(responses[-1][0]["id"], 7)

    def test_update_timeline_uses_plot_sequence_and_atomically_updates_assignments(self):
        handler, project_root, responses = self.relationship_handler()
        first = project_root / "plots" / "001-first.md"
        second = project_root / "plots" / "002-second.md"
        self.write_markdown_at(
            first,
            "---\nid: 1\nsequence: 1\nchapter: act1\ntitle: 开始\nlanes: [旧线]\n---\n正文一\n",
        )
        self.write_markdown_at(
            second,
            "---\nid: 2\nsequence: 2\nchapter: act1\ntitle: 汇合\n---\n正文二\n",
        )
        self.write_markdown_at(project_root / "timeline.md", "## Nodes\n\n- plotId: 1\n  linePosition: 99\n")

        handler.update_timeline(
            {
                "project": "novel",
                "config": {
                    "mainLine": "主线",
                    "lineSpacing": 70,
                    "topPadding": 60,
                    "sidePadding": 32,
                    "pixelsPerStoryUnit": 760,
                    "lines": [
                        {"name": "主线", "color": "#d65f8f", "side": "center"},
                        {
                            "name": "支线",
                            "color": "#3f7fc1",
                            "side": "right",
                            "startPlotId": 1,
                            "endPlotId": 2,
                        },
                    ],
                },
                "assignments": [
                    {"plotId": 1, "lanes": ["主线"]},
                    {"plotId": 2, "lanes": ["支线"]},
                ],
            }
        )

        timeline_text = (project_root / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("version: 2", timeline_text)
        self.assertIn("## Lines", timeline_text)
        self.assertNotIn("## Nodes", timeline_text)
        self.assertIn("startPlotId: 1", timeline_text)
        self.assertIn('lanes: ["主线"]', first.read_text(encoding="utf-8"))
        self.assertIn('lanes: ["支线"]', second.read_text(encoding="utf-8"))
        self.assertEqual(responses[-1][0]["updatedPlotCount"], 2)

    def test_update_timeline_rejects_branch_with_reversed_anchors(self):
        handler, project_root, _ = self.relationship_handler()
        self.write_markdown_at(
            project_root / "plots" / "001-first.md",
            "---\nid: 1\nsequence: 1\nchapter: act1\ntitle: 开始\n---\n正文一\n",
        )
        self.write_markdown_at(
            project_root / "plots" / "002-second.md",
            "---\nid: 2\nsequence: 2\nchapter: act1\ntitle: 汇合\n---\n正文二\n",
        )

        with self.assertRaisesRegex(ValueError, "必须晚于"):
            handler.update_timeline(
                {
                    "project": "novel",
                    "config": {
                        "mainLine": "主线",
                        "lines": [
                            {"name": "主线", "color": "#d65f8f", "side": "center"},
                            {
                                "name": "支线",
                                "color": "#3f7fc1",
                                "side": "left",
                                "startPlotId": 2,
                                "endPlotId": 1,
                            },
                        ],
                    },
                    "assignments": [
                        {"plotId": 1, "lanes": ["主线"]},
                        {"plotId": 2, "lanes": ["支线"]},
                    ],
                }
            )

    def test_delete_plot_moves_to_trash_and_restore_recovers_it(self):
        handler, project_root, responses = self.relationship_handler()
        earlier = project_root / "plots" / "001-earlier.md"
        target = project_root / "plots" / "007-delete-me.md"
        later = project_root / "plots" / "008-later.md"
        self.write_markdown_at(earlier, "---\nid: 1\nsequence: 1\nchapter: act1\ntitle: 前一章\n---\n正文一\n")
        self.write_markdown_at(target, "---\nid: 7\nsequence: 2\nchapter: act2\ntitle: 删除我\n---\n正文七\n")
        self.write_markdown_at(later, "---\nid: 8\nsequence: 3\nchapter: act2\ntitle: 后一章\n---\n正文八\n")
        character = project_root / "characters" / "3-林越.md"
        self.write_markdown_at(character, "---\nid: 3\nname: 林越\nevents: [7, 8]\n---\n人物设定\n")
        entry = project_root / "entries" / "dock.md"
        self.write_markdown_at(entry, "---\nid: dock\nname: 码头\nplots: [7, 8]\n---\n设定\n")
        timeline = project_root / "timeline.md"
        self.write_markdown_at(
            timeline,
            "## Nodes\n\n- plotId: 7\n  line: 主线\n  linePosition: 1\n- plotId: 8\n  line: 主线\n  linePosition: 2\n",
        )
        write_content_index(project_root, build_content_index(project_root))

        handler.delete_plot({"project": "novel", "id": 7})

        self.assertFalse(target.exists())
        self.assertIn("sequence: 2", later.read_text(encoding="utf-8"))
        self.assertIn("events: [7, 8]", character.read_text(encoding="utf-8"))
        self.assertIn("plots: [7, 8]", entry.read_text(encoding="utf-8"))
        timeline_text = timeline.read_text(encoding="utf-8")
        self.assertIn("plotId: 7", timeline_text)
        self.assertIn("plotId: 8", timeline_text)
        self.assertNotIn("./plots/007-delete-me.md", (project_root / "content-index.json").read_text(encoding="utf-8"))
        self.assertEqual(responses[-1][0]["shiftedCount"], 1)
        trash_id = responses[-1][0]["trashId"]
        self.assertTrue((project_root / ".trash" / "plots" / trash_id).is_file())

        handler.local_host = lambda: True
        handler.plot_trash_preview(
            urlparse(f"/api/plots/trash/preview?project=novel&trashId={quote(trash_id)}")
        )
        self.assertIn("正文七", responses[-1][0]["body"])

        handler.restore_plot({"project": "novel", "trashId": trash_id})

        self.assertTrue(target.is_file())
        self.assertIn("sequence: 2", target.read_text(encoding="utf-8"))
        self.assertIn("sequence: 3", later.read_text(encoding="utf-8"))
        self.assertFalse((project_root / ".trash" / "plots" / trash_id).exists())

    def test_delete_plot_normalizes_missing_and_gapped_sequences(self):
        handler, project_root, _ = self.relationship_handler()
        first = project_root / "plots" / "001-first.md"
        target = project_root / "plots" / "002-target.md"
        later = project_root / "plots" / "003-later.md"
        self.write_markdown_at(first, "---\nid: 1\nchapter: act1\ntitle: 第一章\n---\n正文一\n")
        self.write_markdown_at(target, "---\nid: 2\nsequence: 2\nchapter: act1\ntitle: 删除我\n---\n正文二\n")
        self.write_markdown_at(later, "---\nid: 3\nsequence: 9\nchapter: act1\ntitle: 后一章\n---\n正文三\n")

        handler.delete_plot({"project": "novel", "id": 2})

        self.assertIn("sequence: 1", first.read_text(encoding="utf-8"))
        self.assertIn("sequence: 2", later.read_text(encoding="utf-8"))

    def test_expired_plot_trash_is_permanently_deleted_and_cleans_references(self):
        handler, project_root, _ = self.relationship_handler()
        target = project_root / "plots" / "007-delete-me.md"
        self.write_markdown_at(target, "---\nid: 7\nsequence: 7\nchapter: act2\ntitle: 删除我\n---\n正文七\n")
        character = project_root / "characters" / "3-林越.md"
        self.write_markdown_at(character, "---\nid: 3\nname: 林越\nevents: [7, 8]\n---\n人物设定\n")
        entry = project_root / "entries" / "dock.md"
        self.write_markdown_at(entry, "---\nid: dock\nname: 码头\nplots: [7, 8]\n---\n设定\n")
        timeline = project_root / "timeline.md"
        self.write_markdown_at(
            timeline,
            "## Lines\n\n- name: 支线\n  startPlotId: 7\n  endPlotId: 8\n\n## Nodes\n\n- plotId: 7\n  line: 主线\n  linePosition: 1\n",
        )

        handler.delete_plot({"project": "novel", "id": 7})
        record = plot_trash_records(project_root)[0]
        purged = purge_expired_plot_trash(project_root, now=record["expiresAt"] + 1)

        self.assertEqual(purged, 1)
        self.assertFalse(record["_path"].exists())
        self.assertIn("events: [8]", character.read_text(encoding="utf-8"))
        self.assertIn("plots: [8]", entry.read_text(encoding="utf-8"))
        timeline_text = timeline.read_text(encoding="utf-8")
        self.assertNotIn("plotId: 7", timeline_text)
        self.assertNotIn("startPlotId: 7", timeline_text)
        self.assertIn("endPlotId: 8", timeline_text)

    def test_create_plot_does_not_reuse_an_id_held_in_trash(self):
        handler, project_root, responses = self.relationship_handler()
        target = project_root / "plots" / "007-delete-me.md"
        self.write_markdown_at(target, "---\nid: 7\nsequence: 1\nchapter: act1\ntitle: 删除我\n---\n正文\n")
        handler.delete_plot({"project": "novel", "id": 7})

        handler.create_plot(
            {
                "project": "novel",
                "title": "新剧情",
                "body": "新正文",
                "chapter": "act1",
                "status": "草稿",
                "accent": "#3f7fc1",
                "tags": [],
                "lanes": [],
            }
        )

        self.assertEqual(responses[-1][0]["id"], 8)
        self.assertTrue((project_root / "plots" / "008-新剧情.md").is_file())

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

    def test_update_character_scope_writes_frontmatter(self):
        handler, project_root, responses = self.relationship_handler()

        handler.update_character_scope(
            {
                "project": "novel",
                "id": "3",
                "scope": "一次性角色",
            }
        )

        character_text = (project_root / "characters" / "3-林越.md").read_text(encoding="utf-8")
        self.assertIn('characterScope: "一次性角色"', character_text)
        self.assertEqual(responses[-1][0]["scope"], "一次性角色")

        handler.update_character_scope(
            {
                "project": "novel",
                "id": "3",
                "scope": "主线人物",
            }
        )

        character_text = (project_root / "characters" / "3-林越.md").read_text(encoding="utf-8")
        self.assertIn('characterScope: "主线人物"', character_text)
        self.assertNotIn('characterScope: "一次性角色"', character_text)

    def test_update_plot_reorders_all_articles_and_saves_manual_references(self):
        handler, project_root, responses = self.relationship_handler()
        for plot_id in (1, 2, 3):
            self.write_markdown_at(
                project_root / "plots" / f"{plot_id:03d}-plot.md",
                f"---\nid: {plot_id}\nsequence: {plot_id}\nchapter: act1\ntitle: 第{plot_id}章\naccent: \"#3f7fc1\"\nstatus: 草稿\n---\n正文{plot_id}\n",
            )

        handler.update_plot({
            "project": "novel",
            "id": 3,
            "sequence": 1,
            "title": "移动后的章节",
            "summary": "",
            "body": "正文三",
            "chapter": "act1",
            "status": "草稿",
            "accent": "#3f7fc1",
            "tags": [],
            "lanes": [],
            "people": ["3"],
            "entries": ["dock"],
        })

        moved = project_root / "plots" / "003-移动后的章节.md"
        self.assertIn("sequence: 1", moved.read_text(encoding="utf-8"))
        self.assertIn('people: ["3"]', moved.read_text(encoding="utf-8"))
        self.assertIn('entries: ["dock"]', moved.read_text(encoding="utf-8"))
        self.assertIn("sequence: 2", (project_root / "plots" / "001-plot.md").read_text(encoding="utf-8"))
        self.assertIn("sequence: 3", (project_root / "plots" / "002-plot.md").read_text(encoding="utf-8"))
        self.assertEqual(responses[-1][0]["sequence"], 1)

    def test_character_delete_and_restore_includes_relationships_and_references(self):
        handler, project_root, responses = self.relationship_handler()
        relationship = project_root / "relationships" / "3-林越__9-沈清妙.md"
        self.write_markdown_at(
            relationship,
            "---\npeople:\n  - id: 3\n    role: 朋友\n  - id: 9\n    role: 朋友\nlabel: 同伴\n---\n",
        )
        plot = project_root / "plots" / "001.md"
        entry = project_root / "entries" / "dock.md"
        self.write_markdown_at(plot, "---\nid: 1\nsequence: 1\nchapter: act1\ntitle: 测试\npeople: [3, 9]\n---\n正文\n")
        self.write_markdown_at(entry, "---\nid: dock\nname: 码头\npeople: [3, 9]\n---\n设定\n")

        handler.delete_record({"project": "novel", "kind": "character", "id": "3"})

        self.assertFalse((project_root / "characters" / "3-林越.md").exists())
        self.assertFalse(relationship.exists())
        self.assertIn("people: [9]", plot.read_text(encoding="utf-8"))
        self.assertIn("people: [9]", entry.read_text(encoding="utf-8"))
        trash_id = responses[-1][0]["trashId"]

        handler.restore_record({"project": "novel", "trashId": trash_id})

        self.assertTrue((project_root / "characters" / "3-林越.md").is_file())
        self.assertTrue(relationship.is_file())
        self.assertIn("people: [3, 9]", plot.read_text(encoding="utf-8"))
        self.assertFalse((project_root / ".trash" / "records" / trash_id).exists())

    def test_entry_and_fragment_can_be_created_and_updated(self):
        handler, project_root, _ = self.relationship_handler()
        handler.save_entry({
            "project": "novel", "create": True, "id": "old-dock", "name": "旧码头",
            "type": "地点", "subtype": "码头", "area": "东区", "accent": "#3f7fc1",
            "aliases": ["东码头"], "tags": ["旧案"], "people": ["3"], "plots": [],
            "status": "草稿", "body": "码头设定",
        })
        handler.save_fragment({
            "project": "novel", "create": True, "id": "rain-note", "title": "雨夜想法",
            "status": "灵感", "accent": "#7d6bd6", "tags": ["雨夜"], "body": "一句台词。",
        })
        handler.save_fragment({
            "project": "novel", "create": False, "id": "rain-note", "title": "雨夜场景",
            "status": "待整理", "accent": "#d65f8f", "tags": ["雨夜"], "body": "扩写后的场景。",
        })

        self.assertIn("码头设定", (project_root / "entries" / "old-dock.md").read_text(encoding="utf-8"))
        fragment = (project_root / "fragments" / "rain-note.md").read_text(encoding="utf-8")
        self.assertIn('title: "雨夜场景"', fragment)
        self.assertIn("扩写后的场景。", fragment)

    def test_project_and_graph_layout_are_saved_through_api(self):
        handler, project_root, responses = self.relationship_handler()
        self.write_markdown_at(project_root / "manifest.md", "---\ntitle: 旧标题\nchapters: [act1]\nchapterAct1: 第一篇\n---\n")
        handler.update_project({
            "project": "novel", "title": "新作品", "eyebrow": "Novel",
            "chapters": [{"id": "act1", "label": "开篇"}, {"id": "act2", "label": "反击篇"}],
        })
        handler.update_graph_layout({
            "project": "novel", "nodeSpacing": 130, "relationshipDistance": 280,
            "leafDistanceExtra": 60, "centerStrength": 1, "groupStrength": 1,
            "leafStrength": 1, "anchors": [{"id": "3", "x": 120.5, "y": 240.25}],
        })

        manifest = (project_root / "manifest.md").read_text(encoding="utf-8")
        graph = (project_root / "graph-layout.md").read_text(encoding="utf-8")
        self.assertIn('title: "新作品"', manifest)
        self.assertIn('chapters: ["act1", "act2"]', manifest)
        self.assertIn("## Saved Positions", graph)
        self.assertIn("x: 120.5", graph)
        self.assertEqual(responses[-1][0]["anchorCount"], 1)

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
