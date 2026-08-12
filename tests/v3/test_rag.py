from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from storyteller.app import create_app
from storyteller.domain.content import ContentService
from storyteller.domain.services import EntityService
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

    def test_source_revision_change_is_synchronized_before_the_next_read(self):
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
        entity = self.manager.entity("demo", "character:1")
        refreshed = self.manager.status("demo")
        self.assertGreater(refreshed["sourceRevision"], original["sourceRevision"])
        self.assertTrue(refreshed["fresh"])
        self.assertEqual("full", refreshed["lastSyncMode"])
        self.assertIn("低频 RAG 自动更新验证", entity["content"])

    def test_managed_revision_change_incrementally_updates_only_affected_documents(self):
        self.manager.ensure_fresh("demo")
        database = Database(self.project_root)
        result = ContentService(database, "demo").update_character(
            "character:1", 0, {"intro": "林秋的新线索只应更新相关检索文档。"}
        )
        self.assertEqual(1, result.project_revision)
        entity = self.manager.entity("demo", "character:1")
        status = self.manager.status("demo")
        self.assertEqual("incremental", status["lastSyncMode"])
        self.assertGreaterEqual(status["lastChangedDocuments"], 1)
        self.assertLess(status["lastChangedDocuments"], status["documents"])
        self.assertIn("林秋的新线索", entity["content"])

    def test_world_schema_change_forces_a_full_rebuild_without_content_revision(self):
        original = self.manager.ensure_fresh("demo")
        with sqlite3.connect(rag_path(self.project_root)) as connection:
            connection.execute("UPDATE meta SET value='stale-registry' WHERE key='world_schema_hash'")
        self.assertFalse(self.manager.status("demo")["fresh"])
        refreshed = self.manager.ensure_fresh("demo")
        self.assertEqual(original["sourceRevision"], refreshed["sourceRevision"])
        self.assertEqual("full", refreshed["lastSyncMode"])
        self.assertEqual(refreshed["worldSchemaHash"], refreshed["currentWorldSchemaHash"])

    def test_confirmed_unplaced_fragments_are_searched_by_default(self):
        result = self.manager.search("demo", "雨夜敲门声", limit=5)
        fragment = next(item for item in result["results"] if item["entityId"] == "fragment:rain-knocking")
        self.assertEqual("confirmed", fragment["certainty"])
        self.assertEqual("unplaced", fragment["timelineStatus"])
        entity = self.manager.entity("demo", "fragment:rain-knocking")
        self.assertTrue(entity["canonical"])
        self.assertIn("尚未正式编入时间线", entity["content"])

    def test_incremental_delete_removes_fragment_document_and_fts_rows(self):
        self.manager.ensure_fresh("demo")
        EntityService(Database(self.project_root), "demo").delete("fragment:rain-knocking", 0)
        result = self.manager.search("demo", "雨夜敲门声", limit=10)
        self.assertNotIn("fragment:rain-knocking", [item["entityId"] for item in result["results"]])
        self.assertIsNone(self.manager.entity("demo", "fragment:rain-knocking"))
        status = self.manager.status("demo")
        self.assertEqual("incremental", status["lastSyncMode"])
        self.assertEqual(1, status["lastRemovedDocuments"])

    def test_context_combines_live_structured_facts_with_rag(self):
        context = self.manager.context("demo", "林秋与沈砚是什么关系？", limit=8)
        self.assertGreaterEqual(context["retrieval"]["structured"], 2)
        self.assertIn("互相试探", context["contextMarkdown"])
        self.assertTrue(any(item["retrieval"] == "structured" for item in context["citations"]))

    def test_structured_reader_exposes_schema_resolution_and_directional_facts(self):
        database = Database(self.project_root)
        with database.write() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO entry_characters(entry_id, character_id, role, status, sort_key) VALUES('entry:harbor-gate-company', 'character:1', '档案顾问', '现成员', 0)"
            )
            connection.execute(
                "UPDATE relationships SET from_impression='谨慎信任', to_impression='仍在观察' WHERE entity_id='relationship:1__2'"
            )
        schema = self.manager.world_schema("demo")
        self.assertEqual("from-to", schema["entityKinds"]["relationship"]["fields"]["fromImpression"]["direction"])
        resolved = self.manager.resolve("demo", "阿秋")
        self.assertEqual("character:1", resolved["results"][0]["entityId"])
        entity = self.manager.structured_entity("demo", "character:1")
        self.assertEqual("林秋", entity["data"]["name"])
        self.assertEqual("档案顾问", entity["related"]["organizations"][0]["role"])
        relation = next(item for item in entity["related"]["relationships"] if item["otherCharacterId"] == "character:2")
        self.assertEqual("谨慎信任", relation["impression"])
        self.assertEqual("仍在观察", relation["otherImpression"])

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
            schema = client.get("/api/v1/projects/demo/rag/world/schema")
            self.assertEqual(200, schema.status_code, schema.text)
            self.assertIn("relationship", schema.json()["entityKinds"])
            resolved = client.get("/api/v1/projects/demo/rag/world/resolve", params={"q": "阿秋"})
            self.assertEqual("character:1", resolved.json()["results"][0]["entityId"])
            structured = client.get("/api/v1/projects/demo/rag/world/entities/character:1")
            self.assertEqual("林秋", structured.json()["data"]["name"])
            related = client.get("/api/v1/projects/demo/rag/world/entities/character:1/related")
            self.assertEqual(200, related.status_code, related.text)
            self.assertIn("relationships", related.json())
            queried = client.post(
                "/api/v1/projects/demo/rag/world/query",
                json={"kinds": ["entry"], "filters": {"type": "组织"}},
            )
            self.assertEqual("entry:harbor-gate-company", queried.json()["results"][0]["entityId"])
            configured = client.put(
                "/api/v1/projects/demo/rag/config",
                headers={"X-Story-Teller-Token": meta["mutationToken"]},
                json={"provider": "builtin", "model": "hash-char-3-v1", "dimensions": 192},
            )
            self.assertEqual(200, configured.status_code, configured.text)
            self.assertEqual(192, configured.json()["embedding"]["dimensions"])
            tools = asyncio.run(app.state.mcp_server.list_tools())
            tool_names = [tool.name for tool in tools]
            self.assertTrue({
                "list_world_projects", "describe_world", "resolve_world_entity", "query_world",
                "search_world", "get_world_entity",
            }.issubset(tool_names))
            called = asyncio.run(app.state.mcp_server.call_tool(
                "search_world", {"project": "demo", "query": "林秋", "limit": 3}
            ))
            self.assertIsNotNone(called)
            described = asyncio.run(app.state.mcp_server.call_tool(
                "describe_world", {"project": "demo"}
            ))
            self.assertIsNotNone(described)
            direct = asyncio.run(app.state.mcp_server.call_tool(
                "get_world_entity", {"project": "demo", "entity_id": "character:1"}
            ))
            self.assertIsNotNone(direct)
            mounted = client.post("/mcp", follow_redirects=False)
            self.assertEqual(307, mounted.status_code)
            self.assertEqual("/mcp/", mounted.headers["location"])

    def test_global_launcher_discovers_workspace_and_serves_stdio_without_a_port(self):
        nested = self.project_root / "notes" / "drafts"
        nested.mkdir(parents=True)
        environment = {**os.environ, "STORY_WORLD_MCP_DRY_RUN": "1"}
        discovered = subprocess.run(
            [str(ROOT / "story-world-mcp")], cwd=nested, env=environment,
            check=True, capture_output=True, text=True,
        )
        payload = json.loads(discovered.stdout)
        self.assertEqual(str(self.content_root.resolve()), payload["contentRoot"])
        self.assertEqual(["demo"], payload["projects"])
        self.assertEqual("demo", payload["defaultProject"])
        self.assertNotIn("--port", payload["command"])

        async def use_stdio():
            parameters = StdioServerParameters(
                command=str(ROOT / "story-world-mcp"), cwd=nested,
            )
            async with Client(stdio_client(parameters), mode="legacy") as client:
                tools = await client.list_tools()
                self.assertIn("list_world_projects", [tool.name for tool in tools.tools])
                projects = await client.call_tool("list_world_projects", {})
                self.assertEqual(["demo"], projects.structured_content["projects"])
                searched = await client.call_tool("search_world", {"query": "林秋", "limit": 3})
                self.assertEqual("character:1", searched.structured_content["results"][0]["entityId"])

        asyncio.run(use_stdio())

    def test_launcher_requires_explicit_selection_for_a_multi_project_workspace(self):
        second = self.content_root / "second"
        second.mkdir()
        shutil.copy2(self.project_root / "story.db", second / "story.db")
        environment = {**os.environ, "STORY_WORLD_MCP_DRY_RUN": "1"}
        discovered = subprocess.run(
            [str(ROOT / "story-world-mcp")], cwd=self.content_root.parent,
            env=environment, check=True, capture_output=True, text=True,
        )
        payload = json.loads(discovered.stdout)
        self.assertEqual(["demo", "second"], payload["projects"])
        self.assertEqual("", payload["defaultProject"])
        selected = subprocess.run(
            [str(ROOT / "story-world-mcp")], cwd=second,
            env=environment, check=True, capture_output=True, text=True,
        )
        self.assertEqual("second", json.loads(selected.stdout)["defaultProject"])

    def test_installer_creates_a_standalone_launcher_in_a_path_directory(self):
        install_root = Path(self.temporary.name) / "bin"
        install_root.mkdir()
        environment = {**os.environ, "STORY_WORLD_MCP_BIN_DIR": str(install_root)}
        subprocess.run(
            [str(ROOT / "scripts" / "install-story-world-mcp.sh")],
            env=environment, check=True, capture_output=True, text=True,
        )
        installed = install_root / "story-world-mcp"
        self.assertTrue(installed.is_file())
        self.assertFalse(installed.is_symlink())
        self.assertTrue(os.access(installed, os.X_OK))

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
