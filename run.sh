#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HUB_PORT=${STORY_WORLD_HUB_PORT:-4181}
WEB_PORT=${STORY_TELLER_WEB_PORT:-4180}
CONTENT_ROOT=${STORY_TELLER_CONTENT_ROOT:-"$ROOT/content"}
DEFAULT_PROJECT=${STORY_TELLER_DEFAULT_PROJECT:-}
PROJECT=$DEFAULT_PROJECT

if [ -z "$PROJECT" ] && [ -f "$CONTENT_ROOT/demo/story.db" ]; then
  PROJECT=demo
fi
if [ -z "$PROJECT" ]; then
  for candidate in "$CONTENT_ROOT"/*; do
    if [ -d "$candidate" ] && [ -f "$candidate/story.db" ]; then
      PROJECT=$(basename "$candidate")
      break
    fi
  done
fi
if [ -z "$PROJECT" ]; then
  printf 'content 下没有可部署的 Project：%s\n' "$CONTENT_ROOT" >&2
  exit 1
fi
PROJECT_ROOT="$CONTENT_ROOT/$PROJECT"

if [ ! -f "$PROJECT_ROOT/story.db" ]; then
  printf '找不到默认内容包数据库：%s\n' "$PROJECT_ROOT/story.db" >&2
  exit 1
fi

cd "$ROOT"
"$ROOT/scripts/build_frontend.sh"

# Project 检查由 Hub 分别执行；单个损坏或版本不兼容的 Project 不应拖垮整个 Content。

REPOSITORY_ROOT=$(git -C "$CONTENT_ROOT" rev-parse --show-toplevel 2>/dev/null || true)
if [ -z "$REPOSITORY_ROOT" ]; then
  printf 'content 必须位于 Git 仓库内：%s\n' "$CONTENT_ROOT" >&2
  exit 1
fi

printf '正在注册 Content，并启动统一 Web / MCP Hub…\n'
exec "$ROOT/scripts/python.sh" -m storyteller.rag.hubctl attach \
  --bind 127.0.0.1 \
  --port "$HUB_PORT" \
  --web-port "$WEB_PORT" \
  --repository-root "$REPOSITORY_ROOT" \
  --content-root "$CONTENT_ROOT" \
  --framework-root "$ROOT" \
  --project "$PROJECT" \
  --display-name "$(basename "$REPOSITORY_ROOT")"
