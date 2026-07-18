import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from storyteller.app import create_app
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
        self.assertEqual(3, self.meta["schemaVersion"])
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

    def test_editor_mutations_preserve_unowned_metadata_and_read_back_without_snapshot_reload(self):
        snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        revision = snapshot["project"]["revision"]
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
                "chapterId": "chapter:act1",
                "afterEntityId": "plot:1",
                "body": "只通过 V3 API 写入的正文",
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
        self.assertEqual("只通过 V3 API 写入的正文", plot_detail["body"])
        self.assertEqual(["character:1"], plot_detail["people"])
        self.assertEqual(["entry:archive"], plot_detail["entries"])
        self.assertEqual(["timeline_line:主线"], plot_detail["lanes"])
        self.assertTrue(any("增量剧情" in path.name for path in (self.project_root / "plots").glob("*.md")))

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
        self.assertEqual(["entry:archive"], detail["references"])

        updated = self.client.patch(
            f"/api/v1/projects/demo/relationships/{identifier}",
            headers=self.headers,
            json={
                "baseRevision": created.json()["projectRevision"],
                "label": "互相试探",
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
        original_story_time = {
            (item["plotId"], item["lineId"]): item["storySortKey"]
            for item in snapshot["timeline"]["nodes"]
        }
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
        self.assertEqual("重新命名的开篇", updated["chapters"][0]["label"])
        self.assertTrue(all(
            item["chapterId"] != removed_chapter["entityId"]
            for item in updated["plots"]
        ))
        self.assertEqual(original_story_time, {
            (item["plotId"], item["lineId"]): item["storySortKey"]
            for item in updated["timeline"]["nodes"]
        })

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
        self.assertIn("顺序", delete_history["undoBlockedReason"])

        restored = self.client.post(
            f"/api/v1/projects/demo/entities/{removed_plot['entityId']}/restore",
            headers=self.headers,
            json={"baseRevision": reordered.json()["projectRevision"]},
        )
        self.assertEqual(200, restored.status_code, restored.text)
        final_snapshot = self.client.get("/api/v1/projects/demo/snapshot").json()
        self.assertEqual(removed_plot["entityId"], final_snapshot["plots"][-1]["entityId"])
        self.assertEqual(
            list(range(1, len(final_snapshot["plots"]) + 1)),
            [item["sequence"] for item in final_snapshot["plots"]],
        )


if __name__ == "__main__":
    unittest.main()
