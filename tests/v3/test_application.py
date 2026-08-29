from __future__ import annotations

import ast
import shutil
import tempfile
import unittest
from pathlib import Path

from storyteller.application import ApplicationContext, StoryApplication
from storyteller.application.mutations import ProjectExporter
from storyteller.contracts.common import MutationRequest, UndoRequest
from storyteller.contracts.content import (
    CharacterCreate,
    CharacterPatch,
    EntryCreate,
    EntryPatch,
    PlotCreate,
    PlotPatch,
    RelationshipCreate,
    RelationshipPatch,
)
from storyteller.contracts.fragments import (
    FragmentClipboardImport,
    FragmentCreate,
    FragmentPatch,
    FragmentToPlotRequest,
)
from storyteller.contracts.structures import (
    ChapterItem,
    ChaptersUpdate,
    GraphUpdate,
    PlotOrderUpdate,
    StoryPlotItem,
    StoryStructureUpdate,
    TimelineAssignment,
    TimelineLineItem,
    TimelineUpdate,
)
from storyteller.settings import Settings
from storyteller.storage.legacy import V3Migrator
from storyteller.storage.repositories import ProjectRepository


ROOT = Path(__file__).resolve().parents[2]


class RecordingRagScheduler:
    def __init__(self):
        self.calls: list[tuple[str, int]] = []

    def schedule(self, project: str, revision: int) -> bool:
        self.calls.append((project, revision))
        return True


class FailingExporter(ProjectExporter):
    def export(self, database, project_id: str) -> dict:
        raise OSError("test export failure")


class ApplicationMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.content_root = self.root / "content"
        self.project_root = self.content_root / "demo"
        self.project_root.mkdir(parents=True)
        shutil.copy2(
            ROOT / "tests/fixtures/schema-v1-demo.db",
            self.project_root / "legacy.db",
        )
        V3Migrator(self.project_root / "legacy.db", "demo").migrate_to(
            self.project_root / "story.db"
        )
        self.settings = Settings.create(
            ROOT,
            content_root=self.content_root,
            frontend_root=self.root / "missing",
            default_project="demo",
        )
        self.rag = RecordingRagScheduler()
        self.application = StoryApplication.create(self.settings, self.rag)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def revision(self) -> int:
        database = self.application.projects.open("demo")
        return int(ProjectRepository(database, "demo").snapshot()["project"]["revision"])

    def test_direct_application_mutation_persists_exports_and_schedules_rag(self) -> None:
        result = self.application.fragments.create(
            ApplicationContext("demo", source="cli"),
            FragmentCreate(
                baseRevision=self.revision(),
                title="Application 共享碎片",
                body="这次写入没有经过 FastAPI。",
            ),
        )

        created = next(
            item for item in result.changed["fragments"]
            if item["title"] == "Application 共享碎片"
        )
        database = self.application.projects.open("demo")
        detail = ProjectRepository(database, "demo").entity_detail(created["entityId"])

        self.assertEqual("这次写入没有经过 FastAPI。", detail["data"]["body"])
        self.assertEqual("ready", result.export.status)
        self.assertEqual([("demo", result.project_revision)], self.rag.calls)
        self.assertTrue((self.project_root / "project.snapshot.json").is_file())
        self.assertIn(
            "Application 共享碎片",
            (self.project_root / "project.snapshot.json").read_text(encoding="utf-8"),
        )

    def test_export_failure_keeps_committed_data_and_returns_warning(self) -> None:
        application = StoryApplication.create(
            self.settings,
            self.rag,
            exporter=FailingExporter(),
        )
        result = application.fragments.create(
            ApplicationContext("demo", source="system"),
            FragmentCreate(
                baseRevision=self.revision(),
                title="导出失败仍保存",
                body="数据库是真实来源。",
            ),
        )

        created = next(
            item for item in result.changed["fragments"]
            if item["title"] == "导出失败仍保存"
        )
        detail = ProjectRepository(
            application.projects.open("demo"), "demo"
        ).entity_detail(created["entityId"])

        self.assertEqual("数据库是真实来源。", detail["data"]["body"])
        self.assertEqual("failed", result.export.status)
        self.assertIn("test export failure", result.warnings[0])

    def test_fragment_vertical_slice_round_trips_without_http(self) -> None:
        context = ApplicationContext("demo", source="cli")
        created = self.application.fragments.create(
            context,
            FragmentCreate(
                baseRevision=self.revision(),
                title="Application 生命周期碎片",
                body="初始正文。",
            ),
        )
        fragment = next(
            item for item in created.changed["fragments"]
            if item["title"] == "Application 生命周期碎片"
        )
        fragment_id = fragment["entityId"]

        updated = self.application.fragments.update(
            context,
            fragment_id,
            FragmentPatch(
                baseRevision=self.revision(),
                entityRevision=fragment["revision"],
                title="Application 生命周期碎片（已编辑）",
                body="编辑后的正文。",
            ),
        )
        database = self.application.projects.open("demo")
        repository = ProjectRepository(database, "demo")
        self.assertEqual(
            "编辑后的正文。", repository.entity_detail(fragment_id)["data"]["body"]
        )

        self.assertIsNotNone(updated.operation.id)
        self.application.history.undo(
            context,
            UndoRequest(
                baseRevision=self.revision(),
                operationId=updated.operation.id,
            ),
        )
        self.assertEqual(
            "初始正文。", repository.entity_detail(fragment_id)["data"]["body"]
        )

        self.application.entities.delete(
            context,
            fragment_id,
            MutationRequest(baseRevision=self.revision()),
        )
        self.assertIn(fragment_id, {item["entityId"] for item in repository.trash()})
        restored = self.application.entities.restore(
            context,
            fragment_id,
            MutationRequest(baseRevision=self.revision()),
        )
        self.assertIn(fragment_id, {item["entityId"] for item in restored.changed["fragments"]})
        self.assertEqual(
            "初始正文。", repository.entity_detail(fragment_id)["data"]["body"]
        )

        imported = self.application.fragments.import_clipboard(
            context,
            FragmentClipboardImport(
                baseRevision=self.revision(),
                text=(
                    "# Application 导入剧情线\n总览。\n\n"
                    "第一章：远港来信\n第一章正文。\n\n"
                    "第二章：旧仓回声\n第二章正文。"
                ),
            ),
        )
        imported_fragments = imported.changed["fragments"]
        line = next(item for item in imported_fragments if item["fragmentType"] == "line")
        child = next(
            item for item in imported_fragments
            if item.get("parentFragmentId") == line["entityId"]
        )
        promoted = self.application.fragments.promote(
            context,
            child["entityId"],
            FragmentToPlotRequest(
                baseRevision=self.revision(),
                chapterNumber=9001,
            ),
        )
        plot = next(item for item in promoted.changed["plots"] if item["chapterNumber"] == 9001)
        self.assertEqual(
            "第一章正文。", repository.entity_detail(plot["entityId"])["data"]["body"]
        )
        self.assertIn(child["entityId"], promoted.removed["fragments"])

    def test_remaining_content_and_structure_use_cases_round_trip_without_http(self) -> None:
        context = ApplicationContext("demo", source="cli")
        character_result = self.application.characters.create(
            context,
            CharacterCreate(
                baseRevision=self.revision(),
                name="Application 新人物",
                intro="初始人物正文。",
            ),
        )
        character = next(
            item for item in character_result.changed["characters"]
            if item["name"] == "Application 新人物"
        )
        self.application.characters.update(
            context,
            character["entityId"],
            CharacterPatch(
                baseRevision=self.revision(),
                intro="更新后的人物正文。",
            ),
        )

        entry_result = self.application.entries.create(
            context,
            EntryCreate(
                baseRevision=self.revision(),
                name="Application 新设定",
                type="地点",
                body="初始设定正文。",
            ),
        )
        entry = next(
            item for item in entry_result.changed["entries"]
            if item["name"] == "Application 新设定"
        )
        self.application.entries.update(
            context,
            entry["entityId"],
            EntryPatch(
                baseRevision=self.revision(),
                body="更新后的设定正文。",
            ),
        )

        plot_result = self.application.plots.create(
            context,
            PlotCreate(
                baseRevision=self.revision(),
                title="Application 新剧情",
                chapterNumber=9002,
                body="初始剧情正文。",
            ),
        )
        plot = next(
            item for item in plot_result.changed["plots"]
            if item["title"] == "Application 新剧情"
        )
        self.application.plots.update(
            context,
            plot["entityId"],
            PlotPatch(
                baseRevision=self.revision(),
                summary="更新后的剧情摘要。",
            ),
        )

        relationship_result = self.application.relationships.create(
            context,
            RelationshipCreate(
                baseRevision=self.revision(),
                fromCharacterId=character["entityId"],
                toCharacterId="character:1",
                label="Application 初始关系",
            ),
        )
        relationship = next(
            item for item in relationship_result.changed["relationships"]
            if item["label"] == "Application 初始关系"
        )
        self.application.relationships.update(
            context,
            relationship["entityId"],
            RelationshipPatch(
                baseRevision=self.revision(),
                label="Application 更新关系",
                body="关系正文已经更新。",
            ),
        )

        repository = ProjectRepository(self.application.projects.open("demo"), "demo")
        self.assertEqual(
            "更新后的人物正文。",
            repository.entity_detail(character["entityId"])["data"]["intro"],
        )
        self.assertEqual(
            "更新后的设定正文。",
            repository.entity_detail(entry["entityId"])["data"]["body"],
        )
        self.assertEqual(
            "更新后的剧情摘要。",
            repository.entity_detail(plot["entityId"])["data"]["summary"],
        )
        self.assertEqual(
            "Application 更新关系",
            repository.entity_detail(relationship["entityId"])["data"]["label"],
        )

        snapshot = repository.snapshot()
        chapters = [
            ChapterItem(
                entityId=item["entityId"],
                stableId=item["id"],
                label=(item["label"] + "（Application）" if index == 0 else item["label"]),
            )
            for index, item in enumerate(snapshot["chapters"])
        ]
        self.application.structures.update_chapters(
            context,
            ChaptersUpdate(baseRevision=self.revision(), chapters=chapters),
        )
        snapshot = repository.snapshot()
        reversed_plot_ids = [item["entityId"] for item in reversed(snapshot["plots"])]
        self.application.structures.reorder_plots(
            context,
            PlotOrderUpdate(
                baseRevision=self.revision(),
                plotIds=reversed_plot_ids,
            ),
        )
        snapshot = repository.snapshot()
        self.assertEqual(
            reversed_plot_ids,
            [
                item["entityId"]
                for item in sorted(snapshot["plots"], key=lambda value: value["sequence"])
            ],
        )
        self.assertTrue(snapshot["chapters"][0]["label"].endswith("（Application）"))

        self.application.structures.update_story_structure(
            context,
            StoryStructureUpdate(
                baseRevision=self.revision(),
                chapters=[
                    ChapterItem(
                        entityId=item["entityId"],
                        stableId=item["id"],
                        label=item["label"],
                    )
                    for item in snapshot["chapters"]
                ],
                plots=[
                    StoryPlotItem(
                        entityId=item["entityId"],
                        chapterId=item["chapterId"],
                    )
                    for item in snapshot["plots"]
                ],
            ),
        )
        snapshot = repository.snapshot()
        self.application.structures.update_timeline(
            context,
            TimelineUpdate(
                baseRevision=self.revision(),
                mainLineId=snapshot["timeline"]["mainLineId"],
                lineSpacing=snapshot["timeline"]["lineSpacing"],
                topPadding=snapshot["timeline"]["topPadding"],
                sidePadding=snapshot["timeline"]["sidePadding"],
                pixelsPerStoryUnit=snapshot["timeline"]["pixelsPerStoryUnit"],
                lines=[
                    TimelineLineItem(
                        entityId=item["entityId"],
                        stableId=item["id"],
                        name=item["name"],
                        color=item["color"],
                        side=item["side"],
                        startPlotId=item["startPlotId"],
                        endPlotId=item["endPlotId"],
                    )
                    for item in snapshot["timeline"]["lines"]
                ],
                assignments=[
                    TimelineAssignment(
                        plotId=item["entityId"],
                        lineIds=item["lanes"],
                        storySortKey=item["storySortKey"],
                    )
                    for item in snapshot["plots"]
                ],
            ),
        )
        self.application.structures.update_graph(
            context,
            GraphUpdate(
                baseRevision=self.revision(),
                nodeSpacing=143,
            ),
        )
        self.assertEqual(143, repository.snapshot()["graph"]["settings"]["node_spacing"])


class ApplicationDependencyTests(unittest.TestCase):
    def test_application_layer_does_not_import_delivery_adapters(self) -> None:
        forbidden = {"argparse", "fastapi", "storyteller.api", "storyteller.cli"}
        violations: list[str] = []
        for path in sorted((ROOT / "storyteller/application").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    if any(module == item or module.startswith(item + ".") for item in forbidden):
                        violations.append(f"{path.name}: {module}")
        self.assertEqual([], violations)

    def test_migrated_http_routes_are_thin_application_adapters(self) -> None:
        tree = ast.parse(
            (ROOT / "storyteller/app.py").read_text(encoding="utf-8"),
            filename="storyteller/app.py",
        )
        migrated = {
            "create_character",
            "update_character",
            "create_plot",
            "update_plot",
            "move_plot_to_fragment",
            "create_entry",
            "update_entry",
            "create_fragment",
            "update_fragment",
            "import_fragments_from_clipboard",
            "move_fragment_to_plot",
            "create_relationship",
            "update_relationship",
            "update_chapters",
            "reorder_plots",
            "update_story_structure",
            "update_timeline",
            "update_graph",
            "delete_entity",
            "restore_entity",
            "undo",
        }
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in migrated
        }
        self.assertEqual(migrated, set(functions))

        forbidden = {
            "ContentService",
            "EntityService",
            "StructureService",
            "UnitOfWork",
        }
        violations: list[str] = []
        for name, function in functions.items():
            for node in ast.walk(function):
                if isinstance(node, ast.Name) and node.id in forbidden:
                    violations.append(f"{name}: {node.id}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
