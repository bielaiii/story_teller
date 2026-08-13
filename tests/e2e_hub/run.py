from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[2]


def wait_until_ready(process: subprocess.Popen, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    with httpx.Client(timeout=1, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Hub E2E fixture 提前退出：{process.returncode}")
            try:
                response = client.get("http://127.0.0.1:4194/api/v1/contents")
                if response.status_code == 200:
                    workspaces = response.json().get("workspaces", [])
                    if len(workspaces) == 2 and all(
                        item.get("web", {}).get("running")
                        and item.get("mcp", {}).get("running")
                        for item in workspaces
                    ):
                        return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.1)
    raise RuntimeError("Hub E2E fixture 启动超时")


fixture = subprocess.Popen(
    [str(ROOT / "scripts" / "python.sh"), str(ROOT / "tests" / "e2e_hub" / "serve_fixture.py")],
    cwd=ROOT,
)
try:
    wait_until_ready(fixture)
    result = subprocess.run(
        [str(ROOT / "node_modules" / ".bin" / "playwright"), "test", "--config", "playwright.hub.config.js"],
        cwd=ROOT,
    )
    raise SystemExit(result.returncode)
finally:
    fixture.terminate()
    try:
        fixture.wait(timeout=15)
    except subprocess.TimeoutExpired:
        fixture.kill()
        fixture.wait()
