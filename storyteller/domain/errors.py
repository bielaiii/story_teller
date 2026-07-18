class DomainError(ValueError):
    """User-visible domain validation error."""


class ConflictError(DomainError):
    """The mutation was based on an outdated revision."""


class NotFoundError(DomainError):
    """The requested entity does not exist in the requested state."""
