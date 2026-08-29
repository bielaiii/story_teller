from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from storyteller.contracts.common import MutationRequest


class CharacterPersonaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = ""
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
