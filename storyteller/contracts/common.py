from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MutationRequest(BaseModel):
    """Revision preconditions shared by every persisted mutation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    base_revision: int = Field(alias="baseRevision", ge=0)
    entity_revision: int | None = Field(default=None, alias="entityRevision", ge=0)


class UndoRequest(MutationRequest):
    operation_id: int = Field(alias="operationId", gt=0)


def mutation_payload(model: MutationRequest) -> dict[str, Any]:
    """Return domain-facing snake_case fields without the project revision."""

    return model.model_dump(exclude={"base_revision"}, exclude_unset=True)
