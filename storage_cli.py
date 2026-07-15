#!/usr/bin/env python3
"""Explicit maintenance commands for a Story Teller SQLite content package."""

import argparse
import shutil
import sqlite3
import time
from pathlib import Path

from sqlite_store import DATABASE_NAME, SQLiteProjectStore


def project_store(path):
    project_root = Path(path).expanduser().resolve()
    if not project_root.is_dir():
        raise ValueError(f"内容包不存在：{project_root}")
    return SQLiteProjectStore(project_root)


def status(store):
    store.initialize()
    info = store.info()
    with store.connect() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"database: {store.database_path}")
    print(f"schema: {info['schemaVersion']}")
    print(f"integrity: {integrity}")
    print(f"documents: {sum(info['counts'].values())}")
    print(f"last operation: {info['lastOperation'] or '-'}")


def export(store):
    if not store.database_path.is_file():
        raise ValueError(f"数据库不存在：{store.database_path}")
    store.initialize()
    store.materialize_exports(clean=True)
    print(f"已从 {DATABASE_NAME} 重新生成导出文件")


def import_exports(store, force):
    if store.database_path.exists() and not force:
        raise ValueError("数据库已经存在；恢复导入会覆盖它，如已确认请添加 --force")
    if store.database_path.exists():
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup = store.project_root.parent / f"{store.project_root.name}.story-{timestamp}.backup.db"
        shutil.copy2(store.database_path, backup)
        store.database_path.unlink()
        print(f"原数据库已备份到：{backup}")
    store.initialize()
    print(f"已从现有导出文件重建：{store.database_path}")


def main():
    parser = argparse.ArgumentParser(description="Story Teller SQLite 存储维护")
    parser.add_argument("project_root", help="内容包目录，例如 content/demo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status", help="检查数据库版本、完整性和记录数")
    subparsers.add_parser("export", help="从数据库重新生成 Markdown/JSON 导出")
    import_parser = subparsers.add_parser("import-exports", help="显式从导出文件重建数据库")
    import_parser.add_argument("--force", action="store_true", help="备份并替换已经存在的数据库")
    args = parser.parse_args()

    try:
        store = project_store(args.project_root)
        if args.command == "status":
            status(store)
        elif args.command == "export":
            export(store)
        else:
            import_exports(store, args.force)
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
