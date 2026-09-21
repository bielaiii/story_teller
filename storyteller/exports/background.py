from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from storyteller.exports.coordinator import ExportCoordinator
from storyteller.storage.connection import Database


@dataclass
class PendingExport:
    database: Database
    project_id: str
    deadline: float
    latest_start: float


class ExportScheduler:
    """Coalesce web saves; drain accepted jobs on normal server shutdown.

    SQLite's pending/failed export_state survives abrupt shutdown. Bootstrap
    repairs it before the next server start. CLI exports remain synchronous.
    """

    def __init__(self, *, delay_seconds: float = 0.5, max_delay_seconds: float = 5.0):
        self.delay = max(0.0, delay_seconds)
        self.max_delay = max(self.delay, max_delay_seconds)
        self.condition = threading.Condition()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="story-export")
        self.pending: dict[tuple[Path, str], PendingExport] = {}
        self.running = False
        self.closed = False

    def export(self, database: Database, project_id: str) -> dict:
        with self.condition:
            if self.closed:
                raise RuntimeError("导出服务已关闭")
            key = (database.path, project_id)
            now = time.monotonic()
            previous = self.pending.get(key)
            latest_start = previous.latest_start if previous else now + self.max_delay
            self.pending[key] = PendingExport(database, project_id, min(now + self.delay, latest_start), latest_start)
            if not self.running:
                self.running = True
                self.pool.submit(self._run)
            self.condition.notify_all()
        return {"status": "pending"}

    def _run(self) -> None:
        while True:
            with self.condition:
                if not self.pending:
                    self.running = False
                    self.condition.notify_all()
                    return
                key, job = min(self.pending.items(), key=lambda item: item[1].deadline)
                remaining = job.deadline - time.monotonic()
                if remaining > 0 and not self.closed:
                    self.condition.wait(remaining)
                    continue
                del self.pending[key]
            try:
                with job.database.read() as connection:
                    state = connection.execute(
                        "SELECT status, requested_revision, exported_revision FROM export_state WHERE project_id=?",
                        (job.project_id,),
                    ).fetchone()
                # A late mutation response may enqueue a revision already covered
                # by the preceding run. Explicit user exports remain unconditional.
                if not state or state["status"] != "ready" or state["requested_revision"] != state["exported_revision"]:
                    ExportCoordinator(job.database, job.project_id).export(incremental=True)
            except Exception:
                # Coordinator persists failures; another save, explicit export,
                # or startup retries them. Do not retry forever on a full disk.
                pass

    def close(self) -> None:
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.pool.shutdown(wait=True)
