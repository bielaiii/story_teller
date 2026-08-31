from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from fastapi.testclient import TestClient

from storyteller.app import create_app
from storyteller.cli import build_parser
from storyteller.fragment_cli import ApiClient, CliError
from storyteller.settings import Settings
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class LocalApiClient(ApiClient):
    def __init__(self, test_client: TestClient, project: str):
        super().__init__("http://testserver", project)
        self.test_client = test_client

    def request(self, method: str, path: str, *, query=None, payload=None, mutation: bool = False):
        headers = {"X-Story-Teller-Token": self.token} if mutation else {}
        target = "/" + path.lstrip("/")
        if query:
            target += "?" + urlencode(query)
        response = self.test_client.request(method, target, headers=headers, json=payload)
        body = response.json()
        if response.status_code >= 400:
            raise CliError(
                str(body.get("error") or body.get("detail") or "请求失败"),
                code=str(body.get("code") or f"http_{response.status_code}"),
                exit_code=5 if response.status_code == 409 else 6,
            )
        return body


class MarkdownImportCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.content_root = self.root / "content"
        self.project_root = self.content_root / "demo"
        self.project_root.mkdir(parents=True)
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.project_root / "legacy.db")
        V3Migrator(self.project_root / "legacy.db", "demo").migrate_to(self.project_root / "story.db")
        settings = Settings.create(
            ROOT,
            content_root=self.content_root,
            frontend_root=self.root / "missing",
            default_project="demo",
        )
        self.web = TestClient(create_app(settings))
        self.client = LocalApiClient(self.web, "demo")
        self.parser = build_parser()
        self.bundle = self.root / "bundle"
        (self.bundle / "plots").mkdir(parents=True)
        (self.bundle / "fragments" / "CLI 故事").mkdir(parents=True)

    def tearDown(self) -> None:
        self.web.close()
        self.temporary.cleanup()

    def invoke(self, *arguments: str) -> dict:
        args = self.parser.parse_args(["--json", "import", "markdown", *arguments])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            args.handler(self.client, args)
        return json.loads(output.getvalue())

    def test_check_previews_without_writing_then_apply_round_trips_to_disk(self) -> None:
        plot = self.bundle / "plots" / "CLI 导入剧情.md"
        plot.write_text(
            "---\nchapterNumber: 9876\nstories: [主线, CLI 故事]\nsummary: CLI 导入摘要\nkey: true\n---\n林秋检查 CLI 导入证据。",
            encoding="utf-8",
        )
        fragment = self.bundle / "fragments" / "CLI 故事" / "CLI 导入碎片.md"
        fragment.write_text(
            "---\nchapterNumber: 7\ntags: [CLI]\n---\nCLI 碎片正文。",
            encoding="utf-8",
        )
        before = self.client.snapshot()["project"]["revision"]
        preview = self.invoke(
            str(self.bundle / "plots"), str(self.bundle / "fragments"),
            "--root", str(self.bundle), "--recursive", "--check",
        )
        self.assertEqual("preview", preview["mode"])
        self.assertEqual(2, preview["preview"]["fileCount"])
        self.assertEqual(before, self.client.snapshot()["project"]["revision"])

        applied = self.invoke(
            str(self.bundle / "plots"), str(self.bundle / "fragments"),
            "--root", str(self.bundle), "--recursive", "--yes",
        )
        self.assertEqual("applied", applied["mode"])
        self.assertEqual(2, applied["import"]["count"])
        with sqlite3.connect(self.project_root / "story.db") as connection:
            plot_row = connection.execute(
                "SELECT p.chapter_number, p.summary FROM plots p JOIN entities e ON e.id=p.entity_id WHERE e.title=?",
                ("CLI 导入剧情",),
            ).fetchone()
            fragment_row = connection.execute(
                "SELECT json_extract(e.extra_json, '$.chapterNumber'), f.body_markdown FROM fragments f JOIN entities e ON e.id=f.entity_id WHERE e.title=?",
                ("CLI 导入碎片",),
            ).fetchone()
        self.assertEqual((9876, "CLI 导入摘要"), plot_row)
        self.assertEqual((7, "CLI 碎片正文。"), fragment_row)
        exported = json.loads((self.project_root / "project.snapshot.json").read_text(encoding="utf-8"))
        self.assertIn("CLI 导入剧情", {item["title"] for item in exported["plots"]})

    def test_title_conflict_requires_explicit_override_and_hard_conflicts_still_stop(self) -> None:
        existing = self.client.snapshot()["plots"][0]
        title_conflict = self.bundle / "plots" / f"{existing['title']}.md"
        title_conflict.write_text("---\nchapterNumber: 9801\n---\n不同正文", encoding="utf-8")
        args = self.parser.parse_args([
            "--json", "import", "markdown", str(title_conflict),
            "--root", str(self.bundle), "--yes",
        ])
        with self.assertRaisesRegex(CliError, "--allow-title-conflicts") as conflict:
            args.handler(self.client, args)
        self.assertEqual("title", conflict.exception.details["preview"]["conflicts"][0]["conflicts"][0])
        allowed = self.invoke(
            str(title_conflict), "--root", str(self.bundle), "--yes", "--allow-title-conflicts",
        )
        self.assertEqual(1, allowed["import"]["count"])

        chapter_conflict = self.bundle / "plots" / "CLI 冲突章号.md"
        chapter_conflict.write_text(
            f"---\nchapterNumber: {existing['chapterNumber']}\n---\n冲突正文",
            encoding="utf-8",
        )
        args = self.parser.parse_args([
            "--json", "import", "markdown", str(chapter_conflict),
            "--root", str(self.bundle), "--yes", "--allow-title-conflicts",
        ])
        with self.assertRaisesRegex(CliError, "chapterNumber"):
            args.handler(self.client, args)


class MarkdownImportCliProcessTests(unittest.TestCase):
    def test_real_launcher_import_persists_to_temporary_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project_root = workspace / "content" / "demo"
            project_root.mkdir(parents=True)
            shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", project_root / "legacy.db")
            V3Migrator(project_root / "legacy.db", "demo").migrate_to(project_root / "story.db")
            bundle = workspace / "bundle"
            (bundle / "plots").mkdir(parents=True)
            source = bundle / "plots" / "真实进程导入.md"
            source.write_text("---\nchapterNumber: 9899\n---\n真实 CLI 进程导入。", encoding="utf-8")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            server = subprocess.Popen(
                [
                    str(ROOT / "scripts" / "python.sh"), "-m", "storyteller",
                    "--bind", "127.0.0.1", "--port", str(port),
                    "--content-root", str(workspace / "content"),
                    "--frontend-root", str(workspace / "missing"),
                    "--default-project", "demo",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.5) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        pass
                    if server.poll() is not None or time.monotonic() >= deadline:
                        self.fail("测试 Worker 启动失败")
                    time.sleep(0.05)
                completed = subprocess.run(
                    [
                        str(ROOT / "story-teller"), "import", "markdown", str(source),
                        "--root", str(bundle), "--yes", "--project", "demo",
                        "--web-url", f"http://127.0.0.1:{port}", "--json",
                    ],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
                self.assertEqual("applied", json.loads(completed.stdout)["mode"])
            finally:
                server.terminate()
                server.wait(timeout=10)
                if server.stdout:
                    server.stdout.close()
            with sqlite3.connect(project_root / "story.db") as connection:
                stored = connection.execute(
                    "SELECT p.chapter_number, p.body_markdown FROM plots p JOIN entities e ON e.id=p.entity_id WHERE e.title=?",
                    ("真实进程导入",),
                ).fetchone()
            self.assertEqual((9899, "真实 CLI 进程导入。"), stored)

    def test_launcher_automatically_reuses_hub_client_lease(self) -> None:
        hub_root = ROOT.parents[1] / "story_teller_hub"
        self.assertTrue((hub_root / "run.sh").is_file())
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project_root = workspace / "content" / "demo"
            project_root.mkdir(parents=True)
            shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", project_root / "legacy.db")
            V3Migrator(project_root / "legacy.db", "demo").migrate_to(project_root / "story.db")
            (workspace / "story_teller").symlink_to(ROOT, target_is_directory=True)
            bundle = project_root / "import-bundle"
            (bundle / "plots").mkdir(parents=True)
            source = bundle / "plots" / "Hub 自动导入.md"
            source.write_text("---\nchapterNumber: 9901\n---\n通过唯一 Hub 自动启动。", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                hub_port = int(probe.getsockname()[1])
            state_dir = workspace / "hub-state"
            environment = {
                **os.environ,
                "STORY_TELLER_HUB_ROOT": str(hub_root),
                "STORY_WORLD_HUB_PORT": str(hub_port),
                "STORY_WORLD_HUB_STATE_DIR": str(state_dir),
                "STORY_TELLER_HUB_INSTALL_DIR": str(workspace / "installed-hub"),
            }
            try:
                completed = subprocess.run(
                    [
                        str(ROOT / "story-teller"), "import", "markdown", "import-bundle/plots/Hub 自动导入.md",
                        "--root", "import-bundle", "--yes", "--project", "demo", "--json",
                    ],
                    cwd=project_root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
                self.assertEqual("applied", json.loads(completed.stdout)["mode"])
                with urlopen(f"http://127.0.0.1:{hub_port}/api/v1/hub/workspaces", timeout=2) as response:
                    hub_workspace = json.loads(response.read())["workspaces"][0]
                self.assertEqual("client-idle", hub_workspace["web"]["mode"])
                self.assertTrue(hub_workspace["web"]["running"])
                self.assertFalse(hub_workspace["mcp"]["running"])
                self.assertGreaterEqual(hub_workspace["web"]["clientIdleSecondsRemaining"], 58)
            finally:
                try:
                    hub_pid = int((state_dir / "hub.pid").read_text(encoding="utf-8").strip())
                    os.kill(hub_pid, signal.SIGTERM)
                except (FileNotFoundError, ProcessLookupError, ValueError):
                    pass
            with sqlite3.connect(project_root / "story.db") as connection:
                stored = connection.execute(
                    "SELECT p.chapter_number FROM plots p JOIN entities e ON e.id=p.entity_id WHERE e.title=?",
                    ("Hub 自动导入",),
                ).fetchone()
            self.assertEqual((9901,), stored)


if __name__ == "__main__":
    unittest.main()
