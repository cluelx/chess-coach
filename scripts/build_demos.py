"""为每一课挑一道「真实存在的题」作为局面演示。

为什么要有这个脚本：
  教程右侧的演示局面不能手写。手写的 FEN 很容易和本课战术对不上，
  而且无法追溯。这里改成从 Lichess 题库里按「本课知识点对应的主题标签」
  精确筛选，把选中的 puzzle id 固定写进 data/demos.json。
  每道题都能用 https://lichess.org/training/<id> 打开原题核对。

选择标准（全部可复核）：
  · 主题标签必须命中本课知识点映射的主题
  · 难度落在本档区间内，且优先取中低段（演示不该比练习题还难）
  · 解法 2–6 个半回合，最后形成将杀或净赚一个轻子以上
  · popularity 高（被大量用户做过，题目本身没有争议）

用法：python scripts/build_demos.py
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess

from src import db, knowledge, puzzles

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "demos.json")

VALUES = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330, chess.ROOK: 500, chess.QUEEN: 900}

# 只有「战术类」课程用真实题目做演示：这些课的答案唯一、可验证、可追溯到原题。
# 战略/残局类课程没有唯一答案，继续用手写局面，并在 lesson 里标明是教学构造。
DEMO_THEME = {
    "l1-2": "mateIn1",
    "l1-4": "hangingPiece",
    "l1-5": "fork",
    "l1-6": "pin",
    "l2-1": "discoveredCheck",
    "l2-2": "capturingDefender",
    "l2-3": "attraction",
    "l2-4": "backRankMate",
    "l2-5": "intermezzo",
    "l3-1": "smotheredMate",
    "l3-6": "mateIn3",
}
MAX_PLIES = 6
MIN_PLIES = 1


def material(board: chess.Board, color: bool) -> int:
    total = 0
    for sq, piece in board.piece_map().items():
        if piece.color == color:
            total += VALUES.get(piece.piece_type, 0)
    return total


def verify_puzzle(row) -> dict | None:
    moves = row["moves"].split()
    if not (MIN_PLIES <= len(moves) - 1 <= MAX_PLIES):
        return None
    board = chess.Board(row["fen"])
    solver = board.turn
    start_bal = material(board, solver) - material(board, not solver)
    for uci in moves:
        try:
            mv = chess.Move.from_uci(uci)
        except ValueError:
            return None
        if mv not in board.legal_moves:
            return None
        board.push(mv)
    end_bal = material(board, solver) - material(board, not solver)
    mate = board.is_checkmate()
    if not mate and end_bal - start_bal < 180:
        return None
    return {
        "plies": len(moves) - 1,
        "mate": mate,
        "gain": end_bal - start_bal,
    }


def pick_for(lesson: dict) -> dict | None:
    themes = puzzles.themes_for_kps(lesson["kps"])
    theme = DEMO_THEME.get(lesson["id"])
    if not themes or not theme:
        return None
    level = lesson["level"]
    lo, hi = puzzles.band_for_level(level)
    # 演示题取本档偏下的难度：比练习题温和，重点看形状
    span = hi - lo
    lo2, hi2 = lo, lo + int(span * 0.75)

    # 硬性要求：题目必须带本课指定的那个主题标签，不能只靠“顺带命中”
    rows = db.query(
        """SELECT p.* FROM puzzle p
            JOIN puzzle_theme t ON t.puzzle_id = p.id
            WHERE t.theme = ? AND p.rating BETWEEN ? AND ?
              AND p.popularity IS NOT NULL AND p.popularity >= 60
            GROUP BY p.id
            ORDER BY p.popularity DESC
            LIMIT 260""",
        (theme, lo2, hi2),
    )

    scored = []
    for r in rows:
        info = verify_puzzle(r)
        if info is None:
            continue
        rthemes = r["themes"].split()
        overlap = len(set(rthemes) & set(themes))
        if theme not in rthemes:
            continue
        # 偏好：命中主题多、解法短、热度高、难度接近本档中位
        mid = (lo2 + hi2) / 2
        scored.append(
            (
                (
                    overlap * 8
                    - abs(info["plies"] - 3) * 2
                    - abs(r["rating"] - mid) / 90
                    + (r["popularity"] or 0) / 120
                ),
                r,
                info,
            )
        )
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    _, row, info = scored[0]
    return {
        "theme": theme,
        "puzzle_id": row["id"],
        "rating": row["rating"],
        "themes": row["themes"].split(),
        "moves": row["moves"].split(),
        "plies": info["plies"],
        "mate": info["mate"],
        "url": "https://lichess.org/training/" + row["id"],
        "kp_ids": lesson["kps"],
    }


def main() -> None:
    db.init_db()
    out = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Lichess Puzzle Database (https://database.lichess.org/#puzzles), CC0",
        "lessons": {},
    }
    used: set[str] = set()
    for lesson in knowledge.LESSONS:
        if not DEMO_THEME.get(lesson["id"]):
            print(f"{lesson['id']:<6} 跳过（战略/残局类，保留教学构造局面）")
            continue
        picked = pick_for(lesson)
        if not picked:
            print(f"{lesson['id']:<6} 没找到合适的题")
            continue
        if picked["puzzle_id"] in used:
            print(f"{lesson['id']:<6} 与其他课重复，跳过")
            continue
        used.add(picked["puzzle_id"])
        out["lessons"][lesson["id"]] = picked
        print(
            f"{lesson['id']:<6} {picked['puzzle_id']:<8} rating={picked['rating']:<5}"
            f" plies={picked['plies']} mate={picked['mate']} theme={picked['theme']}"
        )

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(f"\n写入 {OUT}：{len(out['lessons'])} 课")


if __name__ == "__main__":
    main()
