"""Compare explicit full export and ordinary incremental export on disposable data."""
import json
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from benchmark_mutation_cost import seed
from storyteller.domain.uow import UnitOfWork
from storyteller.exports.coordinator import ExportCoordinator


def run(root, count, blobs, incremental):
    db = seed(root, count, blobs, False)
    with db.write() as c:
        c.execute("UPDATE entities SET title=title||stable_id WHERE id LIKE 'fragment:bench%'")
    ExportCoordinator(db, 'demo').export()
    times, peaks, writes = [], [], []
    for i in range(3):
        with db.read() as c:
            revision = c.execute('SELECT revision FROM projects').fetchone()[0]
        UnitOfWork(db, 'demo').mutate(base_revision=revision, label='benchmark', action='update', entity_kind='plot',
            callback=lambda c: c.execute("UPDATE entities SET title=? WHERE id='plot:1'", (f'benchmark-{i}',)))
        previous = {p: (p.stat().st_ino, p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        tracemalloc.start()
        start = time.perf_counter()
        ExportCoordinator(db, 'demo').export(incremental=incremental)
        times.append(1000 * (time.perf_counter() - start))
        peaks.append(tracemalloc.get_traced_memory()[1] / 1024**2)
        tracemalloc.stop()
        writes.append(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()
                          and p.name not in {'story.db', 'story.db-wal', 'story.db-shm'}
                          and previous.get(p) != (p.stat().st_ino, p.stat().st_mtime_ns)))
    return {'median_ms': round(statistics.median(times), 2), 'peak_python_mib': round(max(peaks), 2),
            'median_replaced_bytes': int(statistics.median(writes))}


if __name__ == '__main__':
    for name, count, blobs in [('small', 0, 0), ('500_bodies', 500, 0), ('8MiB_asset', 0, 8), ('mixed', 500, 8)]:
        with tempfile.TemporaryDirectory(prefix='story-incremental-benchmark-') as temp:
            print(json.dumps({'scenario': name,
                'full': run(Path(temp) / 'full', count, blobs, False),
                'incremental': run(Path(temp) / 'incremental', count, blobs, True)}), flush=True)
