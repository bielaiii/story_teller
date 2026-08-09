#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORT=${STORY_TELLER_RAG_PORT:-4181}
CONTENT_ROOT=${STORY_TELLER_CONTENT_ROOT:-"$ROOT/content"}
DEFAULT_PROJECT=${STORY_TELLER_DEFAULT_PROJECT:-}

listener_pids() {
  lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
}

process_cwd() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

process_name() {
  lsof -a -p "$1" -iTCP:"$PORT" -sTCP:LISTEN -Fc 2>/dev/null | sed -n 's/^c//p' | head -n 1
}

for pid in $(listener_pids); do
  cwd=$(process_cwd "$pid")
  name=$(process_name "$pid")
  if [ "$cwd" != "$ROOT" ] || { [ "$name" != "Python" ] && [ "$name" != "python" ] && [ "$name" != "python3" ]; }; then
    printf '端口 %s 正被其他程序占用：%s（PID %s）\n' "$PORT" "${name:-未知程序}" "$pid" >&2
    exit 1
  fi
  printf '正在关闭旧 RAG 服务（PID %s）…\n' "$pid"
  kill "$pid"
  attempts=0
  while listener_pids | grep -qx "$pid"; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 30 ]; then
      printf '旧 RAG 服务未能正常关闭。\n' >&2
      exit 1
    fi
    sleep 0.1
  done
done

PROJECT=${DEFAULT_PROJECT:-demo}
PROJECT_ROOT="$CONTENT_ROOT/$PROJECT"
if [ ! -f "$PROJECT_ROOT/story.db" ]; then
  printf '找不到内容包数据库：%s\n' "$PROJECT_ROOT/story.db" >&2
  exit 1
fi

printf '正在从 %s 同步一次 RAG 索引…\n' "$PROJECT_ROOT/story.db"
cd "$ROOT"
exec "$ROOT/scripts/python.sh" -m storyteller.rag \
  --bind 127.0.0.1 \
  --port "$PORT" \
  --content-root "$CONTENT_ROOT" \
  --default-project "$DEFAULT_PROJECT"
