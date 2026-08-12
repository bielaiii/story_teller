#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORT=${STORY_WORLD_HUB_PORT:-${STORY_TELLER_RAG_PORT:-4181}}
CONTENT_ROOT=${STORY_TELLER_CONTENT_ROOT:-"$ROOT/content"}
DEFAULT_PROJECT=${STORY_TELLER_DEFAULT_PROJECT:-}

PROJECT=${DEFAULT_PROJECT:-demo}
PROJECT_ROOT="$CONTENT_ROOT/$PROJECT"
if [ ! -f "$PROJECT_ROOT/story.db" ]; then
  printf '找不到内容包数据库：%s\n' "$PROJECT_ROOT/story.db" >&2
  exit 1
fi

REPOSITORY_ROOT=$(git -C "$CONTENT_ROOT/.." rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$REPOSITORY_ROOT" ]; then
  printf 'content 必须位于 Git 仓库根目录下：%s\n' "$CONTENT_ROOT" >&2
  exit 1
fi

printf '正在启动或复用 Story World Hub，并从 %s 注册项目 worker…\n' "$PROJECT_ROOT/story.db"
cd "$ROOT"
exec "$ROOT/scripts/python.sh" -m storyteller.rag.hubctl register \
  --bind 127.0.0.1 \
  --port "$PORT" \
  --repository-root "$REPOSITORY_ROOT" \
  --content-root "$CONTENT_ROOT" \
  --framework-root "$ROOT" \
  --project "$PROJECT" \
  --display-name "$(basename "$REPOSITORY_ROOT")"
