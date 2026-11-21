"""Experimental pending-concept pruning; production runner is left untouched."""
from pathlib import Path
import sys

runner = Path(__file__).resolve().parents[1] / 'vendor/binprop/run_chess_review.py'
sys.path.insert(0, str(runner.parent))
source = runner.read_text(encoding='utf-8')
# A confirmed hit is monotonic under extension. An unresolved hit is not.
old = '''                if pending:
                    pending_rows[side].add(i)
'''
assert source.count(old) == 1
source = source.replace(old, '')
anchor = '        if (negatives and len(hits) >= 2'
assert source.count(anchor) == 1
source = source.replace(anchor, '''        possible_hits = sum(hit or pending for hit, pending in positives)
        viable = (bool(negatives) and missed * 4 <= len(negatives)
                  and possible_hits >= 2 and possible_hits * 2 >= len(positives))
        if viable:
            for side, verdict in verdicts.items():
                for index, (_, pending) in enumerate(verdict):
                    if pending:
                        pending_rows[side].add(index)
''' + anchor)
exec(compile(source, str(runner), 'exec'), {'__name__': '__main__', '__file__': str(runner)})
