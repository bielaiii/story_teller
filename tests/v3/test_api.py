import shutil
import tempfile
import unittest
import re
from pathlib import Path

from fastapi.testclient import TestClient

from storyteller import SCHEMA_VERSION
from storyteller.app import create_app
from storyteller.colors import CONTENT_COLOR_PALETTE
from storyteller.settings import Settings
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class V3ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.content_root = Path(self.temporary.name) / "content"
        self.project_root = self.content_root / "demo"
        self.project_root.mkdir(parents=True)
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.project_root / "legacy.db")
        V3Migrator(self.project_root / "legacy.db", "demo").migrate_to(self.project_root / "story.db")
        settings = Settings.create(ROOT, content_root=self.content_root, frontend_root=Path(self.temporary.name) / "missing", default_project="demo")
        self.client = TestClient(create_app(settings))
        self.meta = self.client.get("/api/v1/meta?project=demo").json()
        self.headers = {"X-Story-Teller-Token": self.meta["mutationToken"]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_capability_snapshot_delete_preview_restore_and_undo_round_trip(self):
        self.assertEqual(SCHEMA_VERSION, self.meta["schemaVersion"])
        self.assertTrue(self.meta["routes"]["restoreEntity"])
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        revision = snapshot["project"]["revision"]
        response = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:7",
            headers=self.headers, json={"baseRevision": revision},
        )
        self.assertEqual(200, response.status_code, response.text)
        deleted = response.json()
        self.assertEqual(["character:7"], deleted["removed"]["characters"])
        trash = self.client.get("/api/v1/projects/demo/trash").json()["items"]
        self.assertEqual("character", trash[0]["kind"])
        preview = self.client.get("/api/v1/projects/demo/trash/character:7").json()
        self.assertIn("钥匙保管人", preview["data"]["intro"])
        restored = self.client.post(
            "/api/v1/projects/demo/entities/character:7/restore",
            headers=self.headers, json={"baseRevision": deleted["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)
        history = self.client.get("/api/v1/projects/demo/operations").json()["items"]
        self.assertTrue(history[0]["canUndo"])
        undone = self.client.post(
            "/api/v1/projects/demo/operations/undo",
            headers=self.headers,
            json={"baseRevision": restored.json()["projectRevision"], "operationId": history[0]["id"]},
        )
        self.assertEqual(200, undone.status_code, undone.text)
        self.assertEqual(["character:7"], undone.json()["removed"]["characters"])

    def test_stale_revision_and_missing_token_are_rejected_without_writes(self):
        revision = self.client.get("/api/v1/projects/demo/snapshot").json()["project"]["revision"]
        forbidden = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:7", json={"baseRevision": revision}
        )
        self.assertEqual(403, forbidden.status_code)
        first = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:7",
            headers=self.headers, json={"baseRevision": revision},
        )
        self.assertEqual(200, first.status_code)
        stale = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:6",
            headers=self.headers, json={"baseRevision": revision},
        )
        self.assertEqual(409, stale.status_code)

    def test_character_and_plot_edits_use_independent_entity_revisions(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        character = snapshot["characters"][0]
        plot = snapshot["plots"][0]
        character_saved = self.client.patch(
            f"/api/v1/projects/demo/characters/{character['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "entityRevision": character["revision"],
                "group": "人物独立保存测试",
            },
        )
        self.assertEqual(200, character_saved.status_code, character_saved.text)

        plot_saved = self.client.patch(
            f"/api/v1/projects/demo/plots/{plot['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "entityRevision": plot["revision"],
                "summary": "剧情在人物保存后仍可独立保存",
            },
        )
        self.assertEqual(200, plot_saved.status_code, plot_saved.text)
        detail = self.client.get(
            f"/api/v1/projects/demo/entities/{plot['entityId']}"
        ).json()["data"]
        self.assertEqual("剧情在人物保存后仍可独立保存", detail["summary"])

        conflicting = self.client.patch(
            f"/api/v1/projects/demo/plots/{plot['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": character_saved.json()["projectRevision"],
                "entityRevision": plot["revision"],
                "summary": "不应覆盖同一篇剧情的新版本",
            },
        )
        self.assertEqual(409, conflicting.status_code, conflicting.text)

    def test_character_persona_round_trips_as_structured_key_values(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        saved = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "corePersona": [
                    {"key": "核心欲望", "value": "修复被人为抹去的真相"},
                    {"key": "核心矛盾", "value": "越接近真相，越可能伤害仍然信任她的人"},
                ],
                "supplementPersona": [
                    {"key": "生活习惯", "value": "思考时会反复整理纸张边缘"},
                ],
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        detail = self.client.get(
            "/api/v1/projects/demo/entities/character:1"
        ).json()["data"]
        self.assertEqual("核心欲望", detail["corePersona"][0]["key"])
        self.assertEqual("修复被人为抹去的真相", detail["corePersona"][0]["value"])
        self.assertEqual("生活习惯", detail["supplementPersona"][0]["key"])
        self.assertIn("核心欲望：修复被人为抹去的真相", detail["intro"])
        self.assertEqual(["生活习惯：思考时会反复整理纸张边缘"], detail["supplements"])
        self.assertNotIn("characterPersona", detail["extra"])
        exported = next((self.project_root / "characters").glob("1-*.md")).read_text(encoding="utf-8")
        self.assertIn("corePersona:", exported)
        self.assertIn("supplementPersona:", exported)

    def test_unchanged_names_can_save_when_trash_has_a_duplicate(self):
        from storyteller.storage.connection import Database

        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        character = next(item for item in snapshot["characters"] if item["entityId"] == "character:1")
        deleted = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:7",
            headers=self.headers, json={"baseRevision": snapshot["project"]["revision"]},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)

        database = Database(self.project_root)
        with database.write() as connection:
            connection.execute("UPDATE characters SET name=? WHERE entity_id='character:7'", (character["name"],))
            connection.execute("UPDATE entities SET title=? WHERE id='character:7'", (character["name"],))

        saved = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": deleted.json()["projectRevision"],
                "name": character["name"],
                "facts": {"测试字段": "姓名未变化时仍可保存"},
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        detail = self.client.get("/api/v1/projects/demo/entities/character:1").json()["data"]
        self.assertEqual(character["name"], detail["name"])
        self.assertEqual("姓名未变化时仍可保存", detail["facts"]["测试字段"])

        entry = next(item for item in snapshot["entries"] if item["entityId"] == "entry:archive")
        deleted_entry = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/entry:compensation-case",
            headers=self.headers, json={"baseRevision": saved.json()["projectRevision"]},
        )
        self.assertEqual(200, deleted_entry.status_code, deleted_entry.text)
        with database.write() as connection:
            connection.execute(
                "UPDATE entries SET name=? WHERE entity_id='entry:compensation-case'",
                (entry["name"],),
            )
            connection.execute(
                "UPDATE entities SET title=? WHERE id='entry:compensation-case'",
                (entry["name"],),
            )
        saved_entry = self.client.patch(
            "/api/v1/projects/demo/entries/entry:archive",
            headers=self.headers,
            json={
                "baseRevision": deleted_entry.json()["projectRevision"],
                "name": entry["name"],
                "body": "名称未变化时仍可保存设定正文",
            },
        )
        self.assertEqual(200, saved_entry.status_code, saved_entry.text)
        entry_detail = self.client.get("/api/v1/projects/demo/entities/entry:archive").json()["data"]
        self.assertEqual(entry["name"], entry_detail["name"])
        self.assertEqual("名称未变化时仍可保存设定正文", entry_detail["body"])

    def test_character_display_names_may_repeat_while_ids_remain_distinct(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        existing = snapshot["characters"][0]
        created = self.client.post(
            "/api/v1/projects/demo/characters",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "name": existing["name"],
                "narrativeRole": "配角",
                "characterScope": "常驻人物",
                "side": "中立",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        matches = [item for item in created.json()["changed"]["characters"] if item["name"] == existing["name"]]
        self.assertEqual(1, len(matches))
        self.assertNotEqual(existing["entityId"], matches[0]["entityId"])

        deleted = self.client.request(
            "DELETE", f"/api/v1/projects/demo/entities/{matches[0]['entityId']}",
            headers=self.headers,
            json={"baseRevision": created.json()["projectRevision"]},
        )
        restored = self.client.post(
            f"/api/v1/projects/demo/entities/{matches[0]['entityId']}/restore",
            headers=self.headers,
            json={"baseRevision": deleted.json()["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)

    def test_creative_diagnostics_endpoint_is_not_exposed(self):
        response = self.client.get("/api/v1/projects/demo/diagnostics")
        self.assertEqual(404, response.status_code)

    def test_character_destiny_outline_round_trips_and_can_be_cleared(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        saved = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "destinyOutline": "她最终识破家族安排，主动选择自己的归宿。",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        detail = self.client.get("/api/v1/projects/demo/entities/character:1").json()["data"]
        self.assertEqual("她最终识破家族安排，主动选择自己的归宿。", detail["destinyOutline"])
        exported = next((self.project_root / "characters").glob("1-*.md")).read_text(encoding="utf-8")
        self.assertIn("她最终识破家族安排，主动选择自己的归宿。", exported)

        cleared = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": saved.json()["projectRevision"],
                "destinyOutline": "   ",
            },
        )
        self.assertEqual(200, cleared.status_code, cleared.text)
        detail = self.client.get("/api/v1/projects/demo/entities/character:1").json()["data"]
        self.assertEqual("", detail["destinyOutline"])

    def test_editor_mutations_preserve_unowned_metadata_and_read_back_without_snapshot_reload(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        revision = snapshot["project"]["revision"]
        missing_chapter = self.client.post(
            "/api/v1/projects/demo/plots",
            headers=self.headers,
            json={"baseRevision": revision, "title": "缺少正式章号"},
        )
        self.assertEqual(422, missing_chapter.status_code, missing_chapter.text)
        from storyteller.storage.connection import Database
        database = Database(self.project_root)
        with database.write() as connection:
            connection.execute(
                "UPDATE entities SET extra_json=? WHERE id='character:1'",
                ('{"pluginField":"保留我"}',),
            )
        saved = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": revision,
                "name": "林秋改",
                "intro": "保存后的完整档案",
                "facts": {"习惯": "反复确认门锁"},
                "narrativeRole": "主角",
                "characterScope": "常驻人物",
                "side": "主角方",
                "markers": ["主角"],
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual("ready", saved.json()["export"]["status"])
        detail = self.client.get("/api/v1/projects/demo/entities/character:1").json()["data"]
        self.assertEqual("林秋改", detail["name"])
        self.assertEqual("保存后的完整档案", detail["intro"])
        self.assertEqual("保留我", detail["extra"]["pluginField"])
        exported = next((self.project_root / "characters").glob("1-林秋改.md")).read_text(encoding="utf-8")
        self.assertIn("保存后的完整档案", exported)
        self.assertIn("pluginField", exported)

        created = self.client.post(
            "/api/v1/projects/demo/plots",
            headers=self.headers,
            json={
                "baseRevision": saved.json()["projectRevision"],
                "title": "增量剧情",
                "chapterNumber": 100,
                "chapterId": "chapter:act1",
                "afterEntityId": "plot:1",
                "body": "林秋改只通过 V3 API 写入的正文",
                "status": "草稿",
                "people": ["character:1"],
                "entries": ["entry:archive"],
                "lanes": ["timeline_line:主线"],
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        changed = created.json()["changed"]["plots"][0]
        plot_detail = self.client.get(
            f"/api/v1/projects/demo/entities/{changed['entityId']}"
        ).json()["data"]
        self.assertEqual("林秋改只通过 V3 API 写入的正文", plot_detail["body"])
        self.assertEqual(["character:1"], plot_detail["people"])
        self.assertEqual(["entry:archive"], plot_detail["entries"])
        self.assertEqual(["timeline_line:主线"], plot_detail["lanes"])
        self.assertTrue(any("增量剧情" in path.name for path in (self.project_root / "plots").glob("*.md")))

    def test_duplicate_plot_chapter_number_can_shift_following_plots(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        duplicate = self.client.post(
            "/api/v1/projects/demo/plots",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "title": "第 1 章",
                "chapterNumber": 1,
                "shiftFollowing": False,
                "chapterId": snapshot["chapters"][0]["entityId"],
                "body": "重复章号测试",
            },
        )
        self.assertEqual(422, duplicate.status_code, duplicate.text)
        shifted = self.client.post(
            "/api/v1/projects/demo/plots",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "title": "第 1 章",
                "chapterNumber": 1,
                "shiftFollowing": True,
                "chapterId": "",
                "body": "顺延章号测试",
            },
        )
        self.assertEqual(200, shifted.status_code, shifted.text)
        updated = self.client.get("/api/v1/projects/demo/snapshot").json()
        self.assertEqual(1, updated["plots"][0]["chapterNumber"])
        self.assertEqual("", updated["plots"][0]["chapterId"])
        self.assertEqual(list(range(1, len(updated["plots"]) + 1)), [item["chapterNumber"] for item in updated["plots"]])

    def test_entry_and_fragment_stable_ids_are_generated_and_remain_editable(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        entry = self.client.post(
            "/api/v1/projects/demo/entries",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "name": "自动编号设定",
                "type": "术语",
                "body": "第一次保存",
            },
        )
        self.assertEqual(200, entry.status_code, entry.text)
        entry_delta = entry.json()
        created_entry = next(
            item for item in entry_delta["changed"]["entries"]
            if item["name"] == "自动编号设定"
        )
        self.assertRegex(created_entry["entityId"], r"^entry:\d+$")
        updated_entry = self.client.patch(
            f"/api/v1/projects/demo/entries/{created_entry['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": entry_delta["projectRevision"],
                "body": "第二次保存",
            },
        )
        self.assertEqual(200, updated_entry.status_code, updated_entry.text)
        self.assertEqual(
            "第二次保存",
            self.client.get(
                f"/api/v1/projects/demo/entities/{created_entry['entityId']}"
            ).json()["data"]["body"],
        )

        fragment = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": updated_entry.json()["projectRevision"],
                "title": "自动编号碎片",
                "body": "灵感正文",
            },
        )
        self.assertEqual(200, fragment.status_code, fragment.text)
        created_fragment = next(
            item for item in fragment.json()["changed"]["fragments"]
            if item["title"] == "自动编号碎片"
        )
        self.assertRegex(created_fragment["entityId"], r"^fragment:\d+$")

    def test_fragment_story_lines_persist_children_and_protect_the_container(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        line_response = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "title": "码头追踪线",
                "body": "从失踪货单一路追到旧仓库。",
                "fragmentType": "line",
                "tags": ["悬疑"],
            },
        )
        self.assertEqual(200, line_response.status_code, line_response.text)
        line = next(
            item for item in line_response.json()["changed"]["fragments"]
            if item["title"] == "码头追踪线"
        )
        self.assertEqual("line", line["fragmentType"])
        self.assertIsNone(line["parentFragmentId"])

        child_response = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": line_response.json()["projectRevision"],
                "title": "仓库里的第二把锁",
                "body": "她发现门锁刚刚被换过。",
                "fragmentType": "chapter",
                "parentFragmentId": line["entityId"],
            },
        )
        self.assertEqual(200, child_response.status_code, child_response.text)
        child = next(
            item for item in child_response.json()["changed"]["fragments"]
            if item["title"] == "仓库里的第二把锁"
        )
        self.assertEqual(line["entityId"], child["parentFragmentId"])
        self.assertIsNone(child["chapterNumber"])
        self.assertEqual(
            line["entityId"],
            self.client.get(
                f"/api/v1/projects/demo/entities/{child['entityId']}"
            ).json()["data"]["parentFragmentId"],
        )

        delete_line = self.client.request(
            "DELETE",
            f"/api/v1/projects/demo/entities/{line['entityId']}",
            headers=self.headers,
            json={"baseRevision": child_response.json()["projectRevision"]},
        )
        self.assertEqual(200, delete_line.status_code, delete_line.text)
        self.assertIn(line["entityId"], delete_line.json()["removed"]["fragments"])
        self.assertIn(child["entityId"], delete_line.json()["removed"]["fragments"])

        restored_line = self.client.post(
            f"/api/v1/projects/demo/entities/{line['entityId']}/restore",
            headers=self.headers,
            json={"baseRevision": delete_line.json()["projectRevision"]},
        )
        self.assertEqual(200, restored_line.status_code, restored_line.text)
        restored_fragments = restored_line.json()["changed"]["fragments"]
        self.assertEqual(
            {line["entityId"], child["entityId"]},
            {item["entityId"] for item in restored_fragments},
        )
        restored_child = next(
            item for item in restored_fragments
            if item["entityId"] == child["entityId"]
        )
        self.assertEqual(line["entityId"], restored_child["parentFragmentId"])

        renumbered = self.client.patch(
            f"/api/v1/projects/demo/fragments/{child['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": restored_line.json()["projectRevision"],
                "chapterNumber": 25,
                "title": "仓库里的第二把锁",
            },
        )
        self.assertEqual(200, renumbered.status_code, renumbered.text)
        renumbered_child = next(
            item for item in renumbered.json()["changed"]["fragments"]
            if item["entityId"] == child["entityId"]
        )
        self.assertEqual(25, renumbered_child["chapterNumber"])
        self.assertEqual("仓库里的第二把锁", renumbered_child["title"])

        earlier = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": renumbered.json()["projectRevision"],
                "title": "提前出现的账本",
                "body": "章号可以留出空档。",
                "fragmentType": "chapter",
                "parentFragmentId": line["entityId"],
                "chapterNumber": 3,
            },
        )
        self.assertEqual(200, earlier.status_code, earlier.text)
        earlier_child = next(
            item for item in earlier.json()["changed"]["fragments"]
            if item["title"] == "提前出现的账本"
        )
        self.assertEqual(3, earlier_child["chapterNumber"])

        duplicate_number = self.client.patch(
            f"/api/v1/projects/demo/fragments/{earlier_child['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": earlier.json()["projectRevision"],
                "chapterNumber": 25,
            },
        )
        self.assertEqual(422, duplicate_number.status_code, duplicate_number.text)
        self.assertIn("已经存在第 25 章", duplicate_number.text)

        inserted_at_three = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": earlier.json()["projectRevision"],
                "title": "插入第三章",
                "body": "原第三章应向后顺延，空档仍然保留。",
                "fragmentType": "chapter",
                "parentFragmentId": line["entityId"],
                "chapterNumber": 3,
                "shiftFollowing": True,
            },
        )
        self.assertEqual(200, inserted_at_three.status_code, inserted_at_three.text)
        shifted_child = next(
            item for item in inserted_at_three.json()["changed"]["fragments"]
            if item["entityId"] == earlier_child["entityId"]
        )
        self.assertEqual(4, shifted_child["chapterNumber"])
        after_insert = self.client.get("/api/v1/projects/demo/snapshot").json()
        line_children = sorted(
            (
                item for item in after_insert["fragments"]
                if item["parentFragmentId"] == line["entityId"]
            ),
            key=lambda item: item["chapterNumber"],
        )
        self.assertEqual(
            [
                ("插入第三章", 3),
                ("提前出现的账本", 4),
                ("仓库里的第二把锁", 25),
            ],
            [(item["title"], item["chapterNumber"]) for item in line_children],
        )

        inserted_at_four = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": inserted_at_three.json()["projectRevision"],
                "title": "再插入第四章",
                "fragmentType": "chapter",
                "parentFragmentId": line["entityId"],
                "chapterNumber": 4,
                "shiftFollowing": True,
            },
        )
        self.assertEqual(200, inserted_at_four.status_code, inserted_at_four.text)
        after_chain_insert = self.client.get("/api/v1/projects/demo/snapshot").json()
        line_children = sorted(
            (
                item for item in after_chain_insert["fragments"]
                if item["parentFragmentId"] == line["entityId"]
            ),
            key=lambda item: item["chapterNumber"],
        )
        self.assertEqual(
            [
                ("插入第三章", 3),
                ("再插入第四章", 4),
                ("提前出现的账本", 5),
                ("仓库里的第二把锁", 25),
            ],
            [(item["title"], item["chapterNumber"]) for item in line_children],
        )

        convert_line = self.client.post(
            f"/api/v1/projects/demo/fragments/{line['entityId']}/to-plot",
            headers=self.headers,
            json={
                "baseRevision": inserted_at_four.json()["projectRevision"],
                "chapterNumber": 777,
            },
        )
        self.assertEqual(422, convert_line.status_code, convert_line.text)
        self.assertIn("不能直接放入剧情", convert_line.text)

        detached = self.client.patch(
            f"/api/v1/projects/demo/fragments/{child['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": inserted_at_four.json()["projectRevision"],
                "parentFragmentId": None,
            },
        )
        self.assertEqual(200, detached.status_code, detached.text)
        detached_child = next(
            item for item in detached.json()["changed"]["fragments"]
            if item["entityId"] == child["entityId"]
        )
        self.assertIsNone(detached_child["parentFragmentId"])

        deleted = self.client.request(
            "DELETE",
            f"/api/v1/projects/demo/entities/{line['entityId']}",
            headers=self.headers,
            json={"baseRevision": detached.json()["projectRevision"]},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)

    def test_fragment_line_plans_independent_plot_numbers_and_uses_them_on_conversion(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        line_response = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "title": "非连续转正规划",
                "fragmentType": "line",
            },
        )
        line = next(
            item for item in line_response.json()["changed"]["fragments"]
            if item["title"] == "非连续转正规划"
        )
        first_response = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": line_response.json()["projectRevision"],
                "title": "碎片内第一章",
                "fragmentType": "chapter",
                "parentFragmentId": line["entityId"],
                "chapterNumber": 1,
            },
        )
        first = next(
            item for item in first_response.json()["changed"]["fragments"]
            if item["title"] == "碎片内第一章"
        )
        second_response = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": first_response.json()["projectRevision"],
                "title": "碎片内第二章",
                "fragmentType": "chapter",
                "parentFragmentId": line["entityId"],
                "chapterNumber": 2,
            },
        )
        second = next(
            item for item in second_response.json()["changed"]["fragments"]
            if item["title"] == "碎片内第二章"
        )
        existing_numbers = [
            int(match.group(1))
            for plot in snapshot["plots"]
            if (match := re.fullmatch(r"第\s*(\d+)\s*章", plot["title"]))
        ]
        first_target = max(existing_numbers, default=0) + 7
        second_target = first_target + 11
        planned = self.client.patch(
            f"/api/v1/projects/demo/fragments/{line['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": second_response.json()["projectRevision"],
                "plotChapterPlan": {
                    first["entityId"]: first_target,
                    second["entityId"]: second_target,
                },
            },
        )
        self.assertEqual(200, planned.status_code, planned.text)
        planned_line = next(
            item for item in planned.json()["changed"]["fragments"]
            if item["entityId"] == line["entityId"]
        )
        self.assertEqual(
            {
                first["entityId"]: first_target,
                second["entityId"]: second_target,
            },
            planned_line["extra"]["plotChapterPlan"],
        )

        duplicate = self.client.patch(
            f"/api/v1/projects/demo/fragments/{line['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": planned.json()["projectRevision"],
                "plotChapterPlan": {
                    first["entityId"]: first_target,
                    second["entityId"]: first_target,
                },
            },
        )
        self.assertEqual(422, duplicate.status_code, duplicate.text)
        self.assertIn("被重复规划", duplicate.text)

        converted = self.client.post(
            f"/api/v1/projects/demo/fragments/{first['entityId']}/to-plot",
            headers=self.headers,
            json={"baseRevision": planned.json()["projectRevision"], "chapterNumber": first_target},
        )
        self.assertEqual(200, converted.status_code, converted.text)
        created_plot = next(
            item for item in converted.json()["changed"]["plots"]
            if item["chapterNumber"] == first_target
        )
        self.assertEqual("", created_plot["summary"])
        reloaded = self.client.get("/api/v1/projects/demo/snapshot").json()
        self.assertIn(
            first_target,
            {item["chapterNumber"] for item in reloaded["plots"]},
        )
        self.assertNotIn(
            first["entityId"],
            {item["entityId"] for item in reloaded["fragments"]},
        )
        reloaded_line = next(
            item for item in reloaded["fragments"]
            if item["entityId"] == line["entityId"]
        )
        self.assertEqual(
            {second["entityId"]: second_target},
            reloaded_line["extra"]["plotChapterPlan"],
        )

    def test_clipboard_import_builds_unlimited_story_lines_and_single_fragments_atomically(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        source = "# 海港暗线\n总览：线索从旧仓库延伸到远洋船。\n\n" + "\n\n".join(
            f"第 {number} 章：节点 {number}\n这是第 {number} 章的正文。"
            for number in range(1, 37)
        )
        imported = self.client.post(
            "/api/v1/projects/demo/fragments/import-clipboard",
            headers=self.headers,
            json={"baseRevision": snapshot["project"]["revision"], "text": source},
        )
        self.assertEqual(200, imported.status_code, imported.text)
        imported_fragments = imported.json()["changed"]["fragments"]
        line = next(item for item in imported_fragments if item["fragmentType"] == "line")
        self.assertEqual("海港暗线", line["title"])
        children = sorted(
            (
                item for item in imported_fragments
                if item["parentFragmentId"] == line["entityId"]
            ),
            key=lambda item: item["fragmentOrder"],
        )
        self.assertEqual(36, len(children))
        self.assertEqual("节点 1", children[0]["title"])
        self.assertEqual(1, children[0]["chapterNumber"])
        self.assertEqual("节点 36", children[-1]["title"])
        self.assertEqual(36, children[-1]["chapterNumber"])
        first_detail = self.client.get(
            f"/api/v1/projects/demo/entities/{children[0]['entityId']}"
        ).json()["data"]
        self.assertEqual("这是第 1 章的正文。", first_detail["body"])

        chinese = self.client.post(
            "/api/v1/projects/demo/fragments/import-clipboard",
            headers=self.headers,
            json={
                "baseRevision": imported.json()["projectRevision"],
                "text": (
                    "第 一万零三 章：高塔回声\n第一万零三章正文。\n\n"
                    "第三百零六章：旧港回潮\n第三百零六章正文。"
                ),
            },
        )
        self.assertEqual(200, chinese.status_code, chinese.text)
        chinese_fragments = chinese.json()["changed"]["fragments"]
        chinese_line = next(item for item in chinese_fragments if item["fragmentType"] == "line")
        chinese_children = sorted(
            (
                item for item in chinese_fragments
                if item["parentFragmentId"] == chinese_line["entityId"]
            ),
            key=lambda item: item["fragmentOrder"],
        )
        self.assertEqual(
            ["旧港回潮", "高塔回声"],
            [item["title"] for item in chinese_children],
        )
        self.assertEqual(
            [306, 10003],
            [item["chapterNumber"] for item in chinese_children],
        )

        standalone = self.client.post(
            "/api/v1/projects/demo/fragments/import-clipboard",
            headers=self.headers,
            json={
                "baseRevision": chinese.json()["projectRevision"],
                "text": "## 玻璃房里的电话\n\n电话只响了半声，门外却出现了脚步。",
            },
        )
        self.assertEqual(200, standalone.status_code, standalone.text)
        standalone_fragments = standalone.json()["changed"]["fragments"]
        self.assertEqual(1, len(standalone_fragments))
        self.assertEqual("chapter", standalone_fragments[0]["fragmentType"])
        self.assertIsNone(standalone_fragments[0]["chapterNumber"])
        self.assertEqual("玻璃房里的电话", standalone_fragments[0]["title"])
        standalone_detail = self.client.get(
            f"/api/v1/projects/demo/entities/{standalone_fragments[0]['entityId']}"
        ).json()["data"]
        self.assertEqual("电话只响了半声，门外却出现了脚步。", standalone_detail["body"])

        before_duplicate = self.client.get("/api/v1/projects/demo/snapshot").json()
        duplicate = self.client.post(
            "/api/v1/projects/demo/fragments/import-clipboard",
            headers=self.headers,
            json={
                "baseRevision": before_duplicate["project"]["revision"],
                "text": "第一章：开场\nA\n\n第1章：重复\nB",
            },
        )
        self.assertEqual(422, duplicate.status_code, duplicate.text)
        self.assertIn("章号不能重复", duplicate.text)
        after_duplicate = self.client.get("/api/v1/projects/demo/snapshot").json()
        self.assertEqual(
            before_duplicate["project"]["revision"],
            after_duplicate["project"]["revision"],
        )
        self.assertEqual(
            len(before_duplicate["fragments"]),
            len(after_duplicate["fragments"]),
        )

    def test_character_lifecycle_delta_includes_derived_relationships_and_references(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        deleted = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:1",
            headers=self.headers, json={"baseRevision": snapshot["project"]["revision"]},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)
        payload = deleted.json()
        self.assertIn("character:1", payload["removed"]["characters"])
        self.assertGreaterEqual(len(payload["removed"]["relationships"]), 1)
        self.assertGreaterEqual(len(payload["changed"]["plots"]), 1)
        self.assertIn("graph", payload["structures"])
        self.assertNotIn(
            "character:1",
            {item["character_id"] for item in payload["structures"]["graph"]["nodes"]},
        )

        restored = self.client.post(
            "/api/v1/projects/demo/entities/character:1/restore",
            headers=self.headers, json={"baseRevision": payload["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)
        restored_payload = restored.json()
        self.assertGreaterEqual(len(restored_payload["changed"]["relationships"]), 1)
        self.assertTrue(all(
            "character:1" not in item["people"]
            for item in payload["changed"]["plots"]
        ))
        self.assertTrue(any(
            "character:1" in item["people"]
            for item in restored_payload["changed"]["plots"]
        ))

    def test_structural_mutations_return_in_place_timeline_and_graph_deltas(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        timeline = snapshot["timeline"]
        nodes_by_plot = {}
        story_key_by_plot = {}
        for node in timeline["nodes"]:
            nodes_by_plot.setdefault(node["plotId"], []).append(node["lineId"])
            story_key_by_plot.setdefault(node["plotId"], node["storySortKey"])
        timeline_response = self.client.put(
            "/api/v1/projects/demo/timeline",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "mainLineId": timeline["mainLineId"],
                "lineSpacing": timeline["lineSpacing"] + 1,
                "topPadding": timeline["topPadding"],
                "sidePadding": timeline["sidePadding"],
                "pixelsPerStoryUnit": timeline["pixelsPerStoryUnit"],
                "lines": [
                    {
                        "entityId": line["entityId"], "name": line["name"],
                        "color": line["color"], "side": line["side"],
                        "startPlotId": line["startPlotId"], "endPlotId": line["endPlotId"],
                    }
                    for line in timeline["lines"]
                ],
                "assignments": [
                    {
                        "plotId": plot["entityId"],
                        "lineIds": nodes_by_plot.get(plot["entityId"], []),
                        "storySortKey": story_key_by_plot.get(plot["entityId"], plot["sortKey"]),
                    }
                    for plot in snapshot["plots"]
                ],
                "lineReplacements": {},
            },
        )
        self.assertEqual(200, timeline_response.status_code, timeline_response.text)
        timeline_delta = timeline_response.json()
        self.assertEqual(timeline["lineSpacing"] + 1, timeline_delta["structures"]["timeline"]["lineSpacing"])

        graph_people = [item["entityId"] for item in snapshot["characters"][:2]]
        graph_response = self.client.put(
            "/api/v1/projects/demo/graph",
            headers=self.headers,
            json={
                "baseRevision": timeline_delta["projectRevision"],
                "nodeSpacing": 137,
                "nodes": [
                    {"characterId": graph_people[0], "anchorX": 320, "anchorY": 240},
                    {"characterId": graph_people[1], "orbitOf": graph_people[0], "orbitDistance": 180, "orbitAngle": 45},
                ],
                "distances": [{
                    "fromCharacterId": graph_people[0], "toCharacterId": graph_people[1],
                    "distance": 220, "strength": 1.4,
                }],
                "clusters": [{
                    "id": "browser-group", "label": "调查组", "centerX": 400,
                    "centerY": 300, "radius": 260, "strength": 1.2,
                    "members": graph_people,
                }],
            },
        )
        self.assertEqual(200, graph_response.status_code, graph_response.text)
        graph = graph_response.json()["structures"]["graph"]
        self.assertEqual(137, graph["settings"]["node_spacing"])
        self.assertEqual(320, graph["nodes"][0]["anchor_x"])
        self.assertEqual(220, graph["distances"][0]["distance"])
        self.assertEqual("调查组", graph["clusters"][0]["label"])

        invalid_cycle = self.client.put(
            "/api/v1/projects/demo/graph",
            headers=self.headers,
            json={
                "baseRevision": graph_response.json()["projectRevision"],
                "nodes": [
                    {"characterId": graph_people[0], "orbitOf": graph_people[1]},
                    {"characterId": graph_people[1], "orbitOf": graph_people[0]},
                ],
            },
        )
        self.assertEqual(422, invalid_cycle.status_code, invalid_cycle.text)

        no_change = self.client.put(
            "/api/v1/projects/demo/graph",
            headers=self.headers,
            json={"baseRevision": graph_response.json()["projectRevision"]},
        )
        self.assertEqual(200, no_change.status_code, no_change.text)
        self.assertIsNone(no_change.json()["operation"]["id"])
        self.assertEqual({}, no_change.json()["changed"])
        self.assertEqual({}, no_change.json()["removed"])

        character = self.client.get(
            "/api/v1/projects/demo/entities/character:1"
        ).json()["data"]
        unchanged_character = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": no_change.json()["projectRevision"],
                "name": character["name"],
                "intro": character["intro"],
                "aliases": character["aliases"],
                "markers": character["markers"],
                "facts": character["facts"],
                "supplements": character["supplements"],
                "narrativeRole": character["narrativeRole"],
                "characterScope": character["characterScope"],
                "side": character["side"],
                "mainPlotImpact": character["mainPlotImpact"],
                "color": character["color"],
                "gradient": character["gradient"],
                "group": character["group"],
                "graphVisible": character["graphVisible"],
            },
        )
        self.assertEqual(200, unchanged_character.status_code, unchanged_character.text)
        self.assertIsNone(unchanged_character.json()["operation"]["id"])
        self.assertEqual(
            no_change.json()["projectRevision"],
            unchanged_character.json()["projectRevision"],
        )

    def test_timeline_drag_atomically_swaps_story_positions_and_chapter_numbers(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        timeline = snapshot["timeline"]
        plots = snapshot["plots"]
        original_titles = {plot["entityId"]: plot["title"] for plot in plots}
        original_numbers = {}
        for plot in plots:
            match = re.fullmatch(r"第\s*(\d+)\s*章", plot["title"])
            original_numbers[plot["entityId"]] = int(match.group(1)) if match else int(plot["sequence"])
        nodes_by_plot: dict[str, list[str]] = {}
        story_key_by_plot: dict[str, str] = {}
        plot_ids_by_line: dict[str, list[str]] = {}
        for node in timeline["nodes"]:
            nodes_by_plot.setdefault(node["plotId"], []).append(node["lineId"])
            story_key_by_plot.setdefault(node["plotId"], node["storySortKey"])
            plot_ids_by_line.setdefault(node["lineId"], []).append(node["plotId"])
        drag_line_id, drag_plot_ids = next(
            (line_id, plot_ids)
            for line_id, plot_ids in plot_ids_by_line.items()
            if len(plot_ids) >= 2
        )
        drag_plot_ids = sorted(
            drag_plot_ids, key=lambda plot_id: story_key_by_plot[plot_id]
        )
        plots_by_id = {plot["entityId"]: plot for plot in plots}
        first, second = (plots_by_id[plot_id] for plot_id in drag_plot_ids[:2])
        original_story_keys = dict(story_key_by_plot)
        first_key = story_key_by_plot[first["entityId"]]
        second_key = story_key_by_plot[second["entityId"]]
        story_key_by_plot[first["entityId"]] = second_key
        story_key_by_plot[second["entityId"]] = first_key
        swapped_numbers = dict(original_numbers)
        swapped_numbers[first["entityId"]] = original_numbers[second["entityId"]]
        swapped_numbers[second["entityId"]] = original_numbers[first["entityId"]]

        response = self.client.put(
            "/api/v1/projects/demo/timeline",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "mainLineId": timeline["mainLineId"],
                "lineSpacing": timeline["lineSpacing"],
                "topPadding": timeline["topPadding"],
                "sidePadding": timeline["sidePadding"],
                "pixelsPerStoryUnit": timeline["pixelsPerStoryUnit"],
                "lines": [
                    {
                        "entityId": line["entityId"],
                        "name": line["name"],
                        "color": line["color"],
                        "side": line["side"],
                        "startPlotId": line["startPlotId"],
                        "endPlotId": line["endPlotId"],
                    }
                    for line in timeline["lines"]
                ],
                "assignments": [
                    {
                        "plotId": plot["entityId"],
                        "lineIds": nodes_by_plot.get(plot["entityId"], []),
                        "storySortKey": story_key_by_plot.get(plot["entityId"], plot["sortKey"]),
                    }
                    for plot in plots
                ],
                "chapterNumbers": [
                    {"plotId": plot_id, "chapterNumber": number}
                    for plot_id, number in swapped_numbers.items()
                ],
                "lineReplacements": {},
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        saved = self.client.get("/api/v1/projects/demo/snapshot").json()
        saved_numbers = {plot["entityId"]: plot["chapterNumber"] for plot in saved["plots"]}
        self.assertEqual(
            original_numbers[second["entityId"]],
            saved_numbers[first["entityId"]],
        )
        self.assertEqual(
            original_numbers[first["entityId"]],
            saved_numbers[second["entityId"]],
        )
        saved_story_keys = {
            node["plotId"]: node["storySortKey"]
            for node in saved["timeline"]["nodes"]
            if node["lineId"] == drag_line_id
        }
        self.assertEqual(second_key, saved_story_keys[first["entityId"]])
        self.assertEqual(first_key, saved_story_keys[second["entityId"]])
        self.assertIn(first["entityId"], {
            item["entityId"] for item in response.json()["changed"]["plots"]
        })

        undone = self.client.post(
            "/api/v1/projects/demo/operations/undo",
            headers=self.headers,
            json={
                "baseRevision": response.json()["projectRevision"],
                "operationId": response.json()["operation"]["id"],
            },
        )
        self.assertEqual(200, undone.status_code, undone.text)
        restored = self.client.get("/api/v1/projects/demo/snapshot").json()
        restored_titles = {plot["entityId"]: plot["title"] for plot in restored["plots"]}
        self.assertEqual(original_titles, restored_titles)
        restored_story_keys = {
            node["plotId"]: node["storySortKey"]
            for node in restored["timeline"]["nodes"]
            if node["lineId"] == drag_line_id
        }
        for plot_id, story_key in original_story_keys.items():
            if plot_id in restored_story_keys:
                self.assertEqual(story_key, restored_story_keys[plot_id])

    def test_plot_order_changes_sync_timeline_order_without_losing_spacing(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        timeline = snapshot["timeline"]
        plot_ids = [plot["entityId"] for plot in snapshot["plots"]]
        lines_by_plot: dict[str, list[str]] = {}
        for node in timeline["nodes"]:
            lines_by_plot.setdefault(node["plotId"], []).append(node["lineId"])
        spacing_slots = {
            plot_id: f"{(index + 1) * (index + 2) * 500_000_000_000:024d}"
            for index, plot_id in enumerate(plot_ids)
        }
        spaced = self.client.put(
            "/api/v1/projects/demo/timeline",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "mainLineId": timeline["mainLineId"],
                "lineSpacing": timeline["lineSpacing"],
                "topPadding": timeline["topPadding"],
                "sidePadding": timeline["sidePadding"],
                "pixelsPerStoryUnit": timeline["pixelsPerStoryUnit"],
                "lines": [
                    {
                        "entityId": line["entityId"],
                        "name": line["name"],
                        "color": line["color"],
                        "side": line["side"],
                        "startPlotId": line["startPlotId"],
                        "endPlotId": line["endPlotId"],
                    }
                    for line in timeline["lines"]
                ],
                "assignments": [
                    {
                        "plotId": plot_id,
                        "lineIds": lines_by_plot.get(plot_id, []),
                        "storySortKey": spacing_slots[plot_id],
                    }
                    for plot_id in plot_ids
                ],
                "lineReplacements": {},
            },
        )
        self.assertEqual(200, spaced.status_code, spaced.text)

        reversed_ids = list(reversed(plot_ids))
        reordered = self.client.put(
            "/api/v1/projects/demo/plots/order",
            headers=self.headers,
            json={
                "baseRevision": spaced.json()["projectRevision"],
                "plotIds": reversed_ids,
            },
        )
        self.assertEqual(200, reordered.status_code, reordered.text)
        after_reorder = self.client.get("/api/v1/projects/demo/snapshot").json()
        keys_after_reorder = {
            node["plotId"]: node["storySortKey"]
            for node in after_reorder["timeline"]["nodes"]
        }
        self.assertEqual(
            reversed_ids,
            sorted(reversed_ids, key=lambda plot_id: keys_after_reorder[plot_id]),
        )
        self.assertEqual(set(spacing_slots.values()), set(keys_after_reorder.values()))

        restored_structure = self.client.put(
            "/api/v1/projects/demo/story-structure",
            headers=self.headers,
            json={
                "baseRevision": reordered.json()["projectRevision"],
                "chapters": [
                    {
                        "entityId": item["entityId"],
                        "stableId": item["id"],
                        "label": item["label"],
                    }
                    for item in after_reorder["chapters"]
                ],
                "plots": [
                    {
                        "entityId": plot_id,
                        "chapterId": next(
                            item["chapterId"]
                            for item in after_reorder["plots"]
                            if item["entityId"] == plot_id
                        ),
                    }
                    for plot_id in plot_ids
                ],
            },
        )
        self.assertEqual(200, restored_structure.status_code, restored_structure.text)
        after_structure = self.client.get("/api/v1/projects/demo/snapshot").json()
        keys_after_structure = {
            node["plotId"]: node["storySortKey"]
            for node in after_structure["timeline"]["nodes"]
        }
        self.assertEqual(
            plot_ids,
            sorted(plot_ids, key=lambda plot_id: keys_after_structure[plot_id]),
        )
        self.assertEqual(set(spacing_slots.values()), set(keys_after_structure.values()))

    def test_story_position_defaults_to_mainline_and_fixed_anchor_survives_reading_reorder(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        created = self.client.post(
            "/api/v1/projects/demo/plots",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "title": "倒叙锚点",
                "chapterNumber": 100,
                "body": "十年前发生的事情",
                "storyPositionMode": "before",
                "storyAnchorPlotId": "plot:1",
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        saved = self.client.get("/api/v1/projects/demo/snapshot").json()
        created_plot = next(item for item in saved["plots"] if item["entityId"] not in {plot["entityId"] for plot in snapshot["plots"]})
        self.assertEqual("fixed", created_plot["storyOrderMode"])
        self.assertEqual("plot:1", created_plot["storyAnchorPlotId"])
        self.assertEqual("before", created_plot["storyAnchorSide"])
        main_line = saved["timeline"]["mainLineId"]
        self.assertIn(
            {"plotId": created_plot["entityId"], "lineId": main_line, "storySortKey": created_plot["storySortKey"]},
            saved["timeline"]["nodes"],
        )
        fixed_key = created_plot["storySortKey"]
        ordered = [plot["entityId"] for plot in reversed(saved["plots"])]
        reordered = self.client.put(
            "/api/v1/projects/demo/plots/order",
            headers=self.headers,
            json={"baseRevision": saved["project"]["revision"], "plotIds": ordered},
        )
        self.assertEqual(200, reordered.status_code, reordered.text)
        after = self.client.get("/api/v1/projects/demo/snapshot").json()
        after_plot = next(item for item in after["plots"] if item["entityId"] == created_plot["entityId"])
        self.assertEqual(fixed_key, after_plot["storySortKey"])
        self.assertEqual("plot:1", after_plot["storyAnchorPlotId"])
        edited = self.client.patch(
            f"/api/v1/projects/demo/plots/{created_plot['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": after["project"]["revision"],
                "body": "十年前发生的事情（修订）",
            },
        )
        self.assertEqual(200, edited.status_code, edited.text)
        final = self.client.get("/api/v1/projects/demo/snapshot").json()
        final_plot = next(item for item in final["plots"] if item["entityId"] == created_plot["entityId"])
        self.assertEqual("fixed", final_plot["storyOrderMode"])
        self.assertIn("timeline_line:", next(node["lineId"] for node in final["timeline"]["nodes"] if node["plotId"] == created_plot["entityId"]))

    def test_editor_references_persist_and_follow_target_lifecycle(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        fragment_id = snapshot["fragments"][0]["entityId"]
        saved = self.client.patch(
            f"/api/v1/projects/demo/fragments/{fragment_id}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "body": "林秋去了档案室。",
                "references": ["character:1", "entry:archive"],
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        detail = self.client.get(f"/api/v1/projects/demo/entities/{fragment_id}").json()["data"]
        self.assertEqual(["character:1", "entry:archive"], detail["references"])

        deleted = self.client.request(
            "DELETE", "/api/v1/projects/demo/entities/character:1",
            headers=self.headers, json={"baseRevision": saved.json()["projectRevision"]},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)
        changed_fragment = next(
            item for item in deleted.json()["changed"]["fragments"]
            if item["entityId"] == fragment_id
        )
        self.assertEqual(["entry:archive"], changed_fragment["references"])

        restored = self.client.post(
            "/api/v1/projects/demo/entities/character:1/restore",
            headers=self.headers, json={"baseRevision": deleted.json()["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)
        restored_fragment = next(
            item for item in restored.json()["changed"]["fragments"]
            if item["entityId"] == fragment_id
        )
        self.assertEqual(["character:1", "entry:archive"], restored_fragment["references"])

    def test_fragment_appearance_people_api_creates_and_links_a_temporary_character(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        created = self.client.post(
            "/api/v1/projects/demo/fragments",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "title": "出场人物接口测试",
                "body": "林秋在走廊遇见顾闻川。",
                "appearanceNames": ["顾闻川"],
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        payload = created.json()
        fragment = next(
            item for item in payload["changed"]["fragments"]
            if item["title"] == "出场人物接口测试"
        )
        temporary = next(
            item for item in payload["changed"]["characters"]
            if item["name"] == "顾闻川"
        )
        self.assertEqual("一次性角色", temporary["characterScope"])
        detail = self.client.get(
            f"/api/v1/projects/demo/entities/{fragment['entityId']}"
        ).json()["data"]
        self.assertIn("character:1", detail["references"])
        self.assertIn(temporary["entityId"], detail["references"])
        refreshed = self.client.get("/api/v1/projects/demo/snapshot").json()
        refreshed_fragment = next(
            item for item in refreshed["fragments"]
            if item["entityId"] == fragment["entityId"]
        )
        self.assertIn("character:1", refreshed_fragment["references"])
        self.assertIn(temporary["entityId"], refreshed_fragment["references"])

        invalid = self.client.patch(
            f"/api/v1/projects/demo/fragments/{fragment['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": payload["projectRevision"],
                "body": "走廊里已经没有其他人。",
                "appearanceNames": ["周既明"],
            },
        )
        self.assertEqual(422, invalid.status_code, invalid.text)
        self.assertIn("没有出现在当前正文中", invalid.json()["error"])

    def test_safe_rename_updates_only_stably_referenced_bodies_and_undoes_atomically(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        fragment_id = snapshot["fragments"][0]["entityId"]
        unrelated_id = snapshot["fragments"][1]["entityId"]
        referenced = self.client.patch(
            f"/api/v1/projects/demo/fragments/{fragment_id}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "body": "林秋在旧港留下线索。",
                "references": ["character:1"],
            },
        )
        self.assertEqual(200, referenced.status_code, referenced.text)
        unrelated = self.client.patch(
            f"/api/v1/projects/demo/fragments/{unrelated_id}",
            headers=self.headers,
            json={
                "baseRevision": referenced.json()["projectRevision"],
                "body": "林秋只是这段无结构引用文本里的字样。",
                "references": [],
            },
        )
        self.assertEqual(200, unrelated.status_code, unrelated.text)
        renamed = self.client.patch(
            "/api/v1/projects/demo/characters/character:1",
            headers=self.headers,
            json={
                "baseRevision": unrelated.json()["projectRevision"],
                "name": "林秋改",
            },
        )
        self.assertEqual(200, renamed.status_code, renamed.text)
        self.assertEqual("rename", self.client.get("/api/v1/projects/demo/operations").json()["items"][0]["action"])
        self.assertIn(
            "林秋改在旧港",
            self.client.get(f"/api/v1/projects/demo/entities/{fragment_id}").json()["data"]["body"],
        )
        self.assertIn(
            "林秋只是",
            self.client.get(f"/api/v1/projects/demo/entities/{unrelated_id}").json()["data"]["body"],
        )

        undone = self.client.post(
            "/api/v1/projects/demo/operations/undo",
            headers=self.headers,
            json={
                "baseRevision": renamed.json()["projectRevision"],
                "operationId": renamed.json()["operation"]["id"],
            },
        )
        self.assertEqual(200, undone.status_code, undone.text)
        self.assertEqual(
            "林秋",
            self.client.get("/api/v1/projects/demo/entities/character:1").json()["data"]["name"],
        )
        self.assertIn(
            "林秋在旧港",
            self.client.get(f"/api/v1/projects/demo/entities/{fragment_id}").json()["data"]["body"],
        )

    def test_organization_members_round_trip(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        people = snapshot["characters"][:2]
        created = self.client.post(
            "/api/v1/projects/demo/entries",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "stableId": "harbor-watch",
                "name": "港区观察组",
                "type": "组织",
                "subtype": "帮派",
                "status": "活跃",
                "members": [
                    {"characterId": people[0]["entityId"], "role": "负责人", "status": "现成员"},
                    {"characterId": people[1]["entityId"], "role": "线人", "status": "秘密成员"},
                ],
                "references": [item["entityId"] for item in people],
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        organization = next(
            item for item in created.json()["changed"]["entries"] if item["name"] == "港区观察组"
        )
        detail = self.client.get(
            f"/api/v1/projects/demo/entities/{organization['entityId']}"
        ).json()["data"]
        self.assertEqual([item["entityId"] for item in people], detail["people"])
        self.assertIn(detail["accent"], CONTENT_COLOR_PALETTE)
        self.assertEqual("负责人", detail["members"][0]["role"])
        self.assertEqual("秘密成员", detail["members"][1]["status"])
        exported = next((self.project_root / "entries").glob("harbor-watch*.md")).read_text("utf-8")
        self.assertIn("members:", exported)
        self.assertIn("秘密成员", exported)

    def test_relationship_create_update_delete_restore_round_trip(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        existing = {(item["from"], item["to"]) for item in snapshot["relationships"]}
        pair = next(
            (left["entityId"], right["entityId"])
            for left in snapshot["characters"]
            for right in snapshot["characters"]
            if left["entityId"] != right["entityId"]
            and (left["entityId"], right["entityId"]) not in existing
        )
        created = self.client.post(
            "/api/v1/projects/demo/relationships",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "fromCharacterId": pair[0],
                "toCharacterId": pair[1],
                "fromRole": "委托人",
                "toRole": "调查者",
                "fromImpression": "觉得对方谨慎可靠。",
                "toImpression": "认为对方有所隐瞒。",
                "graphScope": "focus",
                "graphLineMode": "double",
                "label": "临时协作",
                "type": "盟友",
                "color": "#3879b8",
                "body": "因档案室建立联系。",
                "references": ["entry:archive"],
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        relationship = next(
            item for item in created.json()["changed"]["relationships"]
            if item["from"] == pair[0] and item["to"] == pair[1]
        )
        identifier = relationship["entityId"]
        detail = self.client.get(
            f"/api/v1/projects/demo/entities/{identifier}"
        ).json()["data"]
        self.assertEqual("因档案室建立联系。", detail["body"])
        self.assertEqual("觉得对方谨慎可靠。", detail["fromImpression"])
        self.assertEqual("认为对方有所隐瞒。", detail["toImpression"])
        self.assertEqual("focus", detail["graphScope"])
        self.assertEqual("double", detail["graphLineMode"])
        self.assertEqual(["entry:archive"], detail["references"])

        updated = self.client.patch(
            f"/api/v1/projects/demo/relationships/{identifier}",
            headers=self.headers,
            json={
                "baseRevision": created.json()["projectRevision"],
                "label": "互相试探",
                "fromImpression": "值得合作，但不能完全信任。",
                "toImpression": "正直得不像地下世界的人。",
                "graphScope": "core",
                "graphLineMode": "single",
                "body": "合作仍然保留边界。",
                "references": ["entry:archive", "character:1"],
            },
        )
        self.assertEqual(200, updated.status_code, updated.text)
        updated_detail = self.client.get(
            f"/api/v1/projects/demo/entities/{identifier}"
        ).json()["data"]
        self.assertEqual("互相试探", updated_detail["label"])
        self.assertEqual("合作仍然保留边界。", updated_detail["body"])
        self.assertEqual("值得合作，但不能完全信任。", updated_detail["fromImpression"])
        self.assertEqual("正直得不像地下世界的人。", updated_detail["toImpression"])
        self.assertEqual("core", updated_detail["graphScope"])
        self.assertEqual("double", updated_detail["graphLineMode"])
        self.assertEqual(["entry:archive", "character:1"], updated_detail["references"])

        deleted = self.client.request(
            "DELETE", f"/api/v1/projects/demo/entities/{identifier}",
            headers=self.headers,
            json={"baseRevision": updated.json()["projectRevision"]},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertIn(identifier, deleted.json()["removed"]["relationships"])
        preview = self.client.get(
            f"/api/v1/projects/demo/trash/{identifier}"
        ).json()["data"]
        self.assertEqual("合作仍然保留边界。", preview["body"])
        restored = self.client.post(
            f"/api/v1/projects/demo/entities/{identifier}/restore",
            headers=self.headers,
            json={"baseRevision": deleted.json()["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)
        self.assertTrue(any(
            item["entityId"] == identifier
            for item in restored.json()["changed"]["relationships"]
        ))

    def test_story_structure_updates_chapters_and_reading_order_atomically(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        removed_chapter = snapshot["chapters"][-1]
        new_chapter_id = "chapter:review-act"
        chapters = [
            {
                "entityId": item["entityId"],
                "stableId": item["id"],
                "label": "重新命名的开篇" if index == 0 else item["label"],
            }
            for index, item in enumerate(snapshot["chapters"][:-1])
        ]
        chapters.append({"entityId": "", "stableId": "review-act", "label": "复盘篇"})
        reversed_plots = list(reversed(snapshot["plots"]))
        original_story_slots = sorted({
            item["storySortKey"]
            for item in snapshot["timeline"]["nodes"]
        })
        response = self.client.put(
            "/api/v1/projects/demo/story-structure",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "chapters": chapters,
                "plots": [
                    {
                        "entityId": item["entityId"],
                        "chapterId": new_chapter_id
                        if item["chapterId"] == removed_chapter["entityId"]
                        else item["chapterId"],
                    }
                    for item in reversed_plots
                ],
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertIn(removed_chapter["entityId"], payload["removed"]["chapters"])
        self.assertTrue(any(
            item["entityId"] == new_chapter_id
            for item in payload["changed"]["chapters"]
        ))
        updated = self.client.get("/api/v1/projects/demo/snapshot").json()
        self.assertEqual(
            [item["entityId"] for item in reversed_plots],
            [item["entityId"] for item in updated["plots"]],
        )
        self.assertEqual(list(range(1, len(updated["plots"]) + 1)), [item["chapterNumber"] for item in updated["plots"]])
        self.assertEqual("重新命名的开篇", updated["chapters"][0]["label"])
        self.assertTrue(all(
            item["chapterId"] != removed_chapter["entityId"]
            for item in updated["plots"]
        ))
        expected_story_slot = dict(zip(
            [item["entityId"] for item in reversed_plots],
            original_story_slots,
            strict=True,
        ))
        self.assertTrue(all(
            item["storySortKey"] == expected_story_slot[item["plotId"]]
            for item in updated["timeline"]["nodes"]
        ))

        undone = self.client.post(
            "/api/v1/projects/demo/operations/undo",
            headers=self.headers,
            json={
                "baseRevision": payload["projectRevision"],
                "operationId": payload["operation"]["id"],
            },
        )
        self.assertEqual(200, undone.status_code, undone.text)
        restored = self.client.get("/api/v1/projects/demo/snapshot").json()
        self.assertEqual(
            [item["entityId"] for item in snapshot["plots"]],
            [item["entityId"] for item in restored["plots"]],
        )
        self.assertTrue(any(
            item["entityId"] == removed_chapter["entityId"]
            for item in restored["chapters"]
        ))

    def test_moving_existing_plot_shifts_only_the_conflicting_chapter_chain(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        original = snapshot["plots"]
        target_index = min(30, len(original) - 1)
        insertion_index = min(11, target_index - 1)
        target = original[target_index]
        original_numbers = {
            item["entityId"]: index
            for index, item in enumerate(original, start=1)
        }
        response = self.client.patch(
            f"/api/v1/projects/demo/plots/{target['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "chapterNumber": insertion_index + 1,
                "shiftFollowing": True,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        updated = self.client.get("/api/v1/projects/demo/snapshot").json()["plots"]
        self.assertEqual(
            [
                *[item["entityId"] for item in original[:insertion_index]],
                target["entityId"],
                *[item["entityId"] for item in original[insertion_index:] if item["entityId"] != target["entityId"]],
            ],
            [item["entityId"] for item in updated],
        )
        updated_numbers = {item["entityId"]: item["chapterNumber"] for item in updated}
        self.assertEqual(insertion_index + 1, updated_numbers[target["entityId"]])
        for item in original:
            if item["entityId"] == target["entityId"]:
                continue
            number = original_numbers[item["entityId"]]
            expected = number + 1 if insertion_index + 1 <= number < original_numbers[target["entityId"]] else number
            self.assertEqual(expected, updated_numbers[item["entityId"]])

    def test_chapter_collision_shift_stops_at_the_first_number_gap(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        first, second, target = snapshot["plots"][:3]
        gap = self.client.patch(
            f"/api/v1/projects/demo/plots/{second['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "chapterNumber": 10,
                "shiftFollowing": False,
            },
        )
        self.assertEqual(200, gap.status_code, gap.text)
        shifted = self.client.patch(
            f"/api/v1/projects/demo/plots/{target['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": gap.json()["projectRevision"],
                "chapterNumber": 1,
                "shiftFollowing": True,
            },
        )
        self.assertEqual(200, shifted.status_code, shifted.text)
        updated = {
            item["entityId"]: (item["chapterNumber"], item["title"])
            for item in self.client.get("/api/v1/projects/demo/snapshot").json()["plots"]
        }
        self.assertEqual(1, updated[target["entityId"]][0])
        self.assertEqual(2, updated[first["entityId"]][0])
        self.assertEqual(10, updated[second["entityId"]][0])

    def test_moving_plot_to_unused_high_chapter_number_preserves_that_number(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        target = snapshot["plots"][-1]
        response = self.client.patch(
            f"/api/v1/projects/demo/plots/{target['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "chapterNumber": 999,
                "shiftFollowing": False,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        updated = self.client.get("/api/v1/projects/demo/snapshot").json()["plots"]
        self.assertEqual(target["entityId"], updated[-1]["entityId"])
        self.assertEqual(999, updated[-1]["chapterNumber"])
        detail = self.client.get(
            f"/api/v1/projects/demo/entities/{target['entityId']}"
        ).json()["data"]
        self.assertEqual(999, detail["chapterNumber"])

    def test_chapter_move_keeps_timeline_ranks_saveable(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        original = snapshot["plots"]
        target = original[-1]
        moved = self.client.patch(
            f"/api/v1/projects/demo/plots/{target['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "chapterNumber": 1,
                "shiftFollowing": True,
            },
        )
        self.assertEqual(200, moved.status_code, moved.text)

        detail = self.client.get(
            f"/api/v1/projects/demo/entities/{target['entityId']}"
        ).json()["data"]
        saved = self.client.patch(
            f"/api/v1/projects/demo/plots/{target['entityId']}",
            headers=self.headers,
            json={
                "baseRevision": moved.json()["projectRevision"],
                "chapterNumber": 1,
                "shiftFollowing": False,
                "lanes": detail["lanes"],
                "body": detail["body"],
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        reloaded = self.client.get(
            f"/api/v1/projects/demo/entities/{target['entityId']}"
        ).json()["data"]
        self.assertEqual(1, reloaded["chapterNumber"])
        self.assertEqual(detail["lanes"], reloaded["lanes"])

    def test_story_structure_accepts_mainline_plot_without_chapter(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        target = snapshot["plots"][0]
        response = self.client.put(
            "/api/v1/projects/demo/story-structure",
            headers=self.headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "chapters": [
                    {
                        "entityId": item["entityId"],
                        "stableId": item["id"],
                        "label": f"第 {index} 章",
                    }
                    for index, item in enumerate(snapshot["chapters"], start=1)
                ],
                "plots": [
                    {
                        "entityId": item["entityId"],
                        "chapterId": "" if item["entityId"] == target["entityId"] else item["chapterId"],
                    }
                    for item in snapshot["plots"]
                ],
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        updated = self.client.get("/api/v1/projects/demo/snapshot").json()
        saved = next(item for item in updated["plots"] if item["entityId"] == target["entityId"])
        self.assertEqual("", saved["chapterId"])

    def test_deleted_plot_can_be_reordered_and_restored_without_rank_collision(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        removed_plot = snapshot["plots"][1]
        deleted = self.client.request(
            "DELETE", f"/api/v1/projects/demo/entities/{removed_plot['entityId']}",
            headers=self.headers,
            json={"baseRevision": snapshot["project"]["revision"]},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)
        remaining_ids = [
            item["entityId"] for item in reversed(snapshot["plots"])
            if item["entityId"] != removed_plot["entityId"]
        ]
        reordered = self.client.put(
            "/api/v1/projects/demo/plots/order",
            headers=self.headers,
            json={
                "baseRevision": deleted.json()["projectRevision"],
                "plotIds": remaining_ids,
            },
        )
        self.assertEqual(200, reordered.status_code, reordered.text)
        history = self.client.get("/api/v1/projects/demo/operations").json()["items"]
        delete_history = next(item for item in history if item["id"] == deleted.json()["operation"]["id"])
        self.assertFalse(delete_history["canUndo"])
        self.assertTrue(delete_history["undoBlockedReason"])

        restored = self.client.post(
            f"/api/v1/projects/demo/entities/{removed_plot['entityId']}/restore",
            headers=self.headers,
            json={"baseRevision": reordered.json()["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)
        final_snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        restored_plot = next(
            item for item in final_snapshot["plots"]
            if item["entityId"] == removed_plot["entityId"]
        )
        self.assertEqual(removed_plot["entityId"], restored_plot["entityId"])
        self.assertEqual(
            list(range(1, len(final_snapshot["plots"]) + 1)),
            sorted(item["sequence"] for item in final_snapshot["plots"]),
        )

    def test_new_character_graph_visibility_defaults_follow_role_and_scope(self):
        revision = self.client.get("/api/v1/projects/demo/snapshot").json()["project"]["revision"]
        cases = [
            ({
                "name": "默认配角", "narrativeRole": "配角",
                "characterScope": "常驻人物", "side": "主角方",
            }, False),
            ({
                "name": "默认主角", "narrativeRole": "主角",
                "characterScope": "常驻人物", "side": "主角方",
            }, True),
            ({
                "name": "一次性反派", "narrativeRole": "配角",
                "characterScope": "一次性角色", "side": "反派方",
            }, False),
        ]
        for payload, expected in cases:
            response = self.client.post(
                "/api/v1/projects/demo/characters",
                headers=self.headers,
                json={"baseRevision": revision, **payload},
            )
            self.assertEqual(200, response.status_code, response.text)
            revision = response.json()["projectRevision"]
            created = next(
                item for item in response.json()["changed"]["characters"]
                if item["name"] == payload["name"]
            )
            self.assertEqual(expected, created["graphVisible"])
            self.assertIn(created["color"], CONTENT_COLOR_PALETTE)


if __name__ == "__main__":
    unittest.main()
