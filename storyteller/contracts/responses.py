from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OperationResult(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: int | None = None
    can_undo: bool = Field(default=False, alias="canUndo")
    expires_at: int | None = Field(default=None, alias="expiresAt")


class ExportResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    revision: int | None = None
    skipped: bool | None = None


class RagResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    revision: int | None = None


class MutationOutcome(BaseModel):
    """Stable mutation response returned by HTTP and future local adapters."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    ok: bool = True
    from_revision: int = Field(alias="fromRevision")
    project_revision: int = Field(alias="projectRevision")
    changed: dict[str, list[dict[str, Any]]] = {}
    removed: dict[str, list[str]] = {}
    structures: dict[str, Any] = {}
    operation: OperationResult
    export: ExportResult
    # Legacy no-op deltas omit ``rag`` entirely; keep that wire shape while still
    # documenting the field in OpenAPI for mutations that schedule a rebuild.
    rag: RagResult | None = Field(default=None, exclude_if=lambda value: value is None)
    warnings: list[str] = []
