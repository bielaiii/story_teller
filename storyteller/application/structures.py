from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import mutation_payload
from storyteller.contracts.responses import MutationOutcome
from storyteller.contracts.structures import (
    ChaptersUpdate,
    GraphUpdate,
    PlotOrderUpdate,
    StoryStructureUpdate,
    TimelineUpdate,
)
from storyteller.domain.structure import StructureService


class StructureUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def update_chapters(
        self,
        context: ApplicationContext,
        command: ChaptersUpdate,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: StructureService(database, context.project_id).update_chapters(
                command.base_revision,
                [item.model_dump() for item in command.chapters],
            ),
        )

    def reorder_plots(
        self,
        context: ApplicationContext,
        command: PlotOrderUpdate,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: StructureService(database, context.project_id).reorder_plots(
                command.base_revision,
                command.plot_ids,
            ),
        )

    def update_story_structure(
        self,
        context: ApplicationContext,
        command: StoryStructureUpdate,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: StructureService(database, context.project_id).update_story_structure(
                command.base_revision,
                [item.model_dump() for item in command.chapters],
                [item.model_dump() for item in command.plots],
            ),
        )

    def update_timeline(
        self,
        context: ApplicationContext,
        command: TimelineUpdate,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: StructureService(database, context.project_id).update_timeline(
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def update_graph(
        self,
        context: ApplicationContext,
        command: GraphUpdate,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: StructureService(database, context.project_id).update_graph(
                command.base_revision,
                mutation_payload(command),
            ),
        )
