from __future__ import annotations

import json
import os
import sys

from storyteller.hub_contract import worker_manifest


COMMAND_MODULES = {
    "prepare": "storyteller.bootstrap",
    "web": "storyteller",
    "mcp": "storyteller.rag.stdio",
}


def _exec_module(module: str, arguments: list[str]) -> None:
    if arguments[:1] == ["--"]:
        arguments = arguments[1:]
    os.execv(sys.executable, [sys.executable, "-m", module, *arguments])


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    arguments = sys.argv[2:]
    if command == "manifest":
        if arguments:
            print("manifest 不接受参数", file=sys.stderr)
            return 2
        print(json.dumps(worker_manifest(), ensure_ascii=False, separators=(",", ":")))
        return 0
    if command == "create-project":
        _exec_module("storyteller.bootstrap", [*arguments, "--create"])
        return 0
    module = COMMAND_MODULES.get(command)
    if module:
        _exec_module(module, arguments)
        return 0
    print(
        "用法：python -m storyteller.hub_worker "
        "{manifest|prepare|web|mcp|create-project} [参数...]",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
