"""Profile real Decode in an isolated process; read experiment data without writing it.

Example: python scripts/benchmark_decode.py --ply 19 --depths 16 19
Stage durations are disjoint. Engine call totals are a breakdown inside stages,
so must not be added to stage durations. No HTTP server or production DB needed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import engine, move_explanation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ply', type=int, default=19)
    parser.add_argument('--depths', type=int, nargs='+', default=[16, 19])
    parser.add_argument('--warm', action='store_true', help='Also repeat each depth with in-process search cache')
    parser.add_argument('--prune', action='store_true', help='Experimental concept pruning in isolated runner only')
    args = parser.parse_args()
    if args.prune:
        move_explanation._RUNNER = ROOT / 'scripts/benchmark_pruning_runner.py'
    if not all(10 <= d <= 19 for d in args.depths):
        parser.error('depths must be between 10 and 19')
    with sqlite3.connect((ROOT / 'data/review-lab/cache.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
        game = json.loads(db.execute('SELECT payload FROM games LIMIT 1').fetchone()[0])
        records = {}
        for depth in args.depths:
            row = db.execute('SELECT payload FROM results WHERE game=? AND ply=? AND depth=?',
                             (game['id'], args.ply, depth)).fetchone()
            if row is None:
                parser.error(f'no experiment record at ply={args.ply}, depth={depth}')
            records[depth] = json.loads(row[0])
    move = game['moves'][args.ply - 1]
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    output = ROOT / 'data/benchmarks' / f'decode-{stamp}'
    output.mkdir(parents=True, exist_ok=False)
    report = {'game_id': game['id'], 'review_id': game['review_id'], 'ply': args.ply,
              'san': move['san'], 'engine': engine.info(),
              'engine_sha256': hashlib.sha256(Path(engine.find_binary()).read_bytes()).hexdigest(),
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in [ROOT/'src/engine.py', ROOT/'src/move_explanation.py',
                                          ROOT/'vendor/binprop/run_chess_review.py']},
              'note': 'One isolated engine. Timings exclude startup and choosing root recommendation. No production DB writes.',
              'experimental_pruning': args.prune, 'runs': []}

    def save():
        (output / 'timings.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    originals = {name: getattr(engine, name) for name in ['comparison_positions', 'extend_review_lines']}
    original_rank = move_explanation._ranked_concepts
    try:
        for depth in args.depths:
            engine._reset()  # Separate engine and empty process cache for each cold run.
            eng = engine._get()
            if eng is None:
                raise RuntimeError('Stockfish unavailable')
            original_analyse = eng.analyse
            for warm in ([False, True] if args.warm else [False]):
                row = {'depth': depth, 'warm_search_cache': warm, 'stages': [], 'searches': []}
                report['runs'].append(row)
                stage = ['other']

                def search(*a, **kw):
                    start = time.perf_counter()
                    try:
                        result = original_analyse(*a, **kw)
                        return result
                    finally:
                        row['searches'].append({'stage': stage[0], 'multipv': kw.get('multipv', 1),
                                                'seconds': time.perf_counter() - start})

                eng.analyse = search

                def wrap(name, fn):
                    def run(*a, **kw):
                        before = stage[0]
                        stage[0] = name
                        start = time.perf_counter()
                        print(f'D{depth} warm={warm}: {name} started', flush=True)
                        try:
                            result = fn(*a, **kw)
                            if name == 'concepts':
                                row.setdefault('concept_passes', []).append({
                                    'evaluated': result.get('evaluated'),
                                    'selected': len(result.get('motifs', [])),
                                    'pending': {k: len(v) for k, v in result.get('pending', {}).items()}})
                            return result
                        finally:
                            elapsed = time.perf_counter() - start
                            row['stages'].append({'name': name, 'seconds': elapsed})
                            stage[0] = before
                            print(f'D{depth}: {name} {elapsed:.3f}s; engine calls={len(row["searches"])}', flush=True)
                            save()
                    return run

                for name, fn in originals.items():
                    setattr(engine, name, wrap(name, fn))
                move_explanation._ranked_concepts = wrap('concepts', original_rank)
                save()
                start = time.perf_counter()
                try:
                    result = move_explanation.explain(move['fen'], records[depth]['recommended'], move['uci'],
                        initial=game['initial'], history=[m['uci'] for m in game['moves'][:args.ply-1]], depth=depth)
                    row.update(status=result.get('status'), motifs=[m['text'] for m in result.get('motifs', [])])
                    (output / f'result-d{depth}-warm{int(warm)}.json').write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                except Exception as exc:
                    row['error'] = repr(exc)
                    raise
                finally:
                    row['total_seconds'] = time.perf_counter() - start
                    row['engine_seconds'] = sum(x['seconds'] for x in row['searches'])
                    row['calls_by_multipv'] = dict(Counter(x['multipv'] for x in row['searches']))
                    save()
                    print(f'D{depth} COMPLETE {row["total_seconds"]:.3f}s; engine={row["engine_seconds"]:.3f}s', flush=True)
    finally:
        for name, fn in originals.items():
            setattr(engine, name, fn)
        move_explanation._ranked_concepts = original_rank
        engine._reset()
        save()
        print(f'REPORT {output / "timings.json"}', flush=True)


if __name__ == '__main__':
    main()
