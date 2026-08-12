from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from storyteller.rag.manager import RagManager


@dataclass(slots=True)
class _ProjectSync:
    generation: int = 0
    requested_revision: int = 0
    timer: threading.Timer | None = None
    running: bool = False
    completed_runs: int = 0
    last_error: str = ""


class RagSyncScheduler:
    """Debounce post-commit RAG work without delaying mutation responses."""

    def __init__(self, manager: RagManager, *, delay_seconds: float = 0.5):
        self.manager = manager
        self.delay_seconds = max(0.0, float(delay_seconds))
        self._condition = threading.Condition(threading.RLock())
        self._projects: dict[str, _ProjectSync] = {}
        self._started = False
        self._closed = False

    def start(self, projects: list[str] | None = None) -> None:
        with self._condition:
            if self._closed:
                return
            self._started = True
        for project in projects or []:
            self.schedule(project, immediate=True)

    def schedule(
        self,
        project: str,
        revision: int | None = None,
        *,
        immediate: bool = False,
    ) -> bool:
        clean = str(project or "").strip()
        if not clean:
            return False
        with self._condition:
            if not self._started or self._closed:
                return False
            state = self._projects.setdefault(clean, _ProjectSync())
            state.generation += 1
            if revision is not None:
                state.requested_revision = max(state.requested_revision, int(revision))
            state.last_error = ""
            if state.running:
                return True
            if state.timer is not None:
                state.timer.cancel()
            self._arm(clean, state.generation, 0.0 if immediate else self.delay_seconds)
            return True

    def _arm(self, project: str, generation: int, delay: float) -> None:
        state = self._projects[project]
        timer = threading.Timer(delay, self._run, args=(project, generation))
        timer.daemon = True
        state.timer = timer
        timer.start()

    def _run(self, project: str, generation: int) -> None:
        with self._condition:
            state = self._projects.get(project)
            if self._closed or state is None or generation != state.generation:
                self._condition.notify_all()
                return
            state.timer = None
            state.running = True
        error = ""
        try:
            self.manager.ensure_fresh(project)
        except Exception as caught:
            # Query-time revision checking remains the retry path after transient failures.
            error = str(caught)
        finally:
            with self._condition:
                state = self._projects.get(project)
                if state is None:
                    return
                state.running = False
                state.completed_runs += 1
                state.last_error = error
                if not self._closed and state.generation != generation:
                    self._arm(project, state.generation, self.delay_seconds)
                self._condition.notify_all()

    def wait_for_idle(self, project: str = "", *, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while True:
                states = (
                    [self._projects[project]]
                    if project and project in self._projects
                    else list(self._projects.values())
                )
                if all(not state.running and state.timer is None for state in states):
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)

    def status(self, project: str) -> dict[str, Any]:
        with self._condition:
            state = self._projects.get(project, _ProjectSync())
            return {
                "started": self._started and not self._closed,
                "pending": state.timer is not None,
                "running": state.running,
                "requestedRevision": state.requested_revision,
                "completedRuns": state.completed_runs,
                "lastError": state.last_error,
            }

    def close(self, *, timeout: float = 10.0) -> None:
        with self._condition:
            self._closed = True
            for state in self._projects.values():
                if state.timer is not None:
                    state.timer.cancel()
                    state.timer = None
            self._condition.notify_all()
        self.wait_for_idle(timeout=timeout)
