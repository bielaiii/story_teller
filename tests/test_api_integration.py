import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from server import StoryTellerHandler, StoryTellerServer


class QuietHandler(StoryTellerHandler):
    def log_message(self, format, *args):
        return


class LocalApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.content_root = Path(self.temporary_directory.name) / "content"
        self.project_root = self.content_root / "novel"
        for directory in ("characters", "plots", "entries", "fragments", "relationships"):
            (self.project_root / directory).mkdir(parents=True, exist_ok=True)
        (self.project_root / "manifest.md").write_text(
            "---\ntitle: 测试作品\nchapters: [act1]\nchapterAct1: 第一篇\n---\n",
            encoding="utf-8",
        )
        self.server = StoryTellerServer(
            ("127.0.0.1", 0),
            QuietHandler,
            content_root=self.content_root,
            default_project="novel",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        capabilities = self.get_json("/api/capabilities?project=novel")
        self.token = capabilities["token"]
        self.assertEqual("sqlite", capabilities["storage"])
        self.assertIn("sqlite-storage-v1", capabilities["features"])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary_directory.cleanup()

    def get_json(self, path):
        with urlopen(self.base_url + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path, payload):
        request = Request(
            self.base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Story-Teller-Token": self.token,
            },
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_character_write_route_persists_and_reads_back_without_restart(self):
        created = self.post_json("/api/characters/create", {
            "project": "novel", "name": "顾遥", "narrativeRole": "配角",
            "characterScope": "常驻人物", "side": "主角方", "group": "调查组",
            "mainPlotImpact": 64, "color": "#3f7fc1", "aliases": ["小顾"],
            "markers": ["记者"], "facts": {"身份": "记者"}, "intro": "初始档案",
        })
        self.assertTrue(created["ok"])
        character_path = self.project_root / created["path"]
        self.assertTrue(character_path.is_file())

        updated = self.post_json("/api/characters/update", {
            "project": "novel", "id": created["id"], "name": "顾遥",
            "narrativeRole": "配角", "characterScope": "主线人物", "side": "主角方",
            "group": "调查组", "mainPlotImpact": 81, "color": "#2a9d8f",
            "aliases": ["小顾"], "markers": ["记者"], "facts": {"身份": "调查记者"},
            "intro": "保存后的完整档案", "graphVisible": True,
        })
        self.assertTrue(updated["ok"])
        persisted = character_path.read_text(encoding="utf-8")
        self.assertIn("mainPlotImpact: 81", persisted)
        self.assertIn("保存后的完整档案", persisted)
        index = self.get_json("/api/content-index?project=novel")
        self.assertIn(f"./{created['path']}", index["collections"]["characters"])
        project_data = self.get_json("/api/project-data?project=novel")
        self.assertEqual("sqlite", project_data["storage"])
        self.assertIn("保存后的完整档案", project_data["documents"][created["path"]])
        (self.project_root / "manifest.md").write_text("---\ntitle: 手工篡改标题\n---\n", encoding="utf-8")
        projects = self.get_json("/api/projects")
        self.assertEqual("测试作品", projects["items"][0]["title"])
        character_path.write_text("不会成为数据源", encoding="utf-8")
        project_data = self.get_json("/api/project-data?project=novel")
        self.assertIn("保存后的完整档案", project_data["documents"][created["path"]])
        self.assertNotIn("不会成为数据源", project_data["documents"][created["path"]])
        preview = self.post_json("/api/refactor/preview", {
            "project": "novel", "type": "character", "id": created["id"], "newName": "顾澜",
        })
        self.assertTrue(preview["ok"])
        self.assertIn("保存后的完整档案", character_path.read_text(encoding="utf-8"))
        storage = self.get_json("/api/storage?project=novel")
        self.assertEqual(1, storage["schemaVersion"])
        self.assertEqual("/api/characters/update", storage["lastOperation"])
        self.assertEqual(1, storage["counts"]["characters"])


if __name__ == "__main__":
    unittest.main()
