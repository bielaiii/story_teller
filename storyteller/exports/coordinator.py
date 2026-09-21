from __future__ import annotations

import os
import shutil
import tempfile
import time
import threading
from contextlib import contextmanager
from pathlib import Path

from storyteller.exports.markdown import MarkdownExporter
from storyteller.exports import incremental as journal
from storyteller.domain.errors import ConflictError
from storyteller.exports.recovery import RECOVERY_FILE, render_recovery_snapshot
from storyteller.exports.static_snapshot import render_static_snapshot
from storyteller.storage.connection import Database, SnapshotDatabase


MANAGED_DIRECTORIES = ("characters", "plots", "entries", "fragments", "relationships", ".trash")
MANAGED_FILES = (
    "manifest.md", "timeline.md", "graph-layout.md", "content-index.json",
    "world-schema.json", "ai-manifest.json", "AI_CONTEXT.md",
    "project.snapshot.json", RECOVERY_FILE,
)


class ExportCoordinator:
    def __init__(self, database: Database, project_id: str):
        self.database = database
        self.project_id = project_id

    _guard = threading.Lock()
    _locks: dict[Path, threading.Lock] = {}

    def export(self, *, incremental: bool = False) -> dict[str, int | str | bool]:
        # All in-process entry points share publication order without holding the
        # mutation lock while rendering. WAL writers can continue saving.
        with self._guard:
            lock = self._locks.setdefault(self.database.path, threading.Lock())
        with lock, self._publication_lock():
            revision = 0
            try:
                with self.database.read() as connection:
                    project = connection.execute(
                        "SELECT revision FROM projects WHERE id=?", (self.project_id,)
                    ).fetchone()
                    if not project:
                        raise ValueError("项目不存在")
                    revision = int(project[0])
                    snapshot = SnapshotDatabase(self.database, connection)
                    index = journal.load_index(self.database.project_root, self.project_id, revision) if incremental else None
                    exporter = MarkdownExporter(snapshot, self.project_id)
                    if index is not None:
                        try:
                            current, dirty, details = journal.plan(snapshot, self.project_id, index)
                        except ConflictError:
                            index = None
                    if index is None:
                        exporter.snapshot_data = exporter.repository.snapshot()
                        files = exporter.render()
                        files["project.snapshot.json"] = render_static_snapshot(snapshot, self.project_id)
                        files[RECOVERY_FILE] = render_recovery_snapshot(snapshot, self.project_id)
                        journal.checkpoint(files, exporter.snapshot_data, exporter.entity_paths, self.project_id)
                        self._deleted_paths = None
                    else:
                        exporter.snapshot_data = current
                        exporter.entity_ids = dirty
                        files = exporter.render()
                        paths = {identifier: value for identifier, value in index["paths"].items() if identifier not in dirty}
                        paths.update(exporter.entity_paths)
                        owners = {}
                        for identifier, values in paths.items():
                            for path in values:
                                if path in owners and owners[path] != identifier:
                                    raise ValueError(f"导出文件名冲突：{path}")
                                owners[path] = identifier
                        previous = {path for values in index["paths"].values() for path in values}
                        self._deleted_paths = previous - set(owners)
                        journal.publish_patch(files, snapshot, self.project_id, index, current, details, paths)
                self._replace_exports(files)
            except Exception as error:
                self._record_state(revision, "failed", str(error))
                raise
            self._record_state(revision, "ready", "")
            return {"ok": True, "revision": revision, "fileCount": len(files), "status": "ready"}

    @contextmanager
    def _publication_lock(self):
        # A separate advisory lock serializes CLI and server processes without
        # blocking SQLite writers. Never unlink it: waiters share its inode.
        path = self.database.project_root / ".story-export.lock"
        with path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                while True:
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        time.sleep(0.05)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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
                    requested_revision=MAX(export_state.requested_revision, excluded.requested_revision),
                    exported_revision=CASE WHEN excluded.status='ready' THEN MAX(export_state.exported_revision, excluded.exported_revision) ELSE export_state.exported_revision END,
                    status=CASE WHEN export_state.requested_revision > excluded.requested_revision THEN export_state.status ELSE excluded.status END,
                    last_error=CASE WHEN export_state.requested_revision > excluded.requested_revision THEN export_state.last_error ELSE excluded.last_error END, updated_at=excluded.updated_at
                WHERE excluded.requested_revision >= export_state.exported_revision
                  AND NOT (excluded.status='failed' AND export_state.status='ready'
                           AND excluded.requested_revision <= export_state.exported_revision)
                """,
                (self.project_id, revision, revision if status == "ready" else 0, status, error[:2000], timestamp),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _managed_path(relative: str) -> bool:
        path = Path(relative)
        return (not path.is_absolute() and ".." not in path.parts and
                (relative in {*MANAGED_FILES, journal.INDEX_FILE}
                 or (len(path.parts) > 1 and path.parts[0] in {*MANAGED_DIRECTORIES, journal.DATA_DIRECTORY})))

    def _replace_exports(self, files: dict[str, bytes]) -> None:
        """Replace only changed files, retaining unrelated inodes and timestamps."""
        root = self.database.project_root
        staging = Path(tempfile.mkdtemp(prefix=".story-export-", dir=root))
        backup = staging / "previous"
        moved_targets = []
        installed_targets = []
        try:
            deleted = getattr(self, "_deleted_paths", None)
            if deleted is None:
                existing = {name for name in (*MANAGED_FILES, journal.INDEX_FILE) if (root / name).is_file()}
                for directory in (*MANAGED_DIRECTORIES, journal.DATA_DIRECTORY):
                    existing.update(str(path.relative_to(root)) for path in (root / directory).rglob("*") if path.is_file())
                # Keep the previous journal usable for readers already in flight.
                old_index = journal.load_index(root, self.project_id, 2**63 - 1, bounded=False)
                keep = set()
                if old_index:
                    keep.update([old_index["staticBase"], old_index["recoveryBase"], *[ref for pair in old_index["patches"] for ref in pair.values()]])
                deleted = existing - set(files) - keep
            changed = {}
            for relative, content in files.items():
                target = root / relative
                if not self._managed_path(relative):
                    raise ValueError("不是受管理的导出文件")
                if root.resolve() not in target.resolve().parents:
                    raise ValueError("导出文件路径越界")
                if target.is_file() and target.stat().st_size == len(content) and target.read_bytes() == content:
                    continue
                changed[relative] = content
                source = staging / "next" / relative
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(content)
            for relative in sorted(set(changed) | deleted):
                target = root / relative
                if not self._managed_path(relative):
                    raise ValueError("不是受管理的导出文件")
                if root.resolve() not in target.resolve().parents:
                    raise ValueError("导出文件路径越界")
                if target.exists():
                    previous = backup / relative
                    previous.parent.mkdir(parents=True, exist_ok=True)
                    # Leave the old target visible until its atomic replacement.
                    shutil.copy2(target, previous)
                    moved_targets.append((target, previous))
            for relative in sorted(changed, key=lambda name: (name == journal.INDEX_FILE, name in {"project.snapshot.json", RECOVERY_FILE}, name)):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging / "next" / relative, target)
                installed_targets.append(target)
            for relative in sorted(deleted):
                (root / relative).unlink(missing_ok=True)
        except Exception:
            for target in reversed(installed_targets):
                target.unlink(missing_ok=True)
            for target, previous in reversed(moved_targets):
                if previous.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(previous, target)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
