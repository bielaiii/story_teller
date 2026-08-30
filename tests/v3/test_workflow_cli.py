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
from storyteller.merge_driver import build_merge
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


class WorkflowCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.content_root = self.root / "content"
        self.project_root = self.content_root / "demo"
        self.project_root.mkdir(parents=True)
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.root / "legacy.db")
        V3Migrator(self.root / "legacy.db", "demo").migrate_to(self.project_root / "story.db")
        settings = Settings.create(
            ROOT, content_root=self.content_root, frontend_root=self.root / "missing", default_project="demo"
        )
        self.web = TestClient(create_app(settings))
        self.client = LocalApiClient(self.web, "demo")
        self.client.meta()
        self.parser = build_parser()

    def tearDown(self) -> None:
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

    def test_global_search_covers_all_web_content_kinds_and_filters(self) -> None:
        snapshot = self.client.snapshot()
        cases = (
            ("character", snapshot["characters"][0]["name"]),
            ("plot", snapshot["plots"][0]["title"]),
            ("entry", snapshot["entries"][0]["name"]),
            ("fragment", snapshot["fragments"][0]["title"]),
        )
        for kind, query in cases:
            items, output = self.invoke("search", query, "--kind", kind)
            self.assertTrue(items, (kind, query))
            self.assertTrue(all(item["kind"] == kind for item in items))
            self.assertEqual(query, output["query"])
            self.assertIn("entityId", items[0])
            self.assertIn("match", items[0])

        limited, _ = self.invoke("search", "第", "--limit", "2")
        self.assertLessEqual(len(limited), 2)

    def test_timeline_lines_main_membership_order_delete_and_undo_round_trip(self) -> None:
        original = self.client.snapshot()
        original_main = original["timeline"]["mainLineId"]
        replacement = next(
            line["entityId"] for line in original["timeline"]["lines"]
            if line["entityId"] != original_main
        )
        first_plot, second_plot = original["plots"][:2]
        first_original_chapter = first_plot["chapterNumber"]
        second_original_chapter = second_plot["chapterNumber"]

        created, _ = self.invoke(
            "timeline", "line", "add", "CLI 调查线", "--id", "cli-investigation",
            "--color", "#123456", "--side", "left",
        )
        line_id = created["item"]["entityId"]
        self.assertEqual("timeline_line:cli-investigation", line_id)
        self.invoke("timeline", "main", line_id)
        assigned, _ = self.invoke(
            "timeline", "node", "assign", first_plot["entityId"],
            "--line", line_id, "--line", replacement,
        )
        self.assertEqual({line_id, replacement}, {node["lineId"] for node in assigned["nodes"]})

        moved, _ = self.invoke(
            "timeline", "node", "move", first_plot["entityId"],
            "--after", second_plot["entityId"],
        )
        self.assertEqual(2, moved["storyOrder"])
        saved = self.client.snapshot()
        saved_by_id = {plot["entityId"]: plot for plot in saved["plots"]}
        self.assertEqual(second_original_chapter, saved_by_id[first_plot["entityId"]]["chapterNumber"])
        self.assertEqual(first_original_chapter, saved_by_id[second_plot["entityId"]]["chapterNumber"])
        saved_keys = {
            node["plotId"]: node["storySortKey"] for node in saved["timeline"]["nodes"]
            if node["lineId"] == line_id
        }
        self.assertIn(first_plot["entityId"], saved_keys)

        history, _ = self.invoke("timeline", "history")
        move_operation = next(item for item in history if item["action"] == "reorder" and item["canUndo"])
        self.invoke("timeline", "undo", str(move_operation["id"]))
        restored = self.client.snapshot()
        restored_by_id = {plot["entityId"]: plot for plot in restored["plots"]}
        self.assertEqual(first_original_chapter, restored_by_id[first_plot["entityId"]]["chapterNumber"])

        self.invoke(
            "timeline", "line", "delete", line_id,
            "--replacement", replacement, "--yes",
        )
        final = self.client.snapshot()
        self.assertNotIn(line_id, {line["entityId"] for line in final["timeline"]["lines"]})
        self.assertEqual(replacement, final["timeline"]["mainLineId"])
        first_lines = {
            node["lineId"] for node in final["timeline"]["nodes"]
            if node["plotId"] == first_plot["entityId"]
        }
        self.assertIn(replacement, first_lines)

        with sqlite3.connect(self.project_root / "story.db") as connection:
            connection.row_factory = sqlite3.Row
            deleted = connection.execute(
                "SELECT deleted_at FROM entities WHERE id=?", (line_id,)
            ).fetchone()
            self.assertIsNotNone(deleted["deleted_at"])
            self.assertEqual(
                1,
                connection.execute(
                    "SELECT COUNT(*) FROM plot_timeline_lines WHERE plot_id=? AND line_id=?",
                    (first_plot["entityId"], replacement),
                ).fetchone()[0],
            )


class MergeWorkflowCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for name in ("base", "ours", "theirs", "result"):
            (self.root / name / "demo").mkdir(parents=True)
        shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", self.root / "legacy.db")
        V3Migrator(self.root / "legacy.db", "demo").migrate_to(self.root / "base/demo/story.db")
        for name in ("ours", "theirs"):
            shutil.copy2(self.root / "base/demo/story.db", self.root / f"{name}/demo/story.db")
        self._change("ours", "本地摘要", "本地正文")
        self._change("theirs", "远程摘要", "远程正文")
        build_merge(
            self.root / "base/demo/story.db", self.root / "ours/demo/story.db",
            self.root / "theirs/demo/story.db", self.root / "result/demo/story.db",
            "content/demo/story.db",
        )
        settings = Settings.create(
            ROOT, content_root=self.root / "result", frontend_root=self.root / "missing", default_project="demo"
        )
        self.web = TestClient(create_app(settings))
        self.client = LocalApiClient(self.web, "demo")
        self.client.meta()
        self.parser = build_parser()

    def _change(self, side: str, summary: str, body: str) -> None:
        with sqlite3.connect(self.root / f"{side}/demo/story.db") as connection:
            connection.execute(
                "UPDATE plots SET summary=?, body_markdown=? WHERE entity_id='plot:1'", (summary, body)
            )
            connection.execute("UPDATE entities SET revision=revision+1, updated_at=updated_at+1 WHERE id='plot:1'")
            connection.execute("UPDATE projects SET revision=revision+1, updated_at=updated_at+1 WHERE id='demo'")

    def tearDown(self) -> None:
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

    def test_field_by_field_resolution_and_final_confirmation(self) -> None:
        state, _ = self.invoke("merge", "status")
        self.assertTrue(state["required"])
        conflict = state["items"][0]
        names = {field["name"] for field in conflict["fields"]}
        self.assertEqual({"body_markdown", "summary"}, names)

        first, _ = self.invoke("merge", "resolve", conflict["id"], "summary", "--ours")
        self.assertEqual("open", first["item"]["status"])
        self.assertEqual(1, first["session"]["resolvedFields"])
        manual_file = self.root / "merged.md"
        manual_file.write_text("人工合并正文", encoding="utf-8")
        second, _ = self.invoke(
            "merge", "resolve", conflict["id"], "body_markdown", "--manual-file", str(manual_file)
        )
        self.assertEqual("resolved", second["item"]["status"])

        with self.assertRaises(CliError) as missing_confirmation:
            args = self.parser.parse_args(["merge", "finalize"])
            args.handler(self.client, args)
        self.assertEqual("confirmation_required", missing_confirmation.exception.code)

        completed, _ = self.invoke("merge", "finalize", "--yes")
        self.assertIsNotNone(completed["operation"]["id"])
        self.assertFalse(self.client.meta()["mergeRequired"])
        with sqlite3.connect(self.root / "result/demo/story.db") as connection:
            row = connection.execute(
                "SELECT summary, body_markdown FROM plots WHERE entity_id='plot:1'"
            ).fetchone()
            self.assertEqual(("本地摘要", "人工合并正文"), row)
            self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))


class WorkflowCliProcessTests(unittest.TestCase):
    def test_real_launcher_worker_persists_search_and_timeline_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            project_root = workspace / "content/demo"
            project_root.mkdir(parents=True)
            shutil.copy2(ROOT / "tests/fixtures/schema-v1-demo.db", workspace / "legacy.db")
            V3Migrator(workspace / "legacy.db", "demo").migrate_to(project_root / "story.db")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            server = subprocess.Popen(
                [
                    str(ROOT / "scripts/python.sh"), "-m", "storyteller",
                    "--bind", "127.0.0.1", "--port", str(port),
                    "--content-root", str(workspace / "content"),
                    "--frontend-root", str(workspace / "missing"),
                    "--default-project", "demo",
                ],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            )

            def run_cli(*arguments: str) -> dict:
                completed = subprocess.run(
                    [
                        str(ROOT / "story-teller"), *arguments,
                        "--project", "demo", "--web-url", f"http://127.0.0.1:{port}", "--json",
                    ],
                    cwd=project_root, capture_output=True, text=True, timeout=120, check=False,
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

                search = run_cli("search", "烧焦的航海日记", "--kind", "plot")
                self.assertEqual("plot:1", search["items"][0]["entityId"])
                line = run_cli(
                    "timeline", "line", "add", "进程测试线", "--id", "process-test", "--main"
                )["item"]
                run_cli(
                    "timeline", "node", "assign", "plot:1",
                    "--line", line["entityId"], "--line", "timeline_line:电台线",
                )
                moved = run_cli("timeline", "node", "move", "plot:1", "--after", "plot:2")
                self.assertEqual(2, moved["storyOrder"])

                with sqlite3.connect(project_root / "story.db") as connection:
                    self.assertEqual(
                        "timeline_line:process-test",
                        connection.execute(
                            "SELECT main_line_id FROM timeline_settings WHERE project_id='demo'"
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        1,
                        connection.execute(
                            "SELECT COUNT(*) FROM plot_timeline_lines WHERE plot_id='plot:1' AND line_id='timeline_line:process-test'"
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        2,
                        connection.execute(
                            "SELECT chapter_number FROM plots WHERE entity_id='plot:1'"
                        ).fetchone()[0],
                    )
                    self.assertEqual([], list(connection.execute("PRAGMA foreign_key_check")))
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=5)
                if server.stdout:
                    server.stdout.close()


if __name__ == "__main__":
    unittest.main()
