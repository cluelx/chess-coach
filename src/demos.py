"""课程演示：把题库里的真实题目组装成棋盘演示。

data/demos.json 由 scripts/build_demos.py 生成，里面是「课程 → 题目 ID」的固定映射。
每道题都带 lichess 原题链接，可以逐条核对。
"""

from __future__ import annotations

import json
import os

import chess

from . import knowledge, puzzles
from .motifs import PIECE_CN, fork_targets_after, sq_name

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "demos.json")

_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(PATH, encoding="utf-8") as fh:
                _cache = json.load(fh)
        except Exception:
            _cache = {"lessons": {}}
    return _cache


def _describe(board: chess.Board, move: chess.Move) -> str:
    """用程序能判定的性质给一步棋写注释，不编造意图。"""
    victim = board.piece_at(move.to_square)
    try:
        targets = fork_targets_after(board, move)
    except Exception:
        targets = []
    board.push(move)
    try:
        mate = board.is_checkmate()
        check = board.is_check()
    finally:
        board.pop()

    bits: list[str] = []
    if victim:
        bits.append(f"吃掉 {sq_name(move.to_square)} 的{PIECE_CN.get(victim.piece_type, '子')}")
    if mate:
        bits.append("直接把对方将死")
    elif check:
        bits.append("同时将军")
    if len(targets) >= 2:
        names = "、".join(f"{t['square']} 的{PIECE_CN.get(t['piece'], '子')}" for t in targets[:3])
        bits.append(f"一手同时攻击 {names}")
    if not bits:
        bits.append("这一手是题目认定的唯一正解")
    return "，".join(bits) + "。"


def for_lesson(lesson_id: str) -> dict | None:
    entry = load().get("lessons", {}).get(lesson_id)
    if not entry:
        return None
    item = puzzles.by_id(entry["puzzle_id"])
    if not item:
        return None

    board = chess.Board(item["fen"])
    # Lichess 格式：第 1 个着法是对手的引子，之后交替；fen 的走子方是「对手」，
    # 所以解题方是 fen.turn 的反方。
    solver_is_white = not board.turn
    seq = ([item["pre"]] if item["pre"] else []) + list(item["solution"])
    moves: list[dict] = []
    marks: list[str] = []
    for i, uci in enumerate(seq):
        try:
            mv = chess.Move.from_uci(uci)
            if mv not in board.legal_moves:
                break
            san = board.san(mv)
        except Exception:
            break
        # i 为偶数 → 对手（引子与应手），奇数 → 解题方
        side = "opp" if i % 2 == 0 else "you"
        if i == 0:
            comment = f"对手先走 {san}，现在轮到你。"
        elif side == "you":
            comment = _describe(board, mv)
            if len(marks) < 2:
                marks.extend([sq_name(mv.from_square), sq_name(mv.to_square)])
        else:
            comment = f"对方这样应对：{san}。"
        moves.append({"uci": uci, "san": san, "comment": comment, "by": side})
        board.push(mv)

    themes_cn = [knowledge.THEME_CN.get(t, t) for t in item["themes"][:3]]
    kind = "将杀" if any("mate" in t.lower() for t in item["themes"]) else "得子"
    return {
        "title": f"题库原题：{kind}（难度 {item['rating']}）",
        "fen": item["fen"],
        "moves": moves,
        "marks": list(dict.fromkeys(marks))[:4],
        "orientation": "white" if solver_is_white else "black",
        "note": f"这是 Lichess 题库里的一道真实题目，主题是「{'、'.join(themes_cn)}」，"
                f"解题方执{'白' if solver_is_white else '黑'}，{max(0, len(moves) - 1)} 个半回合。"
                f"点“下一步”逐步看完整解法。",
        "source": {
            "kind": "puzzle",
            "puzzle_id": item["id"],
            "rating": item["rating"],
            "themes": item["themes"],
            "themes_cn": themes_cn,
            "url": entry.get("url") or ("https://lichess.org/training/" + item["id"]),
        },
    }
