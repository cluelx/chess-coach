"""Validate static witnesses against the original library and real board geometry."""
import io
import json
from pathlib import Path
import random
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
import chess.pgn
from src.review_features import inspect_static, namespace, DEFERRED, relation_text


def main():
    with sqlite3.connect("file:data/chess_coach.db?mode=ro", uri=True) as c:
        pgn = c.execute("SELECT pgn FROM review_detail ORDER BY review_id DESC LIMIT 1").fetchone()[0]
    game = chess.pgn.read_game(io.StringIO(pgn))
    board, positions = game.board(), [game.board().fen()]
    for move in game.mainline_moves():
        board.push(move)
        positions.append(board.fen())
    positions += ["4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1",
                  "k3r3/8/8/8/8/2b5/4N3/4K3 w - - 0 1", "4k3/8/8/8/2P5/2P5/2P5/4K3 w - - 0 1"]
    rng = random.Random(42)
    for _ in range(3):
        board = chess.Board()
        for ply in range(100):
            if board.is_game_over():
                break
            board.push(rng.choice(list(board.legal_moves)))
            if ply % 10 == 9:
                positions.append(board.fen())
    features = edges = pairs = 0
    for index, fen in enumerate(positions, 1):
        board = chess.Board(fen)
        payload = inspect_static(fen)
        assert len(payload["rules"]) == 30 and payload["supported_count"] == 21
        json.dumps(payload, allow_nan=False)
        for rule in payload["rules"]:
            number = rule["id"]
            if number in DEFERRED:
                assert rule["visualization_status"] == "deferred_moves" and rule["white"] is None and rule["black"] is None
                assert rule["matched"] == dict(white=None, black=None)
                continue
            assert rule["visualization_status"] == "ready"
            for color in (chess.WHITE, chess.BLACK):
                side = chess.COLOR_NAMES[color]
                probe = board.copy(stack=False)
                probe.turn = color
                assert rule["matched"][side] == namespace(number)["motif"](probe.fen())
                pairs += 1
                for feature in rule[side]["features"]:
                    assert feature["side"] == side
                    assert all(0 <= chess.parse_square(s) < 64 for s in feature["squares"])
                    for edge, text in zip(feature["relations"], feature["relation_text"]):
                        source, target = chess.parse_square(edge["source"]), chess.parse_square(edge["target"])
                        p, q = board.piece_at(source), board.piece_at(target)
                        assert p and target in board.attacks(source)
                        assert edge["side"] == chess.COLOR_NAMES[p.color] and edge["piece"] == chess.piece_name(p.piece_type)
                        assert edge["type"] == ("protect" if q and q.color == p.color else "attack" if q else "control")
                        assert relation_text(edge) == text
                        edges += 1
                    features += 1
        if index % 20 == 0:
            print(f"positions {index}/{len(positions)}; original rule-side checks {pairs}; features {features}; relations {edges}", flush=True)
    # The payload must be repeatable, including arrays, IDs, tie ordering and texts.
    fen = positions[43]
    first = json.dumps(inspect_static(fen), ensure_ascii=False)
    inspect_static.cache_clear()
    assert first == json.dumps(inspect_static(fen), ensure_ascii=False)
    print(f"PASS {len(positions)} positions; {pairs} rule-side checks; {features} features; {edges} relations; deterministic output")


if __name__ == "__main__":
    main()
