from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import mutation_payload
from storyteller.contracts.content import CharacterCreate, CharacterPatch
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.content import ContentService


class CharacterUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def create(self, context: ApplicationContext, command: CharacterCreate) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).create_character(
                command.base_revision,
                mutation_payload(command),
            ),
        )

    def update(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: CharacterPatch,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: ContentService(database, context.project_id).update_character(
                entity_id,
                command.base_revision,
                mutation_payload(command),
            ),
        )
