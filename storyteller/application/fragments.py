from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import mutation_payload
from storyteller.contracts.fragments import (
    FragmentClipboardImport,
    FragmentCreate,
    FragmentPatch,
    FragmentToPlotRequest,
)
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.content import ContentService


class FragmentUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def create(
        self,
        context: ApplicationContext,
        command: FragmentCreate,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).create_fragment(
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def update(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: FragmentPatch,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).update_fragment(
                entity_id,
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def import_clipboard(
        self,
        context: ApplicationContext,
        command: FragmentClipboardImport,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(
                database, context.project_id
            ).import_fragments_from_clipboard(
                command.base_revision,
                command.text,
            ),
        )

    def promote(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: FragmentToPlotRequest,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).move_fragment_to_plot(
                entity_id,
                command.base_revision,
                mutation_payload(command),
            ),
        )
