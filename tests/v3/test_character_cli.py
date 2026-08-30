from __future__ import annotations

import contextlib
import io
import json
import os
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
from storyteller.cli import build_parser, render_character_markdown, run
from storyteller.fragment_cli import ApiClient, CliError, normalize_global_options, resolve_person
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


class CharacterCliTests(unittest.TestCase):
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

    def test_parser_accepts_global_options_after_nested_commands(self):
        self.assertEqual(
            ["--project", "demo", "--json", "character", "relationship", "list"],
            normalize_global_options(["character", "relationship", "list", "--project", "demo", "--json"]),
        )

    def test_parser_errors_are_one_stable_json_document(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = run(["character", "edit", "--json"])
        self.assertEqual(2, exit_code)
        self.assertEqual("invalid_argument", json.loads(output.getvalue())["code"])

    def test_complete_character_workflow_round_trips_every_web_profile_section(self):
        intro = self.root / "intro.md"
        intro.write_text("她负责潜入目标组织。", encoding="utf-8")
        created, _ = self.invoke(
            "character", "add", "CLI 林冬",
            "--id", "cli-lindong",
            "--role", "反派",
            "--scope", "主线人物",
            "--impact", "77",
            "--group", "调查组",
            "--color", "#123456",
            "--gradient", "linear-gradient(#123456, #654321)",
            "--graph-visible",
            "--alias", "阿冬",
            "--marker", "观察者",
            "--fact", "职业=调查员",
            "--core-note", "不会轻易信任任何人",
            "--core-persona", "核心欲望=查清真相",
            "--supplement-note", "习惯在凌晨整理线索",
            "--supplement-persona", "偏好=黑咖啡",
            "--destiny-outline", "最终选择公开证据。",
            "--reference", "character:1",
        )
        character_id = created["item"]["entityId"]
        stored = self.client.detail(character_id)["data"]
        self.assertEqual("cli-lindong", stored["id"])
        self.assertEqual("反派方", stored["side"])
        self.assertEqual("配角", stored["narrativeRole"])
        self.assertEqual("主线人物", stored["characterScope"])
        self.assertEqual(77, stored["mainPlotImpact"])
        self.assertEqual("#123456", stored["color"])
        self.assertEqual("linear-gradient(#123456, #654321)", stored["gradient"])
        self.assertTrue(stored["graphVisible"])
        self.assertEqual(["阿冬"], stored["aliases"])
        self.assertEqual({"职业": "调查员"}, stored["facts"])
        self.assertEqual("查清真相", stored["corePersona"][1]["value"])
        self.assertEqual("黑咖啡", stored["supplementPersona"][1]["value"])
        self.assertEqual(["习惯在凌晨整理线索", "偏好：黑咖啡"], stored["supplements"])
        self.assertEqual(["character:1"], stored["references"])

        listed, _ = self.invoke(
            "character", "list", "--query", "阿冬", "--role", "反派",
            "--scope", "主线人物", "--group", "调查组",
        )
        self.assertEqual([character_id], [item["entityId"] for item in listed])
        shown, _ = self.invoke("character", "show", "阿冬")
        self.assertEqual(character_id, shown["item"]["entityId"])
        self.assertIn("relationships", shown["related"])

        unsafe_rename = self.parser.parse_args([
            "--json", "character", "edit", character_id, "--name", "未经确认的名字"
        ])
        with self.assertRaises(CliError) as caught:
            unsafe_rename.handler(self.client, unsafe_rename)
        self.assertEqual("confirmation_required", caught.exception.code)

        changed, _ = self.invoke(
            "character", "edit", character_id,
            "--name", "CLI 林冬（归队）",
            "--yes",
            "--role", "主角",
            "--scope", "常驻人物",
            "--impact", "91",
            "--no-graph-visible",
            "--clear-gradient",
            "--clear-aliases",
            "--clear-markers",
            "--clear-facts",
            "--clear-core-persona",
            "--clear-supplement-persona",
            "--clear-destiny-outline",
            "--clear-references",
        )
        edited = changed["item"]["data"]
        self.assertEqual("CLI 林冬（归队）", edited["name"])
        self.assertEqual("主角", edited["narrativeRole"])
        self.assertEqual("主角方", edited["side"])
        self.assertFalse(edited["graphVisible"])
        self.assertEqual("", edited["gradient"])
        self.assertEqual([], edited["aliases"])
        self.assertEqual({}, edited["facts"])
        self.assertEqual([], edited["corePersona"])
        self.assertEqual("", edited["destinyOutline"])

        history, _ = self.invoke("character", "history", "--kind", "character")
        latest_edit = next(item for item in history if item["action"] == "rename" and item["canUndo"])
        self.invoke("character", "undo", str(latest_edit["id"]))
        reverted = self.client.detail(character_id)["data"]
        self.assertEqual("CLI 林冬", reverted["name"])
        self.assertEqual(["阿冬"], reverted["aliases"])

        self.invoke("character", "edit", character_id, "--clear-core-persona")
        self.invoke("character", "edit", character_id, "--intro-file", str(intro))
        self.assertEqual("她负责潜入目标组织。", self.client.detail(character_id)["data"]["intro"])

        exported = self.root / "exports" / "character.md"
        markdown, output = self.invoke("character", "export", character_id, "-o", str(exported))
        self.assertEqual(str(exported.resolve()), output["path"])
        self.assertEqual(1, output["count"])
        self.assertIn("# CLI 林冬", markdown)
        self.assertIn("## 人物简介", markdown)
        self.assertEqual(markdown, exported.read_text(encoding="utf-8"))
        _all_markdown, all_output = self.invoke("character", "export", "--all")
        self.assertEqual(len(self.client.snapshot()["characters"]), all_output["count"])
        self.assertIn(character_id, all_output["entityIds"])
        ordered = self.client.snapshot()["characters"]
        _range_markdown, range_output = self.invoke(
            "character", "export", "--from", ordered[0]["entityId"], "--to", character_id
        )
        self.assertEqual(
            next(index for index, item in enumerate(ordered) if item["entityId"] == character_id) + 1,
            range_output["count"],
        )

        self.invoke("character", "delete", character_id, "--yes")
        trash, _ = self.invoke("character", "trash", "--kind", "character")
        self.assertIn(character_id, {item["entityId"] for item in trash})
        self.invoke("character", "restore", character_id)
        self.assertEqual(character_id, self.client.detail(character_id)["entityId"])

    def test_relationship_crud_reverse_pair_update_recovery_and_history(self):
        first, _ = self.invoke("character", "add", "CLI 甲", "--alias", "甲别名")
        second, _ = self.invoke("character", "add", "CLI 乙")
        first_id = first["item"]["entityId"]
        second_id = second["item"]["entityId"]

        created, _ = self.invoke(
            "character", "relationship", "add", "甲别名", second_id,
            "--label", "互相试探",
            "--type", "盟友",
            "--from-role", "委托人",
            "--to-role", "调查者",
            "--from-impression", "可靠但有所隐瞒",
            "--to-impression", "过于正直",
            "--scope", "core",
            "--line-mode", "double",
            "--color", "#345678",
            "--body", "双方暂时合作。",
            "--reference", "character:1",
        )
        relationship_id = created["item"]["entityId"]
        relationship = created["item"]["data"]
        self.assertEqual(first_id, relationship["from"])
        self.assertEqual(second_id, relationship["to"])
        self.assertEqual("double", relationship["graphLineMode"])
        self.assertEqual("#345678", relationship["color"])
        self.assertEqual(["character:1"], relationship["references"])

        reversed_update, _ = self.invoke(
            "character", "relationship", "add", second_id, first_id,
            "--label", "共同调查",
            "--from-impression", "愿意继续合作",
            "--to-impression", "仍需观察",
        )
        self.assertEqual(relationship_id, reversed_update["item"]["entityId"])
        updated = reversed_update["item"]["data"]
        self.assertEqual("仍需观察", updated["fromImpression"])
        self.assertEqual("愿意继续合作", updated["toImpression"])
        self.assertEqual("委托人", updated["fromRole"])
        self.assertEqual("调查者", updated["toRole"])
        self.assertEqual("double", updated["graphLineMode"])
        self.assertEqual(1, len([
            item for item in self.client.snapshot()["relationships"]
            if {item["from"], item["to"]} == {first_id, second_id}
        ]))
        revision = self.client.snapshot()["project"]["revision"]
        unchanged, unchanged_output = self.invoke(
            "character", "relationship", "add", first_id, second_id
        )
        self.assertTrue(unchanged["unchanged"])
        self.assertTrue(unchanged_output["unchanged"])
        self.assertEqual(revision, self.client.snapshot()["project"]["revision"])

        listed, _ = self.invoke("character", "relationship", "list", "--character", first_id)
        self.assertIn(relationship_id, {item["entityId"] for item in listed})
        shown, _ = self.invoke("character", "relationship", "show", relationship_id)
        self.assertEqual("共同调查", shown["item"]["data"]["label"])
        character_shown, _ = self.invoke("character", "show", first_id)
        self.assertIn(relationship_id, {
            item["entityId"] for item in character_shown["related"]["relationships"]
        })

        edited, _ = self.invoke(
            "character", "relationship", "edit", relationship_id,
            "--scope", "focus",
            "--line-mode", "single",
            "--clear-body",
            "--clear-from-role",
        )
        self.assertEqual("focus", edited["item"]["data"]["graphScope"])
        self.assertEqual("", edited["item"]["data"]["body"])

        self.invoke("character", "relationship", "delete", relationship_id, "--yes")
        trash, _ = self.invoke("character", "trash", "--kind", "relationship")
        self.assertIn(relationship_id, {item["entityId"] for item in trash})
        self.invoke("character", "restore", relationship_id)
        self.assertEqual(relationship_id, self.client.detail(relationship_id)["entityId"])
        history, _ = self.invoke("character", "history", "--kind", "relationship")
        self.assertTrue(history)
        self.assertTrue(all(item["entityKind"] == "relationship" for item in history))

    def test_selector_rejects_alias_ambiguity(self):
        self.invoke("character", "add", "CLI 同名一", "--alias", "影子")
        self.invoke("character", "add", "CLI 同名二", "--alias", "影子")
        with self.assertRaises(CliError) as caught:
            resolve_person(self.client.snapshot(), "影子")
        self.assertEqual("ambiguous_selector", caught.exception.code)

    def test_character_markdown_contains_all_profile_sections(self):
        rendered = render_character_markdown({
            "name": "完整人物",
            "narrativeRole": "主角",
            "side": "主角方",
            "characterScope": "主线人物",
            "group": "调查组",
            "aliases": ["别名"],
            "markers": ["标识"],
            "intro": "简介",
            "destinyOutline": "大纲",
            "corePersona": [{"key": "目标", "value": "复仇"}],
            "supplementPersona": [{"key": "", "value": "怕冷"}],
            "facts": {"职业": "调查员"},
            "supplements": ["左手有伤"],
        })
        for heading in ("基础资料", "人物简介", "人物大纲", "核心人设", "补充人设", "人物档案"):
            self.assertIn(f"## {heading}", rendered)
        self.assertNotIn("## 补充设定", rendered)


class StoryTellerInstallerTests(unittest.TestCase):
    def test_installer_creates_and_refreshes_global_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = {"PATH": "/usr/bin:/bin", "STORY_TELLER_BIN_DIR": directory}
            for _ in range(2):
                completed = subprocess.run(
                    [str(ROOT / "scripts" / "install-story-teller.sh")],
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
            installed = Path(directory) / "story-teller"
            self.assertTrue(installed.is_file())
            self.assertTrue(installed.stat().st_mode & 0o111)
            self.assertEqual((ROOT / "story-teller").read_bytes(), installed.read_bytes())

    def test_installer_refuses_to_overwrite_unrelated_program(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "story-teller"
            target.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")
            completed = subprocess.run(
                [str(ROOT / "scripts" / "install-story-teller.sh")],
                env={"PATH": "/usr/bin:/bin", "STORY_TELLER_BIN_DIR": directory},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("拒绝覆盖", completed.stderr)
            self.assertIn("unrelated", target.read_text(encoding="utf-8"))


class StoryTellerCharacterProcessTests(unittest.TestCase):
    def test_launcher_calls_running_worker_and_persists_character_to_disk(self):
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
                    str(ROOT / "scripts" / "python.sh"),
                    "-m", "storyteller",
                    "--bind", "127.0.0.1",
                    "--port", str(port),
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
                completed = subprocess.run(
                    [
                        str(ROOT / "story-teller"),
                        "character", "add", "CLI 真实进程人物",
                        "--alias", "进程别名",
                        "--fact", "来源=命令行",
                        "--project", "demo",
                        "--web-url", f"http://127.0.0.1:{port}",
                        "--json",
                    ],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
                result = json.loads(completed.stdout)
                self.assertTrue(result["ok"])
                self.assertEqual("CLI 真实进程人物", result["item"]["data"]["name"])
                invalid = subprocess.run(
                    [
                        str(ROOT / "story-teller"),
                        "character", "edit", "进程别名",
                        "--impact", "101",
                        "--project", "demo",
                        "--web-url", f"http://127.0.0.1:{port}",
                        "--json",
                    ],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(6, invalid.returncode, invalid.stderr)
                self.assertEqual("validation", json.loads(invalid.stdout)["code"])
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
                row = connection.execute(
                    "SELECT c.name, c.main_plot_impact FROM characters c JOIN entities e ON e.id=c.entity_id "
                    "WHERE e.project_id=? AND c.name=? AND e.deleted_at IS NULL",
                    ("demo", "CLI 真实进程人物"),
                ).fetchone()
            self.assertEqual(("CLI 真实进程人物", 50), row)
            exported = json.loads((project_root / "project.snapshot.json").read_text(encoding="utf-8"))
            self.assertIn("CLI 真实进程人物", {item["name"] for item in exported["characters"]})


if __name__ == "__main__":
    unittest.main()
