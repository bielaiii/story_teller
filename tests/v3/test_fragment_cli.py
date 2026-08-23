from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from storyteller.app import create_app
from storyteller.fragment_cli import (
    ApiClient,
    CliError,
    SelectionError,
    Workspace,
    build_parser,
    default_web_url,
    discover_workspace,
    normalize_global_options,
    select_project,
)
from storyteller.settings import Settings
from storyteller.storage.legacy import V3Migrator


ROOT = Path(__file__).resolve().parents[2]


class LocalApiClient(ApiClient):
    def __init__(self, test_client: TestClient, project: str):
        super().__init__("http://testserver", project)
        self.test_client = test_client

    def request(
        self,
        method: str,
        path: str,
        *,
        query=None,
        payload=None,
        mutation: bool = False,
    ):
        headers = {"X-Story-Teller-Token": self.token} if mutation else {}
        target = "/" + path.lstrip("/")
        if query:
            target += "?" + urlencode(query)
        response = self.test_client.request(method, target, headers=headers, json=payload)
        try:
            body = response.json()
        except json.JSONDecodeError as error:
            raise AssertionError(response.text) from error
        if response.status_code >= 400:
            exit_code = 5 if response.status_code == 409 else 3 if response.status_code == 503 else 6
            raise CliError(
                str(body.get("error") or body.get("detail") or "请求失败"),
                code=str(body.get("code") or f"http_{response.status_code}"),
                exit_code=exit_code,
            )
        return body


class FragmentCliTests(unittest.TestCase):
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

    def test_workspace_discovery_selection_and_hub_url_are_stable(self):
        nested = self.project_root / "notes" / "drafts"
        nested.mkdir(parents=True)
        workspace = discover_workspace(nested)
        self.assertEqual(self.root.resolve(), workspace.root)
        self.assertEqual((self.root / "content").resolve(), workspace.content_root)
        self.assertEqual(("demo",), workspace.projects)
        self.assertEqual("demo", select_project(workspace, start=nested))
        digest_url = default_web_url(workspace)
        self.assertRegex(digest_url, r"^http://127\.0\.0\.1:4187/w/workspace-[0-9a-f]{16}$")
        self.assertEqual(
            ["--project", "demo", "--json", "list"],
            normalize_global_options(["list", "--project", "demo", "--json"]),
        )

    def test_complete_fragment_workflow_uses_real_api_transactions(self):
        line_result, _ = self.invoke("add", "CLI 复仇主线", "--line", "--body", "主线总览")
        line_id = line_result["item"]["data"]["entityId"]

        child_result, _ = self.invoke(
            "add",
            "CLI 第一次交锋",
            "--parent",
            line_id,
            "--chapter-number",
            "1",
            "--body",
            "她在码头发现了第一条线索。",
            "--tag",
            "交锋",
            "--key",
        )
        child_id = child_result["item"]["data"]["entityId"]
        child = self.client.detail(child_id)["data"]
        self.assertEqual(line_id, child["parentFragmentId"])
        self.assertEqual(1, child["chapterNumber"])
        self.assertTrue(child["key"])

        edited, _ = self.invoke(
            "edit",
            child_id,
            "--title",
            "CLI 第一次正面交锋",
            "--chapter-number",
            "2",
            "--tag",
            "关键节点",
            "--no-key",
        )
        self.assertEqual("CLI 第一次正面交锋", edited["item"]["data"]["title"])
        self.assertEqual(2, edited["item"]["data"]["chapterNumber"])
        self.assertFalse(edited["item"]["data"]["key"])
        self.assertEqual(["关键节点"], edited["item"]["data"]["tags"])

        _tree, tree_json = self.invoke("list", "--tree")
        self.assertIn(line_id, {item["entityId"] for item in tree_json["items"]})
        shown, _ = self.invoke("show", child_id)
        self.assertEqual("她在码头发现了第一条线索。", shown["data"]["body"])

        export_path = self.root / "exports" / "line.md"
        rendered, export_json = self.invoke("export", line_id, "-o", str(export_path))
        self.assertEqual(str(export_path.resolve()), export_json["path"])
        self.assertIn("# 第 2 章 · CLI 第一次正面交锋", rendered)
        self.assertEqual(rendered, export_path.read_text(encoding="utf-8"))

        self.invoke("delete", child_id, "--yes")
        trash, _ = self.invoke("trash")
        self.assertIn(child_id, {item["entityId"] for item in trash})
        self.invoke("restore", child_id)
        self.assertEqual(child_id, self.client.detail(child_id)["entityId"])

        history, _ = self.invoke("history")
        latest = next(item for item in history if item["canUndo"])
        self.invoke("undo", str(latest["id"]))
        with self.assertRaises(CliError):
            self.client.detail(child_id)

    def test_import_and_promote_work_with_minimal_required_parameters(self):
        source = self.root / "import.md"
        source.write_text(
            "# CLI 港口暗线\n总览。\n\n第一章：仓库\n发现账本。\n\n第二章：追踪\n跟到码头。",
            encoding="utf-8",
        )
        imported, _ = self.invoke("import", str(source))
        line = next(item for item in imported["items"] if item["fragmentType"] == "line")
        children = [item for item in imported["items"] if item["parentFragmentId"] == line["entityId"]]
        self.assertEqual([1, 2], sorted(item["chapterNumber"] for item in children))

        snapshot = self.client.snapshot()
        target = max((int(item.get("chapterNumber") or 0) for item in snapshot["plots"]), default=0) + 100
        promoted, _ = self.invoke(
            "promote", children[0]["entityId"], "--chapter-number", str(target)
        )
        self.assertEqual(target, promoted["items"][-1]["chapterNumber"])
        with self.assertRaises(CliError):
            self.client.detail(children[0]["entityId"])

    def test_ambiguous_titles_are_rejected_instead_of_guessed(self):
        self.invoke("add", "CLI 重名碎片", "--body", "A")
        self.invoke("add", "CLI 重名碎片", "--body", "B")
        snapshot = self.client.snapshot()
        with self.assertRaises(SelectionError) as caught:
            from storyteller.fragment_cli import resolve_fragment

            resolve_fragment(snapshot, "CLI 重名碎片")
        self.assertEqual("ambiguous_selector", caught.exception.code)


class FragmentCliInstallerTests(unittest.TestCase):
    def test_installer_creates_and_refreshes_the_global_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {"PATH": "/usr/bin:/bin", "STORY_FRAGMENT_BIN_DIR": directory}
            for _ in range(2):
                completed = subprocess.run(
                    [str(ROOT / "scripts" / "install-story-fragment.sh")],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
            installed = Path(directory) / "story-fragment"
            self.assertTrue(installed.is_file())
            self.assertTrue(installed.stat().st_mode & 0o111)
            self.assertEqual((ROOT / "story-fragment").read_bytes(), installed.read_bytes())

    def test_installer_refuses_to_overwrite_an_unrelated_program(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "story-fragment"
            target.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")
            completed = subprocess.run(
                [str(ROOT / "scripts" / "install-story-fragment.sh")],
                env={"PATH": "/usr/bin:/bin", "STORY_FRAGMENT_BIN_DIR": directory},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("拒绝覆盖", completed.stderr)
            self.assertIn("unrelated", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
