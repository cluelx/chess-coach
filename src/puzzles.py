"""题库检索：知识点 → 主题标签 → SQLite 里的题。"""

from __future__ import annotations

import random
from typing import Iterable

from . import db, knowledge

RATING_FALLBACK = 260


def band_for_level(level: int) -> tuple[int, int]:
    for lv in knowledge.LEVELS:
        if lv["id"] == level:
            return tuple(lv["rating"])
    return (600, 1100)


def themes_for_kps(kp_ids: Iterable[str]) -> list[str]:
    themes: list[str] = []
    for kp in kp_ids:
        meta = knowledge.KP_BY_ID.get(kp)
        if not meta:
            continue
        for t in meta["themes"]:
            if t not in themes:
                themes.append(t)
    return themes


def to_client(row) -> dict:
    moves = row["moves"].split()
    return {
        "id": row["id"],
        "fen": row["fen"],
        "pre": moves[0] if moves else None,
        "solution": moves[1:] if len(moves) > 1 else [],
        "rating": row["rating"],
        "themes": row["themes"].split(),
        "nb_plays": row["nb_plays"],
        "popularity": row["popularity"],
    }


def pick(
    kp_ids: Iterable[str],
    level: int,
    limit: int = 5,
    exclude: Iterable[str] = (),
    spread: bool = True,
    seed: str | None = None,
) -> list[dict]:
    """按知识点取题。优先取本档难度区间，不够再放宽 ±260 分。

    seed 不为空时结果是确定的：同一课、同一档，每次进来看到同一批题。
    课程用它（题目要固定，讲解才对得上）；自由练习不传，保持随机。
    """
    themes = themes_for_kps(kp_ids)
    if not themes:
        return []
    lo, hi = band_for_level(level)
    excl = set(exclude)
    marks = ",".join("?" for _ in themes)
    rows: list = []

    def run(lo2: int, hi2: int) -> list:
        order = "RANDOM()" if seed is None else "(p.popularity IS NULL), -p.popularity, p.id"
        sql = f"""
            SELECT p.* FROM puzzle p
            JOIN puzzle_theme t ON t.puzzle_id = p.id
            WHERE t.theme IN ({marks}) AND p.rating BETWEEN ? AND ?
            GROUP BY p.id
            ORDER BY {order}
            LIMIT ?
        """
        return db.query(sql, (*themes, lo2, hi2, limit * 6))

    rows = run(lo, hi)
    if len(rows) < limit:
        seen = {r["id"] for r in rows}
        for r in run(max(400, lo - RATING_FALLBACK), hi + RATING_FALLBACK):
            if r["id"] not in seen:
                rows.append(r)
                seen.add(r["id"])
    rows = [r for r in rows if r["id"] not in excl]
    if seed is not None:
        rnd = random.Random(str(seed))
        rnd.shuffle(rows)
    if spread and len(rows) > limit:
        # 按主题轮转取样，避免同一个主题霸屏
        buckets: dict[str, list] = {}
        for r in rows:
            key = r["themes"].split(",")[0]
            buckets.setdefault(key, []).append(r)
        out: list = []
        while len(out) < limit and buckets:
            for k in list(buckets.keys()):
                if buckets[k]:
                    out.append(buckets[k].pop(0))
                if not buckets[k]:
                    buckets.pop(k)
                if len(out) >= limit:
                    break
        rows = out
    else:
        rows = rows[:limit]
    return [to_client(r) for r in rows]


def by_id(puzzle_id: str) -> dict | None:
    row = db.one("SELECT * FROM puzzle WHERE id = ?", (puzzle_id,))
    return to_client(row) if row else None


def theme_counts(themes: Iterable[str], level: int) -> dict:
    lo, hi = band_for_level(level)
    marks = ",".join("?" for _ in themes)
    rows = db.query(
        f"""SELECT t.theme, COUNT(*) c FROM puzzle_theme t
            JOIN puzzle p ON p.id = t.puzzle_id
            WHERE t.theme IN ({marks}) AND p.rating BETWEEN ? AND ?
            GROUP BY t.theme""",
        (*list(themes), lo, hi),
    )
    return {r["theme"]: r["c"] for r in rows}


def sample_for_review(kp_id: str, level: int, learner_id: str, limit: int = 3) -> dict:
    """给复盘用：这个知识点下，学员做过的题（复习）与没做过的题（新练）。"""
    studied = db.studied_puzzles(learner_id)
    pool = pick([kp_id], level, limit=24)
    done = [p for p in pool if p["id"] in studied]
    fresh = [p for p in pool if p["id"] not in studied]
    if not done:
        # 学员没做过，退回全库找做过的
        themes = themes_for_kps([kp_id])
        if themes:
            marks = ",".join("?" for _ in themes)
            rows = db.query(
                f"""SELECT p.* FROM puzzle p JOIN puzzle_theme t ON t.puzzle_id = p.id
                    JOIN attempt a ON a.puzzle_id = p.id
                    WHERE t.theme IN ({marks}) AND a.learner_id = ?
                    GROUP BY p.id ORDER BY RANDOM() LIMIT ?""",
                (*themes, learner_id, limit),
            )
            done = [to_client(r) for r in rows]
    random.shuffle(done)
    random.shuffle(fresh)
    return {"review": done[:limit], "new": fresh[:limit]}
