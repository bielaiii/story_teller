#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$ROOT/scripts/python.sh" "$ROOT/scripts/sync_world_schema.py" "$@"
