from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import MutationRequest, mutation_payload
from storyteller.contracts.content import PlotCreate, PlotPatch
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.content import ContentService


class PlotUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def create(self, context: ApplicationContext, command: PlotCreate) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).create_plot(
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def update(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: PlotPatch,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).update_plot(
                entity_id,
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def move_to_fragment(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: MutationRequest,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).move_plot_to_fragment(
                entity_id,
                command.base_revision,
            ),
        )
