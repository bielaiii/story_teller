from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import MutationRequest
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.services import EntityService


class EntityUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def delete(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: MutationRequest,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: EntityService(database, context.project_id).delete(
                entity_id,
                command.base_revision,
            ),
        )

    def restore(
        self,
        context: ApplicationContext,
        entity_id: str,
        command: MutationRequest,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: EntityService(database, context.project_id).restore(
                entity_id,
                command.base_revision,
            ),
        )
