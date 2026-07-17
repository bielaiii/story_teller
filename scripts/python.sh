#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VENV="$ROOT/.venv"
REQUIREMENTS="$ROOT/requirements.txt"
STAMP="$VENV/.requirements.sha256"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi

EXPECTED=$(python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$REQUIREMENTS")
ACTUAL=$([ -f "$STAMP" ] && sed -n '1p' "$STAMP" || true)
if [ "$EXPECTED" != "$ACTUAL" ]; then
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q -r "$REQUIREMENTS"
  "$VENV/bin/python" -c 'import pathlib, sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2] + "\n", encoding="utf-8")' "$STAMP" "$EXPECTED"
fi

exec "$VENV/bin/python" "$@"
