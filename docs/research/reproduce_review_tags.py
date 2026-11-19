"""Research-only reproduction; does not change application code or database."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import chess
import chess.engine
from src import engine
from src.review import analyze_move, _kp_guess

board = chess.Board('3q4/1Q6/3N2rk/6p1/2p5/6P1/1bP3PP/r4RK1 w - - 0 33')
result = {'source': 'Position reconstructed from user screenshot, not complete PGN',
          'fen': board.fen(), 'valid': board.is_valid(), 'depth': 18, 'multipv': 3}
with chess.engine.SimpleEngine.popen_uci(engine.find_binary()) as eng:
    result['engine'] = eng.id
    rows = eng.analyse(board, chess.engine.Limit(depth=18), multipv=3)
    result['variations'] = []
    for row in rows:
        probe = board.copy()
        line = []
        for move in row['pv'][:12]:
            line.append(probe.san(move))
            probe.push(move)
        result['variations'].append({'score_white': str(row['score'].white()),
                                     'pv_san': line, 'depth': row['depth']})
    best = rows[0]['pv'][0]
    result['best_move_san'] = board.san(best)
    result['current_rule_findings_for_engine_best_move'] = analyze_move(board, best, board.turn, 65)

# Deliberately synthetic valid position to isolate capture-before-mate ordering.
test_board = chess.Board('7k/7p/6KQ/8/8/8/8/8 w - - 0 1')
test_move = chess.Move.from_uci('h6h7')
result['capture_mate_order_test'] = {
    'fen': test_board.fen(), 'valid': test_board.is_valid(),
    'move': test_move.uci(), 'legal': test_move in test_board.legal_moves,
    'kp_guess': _kp_guess({'fen': test_board.fen(), 'best': {'uci': test_move.uci()}}),
}
test_board.push(test_move)
result['capture_mate_order_test']['checkmate'] = test_board.is_checkmate()
output = Path(__file__).with_name('review_tag_reproduction.json')
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(output)
print(json.dumps({'variations': result['variations'],
                  'motifs': [f['motif'] for f in result['current_rule_findings_for_engine_best_move']],
                  'capture_mate_order_test': result['capture_mate_order_test']}, ensure_ascii=True))
