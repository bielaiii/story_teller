from __future__ import annotations

import contextlib
import io
import json
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
            exit_code = 5 if response.status_code == 409 else 3 if response.status_code == 503 else 6
            raise CliError(
                str(body.get("error") or body.get("detail") or "请求失败"),
                code=str(body.get("code") or f"http_{response.status_code}"),
                exit_code=exit_code,
            )
        return body


class ContentCliTests(unittest.TestCase):
    def setUp(self):
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

    def tearDown(self):
        self.web.close()
        self.temporary.cleanup()

    def invoke(self, *arguments: str):
        args = self.parser.parse_args(["--json", *arguments])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = args.handler(self.client, args)
        parsed = json.loads(output.getvalue())
        self.assertTrue(parsed["ok"])
        return result, parsed

    def test_plot_complete_workflow_export_conversion_recovery_and_undo(self):
        snapshot = self.client.snapshot()
        person = snapshot["characters"][0]
        entry = snapshot["entries"][0]
        story = snapshot["timeline"]["lines"][0]
        chapter_number = max(int(item.get("chapterNumber") or 0) for item in snapshot["plots"]) + 100
        body = self.root / "plot.md"
        body.write_text(f"{person['name']}遇见CLI路人，并发现新的线索。", encoding="utf-8")
        created, _ = self.invoke(
            "plot", "add", "CLI 正式剧情",
            "--id", "cli-plot",
            "--chapter-number", str(chapter_number),
            "--summary", "CLI 摘要",
            "--body-file", str(body),
            "--status", "定稿",
            "--accent", "#123456",
            "--tag", "调查",
            "--person", person["entityId"],
            "--appearance", "CLI路人",
            "--entry", entry["entityId"],
            "--story", story["entityId"],
            "--reference", entry["entityId"],
            "--key",
        )
        plot_id = created["item"]["entityId"]
        stored = self.client.detail(plot_id)["data"]
        self.assertEqual("cli-plot", stored["id"])
        self.assertEqual(chapter_number, stored["chapterNumber"])
        self.assertEqual("CLI 摘要", stored["summary"])
        self.assertEqual("#123456", stored["accent"])
        self.assertTrue(stored["key"])
        self.assertIn(person["entityId"], stored["people"])
        self.assertIn(entry["entityId"], stored["entries"])
        self.assertIn(story["entityId"], stored["stories"])
        self.assertIn("CLI路人", {item["name"] for item in self.client.snapshot()["characters"]})

        listed, _ = self.invoke(
            "plot", "list", "--query", "CLI 摘要", "--status", "定稿",
            "--tag", "调查", "--story", story["entityId"],
        )
        self.assertEqual([plot_id], [item["entityId"] for item in listed])
        shown, _ = self.invoke("plot", "show", plot_id)
        self.assertEqual(plot_id, shown["item"]["entityId"])
        self.assertIn(person["entityId"], {item["entityId"] for item in shown["related"]["characters"]})

        edited, _ = self.invoke(
            "plot", "edit", plot_id,
            "--title", "CLI 正式剧情（修订）",
            "--summary", "修订摘要",
            "--tag", "高潮前",
            "--clear-entries",
            "--no-key",
            "--climax",
            "--story-position", "fixed",
            "--story-sort-key", "990000000",
        )
        changed = edited["item"]["data"]
        self.assertEqual("CLI 正式剧情（修订）", changed["title"])
        self.assertEqual([], changed["entries"])
        self.assertFalse(changed["key"])
        self.assertTrue(changed["climax"])
        self.assertEqual("fixed", changed["storyOrderMode"])

        history, _ = self.invoke("plot", "history")
        latest = next(item for item in history if item["action"] == "update" and item["canUndo"])
        self.invoke("plot", "undo", str(latest["id"]))
        reverted = self.client.detail(plot_id)["data"]
        self.assertEqual("CLI 正式剧情", reverted["title"])
        self.assertTrue(reverted["key"])

        export_path = self.root / "exports" / "plot.md"
        rendered, single_output = self.invoke("plot", "export", plot_id, "-o", str(export_path))
        self.assertEqual(1, single_output["count"])
        self.assertIn(f"# 第 {chapter_number} 章 · CLI 正式剧情", rendered)
        self.assertEqual(rendered, export_path.read_text(encoding="utf-8"))
        _all, all_output = self.invoke("plot", "export", "--all")
        self.assertEqual(len(self.client.snapshot()["plots"]), all_output["count"])
        ordered = self.client.snapshot()["plots"]
        _range, range_output = self.invoke(
            "plot", "export", "--from", ordered[0]["entityId"], "--to", plot_id
        )
        indexes = {item["entityId"]: index for index, item in enumerate(ordered)}
        self.assertEqual(abs(indexes[plot_id] - indexes[ordered[0]["entityId"]]) + 1, range_output["count"])

        converted, converted_output = self.invoke("plot", "to-fragment", plot_id, "--yes")
        fragment_id = converted["item"]["entityId"]
        self.assertEqual("fragment", converted["item"]["kind"])
        self.assertEqual("CLI 正式剧情", converted["item"]["data"]["title"])
        with self.assertRaises(CliError):
            self.client.detail(plot_id)
        trash, _ = self.invoke("plot", "trash")
        self.assertIn(plot_id, {item["entityId"] for item in trash})
        conversion_history, _ = self.invoke("plot", "history")
        conversion = next(item for item in conversion_history if item["action"] == "convert" and item["canUndo"])
        self.invoke("plot", "undo", str(conversion["id"]))
        self.assertEqual(plot_id, self.client.detail(plot_id)["entityId"])
        with self.assertRaises(CliError):
            self.client.detail(fragment_id)

        self.invoke("plot", "delete", plot_id, "--yes")
        self.invoke("plot", "restore", plot_id)
        self.assertEqual(plot_id, self.client.detail(plot_id)["entityId"])

    def test_entry_and_organization_member_complete_workflow(self):
        snapshot = self.client.snapshot()
        first, second = snapshot["characters"][:2]
        body = self.root / "entry.md"
        body.write_text("负责调查与情报交换。", encoding="utf-8")

        normal, _ = self.invoke(
            "entry", "add", "CLI 地点",
            "--id", "cli-place",
            "--type", "地点",
            "--subtype", "仓库",
            "--area", "港口",
            "--status", "开放",
            "--accent", "#234567",
            "--alias", "旧仓库",
            "--tag", "调查",
            "--person", first["entityId"],
            "--reference", first["entityId"],
            "--body-file", str(body),
        )
        normal_id = normal["item"]["entityId"]
        self.assertEqual("cli-place", normal["item"]["data"]["id"])
        self.assertEqual([first["entityId"]], normal["item"]["data"]["people"])

        organization, _ = self.invoke(
            "entry", "add", "CLI 调查组",
            "--type", "组织",
            "--subtype", "公司",
            "--status", "活跃",
            "--member", f"{first['entityId']}=负责人,现成员",
            "--body", "秘密调查组织。",
        )
        organization_id = organization["item"]["entityId"]
        stored = organization["item"]["data"]
        self.assertEqual("组织", stored["type"])
        self.assertEqual("负责人", stored["members"][0]["role"])
        self.assertIn(first["entityId"], stored["references"])

        self.invoke(
            "entry", "member", "add", organization_id, second["entityId"],
            "--role", "调查员", "--status", "秘密成员",
        )
        members, _ = self.invoke("entry", "member", "list", organization_id)
        self.assertEqual({first["entityId"], second["entityId"]}, {item["characterId"] for item in members})
        self.invoke(
            "entry", "member", "edit", organization_id, second["entityId"],
            "--role", "高级调查员", "--status", "现成员",
        )
        edited_member = next(
            item for item in self.client.detail(organization_id)["data"]["members"]
            if item["characterId"] == second["entityId"]
        )
        self.assertEqual("高级调查员", edited_member["role"])
        self.invoke("entry", "member", "remove", organization_id, first["entityId"])
        after_remove = self.client.detail(organization_id)["data"]
        self.assertEqual([second["entityId"]], [item["characterId"] for item in after_remove["members"]])
        self.assertNotIn(first["entityId"], after_remove["references"])

        listed, _ = self.invoke("entry", "list", "--type", "组织", "--query", "调查组")
        self.assertIn(organization_id, {item["entityId"] for item in listed})
        shown, _ = self.invoke("entry", "show", organization_id)
        self.assertEqual("高级调查员", shown["members"][0]["role"])

        renamed, _ = self.invoke(
            "entry", "edit", normal_id,
            "--name", "CLI 港口仓库", "--yes",
            "--clear-subtype", "--clear-area", "--clear-status",
            "--clear-aliases", "--clear-tags", "--clear-people", "--clear-body",
        )
        self.assertEqual("CLI 港口仓库", renamed["item"]["data"]["name"])
        self.assertEqual([], renamed["item"]["data"]["people"])
        history, _ = self.invoke("entry", "history")
        rename = next(item for item in history if item["action"] == "rename" and item["canUndo"])
        self.invoke("entry", "undo", str(rename["id"]))
        self.assertEqual("CLI 地点", self.client.detail(normal_id)["data"]["name"])

        self.invoke("entry", "delete", organization_id, "--yes")
        trash, _ = self.invoke("entry", "trash")
        self.assertIn(organization_id, {item["entityId"] for item in trash})
        self.invoke("entry", "restore", organization_id)
        self.assertEqual(organization_id, self.client.detail(organization_id)["entityId"])

    def test_rag_rebuild_uses_current_project_and_reports_counts(self):
        _result, output = self.invoke("rag", "rebuild")
        self.assertGreater(output["documents"], 0)
        self.assertGreater(output["chunks"], 0)
        self.assertEqual(self.client.snapshot()["project"]["revision"], output["sourceRevision"])
        self.assertTrue(Path(output["path"]).is_file())


class ContentCliProcessTests(unittest.TestCase):
    def test_real_launcher_worker_persists_entry_plot_and_rebuilds_rag(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project_root = workspace / "content" / "demo"
            project_root.mkdir(parents=True)
            shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", project_root / "legacy.db")
            V3Migrator(project_root / "legacy.db", "demo").migrate_to(project_root / "story.db")
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

            def run_cli(*arguments: str) -> dict:
                completed = subprocess.run(
                    [
                        str(ROOT / "story-teller"), *arguments,
                        "--project", "demo", "--web-url", f"http://127.0.0.1:{port}", "--json",
                    ],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr or completed.stdout)
                result = json.loads(completed.stdout)
                self.assertTrue(result["ok"])
                return result

            try:
                deadline = time.monotonic() + 15
                while True:
                    if server.poll() is not None:
                        output = server.stdout.read() if server.stdout else ""
                        self.fail(f"测试 Worker 提前退出：\n{output}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.5) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        self.fail("测试 Worker 启动超时")
                    time.sleep(0.05)

                organization = run_cli(
                    "entry", "add", "CLI 进程组织", "--type", "组织",
                    "--member", "character:1=负责人,现成员",
                )
                organization_id = organization["item"]["entityId"]
                plot = run_cli(
                    "plot", "add", "CLI 进程剧情", "--chapter-number", "9900",
                    "--entry", organization_id, "--person", "character:1", "--body", "林秋通过真实进程写入。",
                )
                plot_id = plot["item"]["entityId"]
                rag = run_cli("rag", "rebuild")
                self.assertGreater(rag["documents"], 0)
                self.assertGreater(rag["chunks"], 0)
                self.assertTrue(Path(rag["path"]).is_file())
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
                if server.stdout:
                    server.stdout.close()

            with sqlite3.connect(project_root / "story.db") as connection:
                entry_row = connection.execute(
                    "SELECT name FROM entries WHERE entity_id=?", (organization_id,)
                ).fetchone()
                plot_row = connection.execute(
                    "SELECT p.chapter_number, p.body_markdown FROM plots p WHERE p.entity_id=?", (plot_id,)
                ).fetchone()
                member_row = connection.execute(
                    "SELECT role, status FROM entry_characters WHERE entry_id=? AND character_id='character:1'",
                    (organization_id,),
                ).fetchone()
            self.assertEqual(("CLI 进程组织",), entry_row)
            self.assertEqual((9900, "林秋通过真实进程写入。"), plot_row)
            self.assertEqual(("负责人", "现成员"), member_row)
            exported = json.loads((project_root / "project.snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("CLI 进程剧情", {item["title"] for item in exported["plots"]})


if __name__ == "__main__":
    unittest.main()
