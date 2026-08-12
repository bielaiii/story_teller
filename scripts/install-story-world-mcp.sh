#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TARGET_DIR=${STORY_WORLD_MCP_BIN_DIR:-}
if [ -z "$TARGET_DIR" ]; then
  old_ifs=$IFS
  IFS=:
  for candidate in $PATH; do
    if [ -n "$candidate" ] && [ -d "$candidate" ] && [ -w "$candidate" ]; then
      TARGET_DIR=$candidate
      break
    fi
  done
  IFS=$old_ifs
fi
if [ -z "$TARGET_DIR" ]; then
  printf 'PATH 中没有可写安装目录；请通过 STORY_WORLD_MCP_BIN_DIR 指定。\n' >&2
  exit 1
fi
TARGET="$TARGET_DIR/story-world-mcp"

if [ ! -d "$TARGET_DIR" ] || [ ! -w "$TARGET_DIR" ]; then
  printf '安装目录不可写：%s\n可通过 STORY_WORLD_MCP_BIN_DIR 指定 PATH 中的可写目录。\n' "$TARGET_DIR" >&2
  exit 1
fi

if [ -e "$TARGET" ] && [ ! -L "$TARGET" ] && ! grep -q "Discover the nearest Story Teller workspace" "$TARGET" 2>/dev/null; then
  printf '拒绝覆盖非 Story Teller 程序：%s\n' "$TARGET" >&2
  exit 1
fi
if [ -L "$TARGET" ]; then
  unlink "$TARGET"
fi
install -m 755 "$ROOT/story-world-mcp" "$TARGET"
printf '已安装全局启动器：%s\n' "$TARGET"
