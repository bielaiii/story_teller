"""Independent bounded background work; never reads article bodies on save."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from storyteller.backups import Backups
from storyteller.domain.merge_conflicts import has_open_merge
from storyteller.exports.reading import ReadingCopies

log = logging.getLogger(__name__)


class ProjectMaintenance:
    def __init__(self, provider, *, interval=60):
        self.provider = provider
        self.interval = interval
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reading-backup")
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.jobs = {}
        self.errors = {}
        self.projects = []
        self.thread = None

    def start(self, projects):
        self.projects = list(projects)
        self.thread = threading.Thread(target=self._loop, name="reading-schedule", daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            for project in self.projects:
                self.submit(project, "automatic")
            self.stop.wait(self.interval)

    def submit(self, project, kind):
        key = (project, kind)
        with self.lock:
            job = self.jobs.get(key)
            if job and not job.done():
                return {"status": "pending"}
            self.errors.pop(key, None)
            self.jobs[key] = self.pool.submit(self._run, project, kind)
        return {"status": "pending"}

    def _run(self, project, kind):
        try:
            database = self.provider.open(project)
            if has_open_merge(database, project):
                raise ValueError("请先解决数据库合并冲突")
            failures = []
            if kind in {"automatic", "reading"}:
                try:
                    ReadingCopies(database, project).generate(force=kind == "reading")
                except Exception as error:
                    failures.append("Markdown：" + str(error))
            if kind in {"automatic", "backup"}:
                try:
                    backups = Backups(database, project)
                    if kind == "backup" or backups.due():
                        backups.create("manual" if kind == "backup" else "daily")
                except Exception as error:
                    failures.append("备份：" + str(error))
            if failures:
                raise RuntimeError("；".join(failures))
        except Exception as error:
            with self.lock:
                self.errors[(project, kind)] = str(error)
            log.warning("项目后台任务失败 %s %s: %s", project, kind, error)

    def status(self, project):
        database = self.provider.open(project)
        with self.lock:
            pending = [kind for (p, kind), job in self.jobs.items() if p == project and not job.done()]
            errors = {kind: error for (p, kind), error in self.errors.items() if p == project}
        return {"reading": ReadingCopies(database, project).status(),
                "backups": Backups(database, project).status(), "pending": pending, "errors": errors}

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
            for project in self.projects:
                self.submit(project, "automatic")
        self.pool.shutdown(wait=True)
