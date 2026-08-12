from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storyteller.domain.world_schema import (  # noqa: E402
    STORAGE_REGISTRY_PATH,
    load_storage_registry,
    storage_registry_text,
    sync_storage_registry,
    validate_world_schema,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步并校验世界领域注册表")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument("--bootstrap", action="store_true", help="首次建立基线时将现有未映射字段标记为 internal")
    args = parser.parse_args()
    try:
        generated = sync_storage_registry(bootstrap=args.bootstrap)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.check:
        current = load_storage_registry()
        errors = validate_world_schema(current)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        print("世界领域注册表与 SQLite Schema 一致")
        return 0
    STORAGE_REGISTRY_PATH.write_text(storage_registry_text(generated), encoding="utf-8")
    errors = validate_world_schema(generated)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f"已更新 {STORAGE_REGISTRY_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
