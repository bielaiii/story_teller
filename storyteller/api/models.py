from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from storyteller.contracts.common import MutationRequest, UndoRequest, mutation_payload
from storyteller.contracts.content import (
    CharacterCreate,
    CharacterPatch,
    CharacterPersonaItem,
    EntryCreate,
    EntryMember,
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
    GraphClusterItem,
    GraphDistanceItem,
    GraphNodeItem,
    GraphUpdate,
    PlotOrderUpdate,
    StoryPlotItem,
    StoryStructureUpdate,
    TimelineAssignment,
    TimelineChapterNumberItem,
    TimelineLineItem,
    TimelineUpdate,
)


class MarkdownImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    path: str
    text: str
    modified_at: int | None = Field(default=None, alias="modifiedAt", ge=0)


class ReadingCopyConfig(MutationRequest):
    enabled: bool = Field(strict=True)


class MarkdownImportRequest(MutationRequest):
    files: list[MarkdownImportFile]
    allow_conflicts: bool = Field(default=False, alias="allowConflicts")
    preview_fingerprint: str | None = Field(default=None, alias="previewFingerprint")


class PlotTitleRepairApply(MutationRequest):
    plot_ids: list[str] = Field(alias="plotIds", min_length=1)


class PlotTitleRepairConfirmItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    plot_id: str = Field(alias="plotId")
    title: str


class PlotTitleRepairConfirm(MutationRequest):
    items: list[PlotTitleRepairConfirmItem] = Field(min_length=1)


class StoryMigrationApply(MutationRequest):
    acknowledge_warnings: bool = Field(default=False, alias="acknowledgeWarnings")


class MergeFieldResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: Literal["ours", "theirs", "manual", "both"]
    value: Any | None = None


class MergeConflictResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolutions: dict[str, MergeFieldResolution]


class MergeFinalizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    preview_token: str | None = Field(default=None, alias="previewToken")
