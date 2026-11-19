"""SQLite 存取层：题库 + 学员画像。无外部依赖。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "chess_coach.db")

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS puzzle (
  id           TEXT PRIMARY KEY,
  fen          TEXT NOT NULL,
  moves        TEXT NOT NULL,
  rating       INTEGER NOT NULL,
  rd           INTEGER,
  popularity   INTEGER,
  nb_plays     INTEGER,
  themes       TEXT NOT NULL,
  opening_tags TEXT
);
CREATE INDEX IF NOT EXISTS idx_puzzle_rating ON puzzle(rating);

CREATE TABLE IF NOT EXISTS puzzle_theme (
  puzzle_id TEXT NOT NULL,
  theme     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pt_theme ON puzzle_theme(theme, puzzle_id);

CREATE TABLE IF NOT EXISTS learner (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  level      INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS attempt (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  learner_id TEXT NOT NULL,
  puzzle_id  TEXT NOT NULL,
  correct    INTEGER NOT NULL,
  ms         INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attempt_learner ON attempt(learner_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempt_puzzle ON attempt(learner_id, puzzle_id);

CREATE TABLE IF NOT EXISTS kp_state (
  learner_id TEXT NOT NULL,
  kp_id      TEXT NOT NULL,
  seen       INTEGER NOT NULL DEFAULT 0,
  correct    INTEGER NOT NULL DEFAULT 0,
  streak     INTEGER NOT NULL DEFAULT 0,
  last_seen  REAL,
  due_at     REAL,
  PRIMARY KEY (learner_id, kp_id)
);

CREATE TABLE IF NOT EXISTS account (
  id         TEXT PRIMARY KEY,
  username   TEXT NOT NULL UNIQUE,
  pw_hash    TEXT NOT NULL,
  salt       TEXT NOT NULL,
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
  token      TEXT PRIMARY KEY,
  account_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  last_seen  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_session_account ON session(account_id);

CREATE TABLE IF NOT EXISTS review_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  learner_id TEXT NOT NULL,
  created_at REAL NOT NULL,
  payload    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS local_profile (
  singleton  INTEGER PRIMARY KEY CHECK (singleton = 1),
  learner_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_detail (
  review_id INTEGER PRIMARY KEY,
  pgn       TEXT NOT NULL,
  color     TEXT NOT NULL,
  depth     INTEGER NOT NULL,
  analysis  TEXT NOT NULL,
  ply       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learning_source_cache (
  cache_key     TEXT PRIMARY KEY,
  url           TEXT NOT NULL,
  payload       TEXT NOT NULL,
  parser_version TEXT NOT NULL,
  model_key     TEXT NOT NULL,
  created_at    REAL NOT NULL,
  expires_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source_cache_expiry ON learning_source_cache(expires_at);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(sql, tuple(params)).fetchall()


def one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with db() as conn:
        conn.execute(sql, tuple(params))


# ---------- 网页来源缓存 ----------

def source_cache_get(cache_key: str, now: float) -> sqlite3.Row | None:
    return one(
        "SELECT payload, created_at, expires_at FROM learning_source_cache"
        " WHERE cache_key=? AND expires_at>?",
        (cache_key, now),
    )


def source_cache_put(cache_key: str, url: str, payload: str, parser_version: str,
                     model_key: str, created_at: float, expires_at: float) -> None:
    with db() as conn:
        conn.execute("DELETE FROM learning_source_cache WHERE expires_at<=?", (created_at,))
        conn.execute(
            "INSERT OR REPLACE INTO learning_source_cache"
            "(cache_key,url,payload,parser_version,model_key,created_at,expires_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (cache_key, url, payload, parser_version, model_key, created_at, expires_at),
        )


# ---------- 学员 ----------

def ensure_learner(learner_id: str, level: int = 1, name: str = "学员") -> dict:
    row = one("SELECT * FROM learner WHERE id = ?", (learner_id,))
    if row is None:
        execute(
            "INSERT INTO learner(id, name, level, created_at) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING",
            (learner_id, name, level, time.time()),
        )
        row = one("SELECT * FROM learner WHERE id = ?", (learner_id,))
    return dict(row)


def set_level(learner_id: str, level: int) -> None:
    execute("UPDATE learner SET level = ? WHERE id = ?", (level, learner_id))


# ---------- 练习记录 ----------

def record_attempt(learner_id: str, puzzle_id: str, correct: bool, ms: int, kp_ids: list[str]) -> dict:
    now = time.time()
    with db() as conn:
        conn.execute(
            "INSERT INTO attempt(learner_id, puzzle_id, correct, ms, created_at) VALUES(?,?,?,?,?)",
            (learner_id, puzzle_id, 1 if correct else 0, ms, now),
        )
        for kp in kp_ids:
            row = conn.execute(
                "SELECT seen, correct, streak FROM kp_state WHERE learner_id=? AND kp_id=?",
                (learner_id, kp),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO kp_state(learner_id, kp_id, seen, correct, streak, last_seen, due_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (learner_id, kp, 1, 1 if correct else 0, 1 if correct else 0, now, now + 86400),
                )
            else:
                streak = (row["streak"] + 1) if correct else 0
                gap = min(86400 * (2 ** min(streak, 6)), 86400 * 60)
                conn.execute(
                    "UPDATE kp_state SET seen=seen+1, correct=correct+?, streak=?, last_seen=?, due_at=?"
                    " WHERE learner_id=? AND kp_id=?",
                    (1 if correct else 0, streak, now, now + gap, learner_id, kp),
                )
    return kp_progress(learner_id)


def kp_progress(learner_id: str) -> dict:
    rows = query("SELECT * FROM kp_state WHERE learner_id = ?", (learner_id,))
    out = {}
    for r in rows:
        seen = r["seen"] or 0
        acc = (r["correct"] / seen) if seen else 0.0
        out[r["kp_id"]] = {
            "seen": seen,
            "correct": r["correct"],
            "accuracy": round(acc, 3),
            "streak": r["streak"],
            "last_seen": r["last_seen"],
            "due_at": r["due_at"],
            "mastery": round(min(1.0, acc * 0.7 + min(seen, 6) / 6 * 0.3), 3),
        }
    return out


def studied_puzzles(learner_id: str) -> set[str]:
    rows = query("SELECT DISTINCT puzzle_id FROM attempt WHERE learner_id = ?", (learner_id,))
    return {r["puzzle_id"] for r in rows}


def local_learner_id() -> str:
    row = one("SELECT learner_id FROM local_profile WHERE singleton=1")
    return row["learner_id"] if row else "local"


def save_review(learner_id: str, payload: dict, pgn: str, color: str, depth: int, analysis: dict) -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO review_log(learner_id, created_at, payload) VALUES(?,?,?)",
            (learner_id, time.time(), json.dumps(payload, ensure_ascii=False)),
        )
        review_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO review_detail(review_id, pgn, color, depth, analysis) VALUES(?,?,?,?,?)",
            (review_id, pgn, color, depth, json.dumps(analysis, ensure_ascii=False)),
        )
        return review_id


def saved_reviews(learner_id: str) -> list[dict]:
    rows = query(
        "SELECT r.id, r.created_at, r.payload, d.ply FROM review_log r "
        "JOIN review_detail d ON d.review_id=r.id WHERE r.learner_id=? ORDER BY r.id DESC",
        (learner_id,),
    )
    return [{
        "id": r["id"], "created_at": r["created_at"], "ply": r["ply"],
        "headers": json.loads(r["payload"]).get("headers", {}),
    } for r in rows]


def saved_review(learner_id: str, review_id: int) -> dict | None:
    row = one(
        "SELECT r.created_at, d.* FROM review_detail d JOIN review_log r ON r.id=d.review_id "
        "WHERE r.learner_id=? AND r.id=?", (learner_id, review_id),
    )
    if row is None:
        return None
    return {
        "pgn": row["pgn"], "color": row["color"], "depth": row["depth"], "ply": row["ply"],
        "analyzedAt": round(row["created_at"] * 1000),
        "res": {**json.loads(row["analysis"]), "id": review_id},
    }


def update_review_ply(learner_id: str, review_id: int, ply: int) -> bool:
    with db() as conn:
        return bool(conn.execute(
            "UPDATE review_detail SET ply=min(?, json_array_length(analysis, '$.moves')) "
            "WHERE review_id IN (SELECT id FROM review_log WHERE id=? AND learner_id=?)",
            (ply, review_id, learner_id),
        ).rowcount)


def delete_review(learner_id: str, review_id: int) -> bool:
    with db() as conn:
        removed = conn.execute(
            "DELETE FROM review_log WHERE id=? AND learner_id=?", (review_id, learner_id),
        ).rowcount
        if removed:
            conn.execute("DELETE FROM review_detail WHERE review_id=?", (review_id,))
        return bool(removed)


def recent_reviews(learner_id: str, limit: int = 10) -> list[dict]:
    rows = query(
        "SELECT id, created_at, payload FROM review_log WHERE learner_id = ?"
        " ORDER BY created_at DESC LIMIT ?",
        (learner_id, limit),
    )
    return [
        {"id": r["id"], "created_at": r["created_at"], "payload": json.loads(r["payload"])}
        for r in rows
    ]


def stats(learner_id: str) -> dict:
    total = one(
        "SELECT COUNT(*) c, SUM(correct) ok FROM attempt WHERE learner_id = ?", (learner_id,)
    )
    today = one(
        "SELECT COUNT(*) c, SUM(correct) ok FROM attempt WHERE learner_id = ? AND created_at > ?",
        (learner_id, time.time() - 86400),
    )
    kp_total = one("SELECT COUNT(*) c FROM kp_state WHERE learner_id = ?", (learner_id,))
    return {
        "attempts": total["c"] or 0,
        "correct": total["ok"] or 0,
        "today_attempts": today["c"] or 0,
        "today_correct": today["ok"] or 0,
        "kps_touched": kp_total["c"] or 0,
    }
