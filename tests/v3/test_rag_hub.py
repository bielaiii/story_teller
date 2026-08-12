from __future__ import annotations

import asyncio
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from storyteller.rag.hub_registry import HUB_PROTOCOL_VERSION, HubRegistry
from storyteller.rag.hubctl import ensure_token, register_workspace, start_or_reuse_hub
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class RagHubTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.state_dir = self.base / "hub-state"
        self.repositories: list[Path] = []
        self.hub_pid: int | None = None

    def tearDown(self):
        if self.hub_pid:
            try:
                os.kill(self.hub_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    waited, _status = os.waitpid(self.hub_pid, os.WNOHANG)
                except ChildProcessError:
                    waited = self.hub_pid
                if waited == self.hub_pid:
                    break
                time.sleep(0.05)
            else:
                try:
                    os.kill(self.hub_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.temporary.cleanup()

    def make_repository(self, name: str) -> Path:
        repository = self.base / name
        project_root = repository / "content" / "demo"
        project_root.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        (repository / "story_teller").symlink_to(ROOT, target_is_directory=True)
        legacy = project_root / "legacy.db"
        shutil.copy2(ROOT / "tests" / "fixtures" / "schema-v1-demo.db", legacy)
        V3Migrator(legacy, "demo").migrate_to(project_root / "story.db")
        self.repositories.append(repository)
        return repository

    @staticmethod
    def free_port() -> int:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def remember_hub(self) -> None:
        self.hub_pid = int((self.state_dir / "hub.pid").read_text(encoding="utf-8").strip())

    def test_registry_has_stable_ids_persists_and_prunes_missing_repositories(self):
        repository = self.make_repository("novel-a")
        registry_path = self.state_dir / "registry.json"
        registry = HubRegistry(registry_path)
        first = registry.prepare({
            "repositoryRoot": str(repository),
            "contentRoot": str(repository / "content"),
            "frameworkRoot": str(repository / "story_teller"),
            "project": "demo",
            "displayName": "Novel A",
        })
        registry.upsert(first)
        loaded = HubRegistry(registry_path)
        self.assertEqual(HUB_PROTOCOL_VERSION, 1)
        self.assertEqual(first.workspace_id, loaded.resolve("Novel A").workspace_id)
        self.assertEqual(first.workspace_id, loaded.resolve("demo").workspace_id)

        (repository / "content" / "demo" / "story.db").unlink()
        self.assertEqual([first.workspace_id], loaded.prune())
        self.assertEqual([], loaded.records())

    def test_hub_reuses_one_port_and_routes_two_git_repositories(self):
        first_repository = self.make_repository("novel-a")
        second_repository = self.make_repository("novel-b")
        port = self.free_port()
        token = ensure_token(self.state_dir)
        health, started = start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.assertTrue(started)
        self.assertEqual("story-world-hub", health["service"])
        self.remember_hub()
        self.assertEqual(self.hub_pid, health["processId"])

        first = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=first_repository,
            content_root=first_repository / "content",
            framework_root=first_repository / "story_teller",
            project="demo", display_name="Novel A",
        )
        second = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=second_repository,
            content_root=second_repository / "content",
            framework_root=second_repository / "story_teller",
            project="demo", display_name="Novel B",
        )
        reused, started_again = start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=5,
        )
        self.assertFalse(started_again)
        self.assertEqual(health["instanceId"], reused["instanceId"])

        with httpx.Client(trust_env=False) as http:
            listed = http.get(f"http://127.0.0.1:{port}/api/v1/hub/workspaces").json()
            self.assertEqual(2, len(listed["workspaces"]))
            denied = http.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces",
                json={
                    "repositoryRoot": str(first_repository),
                    "contentRoot": str(first_repository / "content"),
                    "frameworkRoot": str(first_repository / "story_teller"),
                    "project": "demo",
                },
            )
            self.assertEqual(403, denied.status_code)

        async def use_hub_mcp():
            transport = streamable_http_client(f"http://127.0.0.1:{port}/mcp/")
            async with Client(transport, mode="legacy") as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertIn("list_world_workspaces", names)
                self.assertIn("search_world", names)
                workspaces = await client.call_tool("list_world_workspaces", {})
                self.assertEqual(2, len(workspaces.structured_content["workspaces"]))
                searched = await client.call_tool("search_world", {
                    "workspace": first["workspace"]["displayName"],
                    "query": "林秋", "limit": 3,
                })
                self.assertEqual("character:1", searched.structured_content["results"][0]["entityId"])
                self.assertEqual(
                    first["workspace"]["workspaceId"],
                    searched.structured_content["workspaceId"],
                )
                ambiguous = await client.call_tool("rag_status", {})
                self.assertTrue(ambiguous.is_error)

        asyncio.run(use_hub_mcp())
        self.assertNotEqual(
            first["workspace"]["workspaceId"],
            second["workspace"]["workspaceId"],
        )

    def test_non_hub_listener_is_never_reused_or_stopped(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"not a hub")

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "非 Story World Hub"):
                start_or_reuse_hub(
                    host="127.0.0.1", port=server.server_port,
                    state_dir=self.state_dir, framework_root=ROOT, timeout=1,
                )
            self.assertTrue(thread.is_alive())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_run_rag_script_registers_from_an_arbitrary_working_directory(self):
        repository = self.make_repository("novel-script")
        port = self.free_port()
        environment = {
            **os.environ,
            "STORY_WORLD_HUB_PORT": str(port),
            "STORY_WORLD_HUB_STATE_DIR": str(self.state_dir),
            "STORY_TELLER_CONTENT_ROOT": str(repository / "content"),
            "STORY_TELLER_DEFAULT_PROJECT": "demo",
        }
        result = subprocess.run(
            [str(ROOT / "run-rag.sh")],
            cwd=self.base,
            env=environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("已注册工作区", result.stdout)
        self.remember_hub()
        with httpx.Client(trust_env=False) as client:
            workspaces = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"]
        self.assertEqual("novel-script", workspaces[0]["displayName"])


if __name__ == "__main__":
    unittest.main()
