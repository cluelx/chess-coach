"""从 Lichess 题库 CSV(zst) 流式筛选建库。

不落地 1.1GB 的解压文件：边解压边按“主题 × 难度段”抽样写入 SQLite。
用法：
    python scripts/fetch_puzzles.py                # 全量建库
    python scripts/fetch_puzzles.py --limit 200000 # 只扫前 N 行（调试）
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import time

import zstandard as zstd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import db, knowledge  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw", "lichess_db_puzzle.csv.zst")

CAP_PER_BUCKET = 420           # 每个（主题 × 难度段）最多保留多少题
MIN_POPULARITY = 60            # 至少被人做过并认可
RATING_MIN, RATING_MAX = 500, 2300
BANDS = [(500, 1099), (1100, 1599), (1600, 2300)]


def wanted_themes() -> set[str]:
    themes: set[str] = set()
    for kp in knowledge.KPS:
        themes.update(kp["themes"])
    # 补充：让入门档也有足够的“一步杀/两步杀”题
    themes.update({"mateIn1", "mateIn2", "mateIn3", "oneMove", "endgame", "middlegame", "opening"})
    return themes


def bucket_of(rating: int) -> int:
    for i, (lo, hi) in enumerate(BANDS):
        if lo <= rating <= hi:
            return i
    return -1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cap", type=int, default=CAP_PER_BUCKET)
    args = ap.parse_args()

    if not os.path.exists(RAW):
        raise SystemExit(f"找不到 {RAW}，先下载题库压缩包")

    db.init_db()
    wanted = wanted_themes()
    print(f"关注 {len(wanted)} 个主题标签，每桶上限 {args.cap}", flush=True)

    counters: dict[tuple[str, int], int] = {}
    accepted = 0
    scanned = 0
    t0 = time.time()

    with open(RAW, "rb") as fh:
        dctx = zstd.ZstdDecompressor()
        with dctx.stream_reader(fh) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8", newline="")
            rdr = csv.reader(text)
            header = next(rdr)
            idx = {name: i for i, name in enumerate(header)}

            conn = db.connect()
            conn.execute("DELETE FROM puzzle_theme")
            conn.execute("DELETE FROM puzzle")
            buf_p, buf_t = [], []

            def flush() -> None:
                nonlocal buf_p, buf_t
                if buf_p:
                    conn.executemany(
                        "INSERT OR REPLACE INTO puzzle(id,fen,moves,rating,rd,popularity,nb_plays,themes,opening_tags)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        buf_p,
                    )
                    conn.executemany("INSERT INTO puzzle_theme(puzzle_id,theme) VALUES(?,?)", buf_t)
                    buf_p, buf_t = [], []
                conn.commit()

            for row in rdr:
                scanned += 1
                if args.limit and scanned > args.limit:
                    break
                if scanned % 250000 == 0:
                    flush()
                    el = time.time() - t0
                    print(f"  扫描 {scanned/1e6:.2f}M 行，已收 {accepted} 题，{el:.0f}s", flush=True)
                try:
                    rating = int(row[idx["Rating"]])
                except (ValueError, IndexError):
                    continue
                if not (RATING_MIN <= rating <= RATING_MAX):
                    continue
                pop_raw = row[idx["Popularity"]]
                try:
                    pop = int(pop_raw)
                except ValueError:
                    pop = 0
                if pop < MIN_POPULARITY:
                    continue
                themes = [t for t in row[idx["Themes"]].split() if t in wanted]
                if not themes:
                    continue
                band = bucket_of(rating)
                if band < 0:
                    continue
                usable = [t for t in themes if counters.get((t, band), 0) < args.cap]
                if not usable:
                    continue
                for t in usable:
                    counters[(t, band)] = counters.get((t, band), 0) + 1
                buf_p.append(
                    (
                        row[idx["PuzzleId"]],
                        row[idx["FEN"]],
                        row[idx["Moves"]],
                        rating,
                        int(row[idx["RatingDeviation"]] or 0),
                        pop,
                        int(row[idx["NbPlays"]] or 0),
                        " ".join(themes),
                        row[idx["OpeningTags"]] if "OpeningTags" in idx else "",
                    )
                )
                buf_t.extend((row[idx["PuzzleId"]], t) for t in themes)
                accepted += 1
                if len(buf_p) >= 2000:
                    flush()

            flush()
            conn.close()

    el = time.time() - t0
    print(f"完成：扫描 {scanned} 行，入库 {accepted} 题，用时 {el:.0f}s", flush=True)
    with db.db() as c:
        total = c.execute("SELECT COUNT(*) FROM puzzle").fetchone()[0]
    print(f"库内总题数 {total}")


if __name__ == "__main__":
    main()
