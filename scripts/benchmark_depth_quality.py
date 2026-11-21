"""Compare cached D10/D16 recommendations with D19, then rescore candidates.

The D19 recommendation is a reference, not ground truth. All differing moves
in one position are rescored together in one D19 root-restricted MultiPV search.
"""
import json
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chess
import chess.engine
from src import engine


def main():
    with sqlite3.connect((ROOT/'data/review-lab/cache.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        game = json.loads(db.execute('SELECT payload FROM games LIMIT 1').fetchone()[0])
        records = {(p, d): json.loads(s) for p, d, s in db.execute('SELECT ply,depth,payload FROM results WHERE game=?', (game['id'],))}
    output = ROOT/'data/benchmarks'/('depth-quality-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.json')
    report = {'review_id':game['review_id'], 'reference_depth':19, 'rows':[],
              'mate_sentinel_note':'100000 marks a downgrade in searched mate status, not an actual centipawn loss. A non-mate score does not prove no forced mate exists.',
              'method':'Cached recommendations, full original history. Cold D19 MultiPV restricted to union of D10/D16/D19 moves. Loss relative to rescored D19 reference; D19 is not ground truth.'}
    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    eng = engine._get()
    if eng is None:
        raise RuntimeError('Stockfish unavailable')
    board = chess.Board(game['initial'])
    try:
        for move in game['moves']:
            ply = move['ply']
            chosen = {str(d):records[ply,d]['recommended'] for d in [10,16,19]}
            candidates = list(dict.fromkeys([chosen['19'],chosen['10'],chosen['16']]))
            row = {'ply':ply,'san':move['san'],'side':move['side'],'turning':move.get('turning',False),
                   'moves':chosen,'different':{d:chosen[d]!=chosen['19'] for d in ['10','16']}}
            if len(candidates)==1:
                row.update(loss_cp={'10':0,'16':0,'19':0},query_seconds=0)
            else:
                started = time.perf_counter()
                infos = eng.analyse(board, chess.engine.Limit(depth=19), multipv=len(candidates),
                    root_moves=[chess.Move.from_uci(x) for x in candidates], game=object())
                scores = {}
                for info in infos:
                    score = info['score'].pov(board.turn)
                    scores[info['pv'][0].uci()] = {'cp':score.score(),'mate':score.mate(),
                        'depth':info.get('depth'),'lowerbound':bool(info.get('lowerbound')),'upperbound':bool(info.get('upperbound'))}
                row.update(scores=scores,query_seconds=time.perf_counter()-started)
                ref = scores[chosen['19']]
                def loss(candidate):
                    s = scores[candidate]
                    if (s['lowerbound'] or s['upperbound'] or ref['lowerbound'] or ref['upperbound']
                        or (s['depth']<19 and s['mate'] is None) or (ref['depth']<19 and ref['mate'] is None)):
                        return None
                    if ref['mate'] is not None or s['mate'] is not None:
                        rsign = 0 if ref['mate'] is None else (1 if ref['mate']>0 else -1)
                        ssign = 0 if s['mate'] is None else (1 if s['mate']>0 else -1)
                        return 100000 if rsign>ssign else 0
                    return max(0,ref['cp']-s['cp'])
                row['loss_cp']={d:loss(chosen[d]) for d in ['10','16','19']}
            report['rows'].append(row)
            save()
            print(f'ply {ply}/70: different={row["different"]} loss_cp={row["loss_cp"]} {row["query_seconds"]:.2f}s',flush=True)
            board.push_uci(move['uci'])
        report['summary']={}
        for depth in ['10','16']:
            valid=[r for r in report['rows'] if r['loss_cp'][depth] is not None]
            report['summary'][depth]={'positions':len(report['rows']),'valid':len(valid),
                'different':sum(r['different'][depth] for r in report['rows']),
                'mate_downgrade':sum(r['loss_cp'][depth]==100000 for r in valid),
                'ordinary_loss_ge_50cp':sum(50<=r['loss_cp'][depth]<100000 for r in valid),
                **{f'loss_ge_{cutoff}cp':sum(r['loss_cp'][depth]>=cutoff for r in valid) for cutoff in [50,120,250]}}
        save()
    finally:
        engine._reset()
        print('REPORT',output,flush=True)


if __name__=='__main__':
    main()
