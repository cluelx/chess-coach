"""Audit saved lines against independent, full-history, per-ply search records."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chess
from scripts.review_lab import connection, result, snapshot


def audit():
    game = snapshot()
    with connection() as c:
        indexes = c.execute("SELECT ply,depth FROM results WHERE game=?", (game["id"],)).fetchall()
    lines = plies = 0
    for index in indexes:
        data = result(index["ply"], index["depth"])
        root = chess.Board(game["initial"])
        for move in game["moves"][:index["ply"] - 1]:
            root.push_uci(move["uci"])
        for first, group in data["roots"].items():
            for line_id, line in group["lines"].items():
                b = root.copy()
                prefix = line_id.split()
                assert line["uci"][:len(prefix)] == prefix
                assert len(line["uci"]) <= 24
                assert len(line["frames"]) == len(line["uci"]) + 1
                records = [data["searches"][key] for key in line["searches"]]
                for n, uci in enumerate(line["uci"]):
                    assert line["frames"][n] == b.fen()
                    assert b.san(chess.Move.from_uci(uci)) == line["san"][n]
                    if n:
                        history = [m.uci() for m in b.move_stack]
                        matches = [s for s in records if s["history"] == history
                                   and s["root"] == b.root().fen()
                                   and s["fen"] == b.fen()]
                        assert matches, (index["ply"], index["depth"], n, "missing independent search")
                        # Opponent choices inside the explicit prefix are sampled MultiPV moves.
                        sampled = n < len(prefix) and n % 2 == 1
                        matches = [s for s in matches if
                                   (any(r["uci"] == uci for r in s["rows"]) if sampled else
                                    s["multipv"] == 1 and s["rows"][0]["uci"] == uci)]
                        assert matches, (index["ply"], index["depth"], n, "not independently chosen")
                        for s in matches:
                            assert s["requested_depth"] == index["depth"] and s["cold"]
                            assert all(r["depth"] >= index["depth"] or r["mate"] is not None for r in s["rows"])
                        plies += 1
                    b.push_uci(uci)
                assert line["frames"][-1] == b.fen()
                assert len(line["rounds"]) == len(line["uci"]) // 2
                assert line["terminal"] == b.is_game_over()
                assert len(line["uci"]) == 24 or line["terminal"]
                assert line["uci"][0] == first
                lines += 1
            for scheme, ids in group["schemes"].items():
                assert all(i in group["lines"] for i in ids)
                assert len(ids) <= {"main": 1, "old8": 8, "3x2": 6, "5x3": 15}[scheme]
    print(json.dumps(dict(results=len(indexes), lines=lines, independently_verified_plies=plies, status="passed")))


if __name__ == "__main__":
    audit()
