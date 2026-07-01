#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PORT=4180

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
printf '正在启动 Story Teller：http://127.0.0.1:%s/\n' "$PORT"
exec python3 server.py --bind 127.0.0.1 --port "$PORT"
