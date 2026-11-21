"""Stockfish 引擎封装（可选组件）。

这一层只做两件事：
  1) 给整盘棋的每个局面打一个分数 —— 用来画评估曲线、找真正的转折点
  2) 给每个局面一个「最优解」 —— 用来在棋盘上画“更优走法”箭头

它不是语言模型：Stockfish 是传统的 alpha-beta 搜索 + 小型局面评估函数（NNUE），
本地二进制运行，不联网、不调用任何 API。没有引擎文件时，复盘会退回到纯规则检测。
"""

from __future__ import annotations

import os
from collections import OrderedDict
import threading

import chess
import chess.engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEARCH_DIRS = [os.path.join(ROOT, "engine"), os.path.join(ROOT, "engine", "stockfish")]

_lock = threading.Lock()
_engine: chess.engine.SimpleEngine | None = None
_failed = False


def find_binary() -> str | None:
    env = os.environ.get("CHESS_ENGINE")
    if env and os.path.exists(env):
        return env
    for d in SEARCH_DIRS:
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.lower().startswith("stockfish") and name.lower().endswith(".exe"):
                return os.path.join(d, name)
    return None


def available() -> bool:
    return find_binary() is not None


def info() -> dict:
    path = find_binary()
    if not path:
        return {"available": False, "path": None, "name": None}
    return {"available": True, "path": os.path.relpath(path, ROOT), "name": "Stockfish"}


def _get() -> chess.engine.SimpleEngine | None:
    global _engine, _failed
    if _engine is not None:
        return _engine
    if _failed:
        return None
    path = find_binary()
    if not path:
        _failed = True
        return None
    try:
        eng = chess.engine.SimpleEngine.popen_uci(path)
        eng.timeout = 60  # A depth-19 MultiPV search may take longer than the default.
        try:
            eng.configure({"Threads": 1, "Hash": 96})
        except Exception:
            pass
        _engine = eng
        return eng
    except Exception:
        _failed = True
        return None


def _reset() -> None:
    global _engine, _failed
    with _lock:
        try:
            if _engine is not None:
                _engine.quit()
        except Exception:
            try:
                _engine.close()
            except Exception:
                pass
        _engine = None
        _failed = False


def shutdown() -> None:
    global _engine
    with _lock:
        if _engine is not None:
            try:
                _engine.quit()
            except Exception:
                pass
            _engine = None


def _score_pov(info: dict, board: chess.Board) -> tuple[int, int | None]:
    """返回 (白方视角的厘兵分, 将杀步数或 None)。mate 统一折算成 ±10000。"""
    score = info.get("score")
    if score is None:
        return 0, None
    white = score.pov(chess.WHITE)
    mate = white.mate()
    if mate is not None:
        # 距离越近分越极端，避免曲线因为 mate 距离抖动
        return (10000 - abs(mate) * 10) * (1 if mate > 0 else -1), mate
    return max(-1500, min(1500, white.score() or 0)), None


def analyse_positions(
    fens: list[str],
    per_move: float = 0.12,
    multipv: int = 1,
    depth: int | None = None,
) -> list[dict]:
    """逐个局部分析。返回与 fens 等长的列表。

    每项：{cp, mate, best_uci, best_san, pv_san}
    cp 为白方视角厘兵分（正=白优）。
    """
    eng = _get()
    if eng is None or not fens:
        return []

    out: list[dict] = []
    for fen in fens:
        try:
            board = chess.Board(fen)
        except ValueError:
            out.append({"cp": None, "mate": None, "best_uci": None, "best_san": None, "pv_san": []})
            continue
        if not board.is_valid():
            # 局面本身非法（比如上一手把王走到被将军的位置）：不交给引擎，避免它崩溃
            out.append({"cp": None, "mate": None, "best_uci": None, "best_san": None, "pv_san": []})
            continue
        if board.is_game_over(claim_draw=False):
            # 终局：将杀按行棋方判负
            if board.is_checkmate():
                cp = -10000 if board.turn == chess.WHITE else 10000
            else:
                cp = 0
            out.append({"cp": cp, "mate": None, "best_uci": None, "best_san": None, "pv_san": []})
            continue
        try:
            limit = chess.engine.Limit(depth=depth) if depth else chess.engine.Limit(time=per_move)
            with _lock:
                info = eng.analyse(board, limit, multipv=multipv)
        except Exception:
            out.append({"cp": None, "mate": None, "best_uci": None, "best_san": None, "pv_san": []})
            # 引擎可能已经退出：丢掉这个进程，下次重新拉起
            _reset()
            continue
        if isinstance(info, dict):
            info = [info]
        best = info[0] if info else {}
        cp, mate = _score_pov(best, board)
        pv = best.get("pv") or []
        pv_san: list[str] = []
        probe = board.copy(stack=False)
        for mv in pv[:8]:
            try:
                pv_san.append(probe.san(mv))
                probe.push(mv)
            except Exception:
                break
        best_uci = pv[0].uci() if pv else None
        best_san = pv_san[0] if pv_san else None
        out.append({"cp": cp, "mate": mate, "best_uci": best_uci, "best_san": best_san, "pv_san": pv_san, "pv_uci": [m.uci() for m in pv[:8]]})
    return out


def best_move(fen: str, per_move: float = 0.2) -> dict | None:
    rows = analyse_positions([fen], per_move=per_move)
    return rows[0] if rows else None


CONCEPT_START_ROUNDS = 7
CONCEPT_FOLLOWUP_ROUNDS = 3
CONCEPT_MAX_ROUNDS = 10


# Both review explanations and the board button use the same main-line search.
REVIEW_REPLY_DEPTH = 19


_review_cache = OrderedDict()
_review_cache_engine = None


def _review_main_line(eng, board: chess.Board, depth: int = REVIEW_REPLY_DEPTH) -> dict:
    global _review_cache_engine
    key = (depth, board.root().fen(), tuple(board.move_stack))
    with _lock:
        if _review_cache_engine is not eng:
            _review_cache.clear()
            _review_cache_engine = eng
        if key in _review_cache:
            _review_cache.move_to_end(key)
            return _review_cache[key]
        # A fresh UCI game keeps earlier searches from changing the next choice.
        info = eng.analyse(board, chess.engine.Limit(depth=depth), game=object())
        if info.get("pv"):
            _review_cache[key] = info
            if len(_review_cache) > 512:
                _review_cache.popitem(last=False)
        return info


def _review_continuation(eng, start: chess.Board, first_info: dict,
                         reply_count: int, depth: int = REVIEW_REPLY_DEPTH) -> list[chess.Move]:
    """Re-search from each position, as the board's Engine Reply button does."""
    board = start.copy()
    moves, info = [], first_info
    for ply in range(reply_count):
        if board.is_game_over():
            break
        if ply:
            info = _review_main_line(eng, board, depth)
        pv = info.get("pv") or []
        if not pv:
            break
        moves.append(pv[0])
        board.push(pv[0])
    return moves


def _replay_history(initial: str, history: list[str]) -> chess.Board:
    board = chess.Board(initial)
    if not board.is_valid():
        raise ValueError("起始局面非法")
    for uci in history:
        if not board.push_uci(uci):
            raise ValueError("变化不能包含空着")
    return board


def _review_row(root, path):
    board = root.copy()
    san, checkpoints = [], []
    for ply, move in enumerate(path, 1):
        san.append(board.san(move))
        board.push(move)
        if ply % 2 == 0:
            checkpoints.append(board.fen())
    return board, {
        "san": san,
        "checkpoints": checkpoints,
        "color": chess.COLOR_NAMES[root.turn],
        "checkmate": board.is_checkmate() and board.turn != root.turn,
        "mated": board.is_checkmate() and board.turn == root.turn,
        "terminal": board.is_game_over(),
    }


def comparison_positions(fen: str, recommended: str, played: str, *,
                         initial: str | None = None, history: list[str] | None = None,
                         depth: int = REVIEW_REPLY_DEPTH) -> dict | None:
    """Branch on the opponent's top three replies and then their top two replies."""
    position = chess.Board(fen)
    if not position.is_valid():
        raise ValueError("局面非法")
    root = position if initial is None else _replay_history(initial, history or [])
    if root.fen() != position.fen():
        raise ValueError("棋步历史与转折点局面不一致")
    moves = [root.parse_uci(uci) for uci in (recommended, played)]
    if not all(moves) or moves[0] == moves[1]:
        raise ValueError("需要两手不同的合法走法")
    eng = _get()
    if eng is None:
        return None

    groups = {}
    try:
        for side, first in zip(("positive", "negative"), moves):
            start, main = _review_row(root, [first])
            rows = []
            groups[side] = {"main": main, "branches": rows, "forced_mate": main["checkmate"]}
            if start.is_game_over():
                rows.append(main)
                continue
            best = _review_main_line(eng, start, depth)
            replies = _review_continuation(eng, start, best, 2 * CONCEPT_START_ROUNDS - 1, depth)
            _, main = _review_row(root, [first, *replies])
            score = best.get("score")
            mate = score.pov(root.turn).mate() if score else None
            groups[side]["main"] = main
            groups[side]["forced_mate"] = (
                mate is not None and mate > 0
                and not best.get("lowerbound") and not best.get("upperbound")
            )

            groups[side]["forced_loss"] = (
                mate is not None and mate < 0
                and not best.get("lowerbound") and not best.get("upperbound")
            )

            def opponent_choices(board, count):
                with _lock:
                    candidates = eng.analyse(
                        board, chess.engine.Limit(depth=depth),
                        multipv=count, game=object(),
                    )
                return list(dict.fromkeys(
                    info["pv"][0] for info in candidates if info.get("pv")
                ))

            for opponent_move in opponent_choices(start, 3):
                prefix = [first, opponent_move]
                response, row = _review_row(root, prefix)
                if row["terminal"]:
                    rows.append(row)
                    continue
                own_info = _review_main_line(eng, response, depth)
                own_pv = own_info.get("pv") or []
                if not own_pv:
                    rows.append(row)
                    continue
                prefix.append(own_pv[0])
                second_reply, row = _review_row(root, prefix)
                if row["terminal"]:
                    rows.append(row)
                    continue
                for second_opponent_move in opponent_choices(second_reply, 2):
                    path = [*prefix, second_opponent_move]
                    probe, row = _review_row(root, path)
                    if not row["terminal"]:
                        info = _review_main_line(eng, probe, depth)
                        tail = _review_continuation(
                            eng, probe, info,
                            2 * CONCEPT_START_ROUNDS - len(path), depth,
                        )
                        _, row = _review_row(root, [*path, *tail])
                    rows.append(row)
    except (chess.engine.EngineError, TimeoutError):
        _reset()
        return None
    return groups


def extend_review_lines(fen, rows, *, initial=None, history=None, depth=REVIEW_REPLY_DEPTH):
    """Extend only branches with an unresolved event, sharing identical prefixes."""
    if not rows:
        return False
    root = chess.Board(fen) if initial is None else _replay_history(initial, history or [])
    eng = _get()
    if eng is None:
        return False
    changed = False
    try:
        for row in {id(row): row for row in rows}.values():
            if row["terminal"] or len(row["san"]) >= 2 * CONCEPT_MAX_ROUNDS:
                continue
            board = root.copy()
            path = [board.push_san(san) for san in row["san"]]
            info = _review_main_line(eng, board, depth)
            tail = _review_continuation(eng, board, info, 2 * CONCEPT_MAX_ROUNDS - len(path), depth)
            if tail:
                row.update(_review_row(root, [*path, *tail])[1])
                changed = True
    except (chess.engine.EngineError, TimeoutError):
        _reset()
    return changed


def analyse_branch(initial: str, history: list[str], depth: int = REVIEW_REPLY_DEPTH) -> dict:
    board = _replay_history(initial, history)
    if board.is_game_over(claim_draw=False):
        return {"status": "finished", "result": board.result()}
    eng = _get()
    if eng is None:
        return {"status": "unavailable"}
    try:
        info = _review_main_line(eng, board, depth)
        cp, mate = _score_pov(info, board)
        pv = info.get("pv") or []
        if not pv:
            return {"status": "unavailable"}
        return {"status": "ok", "uci": pv[0].uci(), "san": board.san(pv[0]),
                "cp": cp, "mate": mate, "pv": [m.uci() for m in pv]}
    except (chess.engine.EngineError, TimeoutError):
        _reset()
        return {"status": "unavailable"}
