from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import mutation_payload
from storyteller.contracts.content import EntryCreate, EntryPatch
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.content import ContentService


class EntryUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def create(self, context: ApplicationContext, command: EntryCreate) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).create_entry(
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def update(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: EntryPatch,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).update_entry(
                entity_id,
                command.base_revision,
                mutation_payload(command),
            ),
        )
