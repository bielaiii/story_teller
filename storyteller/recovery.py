from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from storyteller.exports.recovery import RecoveryImporter


def main() -> int:
    parser = argparse.ArgumentParser(description="从 Story Teller 恢复快照重建 Schema V3 数据库")
    parser.add_argument("source", type=Path, help="包含 recovery.snapshot.json 的导出目录或快照文件")
    parser.add_argument("target", type=Path, help="要创建的 story.db")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    try:
        result = RecoveryImporter(args.source, args.project).import_to(args.target)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"恢复失败：{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
