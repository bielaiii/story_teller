from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def _lock_path(content_root: Path) -> Path:
    resolved = Path(content_root).expanduser().resolve()
    return resolved / ".story-content.lock"


class ContentDeploymentLock:
    """Keep exactly one writable Web process for a physical content root."""

    def __init__(self, content_root: Path):
        self.content_root = Path(content_root).expanduser().resolve()
        self.path = _lock_path(self.content_root)
        self._descriptor: int | None = None
        self._inherited = False

    def acquire(self) -> None:
        if self._descriptor is not None:
            return
        inherited = os.environ.get("STORY_TELLER_LOCK_FD", "")
        if inherited:
            descriptor = int(inherited)
            actual, expected = os.fstat(descriptor), self.path.stat()
            if (actual.st_dev, actual.st_ino) != (expected.st_dev, expected.st_ino):
                raise RuntimeError("Hub 所有权锁与 Content 不匹配")
            self._descriptor = os.dup(descriptor)
            self._inherited = True
            return
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            owner = self.owner()
            detail = f"（PID {owner.get('processId')}）" if owner.get("processId") else ""
            os.close(descriptor)
            raise RuntimeError(
                f"Content 已由另一个 Web 服务托管{detail}：{self.content_root}"
            ) from error
        payload = {
            "contentRoot": str(self.content_root),
            "processId": os.getpid(),
            "startedAt": int(time.time()),
        }
        os.ftruncate(descriptor, 0)
        os.write(descriptor, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        os.fsync(descriptor)
        self._descriptor = descriptor

    def owner(self) -> dict[str, Any]:
        try:
            raw = self.path.read_text(encoding="utf-8").strip()
            value = json.loads(raw) if raw else {}
        except (OSError, ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, None
        if descriptor is None:
            return
        try:
            if not self._inherited:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    def __enter__(self) -> "ContentDeploymentLock":
        self.acquire()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()
