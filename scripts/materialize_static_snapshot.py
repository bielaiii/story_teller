"""Create a standalone snapshot from either full or journal-based exports."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from storyteller.exports.coordinator import ExportCoordinator
from storyteller.exports.incremental import json_bytes, load_snapshot
from storyteller.storage.connection import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = args.project_root.resolve()
    coordinator = ExportCoordinator(Database(root), root.name)
    with coordinator._publication_lock():
        snapshot = load_snapshot(root / 'project.snapshot.json')
    args.output.write_bytes(json_bytes(snapshot))


if __name__ == '__main__':
    main()
