"""Measure isolated synthetic title saves; never opens the user's content.

Run: ./scripts/python.sh scripts/benchmark_mutation_cost.py --baseline HEAD
Times include tracemalloc overhead. Baseline is read from Git, never checked out.
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from storyteller.domain.uow import UnitOfWork
from storyteller.exports.background import ExportScheduler
from storyteller.storage.connection import Database
from storyteller.storage.legacy import V3Migrator
from storyteller.storage.repositories import ProjectRepository


def baseline_class(ref, path, name):
    source = subprocess.check_output(['git', 'show', f'{ref}:{path}'], cwd=ROOT, text=True)
    module = types.ModuleType(f'benchmark_{name}')
    sys.modules[module.__name__] = module
    exec(compile(source, path, 'exec'), module.__dict__)
    return getattr(module, name)


def seed(root, count, blob_mb, trash):
    root.mkdir()
    shutil.copy2(ROOT / 'tests/fixtures/schema-v1-demo.db', root / 'legacy.db')
    V3Migrator(root / 'legacy.db', 'demo').migrate_to(root / 'story.db')
    db = Database(root)
    with db.write() as c:
        for i in range(count):
            key = f'fragment:bench{i}'
            c.execute('INSERT INTO entities(id, project_id, kind, stable_id, title, deleted_at, purge_at, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                      (key, 'demo', 'fragment', f'bench{i}', 'benchmark', 1 if trash else None, 9999999999 if trash else None, 0, 0))
            c.execute('INSERT INTO fragments(entity_id,body_markdown) VALUES(?,?)', (key, 'a' * 8192))
        if blob_mb:
            c.execute("INSERT INTO assets VALUES ('bench','demo',NULL,'bench.bin','application/octet-stream',?,'hash',0)", (b'x' * blob_mb * 1024 * 1024,))
    return db


def measure(db, uow_class, exporter, repeats):
    audit_ms, request_ms, peak_mb = [], [], []
    for i in range(repeats):
        with db.read() as c:
            revision = c.execute('SELECT revision FROM projects').fetchone()[0]
        tracemalloc.start()
        start = time.perf_counter()
        result = uow_class(db, 'demo').mutate(
            base_revision=revision, label='benchmark title', action='update', entity_kind='plot',
            callback=lambda c: c.execute("UPDATE entities SET title=? WHERE id='plot:1'", (f'title {i}',)),
        )
        audit_ms.append((time.perf_counter() - start) * 1000)
        ProjectRepository(db, 'demo').mutation_delta(result)
        exporter(db)
        request_ms.append((time.perf_counter() - start) * 1000)
        peak_mb.append(tracemalloc.get_traced_memory()[1] / 1024**2)
        tracemalloc.stop()
    return {'audit_ms': round(statistics.median(audit_ms), 2),
            'save_pipeline_ms': round(statistics.median(request_ms), 2),
            'python_peak_mb': round(max(peak_mb), 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', required=True)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    old_uow = baseline_class(args.baseline, 'storyteller/domain/uow.py', 'UnitOfWork')
    old_export = baseline_class(args.baseline, 'storyteller/exports/coordinator.py', 'ExportCoordinator')
    for name, count, blobs, trash in [('small', 0, 0, False), ('bodies', 500, 0, False), ('assets', 0, 32, False), ('trash', 500, 0, True), ('mixed', 500, 32, True)]:
        with tempfile.TemporaryDirectory(prefix='story-save-benchmark-') as temp:
            before = seed(Path(temp) / 'before', count, blobs, trash)
            after = seed(Path(temp) / 'after', count, blobs, trash)
            old = measure(before, old_uow, lambda db: old_export(db, 'demo').export(), args.repeats)
            scheduler = ExportScheduler(delay_seconds=60)
            try:
                new = measure(after, UnitOfWork, lambda db: scheduler.export(db, 'demo'), args.repeats)
            finally:
                scheduler.close()
            print(json.dumps({'scenario': name, 'added_rows': count, 'body_bytes_per_row': 8192, 'asset_mb': blobs, 'trash': trash, 'before': old, 'after': new}), flush=True)


if __name__ == '__main__':
    main()
