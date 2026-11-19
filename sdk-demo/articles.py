"""Extract playable boards from article data without executing page scripts."""
import io
import json
import re
from urllib.parse import urlsplit

import chess
import chess.pgn

from materials import FEN, position


def pgn_steps(pgn, fen=None):
    if fen and not re.search(r'^\s*\[FEN\s+"', pgn, re.M):
        pgn = f'[SetUp "1"]\n[FEN "{fen}"]\n{pgn}'
    try:
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game is None or game.errors:
            return None, []
        board = game.board()
        if not board.is_valid() or (fen and board.fen() != fen):
            return None, []
        start = board.fen()
        steps = []
        for move in game.mainline_moves():
            if move not in board.legal_moves:
                return None, []
            san = board.san(move)
            board.push(move)
            steps.append({"san": san, "fen": board.fen()})
        return start, steps
    except ValueError:
        return None, []


def source_steps(fen, rows):
    board = chess.Board(fen)
    moves = []
    for row in rows:
        try:
            move = board.parse_san(row["san"])
            if move not in board.legal_moves:
                return []
            san = board.san(move)
            board.push(move)
            if board.fen() != position(row["fen"]):
                return []
        except (KeyError, TypeError, ValueError, AttributeError):
            return []
        moves.append({"san": san, "fen": board.fen()})
    return moves


def a1_boards(url, soup):
    parts = urlsplit(url)
    path = parts.path.strip("/").split("/")
    if parts.hostname not in {"a1learner.com", "www.a1learner.com"} or len(path) != 3 or path[0] != "learn":
        return []
    state = soup.select_one('script#ng-state[type="application/json"]')
    if state is None:
        return []
    try:
        modules = json.loads(state.get_text()).get(f"a1learner-course:{path[1]}", [])
        lesson = next((lesson for module in modules for lesson in module["lessons"]
                       if lesson["slug"] == path[2]), None)
    except (TypeError, ValueError, KeyError, AttributeError):
        return []
    boards = []
    for snippet in (lesson or {}).get("snippets", []):
        if not isinstance(snippet, dict):
            continue
        fen = position(snippet.get("code", ""))
        stepper = snippet.get("stepper") or {}
        if not isinstance(stepper, dict):
            stepper = {}
        pgn = stepper.get("pgn")
        rows = stepper.get("steps")
        moves = []
        if isinstance(pgn, str) and (not fen or not rows):
            start, moves = pgn_steps(pgn, fen)
            fen = fen or start
        if fen and rows:
            moves = source_steps(fen, rows) if isinstance(rows, list) else []
        if fen:
            boards.append({"heading": snippet.get("heading", ""),
                           "text": snippet.get("text", "")[:1600], "fen": fen, "moves": moves})
    return boards


def article_boards(article):
    boards = []
    for node in article.select("[data-pgn], pre, textarea")[:30]:
        explicit = node.get("data-pgn")
        pgn = explicit or node.get_text()
        if not explicit and not re.search(r'^\s*\[\w+\s+"', pgn, re.M):
            continue
        owner = node if node.has_attr("data-fen") else node.find_parent(attrs={"data-fen": True})
        fen = position(owner["data-fen"]) if owner else None
        section = node.find_parent("section")
        heading = section.find(["h2", "h3", "h4"]) if section else None
        if not fen and section and not re.search(r'^\s*\[FEN\s+"', pgn, re.M):
            positions = set(FEN.findall(section.get_text(" ", strip=True)))
            if len(positions) == 1:
                fen = position(positions.pop())
        start, moves = pgn_steps(pgn, fen)
        if moves:
            boards.append({"heading": heading.get_text(" ", strip=True) if heading else "",
                           "text": section.get_text(" ", strip=True)[:1600] if section else "",
                           "fen": start, "moves": moves})
    return boards
