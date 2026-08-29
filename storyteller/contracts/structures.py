from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from storyteller.contracts.common import MutationRequest


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
