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
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from storyteller.rag.hub_registry import HUB_PROTOCOL_VERSION, HubRegistry
from storyteller.rag.hubctl import (
    acquire_web_lease,
    ensure_token,
    register_workspace,
    release_web_lease,
    set_independent_mcp,
    start_or_reuse_hub,
    start_or_reuse_web_hub,
)
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class RagHubTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.state_dir = self.base / "hub-state"
        self.repositories: list[Path] = []
        self.hub_pid: int | None = None
        self.web_hub_pid: int | None = None

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
        if self.web_hub_pid:
            try:
                os.kill(self.web_hub_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.temporary.cleanup()

    def make_repository(self, name: str) -> Path:
        repository = self.base / name
        (repository / "content").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repository)], check=True)
        (repository / "story_teller").symlink_to(ROOT, target_is_directory=True)
        self.add_project(repository, "demo")
        self.repositories.append(repository)
        return repository

    @staticmethod
    def add_project(repository: Path, project: str) -> None:
        project_root = repository / "content" / project
        project_root.mkdir(parents=True)
        legacy = project_root / "legacy.db"
        shutil.copy2(ROOT / "tests" / "fixtures" / "schema-v1-demo.db", legacy)
        V3Migrator(legacy, project).migrate_to(project_root / "story.db")

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
        self.assertEqual(HUB_PROTOCOL_VERSION, 3)
        self.assertEqual(first.workspace_id, loaded.resolve("Novel A").workspace_id)
        self.assertEqual(first.workspace_id, loaded.resolve("demo").workspace_id)
        self.assertEqual(["demo"], loaded.projects(first))
        self.assertEqual("demo", loaded.resolve_project(first))

        self.add_project(repository, "novel-a")
        matching = replace(first, display_name="novel-a")
        self.assertEqual("novel-a", loaded.default_project(matching))
        self.assertEqual("novel-a", loaded.resolve_project(matching))
        ambiguous = replace(first, display_name="no-match")
        with self.assertRaisesRegex(ValueError, "请指定 project"):
            loaded.resolve_project(ambiguous)
        self.assertEqual("demo", loaded.resolve_project(ambiguous, "demo"))

        second_content = repository / "content-secondary"
        second_content.mkdir()
        second_project = second_content / "demo"
        second_project.mkdir()
        shutil.copy2(repository / "content" / "demo" / "story.db", second_project / "story.db")
        secondary = loaded.prepare({
            "repositoryRoot": str(repository),
            "contentRoot": str(second_content),
            "frameworkRoot": str(repository / "story_teller"),
            "project": "demo",
            "displayName": "Novel A Secondary",
        })
        self.assertNotEqual(first.workspace_id, secondary.workspace_id)

        (repository / "content" / "demo" / "story.db").unlink()
        (repository / "content" / "novel-a" / "story.db").unlink()
        self.assertEqual([first.workspace_id], loaded.prune())
        self.assertEqual([], loaded.records())

    def test_hub_reuses_one_port_and_routes_two_git_repositories(self):
        first_repository = self.make_repository("novel-a")
        self.add_project(first_repository, "side-story")
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
        set_independent_mcp(
            host="127.0.0.1", port=port, token=token,
            workspace_id=first["workspace"]["workspaceId"], enabled=True,
        )
        set_independent_mcp(
            host="127.0.0.1", port=port, token=token,
            workspace_id=second["workspace"]["workspaceId"], enabled=True,
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
            first_listed = next(
                item for item in listed["workspaces"] if item["displayName"] == "Novel A"
            )
            self.assertEqual(["demo", "side-story"], first_listed["projects"])
            self.assertEqual("", first_listed["defaultProject"])
            self.assertTrue(first_listed["requiresProjectSelection"])
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
                self.assertIn("list_world_projects", names)
                self.assertIn("search_world", names)
                search_tool = next(tool for tool in tools.tools if tool.name == "search_world")
                workspace_schema = search_tool.input_schema["properties"]["workspace"]
                self.assertEqual(["Novel A", "Novel B"], workspace_schema["enum"])
                self.assertEqual("工作区", workspace_schema["title"])
                self.assertIn("workspace", search_tool.input_schema["required"])
                project_schema = search_tool.input_schema["properties"]["project"]
                self.assertEqual(["demo", "side-story"], project_schema["enum"])
                self.assertEqual("项目", project_schema["title"])
                workspaces = await client.call_tool("list_world_workspaces", {})
                self.assertEqual(2, len(workspaces.structured_content["workspaces"]))
                projects = await client.call_tool("list_world_projects", {
                    "workspace": first["workspace"]["displayName"],
                })
                self.assertEqual(["demo", "side-story"], projects.structured_content["projects"])
                self.assertTrue(projects.structured_content["requiresProjectSelection"])
                searched = await client.call_tool("search_world", {
                    "workspace": first["workspace"]["displayName"],
                    "project": "side-story",
                    "query": "林秋", "limit": 3,
                })
                self.assertEqual("character:1", searched.structured_content["results"][0]["entityId"])
                self.assertEqual("side-story", searched.structured_content["project"])
                self.assertEqual(
                    first["workspace"]["workspaceId"],
                    searched.structured_content["workspaceId"],
                )
                missing_project = await client.call_tool("rag_status", {
                    "workspace": first["workspace"]["displayName"],
                })
                self.assertTrue(missing_project.is_error)
                defaulted = await client.call_tool("rag_status", {
                    "workspace": second["workspace"]["displayName"],
                })
                self.assertFalse(defaulted.is_error)
                self.assertEqual("demo", defaulted.structured_content["project"])
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
        self.assertIn("MCP 已独立启动", result.stdout)
        self.remember_hub()
        with httpx.Client(trust_env=False) as client:
            workspaces = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"]
        self.assertEqual("novel-script", workspaces[0]["displayName"])
        self.assertEqual("independent", workspaces[0]["mcp"]["mode"])
        self.assertTrue(workspaces[0]["mcp"]["running"])
        status = subprocess.run(
            [str(ROOT / "run-rag.sh"), "status"],
            cwd=self.base, env=environment, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(0, status.returncode, status.stdout + status.stderr)
        self.assertIn("MCP 运行中（独立运行）", status.stdout)
        stopped = subprocess.run(
            [str(ROOT / "run-rag.sh"), "stop"],
            cwd=self.base, env=environment, text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
        with httpx.Client(trust_env=False) as client:
            workspace = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"][0]
        self.assertFalse(workspace["mcp"]["running"])

    def test_web_lease_drives_mcp_and_independent_mode_keeps_it_alive(self):
        repository = self.make_repository("novel-lifecycle")
        self.add_project(repository, "side-story")
        port = self.free_port()
        web_port = self.free_port()
        token = ensure_token(self.state_dir)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        registration = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=repository, content_root=repository / "content",
            framework_root=repository / "story_teller", project="demo",
            display_name="Lifecycle",
        )["workspace"]
        workspace_id = registration["workspaceId"]

        lease = acquire_web_lease(
            host="127.0.0.1", port=port, token=token, workspace_id=workspace_id,
        )["lease"]
        with httpx.Client(trust_env=False) as client:
            listed = client.get(f"http://127.0.0.1:{port}/api/v1/hub/workspaces").json()["workspaces"][0]
        self.assertTrue(listed["web"]["running"])
        self.assertTrue(listed["mcp"]["running"])
        self.assertEqual("follow-web", listed["mcp"]["mode"])

        _web_health, started = start_or_reuse_web_hub(
            host="127.0.0.1", port=web_port, hub_port=port,
            state_dir=self.state_dir, framework_root=ROOT,
        )
        self.assertTrue(started)
        self.web_hub_pid = int((self.state_dir / "web-hub.pid").read_text().strip())
        with httpx.Client(trust_env=False) as client:
            management = client.get(f"http://127.0.0.1:{web_port}/")
            self.assertEqual(200, management.status_code)
            self.assertIn("Story Teller Hub", management.text)
            denied_management = client.post(
                f"http://127.0.0.1:{web_port}/api/v1/contents/{workspace_id}/actions/stop-content"
            )
            self.assertEqual(403, denied_management.status_code)
            meta = client.get(
                f"http://127.0.0.1:{web_port}/w/{workspace_id}/api/v1/meta",
                params={"project": "side-story"},
            )
            self.assertEqual(200, meta.status_code, meta.text)
            self.assertEqual("side-story", meta.json()["project"])
            restarted_mcp = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/actions/restart-mcp",
                headers={"X-Story-World-Hub-Token": token},
            )
            self.assertEqual(200, restarted_mcp.status_code, restarted_mcp.text)
            restarted_content = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/actions/restart-content",
                headers={"X-Story-World-Hub-Token": token},
            )
            self.assertEqual(200, restarted_content.status_code, restarted_content.text)
            reloaded = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/projects/side-story/reload",
                headers={"X-Story-World-Hub-Token": token},
            )
            self.assertEqual(200, reloaded.status_code, reloaded.text)

        release_web_lease(
            host="127.0.0.1", port=port, token=token,
            workspace_id=workspace_id, lease=lease,
        )
        with httpx.Client(trust_env=False) as client:
            listed = client.get(f"http://127.0.0.1:{port}/api/v1/hub/workspaces").json()["workspaces"][0]
        self.assertFalse(listed["web"]["running"])
        self.assertFalse(listed["mcp"]["running"])

        lease = acquire_web_lease(
            host="127.0.0.1", port=port, token=token, workspace_id=workspace_id,
        )["lease"]
        with httpx.Client(trust_env=False) as client:
            disabled = client.put(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/projects/side-story",
                headers={"X-Story-World-Hub-Token": token}, json={"enabled": False},
            )
            self.assertEqual(200, disabled.status_code, disabled.text)
            blocked = client.get(
                f"http://127.0.0.1:{web_port}/w/{workspace_id}/api/v1/meta",
                params={"project": "side-story"},
            )
            self.assertEqual(404, blocked.status_code)
            enabled = client.put(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/projects/side-story",
                headers={"X-Story-World-Hub-Token": token}, json={"enabled": True},
            )
            self.assertEqual(200, enabled.status_code, enabled.text)

        set_independent_mcp(
            host="127.0.0.1", port=port, token=token,
            workspace_id=workspace_id, enabled=True,
        )
        release_web_lease(
            host="127.0.0.1", port=port, token=token,
            workspace_id=workspace_id, lease=lease,
        )
        with httpx.Client(trust_env=False) as client:
            listed = client.get(f"http://127.0.0.1:{port}/api/v1/hub/workspaces").json()["workspaces"][0]
        self.assertFalse(listed["web"]["running"])
        self.assertTrue(listed["mcp"]["running"])
        self.assertEqual("independent", listed["mcp"]["mode"])

        set_independent_mcp(
            host="127.0.0.1", port=port, token=token,
            workspace_id=workspace_id, enabled=False,
        )
        with httpx.Client(trust_env=False) as client:
            listed = client.get(f"http://127.0.0.1:{port}/api/v1/hub/workspaces").json()["workspaces"][0]
        self.assertFalse(listed["mcp"]["running"])

    def test_bad_project_is_isolated_while_healthy_project_remains_available(self):
        repository = self.make_repository("novel-isolation")
        broken = repository / "content" / "broken"
        broken.mkdir()
        (broken / "story.db").write_bytes(b"not a sqlite database")
        port = self.free_port()
        web_port = self.free_port()
        token = ensure_token(self.state_dir)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        registration = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=repository, content_root=repository / "content",
            framework_root=repository / "story_teller", project="demo",
            display_name="Isolation",
        )["workspace"]
        workspace_id = registration["workspaceId"]
        acquire_web_lease(
            host="127.0.0.1", port=port, token=token, workspace_id=workspace_id,
        )
        start_or_reuse_web_hub(
            host="127.0.0.1", port=web_port, hub_port=port,
            state_dir=self.state_dir, framework_root=ROOT,
        )
        self.web_hub_pid = int((self.state_dir / "web-hub.pid").read_text().strip())
        with httpx.Client(trust_env=False) as client:
            workspace = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"][0]
            self.assertTrue(workspace["web"]["running"])
            self.assertEqual(["demo"], workspace["projects"])
            statuses = {item["project"]: item for item in workspace["projectStatuses"]}
            self.assertEqual("ready", statuses["demo"]["state"])
            self.assertEqual("error", statuses["broken"]["state"])
            self.assertTrue(statuses["broken"]["error"])
            healthy = client.get(
                f"http://127.0.0.1:{web_port}/w/{workspace_id}/api/v1/meta",
                params={"project": "demo"},
            )
            self.assertEqual(200, healthy.status_code, healthy.text)
            unavailable = client.get(
                f"http://127.0.0.1:{web_port}/w/{workspace_id}/api/v1/meta",
                params={"project": "broken"},
            )
            self.assertEqual(404, unavailable.status_code)
            (broken / "story.db").unlink()
            legacy = broken / "legacy.db"
            shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", legacy)
            V3Migrator(legacy, "broken").migrate_to(broken / "story.db")
            reloaded = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/projects/broken/reload",
                headers={"X-Story-World-Hub-Token": token}, timeout=30,
            )
            self.assertEqual(200, reloaded.status_code, reloaded.text)
            self.assertEqual(["broken", "demo"], reloaded.json()["workspace"]["projects"])
            recovered = client.get(
                f"http://127.0.0.1:{web_port}/w/{workspace_id}/api/v1/meta",
                params={"project": "broken"},
            )
            self.assertEqual(200, recovered.status_code, recovered.text)

    def test_management_can_create_start_stop_and_remove_content(self):
        repository = self.make_repository("novel-managed")
        port = self.free_port()
        web_port = self.free_port()
        token = ensure_token(self.state_dir)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        registration = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=repository, content_root=repository / "content",
            framework_root=repository / "story_teller", project="demo",
            display_name="Managed",
        )["workspace"]
        workspace_id = registration["workspaceId"]
        start_or_reuse_web_hub(
            host="127.0.0.1", port=web_port, hub_port=port,
            state_dir=self.state_dir, framework_root=ROOT,
        )
        self.web_hub_pid = int((self.state_dir / "web-hub.pid").read_text().strip())
        headers = {"X-Story-World-Hub-Token": token}
        with httpx.Client(trust_env=False) as client:
            created = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/projects",
                headers=headers, json={"project": "new-story", "title": "新故事"},
                timeout=30,
            )
            self.assertEqual(200, created.status_code, created.text)
            self.assertIn("new-story", created.json()["workspace"]["projects"])
            self.assertTrue((repository / "content/new-story/story.db").is_file())
            started = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/actions/start-content",
                headers=headers, timeout=30,
            )
            self.assertEqual(200, started.status_code, started.text)
            self.assertTrue(started.json()["workspace"]["web"]["running"])
            self.assertEqual("managed", started.json()["workspace"]["web"]["mode"])
            logs = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/logs",
                headers=headers,
            )
            self.assertEqual(200, logs.status_code, logs.text)
            stopped = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}/actions/stop-content",
                headers=headers,
            )
            self.assertEqual(200, stopped.status_code, stopped.text)
            self.assertFalse(stopped.json()["workspace"]["web"]["running"])
            unavailable = client.get(
                f"http://127.0.0.1:{web_port}/w/{workspace_id}/api/v1/meta",
                params={"project": "demo"},
            )
            self.assertEqual(503, unavailable.status_code)
            self.assertEqual("api_unavailable", unavailable.json()["code"])
            removed = client.delete(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace_id}",
                headers=headers,
            )
            self.assertEqual(200, removed.status_code, removed.text)
            self.assertFalse(removed.json()["workspace"].get("contentDeleted", False))
            self.assertTrue((repository / "content/demo/story.db").is_file())
            self.assertEqual([], client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"])

    def test_web_worker_exits_after_hub_is_killed_and_can_be_recovered(self):
        repository = self.make_repository("novel-orphan")
        port = self.free_port()
        token = ensure_token(self.state_dir)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        registration = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=repository, content_root=repository / "content",
            framework_root=repository / "story_teller", project="demo",
            display_name="Orphan",
        )["workspace"]
        workspace_id = registration["workspaceId"]
        acquire_web_lease(
            host="127.0.0.1", port=port, token=token, workspace_id=workspace_id,
        )
        with httpx.Client(trust_env=False) as client:
            old_worker_pid = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"][0]["web"]["processId"]
        self.assertGreater(old_worker_pid, 0)
        assert self.hub_pid is not None
        os.kill(self.hub_pid, signal.SIGKILL)
        self.hub_pid = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                os.kill(old_worker_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail(f"Hub 被强杀后 Web Worker {old_worker_pid} 仍然存活")

        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        acquire_web_lease(
            host="127.0.0.1", port=port, token=token, workspace_id=workspace_id,
        )
        with httpx.Client(trust_env=False) as client:
            recovered = client.get(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
            ).json()["workspaces"][0]
        self.assertTrue(recovered["web"]["running"])
        self.assertNotEqual(old_worker_pid, recovered["web"]["processId"])

    def test_running_hub_prunes_a_content_root_that_disappears(self):
        repository = self.make_repository("novel-live-prune")
        port = self.free_port()
        token = ensure_token(self.state_dir)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        registration = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=repository, content_root=repository / "content",
            framework_root=repository / "story_teller", project="demo",
            display_name="Live prune",
        )["workspace"]
        acquire_web_lease(
            host="127.0.0.1", port=port, token=token,
            workspace_id=registration["workspaceId"],
        )
        moved = repository / "content-away"
        (repository / "content").rename(moved)
        deadline = time.monotonic() + 7
        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline:
                workspaces = client.get(
                    f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
                ).json()["workspaces"]
                if not workspaces:
                    break
                time.sleep(0.2)
            else:
                self.fail("失效 Content 没有被运行中的 Hub 清理")
        moved.rename(repository / "content")

    def test_hub_managed_web_is_restored_after_hub_restart(self):
        repository = self.make_repository("novel-managed-restore")
        port = self.free_port()
        token = ensure_token(self.state_dir)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        workspace = register_workspace(
            host="127.0.0.1", port=port, token=token,
            repository_root=repository, content_root=repository / "content",
            framework_root=repository / "story_teller", project="demo",
            display_name="Managed restore",
        )["workspace"]
        headers = {"X-Story-World-Hub-Token": token}
        with httpx.Client(trust_env=False) as client:
            started = client.post(
                f"http://127.0.0.1:{port}/api/v1/hub/workspaces/{workspace['workspaceId']}/actions/start-content",
                headers=headers,
            )
            self.assertEqual(200, started.status_code, started.text)
        assert self.hub_pid is not None
        os.kill(self.hub_pid, signal.SIGTERM)
        self.hub_pid = None
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    pass
            except OSError:
                break
            time.sleep(0.1)
        start_or_reuse_hub(
            host="127.0.0.1", port=port, state_dir=self.state_dir,
            framework_root=ROOT, timeout=20,
        )
        self.remember_hub()
        deadline = time.monotonic() + 15
        with httpx.Client(trust_env=False) as client:
            while time.monotonic() < deadline:
                restored = client.get(
                    f"http://127.0.0.1:{port}/api/v1/hub/workspaces"
                ).json()["workspaces"][0]
                if restored["web"]["running"] and restored["mcp"]["running"]:
                    break
                time.sleep(0.2)
            else:
                self.fail("Hub 托管的 Content 没有在 Hub 重启后恢复")
        self.assertEqual("managed", restored["web"]["mode"])

if __name__ == "__main__":
    unittest.main()
