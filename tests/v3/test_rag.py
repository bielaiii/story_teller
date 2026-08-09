from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

from storyteller.app import create_app
from storyteller.rag.app import create_rag_app
from storyteller.rag.index import rag_path
from storyteller.rag.manager import RagManager
from storyteller.settings import Settings
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class RagTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.content_root = Path(self.temporary.name) / "content"
        self.project_root = self.content_root / "demo"
        self.project_root.mkdir(parents=True)
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.project_root / "legacy.db")
        V3Migrator(self.project_root / "legacy.db", "demo").migrate_to(self.project_root / "story.db")
        self.settings = Settings.create(
            ROOT, content_root=self.content_root,
            frontend_root=Path(self.temporary.name) / "missing",
            default_project="demo",
        )
        self.manager = RagManager(self.settings)

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_index_is_built_and_searches_structured_world_data(self):
        path = rag_path(self.project_root)
        self.assertFalse(path.exists())
        status = self.manager.ensure_fresh("demo")
        self.assertTrue(path.exists())
        self.assertTrue(status["fresh"])
        self.assertGreater(status["documents"], 0)
        result = self.manager.search("demo", "林秋是谁？", limit=3)
        self.assertTrue(result["results"])
        self.assertEqual("character:1", result["results"][0]["entityId"])
        entity = self.manager.entity("demo", "character:1")
        self.assertIn("林秋", entity["content"])
        self.assertIn("citation", entity)

    def test_source_revision_change_is_synchronized_on_next_startup(self):
        original = self.manager.ensure_fresh("demo")
        database = Database(self.project_root)
        with database.write() as connection:
            connection.execute(
                "UPDATE characters SET intro_markdown=intro_markdown || ? WHERE entity_id='character:1'",
                ("\n低频 RAG 自动更新验证。",),
            )
            connection.execute("UPDATE entities SET revision=revision+1 WHERE id='character:1'")
            connection.execute("UPDATE projects SET revision=revision+1 WHERE id='demo'")
        stale = self.manager.status("demo")
        self.assertFalse(stale["fresh"])
        unchanged = self.manager.ensure_fresh("demo")
        self.assertEqual(original["sourceRevision"], unchanged["sourceRevision"])
        self.assertNotIn("低频 RAG 自动更新验证", self.manager.entity("demo", "character:1")["content"])

        restarted = RagManager(self.settings)
        restarted.startup()
        refreshed = restarted.status("demo")
        self.assertGreater(refreshed["sourceRevision"], original["sourceRevision"])
        self.assertIn("低频 RAG 自动更新验证", restarted.entity("demo", "character:1")["content"])

    def test_deleting_index_rebuilds_and_embedding_model_can_switch(self):
        self.manager.ensure_fresh("demo")
        rag_path(self.project_root).unlink()
        rebuilt = self.manager.ensure_fresh("demo")
        self.assertTrue(rebuilt["exists"])
        configured = self.manager.configure("demo", {
            "provider": "builtin", "model": "hash-char-3-v1", "dimensions": 256,
        })
        self.assertEqual("hash-char-3-v1", configured["embedding"]["model"])
        self.assertEqual(256, configured["embedding"]["dimensions"])
        self.assertEqual("ready", configured["rebuild"]["embeddingStatus"])
        rag_path(self.project_root).unlink()
        restored = self.manager.ensure_fresh("demo")
        self.assertEqual("hash-char-3-v1", restored["embedding"]["model"])
        self.assertEqual(256, restored["embedding"]["dimensions"])

    def test_http_and_mcp_expose_the_same_index(self):
        app = create_rag_app(self.settings)
        with TestClient(app) as client:
            meta = client.get("/api/v1/meta?project=demo").json()
            response = client.get("/api/v1/projects/demo/rag/search", params={"q": "林秋"})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual("character:1", response.json()["results"][0]["entityId"])
            configured = client.put(
                "/api/v1/projects/demo/rag/config",
                headers={"X-Story-Teller-Token": meta["mutationToken"]},
                json={"provider": "builtin", "model": "hash-char-3-v1", "dimensions": 192},
            )
            self.assertEqual(200, configured.status_code, configured.text)
            self.assertEqual(192, configured.json()["embedding"]["dimensions"])
            tools = asyncio.run(app.state.mcp_server.list_tools())
            self.assertIn("search_world", [tool.name for tool in tools])
            called = asyncio.run(app.state.mcp_server.call_tool(
                "search_world", {"project": "demo", "query": "林秋", "limit": 3}
            ))
            self.assertIsNotNone(called)
            mounted = client.post("/mcp", follow_redirects=False)
            self.assertEqual(307, mounted.status_code)
            self.assertEqual("/mcp/", mounted.headers["location"])

    def test_main_writing_service_does_not_mount_rag(self):
        app = create_app(self.settings)
        with TestClient(app) as client:
            self.assertEqual(404, client.get("/api/v1/projects/demo/rag/status").status_code)
            self.assertEqual(404, client.post("/mcp").status_code)

    def test_openai_compatible_embedding_model_can_be_selected(self):
        class EmbeddingHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                inputs = payload["input"] if isinstance(payload["input"], list) else [payload["input"]]
                body = json.dumps({
                    "data": [
                        {"index": index, "embedding": [1.0] + [0.0] * 31}
                        for index, _value in enumerate(inputs)
                    ]
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), EmbeddingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            configured = self.manager.configure("demo", {
                "provider": "openai-compatible", "model": "mock-embedding-v2",
                "dimensions": 32, "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
                "apiKeyEnv": "RAG_TEST_UNUSED_KEY", "batchSize": 8,
            })
            self.assertEqual("mock-embedding-v2", configured["embedding"]["model"])
            self.assertEqual("ready", configured["rebuild"]["embeddingStatus"])
            result = self.manager.search("demo", "林秋是谁？", limit=3)
            self.assertTrue(result["results"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
