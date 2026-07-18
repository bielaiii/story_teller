from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from storyteller.exports.markdown import MarkdownExporter
from storyteller.exports.recovery import RECOVERY_FILE, render_recovery_snapshot
from storyteller.exports.static_snapshot import render_static_snapshot
from storyteller.storage.connection import Database


MANAGED_DIRECTORIES = ("characters", "plots", "entries", "fragments", "relationships", ".trash")
MANAGED_FILES = ("manifest.md", "timeline.md", "graph-layout.md", "content-index.json", "project.snapshot.json", RECOVERY_FILE)


class ExportCoordinator:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id

    def export(self) -> dict[str, int | str | bool]:
        with self.database.read() as connection:
            project = connection.execute(
                "SELECT revision FROM projects WHERE id=?", (self.project_id,)
            ).fetchone()
            if not project:
                raise ValueError("项目不存在")
            revision = int(project[0])
        files = MarkdownExporter(self.database, self.project_id).render()
        files["project.snapshot.json"] = render_static_snapshot(self.database, self.project_id)
        files[RECOVERY_FILE] = render_recovery_snapshot(self.database, self.project_id)
        try:
            self._replace_exports(files)
        except Exception as error:
            self._record_state(revision, "failed", str(error))
            raise
        self._record_state(revision, "ready", "")
        return {"ok": True, "revision": revision, "fileCount": len(files), "status": "ready"}

    def _record_state(self, revision: int, status: str, error: str) -> None:
        timestamp = int(time.time())
        connection = self.database.connect()
        try:
            self.database.require_v3(connection)
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO export_state(project_id, requested_revision, exported_revision, status, last_error, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    requested_revision=excluded.requested_revision,
                    exported_revision=CASE WHEN excluded.status='ready' THEN excluded.exported_revision ELSE export_state.exported_revision END,
                    status=excluded.status, last_error=excluded.last_error, updated_at=excluded.updated_at
                """,
                (self.project_id, revision, revision if status == "ready" else 0, status, error[:2000], timestamp),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _replace_exports(self, files: dict[str, bytes]) -> None:
        root = self.database.project_root
        staging = Path(tempfile.mkdtemp(prefix=".story-export-", dir=root))
        backup = staging / "previous"
        backup.mkdir()
        moved_targets: list[tuple[Path, Path]] = []
        installed_targets: list[Path] = []
        try:
            for relative, content in sorted(files.items()):
                target = staging / "next" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            targets = [root / name for name in (*MANAGED_DIRECTORIES, *MANAGED_FILES)]
            for target in targets:
                if not target.exists():
                    continue
                previous = backup / target.name
                os.replace(target, previous)
                moved_targets.append((target, previous))
            for name in MANAGED_DIRECTORIES:
                source = staging / "next" / name
                if source.exists():
                    target = root / name
                    os.replace(source, target)
                    installed_targets.append(target)
            for name in MANAGED_FILES:
                source = staging / "next" / name
                if source.exists():
                    target = root / name
                    os.replace(source, target)
                    installed_targets.append(target)
        except Exception:
            for target in reversed(installed_targets):
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                else:
                    target.unlink(missing_ok=True)
            for target, previous in reversed(moved_targets):
                if previous.exists():
                    os.replace(previous, target)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
