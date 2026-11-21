"""Check observer equivalence and diagram geometry for all 30 original rules."""
import io
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
import chess.pgn
from src.review_evidence import inspect_rule, library


def main():
    with sqlite3.connect("file:data/chess_coach.db?mode=ro", uri=True) as c:
        pgn = c.execute("SELECT pgn FROM review_detail ORDER BY review_id DESC LIMIT 1").fetchone()[0]
    game = chess.pgn.read_game(io.StringIO(pgn))
    b, positions = game.board(), [game.board().fen()]
    for ply, move in enumerate(game.mainline_moves(), 1):
        b.push(move)
        if ply in (19, 29, 43, 57, 66, 70):
            positions.append(b.fen())
    positions += ["4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
                  "1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1",
                  "k3r3/8/8/8/8/2b5/4N3/4K3 w - - 0 1"]
    checks = queries = maximum = omitted = 0
    for n, fen in enumerate(positions, 1):
        assert chess.Board(fen).is_valid()
        for rule in library():
            for color in ("white", "black"):
                result = inspect_rule(fen, color, rule["name"])
                assert result["consistent"]
                maximum = max(maximum, len(result["records"]))
                omitted += result["omitted"]
                for record in result["records"]:
                    board = chess.Board(record["fen"])
                    if record["kind"] == "attackers":
                        actual = board.attackers(record["color"] == "white", chess.parse_square(record["target"]), record["occupied"])
                        assert [chess.square_name(s) for s in actual] == record["sources"]
                        queries += 1
                    elif record["kind"] == "coverage":
                        actual = board.attacks(chess.parse_square(record["source"]))
                        assert [chess.square_name(s) for s in actual] == record["targets"]
                        queries += 1
                c = result["captures"]
                assert c["difference"] == c["own"]["best"] - c["opponent"]["best"]
                for key in ("own", "opponent"):
                    for capture in c[key]["candidates"]:
                        assert capture["gain"] == capture["backed"][0]
                        before = chess.Board(capture["fen"])
                        assert chess.Move.from_uci(capture["uci"]) in before.legal_moves
                checks += 1
        inspect_rule.cache_clear()
        print(f"positions {n}/{len(positions)}, rule-perspectives {checks}, geometry queries {queries}", flush=True)
    print(f"PASS: {checks} original/observed pairs; {queries} geometry checks; max records {maximum}; omitted {omitted}")


if __name__ == "__main__":
    main()
