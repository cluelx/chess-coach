"""High precision matching for verified short mating combinations."""
from functools import lru_cache
from collections import defaultdict
import chess
from . import db, puzzles


def _core(b, move):
    after = b.copy(stack=False)
    after.push(move)
    king = after.king(chess.BLACK)
    zone = set(chess.SquareSet(chess.BB_KING_ATTACKS[king])) | {king}
    core = zone | {move.from_square, move.to_square}
    for sq in zone:
        for color in chess.COLORS:
            core.update(b.attackers(color, sq))
            core.update(after.attackers(color, sq))
    def pieces(board):
        return tuple((sq, str(board.piece_at(sq))) for sq in sorted(core) if board.piece_at(sq))
    return king, move.uci(), pieces(b), pieces(after)


def signature(board, line):
    if len(line) not in (1, 3, 5) or not board.is_valid() or board.castling_rights or board.ep_square is not None:
        return None
    b = board.copy(stack=False)
    if not b.turn:
        b = b.mirror()
        line = [chess.Move(chess.square_mirror(m.from_square), chess.square_mirror(m.to_square), promotion=m.promotion) for m in line]
    sig = []
    for i, move in enumerate(line):
        if move not in b.legal_moves:
            return None
        # Preserve the geometry and material roles of each move, including defenses.
        sig.append(_core(b, move))
        b.push(move)
    return tuple(sig) if b.is_checkmate() else None


def proves_mate(board, first, plies, budget=25000):
    """Check every legal defense, with a fixed first move and a finite node budget."""
    b = board.copy(stack=False)
    attacker = b.turn
    remaining = budget

    def visit(n):
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise TimeoutError()
        if b.is_checkmate():
            return b.turn != attacker
        if n == 0 or b.is_game_over():
            return False
        attacking = b.turn == attacker
        if not attacking and b.halfmove_clock >= 99 and b.can_claim_fifty_moves():
            return False
        moves = list(b.legal_moves)
        if attacking:
            moves.sort(key=lambda m: (b.gives_check(m), b.is_capture(m)), reverse=True)
        for move in moves:
            b.push(move)
            try:
                won = visit(n - 1)
            finally:
                b.pop()
            if won == attacking:
                return attacking
        return not attacking

    b.push(first)
    try:
        return visit(plies - 1)
    except TimeoutError:
        return False


@lru_cache(maxsize=3)
def index(plies=1):
    found = defaultdict(list)
    theme = "mateIn" + str((plies+1)//2)
    rows = db.query("SELECT p.* FROM puzzle p JOIN puzzle_theme t ON p.id=t.puzzle_id WHERE t.theme=? ORDER BY p.popularity DESC,p.id", (theme,))
    for row in rows:
        try:
            moves = row["moves"].split()
            b = chess.Board(row["fen"])
            b.push_uci(moves[0])
            line = [chess.Move.from_uci(m) for m in moves[1:]]
            key = signature(b, line) if len(line) == plies else None
            if key:
                found[key].append(puzzles.to_client(row))
        except (ValueError, IndexError):
            continue
    return found


def recommend(fen, uci, pv=None):
    board = chess.Board(fen)
    first = chess.Move.from_uci(uci)
    if first not in board.legal_moves:
        return []
    candidates = [first]
    if pv and pv[0] == uci:
        candidates = [chess.Move.from_uci(m) for m in pv[:5]]
    key = None
    for plies in (1, 3, 5):
        if len(candidates) >= plies:
            key = signature(board, candidates[:plies])
            if key:
                break
    if not key:
        return []
    matches = index(plies).get(key, [])
    if not matches or not proves_mate(board, first, plies):
        return []
    out = []
    normalize = lambda b: (b if b.turn else b.mirror()).board_fen()
    seen = {normalize(board)}
    for item in matches[:32]:
        b = chess.Board(item["fen"])
        b.push_uci(item["pre"])
        pos = normalize(b)
        if pos in seen or not proves_mate(b, chess.Move.from_uci(item["solution"][0]), plies):
            continue
        seen.add(pos)
        out.append(item)
        if len(out) == 2:
            break
    return out
