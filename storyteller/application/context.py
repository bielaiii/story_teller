from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ApplicationContext:
    project_id: str
    source: Literal["web", "cli", "system"] = "web"
