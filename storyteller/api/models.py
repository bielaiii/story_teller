from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    base_revision: int = Field(alias="baseRevision", ge=0)
    entity_revision: int | None = Field(default=None, alias="entityRevision", ge=0)


class UndoRequest(MutationRequest):
    operation_id: int = Field(alias="operationId", gt=0)


class CharacterPersonaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: str


class CharacterCreate(MutationRequest):
    stable_id: str = Field(default="", alias="stableId")
    name: str
    intro: str = ""
    aliases: list[str] = []
    markers: list[str] = []
    facts: dict[str, str] = {}
    supplements: list[str] = []
    core_persona: list[CharacterPersonaItem] = Field(default=[], alias="corePersona")
    supplement_persona: list[CharacterPersonaItem] = Field(default=[], alias="supplementPersona")
    destiny_outline: str = Field(default="", alias="destinyOutline")
    narrative_role: str = Field(default="配角", alias="narrativeRole")
    character_scope: str = Field(default="常驻人物", alias="characterScope")
    side: str = "中立"
    main_plot_impact: int = Field(default=0, alias="mainPlotImpact")
    color: str | None = None
    gradient: str = ""
    group: str = ""
    graph_visible: bool | None = Field(default=None, alias="graphVisible")
    references: list[str] = []


class CharacterPatch(MutationRequest):
    name: str | None = None
    intro: str | None = None
    aliases: list[str] | None = None
    markers: list[str] | None = None
    facts: dict[str, str] | None = None
    supplements: list[str] | None = None
    core_persona: list[CharacterPersonaItem] | None = Field(default=None, alias="corePersona")
    supplement_persona: list[CharacterPersonaItem] | None = Field(default=None, alias="supplementPersona")
    destiny_outline: str | None = Field(default=None, alias="destinyOutline")
    narrative_role: str | None = Field(default=None, alias="narrativeRole")
    character_scope: str | None = Field(default=None, alias="characterScope")
    side: str | None = None
    main_plot_impact: int | None = Field(default=None, alias="mainPlotImpact")
    color: str | None = None
    gradient: str | None = None
    group: str | None = None
    graph_visible: bool | None = Field(default=None, alias="graphVisible")
    references: list[str] | None = None


class PlotCreate(MutationRequest):
    stable_id: str = Field(default="", alias="stableId")
    title: str
    chapter_number: int = Field(alias="chapterNumber", ge=1, le=99999)
    shift_following: bool = Field(default=False, alias="shiftFollowing")
    chapter_id: str | None = Field(default=None, alias="chapterId")
    after_entity_id: str | None = Field(default=None, alias="afterEntityId")
    summary: str = ""
    body: str = ""
    status: str = "草稿"
    accent: str = "#7d6bd6"
    key: bool = False
    climax: bool = False
    tags: list[str] = []
    people: list[str] = []
    appearance_names: list[str] = Field(default=[], alias="appearanceNames")
    entries: list[str] = []
    lanes: list[str] = []
    stories: list[str] = []
    story_position_mode: Literal["follow_reading", "before", "after", "fixed"] = Field(default="follow_reading", alias="storyPositionMode")
    story_anchor_plot_id: str | None = Field(default=None, alias="storyAnchorPlotId")
    story_sort_key: str | None = Field(default=None, alias="storySortKey")
    references: list[str] = []


class PlotPatch(MutationRequest):
    title: str | None = None
    chapter_number: int | None = Field(default=None, alias="chapterNumber", ge=1, le=99999)
    shift_following: bool = Field(default=False, alias="shiftFollowing")
    chapter_id: str | None = Field(default=None, alias="chapterId")
    summary: str | None = None
    body: str | None = None
    status: str | None = None
    accent: str | None = None
    key: bool | None = None
    climax: bool | None = None
    tags: list[str] | None = None
    people: list[str] | None = None
    appearance_names: list[str] | None = Field(default=None, alias="appearanceNames")
    entries: list[str] | None = None
    lanes: list[str] | None = None
    stories: list[str] | None = None
    story_position_mode: Literal["follow_reading", "before", "after", "fixed"] | None = Field(default=None, alias="storyPositionMode")
    story_anchor_plot_id: str | None = Field(default=None, alias="storyAnchorPlotId")
    story_sort_key: str | None = Field(default=None, alias="storySortKey")
    references: list[str] | None = None


class EntryMember(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    character_id: str = Field(alias="characterId")
    role: str = ""
    status: str = "现成员"


class EntryCreate(MutationRequest):
    stable_id: str = Field(default="", alias="stableId")
    name: str
    type: str
    subtype: str = ""
    area: str = ""
    body: str = ""
    status: str = ""
    accent: str | None = None
    aliases: list[str] = []
    tags: list[str] = []
    people: list[str] = []
    members: list[EntryMember] = []
    references: list[str] = []


class EntryPatch(MutationRequest):
    name: str | None = None
    type: str | None = None
    subtype: str | None = None
    area: str | None = None
    body: str | None = None
    status: str | None = None
    accent: str | None = None
    aliases: list[str] | None = None
    tags: list[str] | None = None
    people: list[str] | None = None
    members: list[EntryMember] | None = None
    references: list[str] | None = None


class FragmentCreate(MutationRequest):
    stable_id: str = Field(default="", alias="stableId")
    title: str
    body: str = ""
    status: str = ""
    accent: str = "#7d6bd6"
    key: bool = False
    climax: bool = False
    tags: list[str] = []
    people: list[str] = []
    appearance_names: list[str] = Field(default=[], alias="appearanceNames")
    references: list[str] = []
    fragment_type: str = Field(default="chapter", alias="fragmentType")
    parent_fragment_id: str | None = Field(default=None, alias="parentFragmentId")
    fragment_order: int | None = Field(default=None, alias="fragmentOrder", ge=0)
    chapter_number: int | None = Field(default=None, alias="chapterNumber", ge=1)
    plot_chapter_plan: dict[str, int] = Field(default={}, alias="plotChapterPlan")
    shift_following: bool = Field(default=False, alias="shiftFollowing")


class FragmentPatch(MutationRequest):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    accent: str | None = None
    key: bool | None = None
    climax: bool | None = None
    tags: list[str] | None = None
    people: list[str] | None = None
    appearance_names: list[str] | None = Field(default=None, alias="appearanceNames")
    references: list[str] | None = None
    fragment_type: str | None = Field(default=None, alias="fragmentType")
    parent_fragment_id: str | None = Field(default=None, alias="parentFragmentId")
    fragment_order: int | None = Field(default=None, alias="fragmentOrder", ge=0)
    chapter_number: int | None = Field(default=None, alias="chapterNumber", ge=1)
    plot_chapter_plan: dict[str, int] | None = Field(default=None, alias="plotChapterPlan")
    shift_following: bool = Field(default=False, alias="shiftFollowing")


class FragmentClipboardImport(MutationRequest):
    text: str


class MarkdownImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    path: str
    text: str
    modified_at: int | None = Field(default=None, alias="modifiedAt", ge=0)


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


class FragmentToPlotRequest(MutationRequest):
    chapter_number: int = Field(alias="chapterNumber", ge=1, le=99999)
    title: str | None = None
    stories: list[str] = []


class RelationshipCreate(MutationRequest):
    from_character_id: str = Field(alias="fromCharacterId")
    to_character_id: str = Field(alias="toCharacterId")
    from_role: str = Field(default="", alias="fromRole")
    to_role: str = Field(default="", alias="toRole")
    from_impression: str = Field(default="", alias="fromImpression")
    to_impression: str = Field(default="", alias="toImpression")
    graph_scope: str = Field(default="", alias="graphScope")
    graph_line_mode: str = Field(default="single", alias="graphLineMode")
    label: str = ""
    type: str = ""
    color: str = "#8b95a7"
    body: str = ""
    references: list[str] = []


class RelationshipPatch(MutationRequest):
    from_role: str | None = Field(default=None, alias="fromRole")
    to_role: str | None = Field(default=None, alias="toRole")
    from_impression: str | None = Field(default=None, alias="fromImpression")
    to_impression: str | None = Field(default=None, alias="toImpression")
    graph_scope: str | None = Field(default=None, alias="graphScope")
    graph_line_mode: str | None = Field(default=None, alias="graphLineMode")
    label: str | None = None
    type: str | None = None
    color: str | None = None
    body: str | None = None
    references: list[str] | None = None


class ChapterItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    entity_id: str = Field(default="", alias="entityId")
    stable_id: str = Field(default="", alias="stableId")
    label: str


class ChaptersUpdate(MutationRequest):
    chapters: list[ChapterItem]


class PlotOrderUpdate(MutationRequest):
    plot_ids: list[str] = Field(alias="plotIds")


class StoryPlotItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    entity_id: str = Field(alias="entityId")
    chapter_id: str = Field(alias="chapterId")


class StoryStructureUpdate(MutationRequest):
    chapters: list[ChapterItem]
    plots: list[StoryPlotItem]


class TimelineLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    entity_id: str = Field(default="", alias="entityId")
    stable_id: str = Field(default="", alias="stableId")
    name: str
    color: str = "#3f7fc1"
    side: str = "right"
    start_plot_id: str | None = Field(default=None, alias="startPlotId")
    end_plot_id: str | None = Field(default=None, alias="endPlotId")


class TimelineAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    plot_id: str = Field(alias="plotId")
    line_ids: list[str] = Field(default=[], alias="lineIds")
    story_sort_key: str = Field(default="", alias="storySortKey")
    story_order_mode: Literal["follow_reading", "fixed"] | None = Field(default=None, alias="storyOrderMode")
    story_order: int | None = Field(default=None, alias="storyOrder")


class TimelineChapterNumberItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    plot_id: str = Field(alias="plotId")
    chapter_number: int = Field(alias="chapterNumber", ge=1, le=99999)


class TimelineUpdate(MutationRequest):
    main_line_id: str = Field(alias="mainLineId")
    line_spacing: int = Field(default=72, alias="lineSpacing")
    top_padding: int = Field(default=64, alias="topPadding")
    side_padding: int = Field(default=36, alias="sidePadding")
    pixels_per_story_unit: int = Field(default=760, alias="pixelsPerStoryUnit")
    lines: list[TimelineLineItem]
    assignments: list[TimelineAssignment]
    chapter_numbers: list[TimelineChapterNumberItem] | None = Field(default=None, alias="chapterNumbers")
    line_replacements: dict[str, str] = Field(default={}, alias="lineReplacements")


class GraphNodeItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    character_id: str = Field(alias="characterId")
    orbit_of: str | None = Field(default=None, alias="orbitOf")
    orbit_distance: float | None = Field(default=None, alias="orbitDistance")
    orbit_angle: float | None = Field(default=None, alias="orbitAngle")
    strength: float | None = None
    anchor_x: float | None = Field(default=None, alias="anchorX")
    anchor_y: float | None = Field(default=None, alias="anchorY")


class GraphDistanceItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_character_id: str = Field(alias="fromCharacterId")
    to_character_id: str = Field(alias="toCharacterId")
    distance: float
    strength: float


class GraphClusterItem(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    id: str
    label: str
    center_x: float | None = Field(default=None, alias="centerX")
    center_y: float | None = Field(default=None, alias="centerY")
    radius: float | None = None
    strength: float | None = None
    members: list[str] = []


class GraphUpdate(MutationRequest):
    node_spacing: float | None = Field(default=None, alias="nodeSpacing")
    initial_jitter: float | None = Field(default=None, alias="initialJitter")
    relationship_distance: float | None = Field(default=None, alias="relationshipDistance")
    leaf_distance_extra: float | None = Field(default=None, alias="leafDistanceExtra")
    center_strength: float | None = Field(default=None, alias="centerStrength")
    group_strength: float | None = Field(default=None, alias="groupStrength")
    leaf_strength: float | None = Field(default=None, alias="leafStrength")
    nodes: list[GraphNodeItem] | None = None
    distances: list[GraphDistanceItem] | None = None
    clusters: list[GraphClusterItem] | None = None


class MergeFieldResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: str
    value: Any | None = None


class MergeConflictResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolutions: dict[str, MergeFieldResolution]


def mutation_payload(model: MutationRequest) -> dict[str, Any]:
    return model.model_dump(exclude={"base_revision"}, exclude_unset=True)
