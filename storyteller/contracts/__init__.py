"""Stable application boundary contracts shared by all adapters."""

from storyteller.contracts.common import MutationRequest, UndoRequest, mutation_payload
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
from storyteller.contracts.responses import MutationOutcome
from storyteller.contracts.structures import (
    ChaptersUpdate,
    GraphUpdate,
    PlotOrderUpdate,
    StoryStructureUpdate,
    TimelineUpdate,
)

__all__ = [
    "CharacterCreate",
    "CharacterPatch",
    "ChaptersUpdate",
    "EntryCreate",
    "EntryPatch",
    "FragmentClipboardImport",
    "FragmentCreate",
    "FragmentPatch",
    "FragmentToPlotRequest",
    "GraphUpdate",
    "MutationOutcome",
    "MutationRequest",
    "PlotCreate",
    "PlotOrderUpdate",
    "PlotPatch",
    "RelationshipCreate",
    "RelationshipPatch",
    "StoryStructureUpdate",
    "TimelineUpdate",
    "UndoRequest",
    "mutation_payload",
]
