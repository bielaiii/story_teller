#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONTENT_ROOT=${STORY_TELLER_CONTENT_ROOT:-"$ROOT/content"}
DEFAULT_PROJECT=${STORY_TELLER_DEFAULT_PROJECT:-demo}
PROJECT_ROOT="$CONTENT_ROOT/$DEFAULT_PROJECT"

"$ROOT/scripts/build_frontend.sh"
"$ROOT/scripts/python.sh" -m storyteller.bootstrap "$PROJECT_ROOT"

cleanup() {
  if [ -n "${API_PID:-}" ]; then
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

"$ROOT/scripts/python.sh" -m storyteller \
  --bind 127.0.0.1 \
  --port 4180 \
  --content-root "$CONTENT_ROOT" \
  --frontend-root "$ROOT/dist" \
  --default-project "$DEFAULT_PROJECT" &
API_PID=$!

cd "$ROOT"
npm run dev
