from __future__ import annotations

from dataclasses import dataclass

from storyteller.application.characters import CharacterUseCases
from storyteller.application.entities import EntityUseCases
from storyteller.application.entries import EntryUseCases
from storyteller.application.fragments import FragmentUseCases
from storyteller.application.history import HistoryUseCases
from storyteller.application.mutations import (
    MutationExecutor,
    ProjectExporter,
    RagScheduler,
)
from storyteller.application.projects import ProjectProvider
from storyteller.application.plots import PlotUseCases
from storyteller.application.relationships import RelationshipUseCases
from storyteller.application.structures import StructureUseCases
from storyteller.settings import Settings


@dataclass(frozen=True, slots=True)
class StoryApplication:
    projects: ProjectProvider
    mutations: MutationExecutor
    fragments: FragmentUseCases
    characters: CharacterUseCases
    plots: PlotUseCases
    entries: EntryUseCases
    relationships: RelationshipUseCases
    structures: StructureUseCases
    entities: EntityUseCases
    history: HistoryUseCases

    @classmethod
    def create(
        cls,
        settings: Settings,
        rag_sync: RagScheduler,
        exporter: ProjectExporter | None = None,
    ) -> "StoryApplication":
        projects = ProjectProvider(settings)
        mutations = MutationExecutor(projects, rag_sync, exporter)
        return cls(
            projects=projects,
            mutations=mutations,
            fragments=FragmentUseCases(mutations),
            characters=CharacterUseCases(mutations),
            plots=PlotUseCases(mutations),
            entries=EntryUseCases(mutations),
            relationships=RelationshipUseCases(mutations),
            structures=StructureUseCases(mutations),
            entities=EntityUseCases(mutations),
            history=HistoryUseCases(mutations),
        )
