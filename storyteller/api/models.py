from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MutationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    base_revision: int = Field(alias="baseRevision", ge=0)


class UndoRequest(MutationRequest):
    operation_id: int = Field(alias="operationId", gt=0)


class DiagnosticIgnoreRequest(MutationRequest):
    reason: str = ""


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
    narrative_role: str = Field(default="配角", alias="narrativeRole")
    character_scope: str = Field(default="常驻人物", alias="characterScope")
    side: str = "中立"
    main_plot_impact: int = Field(default=0, alias="mainPlotImpact")
    color: str = "#7d6bd6"
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
    entries: list[str] = []
    lanes: list[str] = []
    references: list[str] = []


class PlotPatch(MutationRequest):
    title: str | None = None
    chapter_id: str | None = Field(default=None, alias="chapterId")
    summary: str | None = None
    body: str | None = None
    status: str | None = None
    accent: str | None = None
    key: bool | None = None
    climax: bool | None = None
    tags: list[str] | None = None
    people: list[str] | None = None
    entries: list[str] | None = None
    lanes: list[str] | None = None
    references: list[str] | None = None


class EntryCreate(MutationRequest):
    stable_id: str = Field(default="", alias="stableId")
    name: str
    type: str
    subtype: str = ""
    area: str = ""
    body: str = ""
    status: str = ""
    accent: str = "#7d6bd6"
    aliases: list[str] = []
    tags: list[str] = []
    people: list[str] = []
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
    references: list[str] | None = None


class FragmentCreate(MutationRequest):
    stable_id: str = Field(default="", alias="stableId")
    title: str
    body: str = ""
    status: str = ""
    accent: str = "#7d6bd6"
    tags: list[str] = []
    references: list[str] = []


class FragmentPatch(MutationRequest):
    title: str | None = None
    body: str | None = None
    status: str | None = None
    accent: str | None = None
    tags: list[str] | None = None
    references: list[str] | None = None


class RelationshipCreate(MutationRequest):
    from_character_id: str = Field(alias="fromCharacterId")
    to_character_id: str = Field(alias="toCharacterId")
    from_role: str = Field(default="", alias="fromRole")
    to_role: str = Field(default="", alias="toRole")
    label: str = ""
    type: str = ""
    color: str = "#8b95a7"
    body: str = ""
    references: list[str] = []


class RelationshipPatch(MutationRequest):
    from_role: str | None = Field(default=None, alias="fromRole")
    to_role: str | None = Field(default=None, alias="toRole")
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
    story_order: int | None = Field(default=None, alias="storyOrder")


class TimelineUpdate(MutationRequest):
    main_line_id: str = Field(alias="mainLineId")
    line_spacing: int = Field(default=72, alias="lineSpacing")
    top_padding: int = Field(default=64, alias="topPadding")
    side_padding: int = Field(default=36, alias="sidePadding")
    pixels_per_story_unit: int = Field(default=760, alias="pixelsPerStoryUnit")
    lines: list[TimelineLineItem]
    assignments: list[TimelineAssignment]
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


def mutation_payload(model: MutationRequest) -> dict[str, Any]:
    return model.model_dump(exclude={"base_revision"}, exclude_unset=True)
