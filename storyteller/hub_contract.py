from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from storyteller import API_VERSION, SCHEMA_VERSION


WORKER_SERVICE = "story-teller-worker"
WORKER_PROTOCOL_MAJOR = 1
WORKER_PROTOCOL_MINOR = 0
WORKER_CAPABILITIES = (
    "project-prepare-v1",
    "web-proxy-v1",
    "world-mcp-v1",
    "project-create-v1",
)


def _git_diagnostics(root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--binary", "HEAD", "--"],
            check=True,
            capture_output=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "commit": "",
            "dirty": False,
            "runtimeIdentity": hashlib.sha256(str(root).encode()).hexdigest(),
            "diagnosticError": str(error),
        }
    identity = hashlib.sha256()
    identity.update(commit.encode())
    identity.update(b"\0")
    identity.update(status.encode())
    identity.update(b"\0")
    identity.update(diff)
    return {
        "commit": commit,
        "dirty": bool(status.strip()),
        "runtimeIdentity": identity.hexdigest(),
        "diagnosticError": "",
    }


def worker_manifest(root: Path | None = None) -> dict[str, Any]:
    framework_root = (root or Path(__file__).resolve().parents[1]).resolve()
    git = _git_diagnostics(framework_root)
    return {
        "service": WORKER_SERVICE,
        "protocolMajor": WORKER_PROTOCOL_MAJOR,
        "protocolMinor": WORKER_PROTOCOL_MINOR,
        "capabilities": list(WORKER_CAPABILITIES),
        "runtimeIdentity": git["runtimeIdentity"],
        "storyTellerCommit": git["commit"],
        "dirty": git["dirty"],
        "diagnosticError": git["diagnosticError"],
        "apiVersion": API_VERSION,
        "schemaVersion": SCHEMA_VERSION,
    }
