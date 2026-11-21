"""Regression check using saved experiment evidence; no engine or DB writes."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'vendor/binprop'))
from src import engine, move_explanation
import chess

spec = importlib.util.spec_from_file_location('review_runner', ROOT/'vendor/binprop/run_chess_review.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
library = runner.load_library(ROOT/'vendor/binprop/binary_properties/motifs/chess/claude-opus-5.json')
names = {m.source:m.name for m in library.motifs}


def ranked(samples, truths):
    payload = {'groups':samples,'start_limit':7,'followup':3}
    def evaluate(game, source, positions, **kwargs):
        return SimpleNamespace(values=[names[source] in truths[(p.board,p.color)] for p in positions])
    output = io.StringIO()
    with patch.object(sys, 'stdin', io.StringIO(json.dumps(payload))), patch.object(runner, 'evaluate_source', evaluate), contextlib.redirect_stdout(output):
        runner.main()
    return json.loads(output.getvalue())


def main():
    with sqlite3.connect((ROOT/'data/review-lab/cache.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        game = json.loads(db.execute('SELECT payload FROM games LIMIT 1').fetchone()[0])
        expected = {19:('strict',2,2),25:('branch_gap',2,2),39:('branch_gap',3,3),
                    49:('branch_gap',1,1),57:('strict',1,1),65:(None,0,0),67:('mainline',1,0)}
        for ply,(tier,count,visible) in expected.items():
            data = json.loads(db.execute('SELECT payload FROM results WHERE game=? AND ply=? AND depth=16', (game['id'],ply)).fetchone()[0])
            root = chess.Board(game['initial'])
            for m in game['moves'][:ply-1]:root.push_uci(m['uci'])
            groups, truths = {}, {}
            for side,first in [('positive',data['recommended']),('negative',data['played'])]:
                g = data['roots'][first]
                def row(lid):
                    line = g['lines'][lid]
                    path = [chess.Move.from_uci(u) for u in line['uci'][:20]]
                    item = engine._review_row(root,path)[1]
                    for fen, checkpoint in zip(item['checkpoints'],line['rounds']):
                        truths[(fen,item['color'])] = set(checkpoint['own'])
                    return item
                mainrow = row(g['schemes']['main'][0])
                score = None
                for key in g['lines'][g['schemes']['main'][0]]['searches']:
                    search = json.loads(db.execute('SELECT payload FROM searches WHERE id=?',(key,)).fetchone()[0])
                    if len(search['history'])==ply:
                        score=search['rows'][0];break
                mate = score['mate'] if score else None
                if mate is not None and not root.turn:mate=-mate
                exact = score and not score['lowerbound'] and not score['upperbound']
                groups[side]={'main':mainrow,'branches':[row(i) for i in g['schemes']['3x2']],
                              'forced_mate':bool(exact and mate is not None and mate>0),
                              'forced_loss':bool(exact and mate is not None and mate<0)}
            samples={s:g['branches'] for s,g in groups.items()}
            samples['main']=[groups['positive']['main'],groups['negative']['main']]
            raw = ranked(samples,truths)
            assert (raw['tier'],len(raw['motifs']))==(tier,count),(ply,raw['tier'],raw['motifs'])
            with patch.object(engine,'comparison_positions',return_value=groups), patch.object(engine,'extend_review_lines',return_value=False), patch.object(move_explanation,'_ranked_concepts',side_effect=lambda samples:ranked(samples,truths)):
                result=move_explanation.explain(root.fen(),data['recommended'],data['played'])
            assert len(result['motifs'])==visible,(ply,result)
            assert all(m['tier']==tier for m in result['motifs'])
            assert all(m['branches'] for m in result['motifs'])
            print(f'PASS ply={ply}: tier={tier}, raw={count}, visible={visible}')
    def candidate(name,strict=False,main=False,gap=False):
        return (main,0,0,dict(name=name,strict_qualified=strict,main_difference=main,gap_qualified=gap))
    tier, rows=runner.select_fallback([candidate('strict',strict=True),candidate('main',main=True),candidate('gap',gap=True)])
    assert tier=='strict' and [r['name'] for r in rows]==['strict']
    tier, rows=runner.select_fallback([candidate('main',main=True),candidate('gap',gap=True)])
    assert tier=='branch_gap' and [r['name'] for r in rows]==['gap']
    tier, rows=runner.select_fallback([candidate('main',main=True)])
    assert tier=='mainline' and [r['name'] for r in rows]==['main']
    assert runner._confirmed([True]*3,7,3,True)[0]==[]
    assert runner._confirmed([True]*4,7,3,True)[0]==[1]
    print('PASS tier precedence, four-round confirmation, evidence branches and mate suppression')


if __name__=='__main__':main()
