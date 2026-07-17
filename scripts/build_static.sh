#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PROJECT_ROOT=${1:?用法: ./scripts/build_static.sh <content/project> [output]}
OUTPUT=${2:-"$PROJECT_ROOT/static-site"}
STAGING="$OUTPUT.tmp.$$"
BACKUP="$OUTPUT.previous.$$"

"$ROOT/scripts/python.sh" -m storyteller.bootstrap "$PROJECT_ROOT"
"$ROOT/scripts/build_frontend.sh"

rm -rf "$STAGING" "$BACKUP"
mkdir -p "$STAGING"
cp -R "$ROOT/dist/." "$STAGING/"
cp "$PROJECT_ROOT/project.snapshot.json" "$STAGING/project.snapshot.json"

if [ -e "$OUTPUT" ]; then
  mv "$OUTPUT" "$BACKUP"
fi
if mv "$STAGING" "$OUTPUT"; then
  rm -rf "$BACKUP"
else
  rm -rf "$STAGING"
  if [ -e "$BACKUP" ]; then mv "$BACKUP" "$OUTPUT"; fi
  exit 1
fi

printf '静态只读站点已生成：%s\n' "$OUTPUT"
