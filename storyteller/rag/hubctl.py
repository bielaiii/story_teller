from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from storyteller.rag.hub_app import HUB_SERVICE
from storyteller.rag.hub_registry import HUB_PROTOCOL_VERSION, default_hub_state_dir
from storyteller.settings import require_loopback


DEFAULT_PORT = 4181
HEALTH_PATH = "/api/v1/hub/health"
WORKSPACES_PATH = "/api/v1/hub/workspaces"


def _atomic_write(path: Path, value: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def ensure_token(state_dir: Path) -> str:
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    token_path = state_dir / "token"
    try:
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = token_path.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"Hub token 为空：{token_path}")
        return token
    token = secrets.token_urlsafe(32)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(token + "\n")
    return token


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def probe_hub(host: str, port: int) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            response = client.get(_base_url(host, port) + HEALTH_PATH)
            if response.status_code != 200:
                return None
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("service") != HUB_SERVICE:
        return None
    return payload


def _is_compatible_hub(payload: dict[str, Any]) -> bool:
    return (
        payload.get("ok") is True
        and int(payload.get("protocolVersion", 0)) == HUB_PROTOCOL_VERSION
        and payload.get("transport") == "streamable-http"
        and payload.get("mcp") == "/mcp/"
        and bool(str(payload.get("instanceId") or "").strip())
    )


def _log_tail(path: Path, limit: int = 4000) -> str:
    try:
        value = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return value[-limit:].strip()


def _spawn_detached(command: list[str], *, cwd: Path, environment: dict[str, str], log_path: Path) -> int:
    """Start a daemon without leaving it as a child of the web/deploy process."""
    helper = subprocess.run(
        [
            sys.executable, "-m", "storyteller.rag.hub_daemon",
            "--cwd", str(cwd), "--log", str(log_path), "--", *command,
        ],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=10,
    )
    if helper.returncode != 0:
        detail = helper.stderr.strip() or helper.stdout.strip()
        raise RuntimeError(f"无法创建 Story World Hub 后台进程{': ' + detail if detail else ''}")
    try:
        return int(helper.stdout.strip())
    except ValueError as error:
        raise RuntimeError("Hub 后台启动器没有返回有效 PID") from error


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def start_or_reuse_hub(
    *,
    host: str,
    port: int,
    state_dir: Path,
    framework_root: Path,
    timeout: float = 20.0,
) -> tuple[dict[str, Any], bool]:
    if _port_is_open(host, port):
        payload = probe_hub(host, port)
        if payload is None:
            raise RuntimeError(f"端口 {port} 已被非 Story World Hub 服务占用")
        if not _is_compatible_hub(payload):
            raise RuntimeError(
                f"端口 {port} 上的 Story World Hub 协议不兼容："
                f"{payload.get('protocolVersion')} != {HUB_PROTOCOL_VERSION}"
            )
        if payload.get("processId"):
            _atomic_write(state_dir / "hub.pid", f"{int(payload['processId'])}\n")
        return payload, False

    python_launcher = framework_root / "scripts" / "python.sh"
    if not python_launcher.is_file():
        raise RuntimeError(f"找不到 Python 启动器：{python_launcher}")
    ensure_token(state_dir)
    log_path = state_dir / "hub.log"
    command = [
        str(python_launcher), "-m", "storyteller.rag.hub",
        "--bind", host,
        "--port", str(port),
        "--state-dir", str(state_dir),
    ]
    environment = os.environ.copy()
    environment["STORY_WORLD_HUB_STATE_DIR"] = str(state_dir)
    daemon_pid = _spawn_detached(
        command, cwd=framework_root, environment=environment, log_path=log_path,
    )
    _atomic_write(state_dir / "hub.pid", f"{daemon_pid}\n")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = probe_hub(host, port)
        if payload is not None:
            if not _is_compatible_hub(payload):
                raise RuntimeError("刚启动的 Hub 协议版本不兼容")
            owner_pid = int(payload.get("processId") or daemon_pid)
            _atomic_write(state_dir / "hub.pid", f"{owner_pid}\n")
            return payload, True
        if not _pid_is_alive(daemon_pid):
            # A concurrent deployment may have won the bind race.
            payload = probe_hub(host, port)
            if payload is not None and _is_compatible_hub(payload):
                return payload, False
            detail = _log_tail(log_path)
            raise RuntimeError(f"Story World Hub 启动失败{': ' + detail if detail else ''}")
        time.sleep(0.1)

    if _port_is_open(host, port):
        raise RuntimeError(f"端口 {port} 已监听，但不是可识别的 Story World Hub")
    raise RuntimeError(f"Story World Hub 未能在 {timeout:g} 秒内启动；日志：{log_path}")


def register_workspace(
    *,
    host: str,
    port: int,
    token: str,
    repository_root: Path,
    content_root: Path,
    framework_root: Path,
    project: str,
    display_name: str,
    timeout: float = 120.0,
) -> dict[str, Any]:
    payload = {
        "repositoryRoot": str(repository_root.resolve()),
        "contentRoot": str(content_root.resolve()),
        "frameworkRoot": str(framework_root.resolve()),
        "project": project,
        "displayName": display_name,
    }
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                _base_url(host, port) + WORKSPACES_PATH,
                headers={"X-Story-World-Hub-Token": token},
                json=payload,
            )
    except httpx.HTTPError as error:
        raise RuntimeError(f"无法向 Story World Hub 注册工作区：{error}") from error
    if response.status_code != 200:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = response.text.strip()
        raise RuntimeError(f"Story World Hub 拒绝注册（HTTP {response.status_code}）：{detail}")
    result = response.json()
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Story World Hub 返回了无效的注册结果")
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动或复用 Story World Hub，并注册当前小说仓库")
    parser.add_argument("command", choices=("register", "status"), nargs="?", default="register")
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--state-dir", type=Path, default=default_hub_state_dir())
    parser.add_argument("--framework-root", type=Path, default=Path.cwd())
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--content-root", type=Path)
    parser.add_argument("--project", default="")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        host = require_loopback(args.bind)
        if not 1 <= args.port <= 65535:
            raise ValueError("端口不合法")
        state_dir = args.state_dir.expanduser().resolve()
        framework_root = args.framework_root.expanduser().resolve()
        token = ensure_token(state_dir)
        health, started = start_or_reuse_hub(
            host=host,
            port=args.port,
            state_dir=state_dir,
            framework_root=framework_root,
        )
        output: dict[str, Any] = {"hub": health, "started": started}
        if args.command == "register":
            if args.repository_root is None or args.content_root is None or not args.project:
                raise ValueError("register 需要 --repository-root、--content-root 和 --project")
            repository_root = args.repository_root.expanduser().resolve()
            output["registration"] = register_workspace(
                host=host,
                port=args.port,
                token=token,
                repository_root=repository_root,
                content_root=args.content_root.expanduser().resolve(),
                framework_root=framework_root,
                project=args.project,
                display_name=args.display_name.strip() or repository_root.name,
            )
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif args.command == "register":
            action = "已启动" if started else "已复用"
            workspace = output["registration"]["workspace"]
            print(f"{action} Story World Hub：{_base_url(host, args.port)}/mcp/")
            print(f"已注册工作区：{workspace['displayName']}（{workspace['workspaceId']}）")
        else:
            action = "已启动" if started else "运行中"
            print(f"Story World Hub {action}：{_base_url(host, args.port)}/mcp/")
        return 0
    except (OSError, RuntimeError, ValueError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
