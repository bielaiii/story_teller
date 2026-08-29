from __future__ import annotations

from pydantic import Field

from storyteller.contracts.common import MutationRequest


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


class FragmentToPlotRequest(MutationRequest):
    chapter_number: int = Field(alias="chapterNumber", ge=1, le=99999)
    title: str | None = None
    stories: list[str] = []
