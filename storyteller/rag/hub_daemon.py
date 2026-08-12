from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def spawn(command: list[str], *, cwd: Path, log_path: Path) -> int:
    if not command:
        raise ValueError("缺少 Hub 启动命令")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    read_descriptor, write_descriptor = os.pipe()
    first_pid = os.fork()
    if first_pid == 0:
        try:
            os.close(read_descriptor)
            os.setsid()
            daemon_pid = os.fork()
            if daemon_pid > 0:
                os.write(write_descriptor, str(daemon_pid).encode("ascii"))
                os._exit(0)
            null_descriptor = os.open(os.devnull, os.O_RDONLY)
            os.dup2(null_descriptor, 0)
            os.dup2(log_descriptor, 1)
            os.dup2(log_descriptor, 2)
            for descriptor in (null_descriptor, log_descriptor, write_descriptor):
                if descriptor > 2:
                    os.close(descriptor)
            os.chdir(cwd)
            os.execve(command[0], command, os.environ.copy())
        except BaseException:
            os._exit(127)

    os.close(write_descriptor)
    os.close(log_descriptor)
    try:
        raw_pid = os.read(read_descriptor, 64)
    finally:
        os.close(read_descriptor)
        os.waitpid(first_pid, 0)
    if not raw_pid:
        raise RuntimeError("无法创建 Story World Hub 后台进程")
    return int(raw_pid.decode("ascii"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Story World Hub detached process helper")
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    print(spawn(command, cwd=args.cwd.resolve(), log_path=args.log.resolve()))


if __name__ == "__main__":
    main()
