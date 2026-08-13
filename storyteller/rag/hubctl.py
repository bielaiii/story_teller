from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
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
from storyteller.web_hub_app import WEB_HUB_PROTOCOL_VERSION, WEB_HUB_SERVICE


DEFAULT_PORT = 4181
DEFAULT_WEB_PORT = 4180
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


def _owned_hub_process(pid: int, state_dir: Path) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    arguments = [item.decode("utf-8", errors="replace") for item in raw.split(b"\0") if item]
    if "storyteller.rag.hub" not in arguments:
        return False
    try:
        index = arguments.index("--state-dir")
        configured = Path(arguments[index + 1]).expanduser().resolve()
    except (ValueError, IndexError):
        return False
    return configured == state_dir.resolve()


def _owned_web_hub_process(pid: int, state_dir: Path) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    arguments = [item.decode("utf-8", errors="replace") for item in raw.split(b"\0") if item]
    if "storyteller.web_hub" not in arguments:
        return False
    try:
        index = arguments.index("--state-dir")
        configured = Path(arguments[index + 1]).expanduser().resolve()
    except (ValueError, IndexError):
        return False
    return configured == state_dir.resolve()


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
            process_id = int(payload.get("processId") or 0)
            remote_version = int(payload.get("protocolVersion") or 0)
            if remote_version >= HUB_PROTOCOL_VERSION or not _owned_hub_process(process_id, state_dir):
                raise RuntimeError(
                    f"端口 {port} 上的 Story World Hub 协议不兼容："
                    f"{remote_version} != {HUB_PROTOCOL_VERSION}"
                )
            os.kill(process_id, signal.SIGTERM)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and _port_is_open(host, port):
                time.sleep(0.1)
            if _port_is_open(host, port):
                raise RuntimeError("旧版 Story World Hub 未能正常退出")
        else:
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


def _authorized_request(
    method: str,
    *,
    host: str,
    port: int,
    token: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.request(
                method,
                _base_url(host, port) + path,
                headers={"X-Story-World-Hub-Token": token},
                json=payload,
            )
    except httpx.HTTPError as error:
        raise RuntimeError(f"Story World Hub 请求失败：{error}") from error
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = response.text.strip()
        raise RuntimeError(f"Story World Hub 请求失败（HTTP {response.status_code}）：{detail}")
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Story World Hub 返回了无效结果")
    return result


def set_independent_mcp(*, host: str, port: int, token: str, workspace_id: str, enabled: bool) -> dict[str, Any]:
    return _authorized_request(
        "PUT", host=host, port=port, token=token,
        path=f"{WORKSPACES_PATH}/{workspace_id}/mcp-independent",
        payload={"enabled": enabled}, timeout=120,
    )


def acquire_web_lease(*, host: str, port: int, token: str, workspace_id: str) -> dict[str, Any]:
    return _authorized_request(
        "POST", host=host, port=port, token=token,
        path=f"{WORKSPACES_PATH}/{workspace_id}/web-leases", timeout=120,
    )


def heartbeat_web_lease(*, host: str, port: int, token: str, workspace_id: str, lease: str) -> dict[str, Any]:
    return _authorized_request(
        "PUT", host=host, port=port, token=token,
        path=f"{WORKSPACES_PATH}/{workspace_id}/web-leases/{lease}", timeout=120,
    )


def release_web_lease(*, host: str, port: int, token: str, workspace_id: str, lease: str) -> None:
    _authorized_request(
        "DELETE", host=host, port=port, token=token,
        path=f"{WORKSPACES_PATH}/{workspace_id}/web-leases/{lease}", timeout=30,
    )


def workspace_status(*, host: str, port: int, token: str, workspace_id: str) -> dict[str, Any]:
    result = _authorized_request(
        "GET", host=host, port=port, token=token, path=WORKSPACES_PATH,
    )
    for workspace in result.get("workspaces", []):
        if workspace.get("workspaceId") == workspace_id:
            return workspace
    raise RuntimeError(f"Story World Hub 中没有 Content：{workspace_id}")


def probe_web_hub(host: str, port: int) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=1.0, trust_env=False) as client:
            response = client.get(_base_url(host, port) + "/api/v1/health")
            if response.status_code != 200:
                return None
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("service") != WEB_HUB_SERVICE:
        return None
    return payload


def start_or_reuse_web_hub(
    *,
    host: str,
    port: int,
    hub_port: int,
    state_dir: Path,
    framework_root: Path,
    timeout: float = 20,
) -> tuple[dict[str, Any], bool]:
    if _port_is_open(host, port):
        payload = probe_web_hub(host, port)
        if payload is None:
            raise RuntimeError(f"端口 {port} 已被非 Story Teller Web Hub 服务占用")
        remote_version = int(payload.get("protocolVersion", 0))
        if remote_version != WEB_HUB_PROTOCOL_VERSION:
            process_id = int(payload.get("processId") or 0)
            if not process_id:
                try:
                    process_id = int((state_dir / "web-hub.pid").read_text(encoding="utf-8").strip())
                except (OSError, ValueError):
                    process_id = 0
            if (
                remote_version >= WEB_HUB_PROTOCOL_VERSION
                or not _owned_web_hub_process(process_id, state_dir)
            ):
                raise RuntimeError(
                    f"Story Teller Web Hub 协议不兼容："
                    f"{remote_version} != {WEB_HUB_PROTOCOL_VERSION}"
                )
            os.kill(process_id, signal.SIGTERM)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and _port_is_open(host, port):
                time.sleep(0.1)
            if _port_is_open(host, port):
                raise RuntimeError("旧版 Story Teller Web Hub 未能正常退出")
        else:
            return payload, False
    launcher = framework_root / "scripts" / "python.sh"
    log_path = state_dir / "web-hub.log"
    daemon_pid = _spawn_detached(
        [
            str(launcher), "-m", "storyteller.web_hub",
            "--bind", host,
            "--port", str(port),
            "--hub-port", str(hub_port),
            "--state-dir", str(state_dir),
        ],
        cwd=framework_root,
        environment=os.environ.copy(),
        log_path=log_path,
    )
    _atomic_write(state_dir / "web-hub.pid", f"{daemon_pid}\n")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = probe_web_hub(host, port)
        if payload is not None:
            return payload, True
        if not _pid_is_alive(daemon_pid):
            detail = _log_tail(log_path)
            raise RuntimeError(f"Story Teller Web Hub 启动失败{': ' + detail if detail else ''}")
        time.sleep(0.1)
    raise RuntimeError(f"Story Teller Web Hub 未能在 {timeout:g} 秒内启动；日志：{log_path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理 Story Teller Content 与 MCP 生命周期")
    parser.add_argument(
        "command",
        choices=("attach", "mcp-start", "mcp-stop", "mcp-status", "register", "status"),
        nargs="?",
        default="attach",
    )
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT)
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
        if args.command in {"attach", "mcp-start", "mcp-stop", "mcp-status", "register"}:
            if args.repository_root is None or args.content_root is None or not args.project:
                raise ValueError(f"{args.command} 需要 --repository-root、--content-root 和 --project")
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
            workspace = output["registration"]["workspace"]
            workspace_id = workspace["workspaceId"]
            if args.command in {"mcp-start", "register"}:
                output["runtime"] = set_independent_mcp(
                    host=host, port=args.port, token=token,
                    workspace_id=workspace_id, enabled=True,
                )
            elif args.command == "mcp-stop":
                output["runtime"] = set_independent_mcp(
                    host=host, port=args.port, token=token,
                    workspace_id=workspace_id, enabled=False,
                )
            elif args.command == "mcp-status":
                output["runtime"] = workspace_status(
                    host=host, port=args.port, token=token, workspace_id=workspace_id,
                )
            elif args.command == "attach":
                start_or_reuse_web_hub(
                    host=host, port=args.web_port, hub_port=args.port,
                    state_dir=state_dir, framework_root=framework_root,
                )
                acquired = acquire_web_lease(
                    host=host, port=args.port, token=token, workspace_id=workspace_id,
                )
                lease = str(acquired["lease"])
                hub_instance_id = str(health.get("instanceId") or "")
                print(f"Story Teller Hub：http://{host}:{args.web_port}/")
                print(f"当前 Content：http://{host}:{args.web_port}/w/{workspace_id}/?project={args.project}")
                print("MCP 正在跟随当前 Web Content 运行；按 Ctrl+C 停止。")
                try:
                    while True:
                        time.sleep(5)
                        start_or_reuse_web_hub(
                            host=host, port=args.web_port, hub_port=args.port,
                            state_dir=state_dir, framework_root=framework_root,
                        )
                        try:
                            heartbeat_web_lease(
                                host=host, port=args.port, token=token,
                                workspace_id=workspace_id, lease=lease,
                            )
                            continue
                        except RuntimeError as error:
                            current, _restarted = start_or_reuse_hub(
                                host=host, port=args.port, state_dir=state_dir,
                                framework_root=framework_root,
                            )
                            if str(current.get("instanceId") or "") == hub_instance_id:
                                print(f"Content 已由 Hub 停止：{error}")
                                break
                            refreshed = register_workspace(
                                host=host, port=args.port, token=token,
                                repository_root=repository_root,
                                content_root=args.content_root.expanduser().resolve(),
                                framework_root=framework_root,
                                project=args.project,
                                display_name=args.display_name.strip() or repository_root.name,
                            )["workspace"]
                            workspace_id = refreshed["workspaceId"]
                            acquired = acquire_web_lease(
                                host=host, port=args.port, token=token, workspace_id=workspace_id,
                            )
                            lease = str(acquired["lease"])
                            hub_instance_id = str(current.get("instanceId") or "")
                            print("Story World Hub 已恢复，Content 与 MCP 已重新连接。")
                except KeyboardInterrupt:
                    pass
                finally:
                    try:
                        release_web_lease(
                            host=host, port=args.port, token=token,
                            workspace_id=workspace_id, lease=lease,
                        )
                    except RuntimeError:
                        pass
                return 0
        if args.json:
            print(json.dumps(output, ensure_ascii=False, indent=2))
        elif args.command in {"mcp-start", "register"}:
            action = "已启动" if started else "已复用"
            workspace = output["registration"]["workspace"]
            print(f"{action} Story World Hub：{_base_url(host, args.port)}/mcp/")
            print(f"MCP 已独立启动：{workspace['displayName']}（{workspace['workspaceId']}）")
        elif args.command == "mcp-stop":
            workspace = output["registration"]["workspace"]
            still_running = bool(output["runtime"]["workspace"]["mcp"]["running"])
            suffix = "；Web 仍在线，因此 MCP 继续跟随" if still_running else ""
            print(f"MCP 已关闭独立运行：{workspace['displayName']}{suffix}")
        elif args.command == "mcp-status":
            workspace = output["runtime"]
            print(
                f"{workspace['displayName']}：Web "
                f"{'运行中' if workspace['web']['running'] else '已停止'}；MCP "
                f"{'运行中' if workspace['mcp']['running'] else '已停止'}（"
                f"{'独立运行' if workspace['mcp']['mode'] == 'independent' else '跟随 Web'}）"
            )
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
