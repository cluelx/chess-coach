"""确定性战术检测器。

全部基于 python-chess 的规则推理，不调用任何模型、不需要引擎。
原则：宁可漏报，不可误报——复盘的信任度完全取决于误报率。

关键取舍：判断“送子”时不做单步吃子估值，而是算“对方吃 — 我回吃”两步之后的
真实子力差，这样正常的兑子不会被误判成失误。
"""

from __future__ import annotations

import chess

VAL = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

PIECE_CN = {
    chess.PAWN: "兵",
    chess.KNIGHT: "马",
    chess.BISHOP: "象",
    chess.ROOK: "车",
    chess.QUEEN: "后",
    chess.KING: "王",
}


def value(piece: chess.Piece | None) -> int:
    if piece is None:
        return 0
    return VAL.get(piece.piece_type, 0)


def sq_name(sq: int) -> str:
    return chess.square_name(sq)


def balance(board: chess.Board, color: bool) -> int:
    """从 color 视角的子力差。"""
    s = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p is None:
            continue
        s += value(p) if p.color == color else -value(p)
    return s


def capture_gain_on_square(board: chess.Board, sq: int, depth: int) -> int:
    """只在这个格子上继续交换，返回当前走子方最多能赚多少。"""
    if depth <= 0 or board.piece_at(sq) is None:
        return 0
    best = 0
    for m in [mv for mv in board.legal_moves if mv.to_square == sq]:
        taken = value(board.piece_at(sq))
        board.push(m)
        rest = capture_gain_on_square(board, sq, depth - 1)
        board.pop()
        gain = taken - rest
        if gain > best:
            best = gain
    return best


def best_capture_gain(board: chess.Board, depth: int = 3) -> tuple[int, chess.Move | None]:
    """board.turn 一方通过一串强制吃子最多能净赚多少。"""
    best, best_move = 0, None
    for m in list(board.legal_moves):
        if board.piece_at(m.to_square) is None:
            continue
        taken = value(board.piece_at(m.to_square))
        board.push(m)
        rest = capture_gain_on_square(board, m.to_square, depth - 1)
        board.pop()
        gain = taken - rest
        if gain > best:
            best, best_move = gain, m
    return best, best_move


def worst_capture_delta(board: chess.Board, color: bool) -> tuple[int, chess.Move | None]:
    """board.turn 是对方。返回 color 一方在这串强制吃子里的净损失（负数）与对方的吃子。"""
    gain, mv = best_capture_gain(board, depth=3)
    return -gain, mv


def mate_in_1(board: chess.Board) -> chess.Move | None:
    for move in board.legal_moves:
        board.push(move)
        try:
            if board.is_checkmate():
                return move
        finally:
            board.pop()
    return None


def fork_targets_after(board: chess.Board, move: chess.Move) -> list[dict]:
    """走完这一手之后，落子同时攻击到的、真正值钱的目标。"""
    if board.piece_at(move.from_square) is None:
        return []
    board.push(move)
    try:
        targets = []
        for sq in board.attacks(move.to_square):
            tgt = board.piece_at(sq)
            if tgt is None:
                continue
            mover = board.piece_at(move.to_square)
            if mover is None or tgt.color == mover.color:
                continue
            if tgt.piece_type == chess.KING:
                targets.append({"square": sq_name(sq), "piece": "王", "weight": 900})
                continue
            if value(tgt) < 300:
                continue
            defenders = board.attackers(tgt.color, sq)
            if defenders:
                cheapest = min(value(board.piece_at(d)) for d in defenders)
                if cheapest <= value(mover):
                    continue  # 被更便宜的子守着，不算叉子目标
            targets.append(
                {"square": sq_name(sq), "piece": PIECE_CN.get(tgt.piece_type, "子"), "weight": value(tgt)}
            )
        return targets
    finally:
        board.pop()


def is_safe_move(board: chess.Board, move: chess.Move) -> bool:
    """走完之后不会立刻被白吃。"""
    board.push(move)
    try:
        delta, _ = worst_capture_delta(board, not board.turn)
    finally:
        board.pop()
    return delta > -150


def safe_fork_move(board: chess.Board, min_total: int = 900) -> chess.Move | None:
    best = None
    best_score = 0
    for move in board.legal_moves:
        targets = fork_targets_after(board, move)
        if len(targets) < 2:
            continue
        score = sum(t["weight"] for t in targets)
        if score < min_total:
            continue
        piece = board.piece_at(move.to_square)
        if piece is not None and piece.piece_type == chess.KING:
            continue
        if not is_safe_move(board, move):
            continue
        if score > best_score:
            best_score = score
            best = move
    return best


def has_mate_threat(board: chess.Board) -> bool:
    return mate_in_1(board) is not None


def back_rank_exposed(board: chess.Board, color: bool) -> bool:
    """王在底排、身前 f/g/h 至少两个兵没动、对方仍有重子 —— 底线没有气口。"""
    king_sq = board.king(color)
    if king_sq is None:
        return False
    home = 0 if color == chess.WHITE else 7
    if chess.square_rank(king_sq) != home:
        return False
    fwd = 1 if color == chess.WHITE else -1
    shield = 0
    for f in (5, 6, 7):
        p = board.piece_at(chess.square(f, home + fwd))
        if p is not None and p.color == color and p.piece_type == chess.PAWN:
            shield += 1
    if shield < 2:
        return False
    heavy = board.pieces(chess.ROOK, not color) | board.pieces(chess.QUEEN, not color)
    return len(heavy) > 0


def heavy_on_home_rank(board: chess.Board, color: bool) -> bool:
    home = 0 if color == chess.WHITE else 7
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p is None or p.color == color:
            continue
        if p.piece_type in (chess.ROOK, chess.QUEEN) and any(
            chess.square_rank(t) == home for t in board.attacks(sq)
        ):
            return True
    return False


def pinned_pieces(board: chess.Board, color: bool, min_value: int = 300) -> set[int]:
    out = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None or piece.color != color:
            continue
        if value(piece) < min_value:
            continue
        if board.is_pinned(color, sq):
            out.add(sq)
    return out


def pinning_moves(board: chess.Board, color: bool, min_value: int = 300) -> chess.Move | None:
    """能立刻钉住对方一个值钱子（且不白送）的着法。"""
    if board.turn != color:
        return None
    before = pinned_pieces(board, not color, min_value)
    for move in list(board.legal_moves):
        board.push(move)
        after = pinned_pieces(board, not color, min_value)
        board.pop()
        if len(after) > len(before) and is_safe_move(board, move):
            return move
    return None


def knight_rim(board: chess.Board, color: bool) -> list[int]:
    return [
        sq
        for sq in board.pieces(chess.KNIGHT, color)
        if chess.square_file(sq) in (0, 7)
    ]


def pawn_weak_count(board: chess.Board, color: bool) -> int:
    files = [0] * 8
    for sq in board.pieces(chess.PAWN, color):
        files[chess.square_file(sq)] += 1
    doubled = sum(c - 1 for c in files if c > 1)
    isolated = 0
    for f in range(8):
        if files[f] == 0:
            continue
        neigh = (files[f - 1] if f > 0 else 0) + (files[f + 1] if f < 7 else 0)
        if neigh == 0:
            isolated += files[f]
    return doubled * 2 + isolated
