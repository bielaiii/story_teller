from __future__ import annotations

from storyteller.application.context import ApplicationContext
from storyteller.application.mutations import MutationExecutor
from storyteller.contracts.common import UndoRequest
from storyteller.contracts.responses import MutationOutcome
from storyteller.domain.uow import UnitOfWork


class HistoryUseCases:
    def __init__(self, mutations: MutationExecutor):
        self.mutations = mutations

    def undo(
        self,
        context: ApplicationContext,
        command: UndoRequest,
    ) -> MutationOutcome:
        return self.mutations.execute(
            context,
            lambda database: UnitOfWork(database, context.project_id).undo(
                command.operation_id,
                command.base_revision,
            ),
        )
