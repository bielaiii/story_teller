import shutil
import tempfile
import time
import unittest
from pathlib import Path

from storyteller.domain.content import ContentService
from storyteller.domain.errors import ConflictError, DomainError
from storyteller.domain.maintenance import MaintenanceService
from storyteller.domain.services import EntityService
from storyteller.domain.uow import UnitOfWork
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator
from storyteller.storage.repositories import ProjectRepository


ROOT = Path(__file__).resolve().parents[2]


class V3TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "demo"
        self.root.mkdir()
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.root / "legacy.db")
        V3Migrator(self.root / "legacy.db", "demo").migrate_to(self.root / "story.db")
        self.database = Database(self.root)
        self.repository = ProjectRepository(self.database, "demo")
        self.service = EntityService(self.database, "demo")
        self.content = ContentService(self.database, "demo")

    def tearDown(self):
        self.temporary.cleanup()

    def revision(self):
        return self.repository.snapshot()["project"]["revision"]

    def test_soft_delete_hides_character_graph_and_edges_then_restore_recovers_them(self):
        before = self.repository.snapshot()
        now = int(time.time())
        result = self.service.delete("character:7", self.revision(), now=now)
        deleted = self.repository.snapshot()
        self.assertNotIn("character:7", {item["entityId"] for item in deleted["characters"]})
        self.assertNotIn("relationship:7__4", {item["entityId"] for item in deleted["relationships"]})
        self.assertEqual(1, len(self.repository.trash()))
        restored = self.service.restore("character:7", result.project_revision, now=now + 1)
        after = self.repository.snapshot()
        self.assertEqual(len(before["characters"]), len(after["characters"]))
        self.assertEqual(len(before["relationships"]), len(after["relationships"]))
        self.assertEqual([], self.repository.trash())
        self.assertEqual(result.project_revision + 1, restored.project_revision)

    def test_save_discards_reference_to_soft_deleted_target(self):
        deleted = self.service.delete("character:7", self.revision(), now=2_000_000)
        result = self.content.update_plot(
            "plot:1",
            deleted.project_revision,
            {"body": "保留正文修改", "references": ["character:7"]},
        )

        self.assertEqual(deleted.project_revision + 1, result.project_revision)
        detail = self.repository.entity_detail("plot:1")
        self.assertEqual("保留正文修改", detail["data"]["body"])
        self.assertEqual([], detail["data"]["references"])

    def test_plot_delete_keeps_other_sort_keys_and_display_sequence_is_contiguous(self):
        before = {item["entityId"]: item["sortKey"] for item in self.repository.snapshot()["plots"]}
        deleted = self.service.delete("plot:4", self.revision(), now=2_000_000)
        active = self.repository.snapshot()["plots"]
        self.assertEqual(list(range(1, len(active) + 1)), [item["sequence"] for item in active])
        self.assertEqual(
            {key: value for key, value in before.items() if key != "plot:4"},
            {item["entityId"]: item["sortKey"] for item in active},
        )
        self.service.restore("plot:4", deleted.project_revision, now=2_000_001)
        restored = self.repository.snapshot()["plots"]
        self.assertEqual(list(before), [item["entityId"] for item in restored])

    def test_plot_delete_compacts_only_the_following_contiguous_chapter_chain(self):
        created_ids: dict[int, str] = {}
        revision = self.revision()
        for chapter_number in (900, 901, 903):
            created = self.content.create_plot(
                revision,
                {
                    "title": f"第 {chapter_number} 章",
                    "chapter_number": chapter_number,
                    "body": f"第 {chapter_number} 章正文",
                },
            )
            revision = created.project_revision
            created_ids[chapter_number] = created.callback_result["entityId"]

        deleted = self.service.delete(
            created_ids[900],
            revision,
            now=2_100_000,
        )
        active_by_id = {
            item["entityId"]: item
            for item in self.repository.snapshot()["plots"]
        }
        self.assertEqual(
            900,
            active_by_id[created_ids[901]]["chapterNumber"],
        )
        self.assertEqual(
            903,
            active_by_id[created_ids[903]]["chapterNumber"],
        )
        self.assertIn(created_ids[901], deleted.changed_entity_ids)
        self.assertNotIn(created_ids[903], deleted.changed_entity_ids)

        restored = self.service.restore(
            created_ids[900],
            deleted.project_revision,
            now=2_100_001,
        )
        restored_by_id = {
            item["entityId"]: item
            for item in self.repository.snapshot()["plots"]
        }
        self.assertEqual(
            "第 900 章",
            restored_by_id[created_ids[900]]["title"],
        )
        self.assertEqual(
            "第 901 章",
            restored_by_id[created_ids[901]]["title"],
        )
        self.assertEqual(
            "第 903 章",
            restored_by_id[created_ids[903]]["title"],
        )
        self.assertIn(created_ids[901], restored.changed_entity_ids)

    def test_fragment_delete_compacts_only_siblings_in_the_same_contiguous_chain(self):
        line = self.content.create_fragment(
            self.revision(),
            {
                "title": "删除顺延测试线",
                "fragment_type": "line",
            },
        )
        line_id = line.callback_result["entityId"]
        revision = line.project_revision
        created_ids: dict[int, str] = {}
        for chapter_number in (3, 4, 6):
            created = self.content.create_fragment(
                revision,
                {
                    "title": f"节点 {chapter_number}",
                    "fragment_type": "chapter",
                    "parent_fragment_id": line_id,
                    "chapter_number": chapter_number,
                },
            )
            revision = created.project_revision
            created_ids[chapter_number] = created.callback_result["entityId"]

        deleted = self.service.delete(
            created_ids[3],
            revision,
            now=2_200_000,
        )
        active_by_id = {
            item["entityId"]: item
            for item in self.repository.snapshot()["fragments"]
        }
        self.assertEqual(
            3,
            active_by_id[created_ids[4]]["chapterNumber"],
        )
        self.assertEqual(
            6,
            active_by_id[created_ids[6]]["chapterNumber"],
        )
        self.assertIn(created_ids[4], deleted.changed_entity_ids)
        self.assertNotIn(created_ids[6], deleted.changed_entity_ids)

        restored = self.service.restore(
            created_ids[3],
            deleted.project_revision,
            now=2_200_001,
        )
        restored_by_id = {
            item["entityId"]: item
            for item in self.repository.snapshot()["fragments"]
        }
        self.assertEqual(
            3,
            restored_by_id[created_ids[3]]["chapterNumber"],
        )
        self.assertEqual(
            4,
            restored_by_id[created_ids[4]]["chapterNumber"],
        )
        self.assertEqual(
            6,
            restored_by_id[created_ids[6]]["chapterNumber"],
        )
        self.assertIn(created_ids[4], restored.changed_entity_ids)

    def test_fragments_are_listed_by_creation_time_descending(self):
        created_ids: list[str] = []
        revision = self.revision()
        for title in ("较早碎片", "最新碎片", "中间碎片"):
            created = self.content.create_fragment(
                revision,
                {"title": title, "body": title},
            )
            revision = created.project_revision
            created_ids.append(created.callback_result["entityId"])

        with self.database.write() as connection:
            for identifier, created_at in zip(created_ids, (100, 300, 200)):
                connection.execute(
                    "UPDATE entities SET created_at=? WHERE id=?",
                    (created_at, identifier),
                )

        visible_ids = [
            item["entityId"]
            for item in self.repository.snapshot()["fragments"]
            if item["entityId"] in created_ids
        ]
        self.assertEqual([created_ids[1], created_ids[2], created_ids[0]], visible_ids)

    def test_transaction_failure_rolls_back_every_row_and_revision(self):
        revision = self.revision()

        def fail(connection):
            connection.execute("UPDATE entities SET title='不应保存' WHERE id='character:1'")
            raise RuntimeError("injected")

        with self.assertRaisesRegex(RuntimeError, "injected"):
            UnitOfWork(self.database, "demo").mutate(
                base_revision=revision, label="失败注入", action="update",
                entity_kind="character", callback=fail,
            )
        self.assertEqual(revision, self.revision())
        self.assertEqual("林秋", self.repository.entity_detail("character:1")["title"])

    def test_undo_rejects_a_row_changed_by_a_newer_operation(self):
        deleted = self.service.delete("character:7", self.revision(), now=3_000_000)
        self.service.restore("character:7", deleted.project_revision, now=3_000_001)
        with self.assertRaises(ConflictError):
            UnitOfWork(self.database, "demo").undo(deleted.operation_id, self.revision(), now=3_000_002)

    def test_hard_purge_uses_foreign_key_cascade_and_vacuum(self):
        deleted = self.service.delete("character:7", self.revision(), now=4_000_000)
        result = MaintenanceService(self.database, "demo").purge_expired(now=4_000_000 + 8 * 24 * 60 * 60)
        self.assertEqual(2, result["purgedEntities"])
        self.assertEqual(1, result["purgedRelationships"])
        self.assertEqual(4_000_000 + 8 * 24 * 60 * 60, result["checkedAt"])
        with self.database.read() as connection:
            self.assertEqual(
                str(result["checkedAt"]),
                connection.execute(
                    "SELECT value FROM metadata WHERE key='maintenance_last_checked_at'"
                ).fetchone()[0],
            )
        self.assertTrue(result["vacuumed"])
        with self.database.read() as connection:
            self.assertFalse(connection.execute("SELECT 1 FROM characters WHERE entity_id='character:7'").fetchone())
            self.assertFalse(connection.execute("SELECT 1 FROM relationships WHERE from_character_id='character:7' OR to_character_id='character:7'").fetchone())
            self.assertFalse(connection.execute("SELECT 1 FROM entities WHERE id='relationship:7__4'").fetchone())
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_hard_purge_detaches_active_plot_and_timeline_references(self):
        deleted = self.service.delete("plot:3", self.revision(), now=4_100_000)
        with self.database.write() as connection:
            connection.execute(
                """
                UPDATE plots
                SET story_order_mode='fixed', story_anchor_plot_id='plot:3', story_anchor_side='before'
                WHERE entity_id='plot:1'
                """
            )
            line_id = str(connection.execute(
                "SELECT entity_id FROM timeline_lines ORDER BY sort_key LIMIT 1"
            ).fetchone()[0])
            connection.execute(
                "UPDATE timeline_lines SET start_plot_id='plot:3', end_plot_id=NULL WHERE entity_id=?",
                (line_id,),
            )

        result = MaintenanceService(self.database, "demo").purge_expired(
            now=4_100_000 + 8 * 24 * 60 * 60
        )

        self.assertGreaterEqual(result["purgedEntities"], 1)
        with self.database.read() as connection:
            self.assertFalse(connection.execute(
                "SELECT 1 FROM entities WHERE id='plot:3'"
            ).fetchone())
            active = connection.execute(
                """
                SELECT story_order_mode, story_anchor_plot_id, story_anchor_side
                FROM plots WHERE entity_id='plot:1'
                """
            ).fetchone()
            self.assertEqual(("follow_reading", None, None), tuple(active))
            line = connection.execute(
                "SELECT start_plot_id FROM timeline_lines WHERE entity_id=?", (line_id,)
            ).fetchone()
            self.assertIsNone(line[0])

        with self.database.read() as connection:
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_hard_purge_detaches_nullable_structural_references(self):
        purge_at = 4_000_000 + 7 * 24 * 60 * 60
        with self.database.write() as connection:
            connection.execute(
                "UPDATE plots SET story_anchor_plot_id='plot:1' WHERE entity_id='plot:2'"
            )
            connection.execute(
                "UPDATE timeline_lines SET start_plot_id='plot:1' "
                "WHERE entity_id='timeline_line:主线'"
            )
            connection.execute(
                "UPDATE entities SET deleted_at=?, purge_at=? WHERE id='plot:1'",
                (4_000_000, purge_at),
            )

        result = MaintenanceService(self.database, "demo").purge_expired(
            now=purge_at + 1
        )

        self.assertEqual(2, result["detachedReferences"])
        with self.database.read() as connection:
            self.assertIsNone(connection.execute(
                "SELECT story_anchor_plot_id FROM plots WHERE entity_id='plot:2'"
            ).fetchone()[0])
            self.assertIsNone(connection.execute(
                "SELECT start_plot_id FROM timeline_lines WHERE entity_id='timeline_line:主线'"
            ).fetchone()[0])
            self.assertFalse(connection.execute(
                "SELECT 1 FROM entities WHERE id='plot:1'"
            ).fetchone())
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_plot_save_archives_unknown_named_speaker_as_one_time_character(self):
        body = "\n".join((
            "**方启年：**",
            "我会处理。",
            "",
            "**旁白：**",
            "会议结束。",
        ))
        saved = self.content.update_plot(
            "plot:3",
            self.revision(),
            {"body": body, "chapter_number": 63},
        )
        snapshot = self.repository.snapshot()
        archived = [item for item in snapshot["characters"] if item["name"] == "方启年"]
        self.assertEqual(1, len(archived))
        self.assertFalse(any(item["name"] == "旁白" for item in snapshot["characters"]))
        character = archived[0]
        self.assertEqual("一次性角色", character["characterScope"])
        self.assertEqual("一次性角色", character["group"])
        self.assertFalse(character["graphVisible"])
        self.assertIn(character["entityId"], saved.changed_entity_ids)
        plot = next(item for item in snapshot["plots"] if item["entityId"] == "plot:3")
        self.assertIn(character["entityId"], plot["people"])
        detail = self.repository.entity_detail(character["entityId"])["data"]
        self.assertEqual("第 63 章", detail["facts"]["首次出场"])
        self.assertIn("自动归档", detail["intro"])

        self.content.update_plot(
            "plot:3",
            saved.project_revision,
            {"body": body, "chapter_number": 63},
        )
        self.assertEqual(
            1,
            sum(item["name"] == "方启年" for item in self.repository.snapshot()["characters"]),
        )

    def test_fragment_automatically_links_known_people_and_manual_names_create_one_time_people(self):
        created = self.content.create_fragment(
            self.revision(),
            {
                "title": "人物识别测试",
                "body": "林秋在门口见到了顾闻川。",
                "appearance_names": ["顾闻川"],
            },
        )
        fragment_id = created.callback_result["entityId"]
        snapshot = self.repository.snapshot()
        lin_qiu = next(item for item in snapshot["characters"] if item["name"] == "林秋")
        temporary = next(item for item in snapshot["characters"] if item["name"] == "顾闻川")
        self.assertEqual("一次性角色", temporary["characterScope"])
        self.assertFalse(temporary["graphVisible"])
        detail = self.repository.entity_detail(fragment_id)["data"]
        self.assertIn(lin_qiu["entityId"], detail["references"])
        self.assertIn(temporary["entityId"], detail["references"])

    def test_story_line_fragment_chapter_uses_the_same_people_recognition(self):
        line = self.content.create_fragment(
            self.revision(),
            {
                "title": "人物识别剧情线",
                "fragment_type": "line",
            },
        )
        line_id = line.callback_result["entityId"]
        chapter = self.content.create_fragment(
            line.project_revision,
            {
                "title": "线内章节",
                "body": "苏眠把文件交给周既明。",
                "fragment_type": "chapter",
                "parent_fragment_id": line_id,
                "fragment_order": 0,
                "chapter_number": 1,
                "appearance_names": ["周既明"],
            },
        )
        detail = self.repository.entity_detail(chapter.callback_result["entityId"])["data"]
        people = {
            item["entityId"]: item for item in self.repository.snapshot()["characters"]
        }
        referenced_names = {
            people[identifier]["name"]
            for identifier in detail["references"]
            if identifier in people
        }
        self.assertEqual({"苏眠", "周既明"}, referenced_names)

    def test_manual_appearance_name_must_exist_in_current_body(self):
        before = len(self.repository.snapshot()["characters"])
        with self.assertRaisesRegex(
            DomainError,
            "出场人物“顾闻川”没有出现在当前正文中",
        ):
            self.content.create_fragment(
                self.revision(),
                {
                    "title": "无效人物",
                    "body": "这里只有一间空房。",
                    "appearance_names": ["顾闻川"],
                },
            )
        self.assertEqual(before, len(self.repository.snapshot()["characters"]))

    def test_plot_people_are_rescanned_and_removed_when_the_name_leaves_the_body(self):
        mentioned = self.content.update_plot(
            "plot:3",
            self.revision(),
            {"body": "林秋走进会议室。", "people": ["character:1"]},
        )
        detail = self.repository.entity_detail("plot:3")["data"]
        self.assertIn("character:1", detail["people"])
        self.assertIn("character:1", detail["references"])

        self.content.update_plot(
            "plot:3",
            mentioned.project_revision,
            {"body": "会议室里已经没有其他人。", "people": []},
        )
        detail = self.repository.entity_detail("plot:3")["data"]
        self.assertNotIn("character:1", detail["people"])
        self.assertNotIn("character:1", detail["references"])

    def test_removing_character_from_plot_body_removes_related_plot_without_touching_character(self):
        character_before = self.repository.entity_detail("character:1")["data"]
        mentioned = self.content.update_plot(
            "plot:3",
            self.revision(),
            {
                "body": "林秋走进会议室。",
                "references": ["character:1"],
            },
        )
        plot = next(item for item in self.repository.snapshot()["plots"] if item["entityId"] == "plot:3")
        self.assertIn("character:1", plot["people"])

        removed = self.content.update_plot(
            "plot:3",
            mentioned.project_revision,
            {
                "body": "会议室里已经没有其他人。",
                "references": ["character:1"],
            },
        )
        plot = next(item for item in self.repository.snapshot()["plots"] if item["entityId"] == "plot:3")
        self.assertNotIn("character:1", plot["people"])
        character_after = self.repository.entity_detail("character:1")["data"]
        self.assertEqual(character_before["revision"], character_after["revision"])
        self.assertIsNotNone(removed.operation_id)

    def test_generic_villain_text_never_maps_to_a_character(self):
        created = self.content.create_character(
            self.revision(),
            {
                "name": "反派",
                "narrative_role": "配角",
                "character_scope": "一次性角色",
                "side": "反派方",
            },
        )
        saved = self.content.update_plot(
            "plot:3",
            created.project_revision,
            {"body": "反派离开房间。\n\n**反派：**\n他没有回头。"},
        )
        plot = next(
            item for item in self.repository.snapshot()["plots"]
            if item["entityId"] == "plot:3"
        )
        villain = next(
            item for item in self.repository.snapshot()["characters"]
            if item["name"] == "反派"
        )
        self.assertNotIn(villain["entityId"], plot["people"])
        self.assertFalse(any(
            item["name"] == "反派" and item["entityId"] != villain["entityId"]
            for item in self.repository.snapshot()["characters"]
        ))
        self.assertIsNotNone(saved.operation_id)

    def test_plot_can_move_to_fragment_in_one_undoable_transaction(self):
        updated = self.content.update_plot(
            "plot:3",
            self.revision(),
            {
                "body": "林秋把尚未采用的场景放回灵感箱。",
                "summary": "待重新构思的场景",
                "tags": ["待重写"],
                "references": ["character:1"],
            },
        )
        converted = self.content.move_plot_to_fragment(
            "plot:3", updated.project_revision
        )
        target_id = converted.callback_result["entityId"]
        snapshot = self.repository.snapshot()
        self.assertNotIn("plot:3", {item["entityId"] for item in snapshot["plots"]})
        fragment = next(
            item for item in snapshot["fragments"] if item["entityId"] == target_id
        )
        self.assertEqual(["待重写"], fragment["tags"])
        detail = self.repository.entity_detail(target_id)["data"]
        self.assertEqual("林秋把尚未采用的场景放回灵感箱。", detail["body"])
        self.assertIn("character:1", detail["references"])
        self.assertTrue(any(item["entityId"] == "plot:3" for item in self.repository.trash()))

        UnitOfWork(self.database, "demo").undo(
            converted.operation_id, converted.project_revision
        )
        restored = self.repository.snapshot()
        self.assertIn("plot:3", {item["entityId"] for item in restored["plots"]})
        self.assertNotIn(target_id, {item["entityId"] for item in restored["fragments"]})

    def test_converted_plot_timeline_slots_do_not_block_future_plot_creates(self):
        converted = self.content.move_plot_to_fragment(
            "plot:6", self.revision()
        )

        created = self.content.create_plot(
            converted.project_revision,
            {
                "title": "转换后的新剧情",
                "body": "回收站中的时间线排序槽不会阻止这次保存。",
            },
        )

        self.assertEqual(converted.project_revision + 1, created.project_revision)
        self.assertIn(
            created.callback_result["entityId"],
            {item["entityId"] for item in self.repository.snapshot()["plots"]},
        )
        with self.database.read() as connection:
            duplicate_count = int(connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT line_id, story_sort_key
                    FROM plot_timeline_lines
                    GROUP BY line_id, story_sort_key
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0])
        self.assertEqual(0, duplicate_count)

    def test_fixed_story_slot_does_not_block_follow_reading_plot_create(self):
        snapshot = self.repository.snapshot()
        next_reading_key = f"{(len(snapshot['plots']) + 1) * 10**12:024d}"
        fixed = self.content.update_plot(
            snapshot["plots"][0]["entityId"],
            self.revision(),
            {
                "story_position_mode": "fixed",
                "story_sort_key": next_reading_key,
            },
        )

        created = self.content.create_plot(
            fixed.project_revision,
            {
                "title": "固定故事位置后的新剧情",
                "body": "新剧情继续跟随阅读顺序。",
            },
        )

        self.assertEqual(fixed.project_revision + 1, created.project_revision)
        with self.database.read() as connection:
            duplicate_count = int(connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT line_id, story_sort_key
                    FROM plot_timeline_lines
                    GROUP BY line_id, story_sort_key
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0])
        self.assertEqual(0, duplicate_count)

    def test_saving_follow_reading_plot_repairs_stale_timeline_story_key(self):
        snapshot = self.repository.snapshot()
        target = snapshot["plots"][0]
        donor = snapshot["plots"][1]
        line_id = target["lanes"][0]

        # Simulate a database written before follow-reading keys were kept in
        # sync. The target's timeline row still has its old key, while the
        # plot row has drifted onto another plot's key.
        with self.database.write() as connection:
            connection.execute(
                "UPDATE plots SET story_sort_key=? WHERE entity_id=?",
                (donor["storySortKey"], target["entityId"]),
            )

        result = self.content.update_plot(
            target["entityId"],
            self.revision(),
            {
                "body": "保存时修复故事时间排序键。",
                "lanes": [line_id],
                "story_position_mode": "follow_reading",
            },
        )

        self.assertEqual(self.revision(), result.project_revision)
        with self.database.read() as connection:
            duplicate_count = int(connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT line_id, story_sort_key
                    FROM plot_timeline_lines
                    GROUP BY line_id, story_sort_key
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0])
            target_key = str(connection.execute(
                "SELECT story_sort_key FROM plots WHERE entity_id=?",
                (target["entityId"],),
            ).fetchone()[0])
            target_node_key = str(connection.execute(
                "SELECT story_sort_key FROM plot_timeline_lines WHERE plot_id=? AND line_id=?",
                (target["entityId"], line_id),
            ).fetchone()[0])
        self.assertEqual(0, duplicate_count)
        self.assertEqual(target_key, target_node_key)

    def test_fragment_can_move_to_next_mainline_plot(self):
        created = self.content.create_fragment(
            self.revision(),
            {
                "title": "雨夜追踪",
                "body": "**林秋：**\n先去码头。",
                "tags": ["待采用"],
                "references": ["character:1"],
                "accent": "#445566",
            },
        )
        fragment_id = created.callback_result["entityId"]
        converted = self.content.move_fragment_to_plot(
            fragment_id, created.project_revision
        )
        target_id = converted.callback_result["entityId"]
        snapshot = self.repository.snapshot()
        self.assertNotIn(
            fragment_id, {item["entityId"] for item in snapshot["fragments"]}
        )
        plot = next(item for item in snapshot["plots"] if item["entityId"] == target_id)
        self.assertEqual("", plot["chapterId"])
        self.assertEqual("", plot["summary"])
        self.assertEqual("#445566", plot["accent"])
        self.assertEqual(["待采用"], plot["tags"])
        self.assertIn("character:1", plot["people"])
        self.assertEqual(
            "**林秋：**\n先去码头。",
            self.repository.entity_detail(target_id)["data"]["body"],
        )
        self.assertTrue(
            any(item["entityId"] == fragment_id for item in self.repository.trash())
        )


if __name__ == "__main__":
    unittest.main()
