from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from storyteller.app import create_app
from storyteller.bootstrap import prepare_project
from storyteller.domain.merge_conflicts import MergeConflictService, has_open_merge
from storyteller.merge_driver import build_merge
from storyteller.settings import Settings
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class MergeDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.base_root = self.root / "base" / "demo"
        self.ours_root = self.root / "ours" / "demo"
        self.theirs_root = self.root / "theirs" / "demo"
        self.result_root = self.root / "result" / "demo"
        for root in (self.base_root, self.ours_root, self.theirs_root, self.result_root):
            root.mkdir(parents=True)
        legacy = self.root / "legacy.db"
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", legacy)
        V3Migrator(legacy, "demo").migrate_to(self.base_root / "story.db")
        shutil.copy2(self.base_root / "story.db", self.ours_root / "story.db")
        shutil.copy2(self.base_root / "story.db", self.theirs_root / "story.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def update(
        database: Path,
        statement: str,
        parameters: tuple[object, ...],
        entity_id: str,
    ) -> None:
        with sqlite3.connect(database) as connection:
            connection.execute(statement, parameters)
            connection.execute(
                "UPDATE entities SET revision=revision+1, updated_at=updated_at+1 WHERE id=?",
                (entity_id,),
            )
            connection.execute(
                "UPDATE projects SET revision=revision+1, updated_at=updated_at+1 WHERE id='demo'"
            )

    def test_non_overlapping_rows_are_merged_without_a_session(self) -> None:
        self.update(
            self.ours_root / "story.db",
            "UPDATE characters SET intro_markdown=? WHERE entity_id='character:1'",
            ("当前电脑补充的人物介绍",),
            "character:1",
        )
        self.update(
            self.theirs_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("另一台电脑补充的剧情摘要",),
            "plot:1",
        )

        count, session_id = build_merge(
            self.base_root / "story.db",
            self.ours_root / "story.db",
            self.theirs_root / "story.db",
            self.result_root / "story.db",
            "content/demo/story.db",
        )

        self.assertEqual(0, count)
        self.assertIsNone(session_id)
        self.assertEqual([], list(self.root.rglob("*-wal")))
        self.assertEqual([], list(self.root.rglob("*-shm")))
        with sqlite3.connect(self.result_root / "story.db") as connection:
            self.assertEqual(
                "当前电脑补充的人物介绍",
                connection.execute(
                    "SELECT intro_markdown FROM characters WHERE entity_id='character:1'"
                ).fetchone()[0],
            )
            self.assertEqual(
                "另一台电脑补充的剧情摘要",
                connection.execute(
                    "SELECT summary FROM plots WHERE entity_id='plot:1'"
                ).fetchone()[0],
            )
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM merge_sessions WHERE status='open'"
            ).fetchone()[0])
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_same_field_is_preserved_and_can_be_resolved_manually(self) -> None:
        self.update(
            self.ours_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("当前电脑版本",),
            "plot:1",
        )
        self.update(
            self.theirs_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("远程版本",),
            "plot:1",
        )

        count, session_id = build_merge(
            self.base_root / "story.db",
            self.ours_root / "story.db",
            self.theirs_root / "story.db",
            self.result_root / "story.db",
            "content/demo/story.db",
        )

        self.assertEqual(1, count)
        self.assertIsNotNone(session_id)
        database = Database(self.result_root)
        self.assertTrue(has_open_merge(database, "demo"))
        service = MergeConflictService(database, "demo")
        state = service.current()
        self.assertTrue(state["required"])
        self.assertEqual("summary", state["items"][0]["fields"][0]["name"])
        self.assertEqual("当前电脑版本", state["items"][0]["fields"][0]["ours"])
        self.assertEqual("远程版本", state["items"][0]["fields"][0]["theirs"])

        service.save(
            state["items"][0]["id"],
            {"summary": {"choice": "manual", "value": "人工保留双方重点"}},
        )
        result = service.finalize(str(session_id))
        self.assertIsNotNone(result.operation_id)
        self.assertFalse(has_open_merge(database, "demo"))
        with database.read() as connection:
            self.assertEqual(
                "人工保留双方重点",
                connection.execute(
                    "SELECT summary FROM plots WHERE entity_id='plot:1'"
                ).fetchone()[0],
            )
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))

    def test_non_overlapping_paragraph_edits_use_gits_native_text_merge(self) -> None:
        base_body = "第一段原文\n\n中间共同段落\n\n第三段原文\n"
        with sqlite3.connect(self.base_root / "story.db") as connection:
            connection.execute(
                "UPDATE plots SET body_markdown=? WHERE entity_id='plot:1'", (base_body,)
            )
        shutil.copy2(self.base_root / "story.db", self.ours_root / "story.db")
        shutil.copy2(self.base_root / "story.db", self.theirs_root / "story.db")
        self.update(
            self.ours_root / "story.db",
            "UPDATE plots SET body_markdown=? WHERE entity_id='plot:1'",
            ("第一段由当前电脑修改\n\n中间共同段落\n\n第三段原文\n",),
            "plot:1",
        )
        self.update(
            self.theirs_root / "story.db",
            "UPDATE plots SET body_markdown=? WHERE entity_id='plot:1'",
            ("第一段原文\n\n中间共同段落\n\n第三段由另一台电脑修改\n",),
            "plot:1",
        )

        count, _ = build_merge(
            self.base_root / "story.db",
            self.ours_root / "story.db",
            self.theirs_root / "story.db",
            self.result_root / "story.db",
            "content/demo/story.db",
        )

        self.assertEqual(0, count)
        with sqlite3.connect(self.result_root / "story.db") as connection:
            body = connection.execute(
                "SELECT body_markdown FROM plots WHERE entity_id='plot:1'"
            ).fetchone()[0]
        self.assertIn("第一段由当前电脑修改", body)
        self.assertIn("第三段由另一台电脑修改", body)

    def test_api_blocks_writes_until_every_conflict_is_resolved(self) -> None:
        self.update(
            self.ours_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("本地摘要",),
            "plot:1",
        )
        self.update(
            self.theirs_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("远程摘要",),
            "plot:1",
        )
        _, session_id = build_merge(
            self.base_root / "story.db",
            self.ours_root / "story.db",
            self.theirs_root / "story.db",
            self.result_root / "story.db",
            "content/demo/story.db",
        )
        settings = Settings.create(
            ROOT,
            content_root=self.result_root.parent,
            frontend_root=self.root / "missing",
            default_project="demo",
        )
        client = TestClient(create_app(settings))
        meta = client.get("/api/v1/meta?project=demo").json()
        headers = {"X-Story-Teller-Token": meta["mutationToken"]}
        self.assertTrue(meta["mergeRequired"])
        self.assertFalse(meta["contentWritable"])
        snapshot = client.get("/api/v1/projects/demo/snapshot").json()
        blocked = client.patch(
            "/api/v1/projects/demo/plots/plot:1",
            headers=headers,
            json={
                "baseRevision": snapshot["project"]["revision"],
                "entityRevision": snapshot["plots"][0]["revision"],
                "summary": "不应写入",
            },
        )
        self.assertEqual(423, blocked.status_code, blocked.text)
        self.assertEqual("merge_required", blocked.json()["code"])

        conflicts = client.get("/api/v1/projects/demo/merge-conflicts").json()
        conflict = conflicts["items"][0]
        saved = client.put(
            f"/api/v1/projects/demo/merge-conflicts/{conflict['id']}",
            headers=headers,
            json={"resolutions": {"summary": {"choice": "theirs"}}},
        )
        self.assertEqual(200, saved.status_code, saved.text)
        completed = client.post(
            f"/api/v1/projects/demo/merge-conflicts/{session_id}/finalize",
            headers=headers,
        )
        self.assertEqual(200, completed.status_code, completed.text)
        self.assertFalse(client.get("/api/v1/meta?project=demo").json()["mergeRequired"])
        detail = client.get("/api/v1/projects/demo/entities/plot:1").json()
        self.assertEqual("远程摘要", detail["data"]["summary"])

    def test_deployment_preparation_preserves_conflicts_and_skips_content_work(self) -> None:
        self.update(
            self.ours_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("本地部署版本",),
            "plot:1",
        )
        self.update(
            self.theirs_root / "story.db",
            "UPDATE plots SET summary=? WHERE entity_id='plot:1'",
            ("远程部署版本",),
            "plot:1",
        )
        build_merge(
            self.base_root / "story.db",
            self.ours_root / "story.db",
            self.theirs_root / "story.db",
            self.result_root / "story.db",
            "content/demo/story.db",
        )

        result = prepare_project(self.result_root)

        self.assertTrue(result["mergeRequired"])
        self.assertTrue(result["maintenance"]["skipped"])
        self.assertEqual("blocked", result["export"]["status"])
        self.assertTrue(has_open_merge(Database(self.result_root), "demo"))


if __name__ == "__main__":
    unittest.main()
