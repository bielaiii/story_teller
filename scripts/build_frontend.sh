#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
STATE_ROOT="$ROOT/.story-teller"
STAMP="$STATE_ROOT/package-lock.sha256"

if ! command -v npm >/dev/null 2>&1; then
  printf '缺少 Node.js/npm，无法构建 Story Teller 前端。\n' >&2
  exit 1
fi

mkdir -p "$STATE_ROOT"
EXPECTED=$(python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$ROOT/package-lock.json")
ACTUAL=$([ -f "$STAMP" ] && sed -n '1p' "$STAMP" || true)
if [ ! -d "$ROOT/node_modules" ] || [ "$EXPECTED" != "$ACTUAL" ]; then
  printf '正在准备 Story Teller 前端依赖…\n'
  (cd "$ROOT" && npm ci --no-audit --no-fund)
  python3 -c 'import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2] + "\n", encoding="utf-8")' "$STAMP" "$EXPECTED"
fi

printf '正在构建 Story Teller 前端…\n'
(cd "$ROOT" && npm run build --silent)
