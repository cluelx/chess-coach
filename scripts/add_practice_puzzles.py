"""Add the four missing tutorial themes from the local Lichess export."""

import csv
import io

import chess
import zstandard

from fetch_puzzles import (
    BANDS, MIN_POPULARITY, RAW, bucket_of, db, wanted_themes,
)

THEMES = {"skewer", "doubleCheck", "overloading", "underPromotion"}
PER_BAND = 40


def verified_tags(fen, moves, tags):
    board = chess.Board(fen)
    if not board.is_valid():
        return set()
    verified = tags - {"doubleCheck", "underPromotion"}
    for i, uci in enumerate(moves.split()):
        move = board.push_uci(uci)
        if i % 2 == 1:
            if "doubleCheck" in tags and len(board.checkers()) >= 2:
                verified.add("doubleCheck")
            if "underPromotion" in tags and move.promotion in (chess.ROOK, chess.BISHOP, chess.KNIGHT):
                verified.add("underPromotion")
    return verified


def collect():
    quotas = {(theme, band): 0 for theme in THEMES for band in range(len(BANDS))}
    seen = set()
    rows = []
    with open(RAW, "rb") as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
            for row in csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8", newline="")):
                raw_tags = set(row["Themes"].split())
                seen.update(raw_tags & THEMES)
                if not raw_tags & THEMES:
                    continue
                rating, popularity = int(row["Rating"]), int(row["Popularity"])
                band = bucket_of(rating)
                if band == -1 or popularity < MIN_POPULARITY:
                    continue
                eligible = {tag for tag in raw_tags & THEMES if quotas[tag, band] < PER_BAND}
                if not eligible:
                    continue
                try:
                    selected = verified_tags(row["FEN"], row["Moves"], eligible)
                except ValueError:
                    continue
                if selected:
                    rows.append((row, selected))
                    for tag in selected:
                        quotas[tag, band] += 1
                    if all(n == PER_BAND for n in quotas.values()):
                        break
    return rows, quotas, seen


def main():
    rows, quotas, seen = collect()
    if not rows:
        raise SystemExit("No usable puzzles. No changes applied.")

    original_themes = wanted_themes() - THEMES
    with db.db() as conn:
        for row, selected in rows:
            puzzle_id, fen, moves = row["PuzzleId"], row["FEN"], row["Moves"]
            current = conn.execute("SELECT fen, moves, themes FROM puzzle WHERE id=?", (puzzle_id,)).fetchone()
            if current and (current["fen"], current["moves"]) != (fen, moves):
                raise ValueError(f"Puzzle source differs from SQLite: {puzzle_id}")
            if current:
                tags = set(current["themes"].split()) | selected
                conn.execute("UPDATE puzzle SET themes=? WHERE id=?", (" ".join(sorted(tags)), puzzle_id))
            else:
                tags = set(row["Themes"].split()) & original_themes | selected
                conn.execute(
                    "INSERT INTO puzzle VALUES(?,?,?,?,?,?,?,?,?)",
                    (puzzle_id, fen, moves, int(row["Rating"]), int(row["RatingDeviation"]),
                     int(row["Popularity"]), int(row["NbPlays"]), " ".join(sorted(tags)), row["OpeningTags"]),
                )
            conn.executemany(
                "INSERT INTO puzzle_theme(puzzle_id,theme) SELECT ?,? "
                "WHERE NOT EXISTS (SELECT 1 FROM puzzle_theme WHERE puzzle_id=? AND theme=?)",
                [(puzzle_id, tag, puzzle_id, tag) for tag in sorted(tags)],
            )
    for theme in sorted(THEMES):
        print(theme, [quotas[theme, band] for band in range(len(BANDS))],
              "present in source" if theme in seen else "absent from source")


if __name__ == "__main__":
    main()
