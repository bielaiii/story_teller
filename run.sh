#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORT=4180
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

stop_listener() {
  pid=$1
  cwd=$(process_cwd "$pid")
  name=$(process_name "$pid")
  trusted=false

  case "$name" in
    Python|python|python3) [ "$cwd" = "$ROOT" ] && trusted=true ;;
  esac

  if [ "$trusted" != true ]; then
    printf '端口 %s 正被其他程序占用：%s（PID %s）\n' "$PORT" "${name:-未知程序}" "$pid"
    if [ ! -t 0 ]; then
      printf '为避免误关其他程序，本次启动已取消。\n'
      exit 1
    fi
    printf '是否关闭这个程序并继续启动？[y/N] '
    read -r answer
    case "$answer" in
      y|Y|yes|YES) ;;
      *) printf '已取消启动。\n'; exit 1 ;;
    esac
  else
    printf '正在关闭本项目占用 %s 端口的旧服务（PID %s）…\n' "$PORT" "$pid"
  fi

  kill "$pid"
  attempts=0
  while listener_pids | grep -qx "$pid"; do
    attempts=$((attempts + 1))
    if [ "$attempts" -ge 30 ]; then
      printf '旧服务未能正常关闭，请稍后再试。\n'
      exit 1
    fi
    sleep 0.1
  done
}

for pid in $(listener_pids); do
  stop_listener "$pid"
done

cd "$ROOT"
"$ROOT/scripts/build_frontend.sh"

PROJECT=${DEFAULT_PROJECT:-demo}
PROJECT_ROOT="$CONTENT_ROOT/$PROJECT"
if [ ! -f "$PROJECT_ROOT/story.db" ]; then
  printf '找不到内容包数据库：%s\n' "$PROJECT_ROOT/story.db" >&2
  exit 1
fi
printf '正在检查内容包 %s…\n' "$PROJECT"
"$ROOT/scripts/python.sh" -m storyteller.bootstrap "$PROJECT_ROOT"

printf '正在启动 Story Teller：http://127.0.0.1:%s/\n' "$PORT"
exec "$ROOT/scripts/python.sh" -m storyteller \
  --bind 127.0.0.1 \
  --port "$PORT" \
  --content-root "$CONTENT_ROOT" \
  --frontend-root "$ROOT/dist" \
  --default-project "$DEFAULT_PROJECT"
