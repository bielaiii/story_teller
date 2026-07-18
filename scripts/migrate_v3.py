#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from storyteller.storage.legacy import V3Migrator, migrate_database_atomic


def main() -> int:
    parser = argparse.ArgumentParser(description="将 Story Teller Schema V1/V2 一次性迁移到 V3")
    parser.add_argument("project_root", type=Path, help="内容包目录")
    parser.add_argument("--apply", action="store_true", help="校验通过后原子替换正式 story.db")
    parser.add_argument("--output", type=Path, help="仅校验时保留生成的 V3 数据库")
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    try:
        if args.apply:
            report = migrate_database_atomic(root)
        else:
            output = args.output or root / "story.v3-preview.db"
            output = output.expanduser().resolve()
            output.unlink(missing_ok=True)
            report = V3Migrator(root / "story.db", root.name).migrate_to(output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"迁移失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
