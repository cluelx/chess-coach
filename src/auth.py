"""本地账号：注册、登录、会话。

没有第三方依赖，也没有任何外部服务：
  · 密码用 PBKDF2-SHA256（20 万轮 + 每账号独立盐）存哈希，不存明文
  · 会话是随机 token，放在 HttpOnly Cookie 里
数据全在本机 SQLite 里，不上传。
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time

from . import db

USER_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,20}$")
ITERATIONS = 200_000
COOKIE = "cc_session"
COOKIE_MAX_AGE = 30 * 86400


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()


def _new_id() -> str:
    return "u" + secrets.token_hex(6)


def register(username: str, password: str, level: int = 1, guest_id: str | None = None) -> dict:
    username = (username or "").strip()
    if not USER_RE.match(username):
        raise ValueError("用户名 2–20 个字符，只能用中英文、数字、下划线")
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")
    if db.one("SELECT id FROM account WHERE username = ?", (username,)):
        raise ValueError("这个用户名已经被注册了")

    salt = secrets.token_hex(16)
    aid = _new_id()
    now = time.time()
    with db.db() as conn:
        conn.execute(
            "INSERT INTO account(id, username, pw_hash, salt, created_at) VALUES(?,?,?,?,?)",
            (aid, username, _hash(password, salt), salt, now),
        )
        conn.execute(
            "INSERT INTO learner(id, name, level, created_at) VALUES(?,?,?,?)",
            (aid, username, level, now),
        )
    if guest_id and guest_id != aid:
        merge_guest(aid, guest_id)
    token = _new_session(aid)
    return {"token": token, "account": {"id": aid, "username": username, "level": level}}


def login(username: str, password: str) -> dict:
    row = db.one("SELECT * FROM account WHERE username = ?", ((username or "").strip(),))
    if row is None or _hash(password or "", row["salt"]) != row["pw_hash"]:
        raise ValueError("用户名或密码不对")
    token = _new_session(row["id"])
    learner = db.ensure_learner(row["id"], 1, row["username"])
    return {"token": token, "account": {"id": row["id"], "username": row["username"], "level": learner["level"]}}


def _new_session(account_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    with db.db() as conn:
        conn.execute(
            "INSERT INTO session(token, account_id, created_at, last_seen) VALUES(?,?,?,?)",
            (token, account_id, now, now),
        )
    return token


def account_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    row = db.one(
        "SELECT a.id, a.username, a.created_at FROM session s JOIN account a ON a.id = s.account_id WHERE s.token = ?",
        (token,),
    )
    if row is None:
        return None
    db.execute("UPDATE session SET last_seen = ? WHERE token = ?", (time.time(), token))
    learner = db.one("SELECT * FROM learner WHERE id = ?", (row["id"],))
    return {"id": row["id"], "username": row["username"], "level": learner["level"] if learner else 1}


def logout(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM session WHERE token = ?", (token,))


def merge_guest(account_id: str, guest_id: str) -> int:
    """把游客期间的练习记录并入新账号，返回迁移的作答数。"""
    if not guest_id or guest_id == account_id:
        return 0
    with db.db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM attempt WHERE learner_id = ?", (guest_id,)).fetchone()["c"]
        conn.execute("UPDATE OR IGNORE lesson_read SET learner_id=? WHERE learner_id=?", (account_id, guest_id))
        conn.execute("UPDATE OR IGNORE coach_state SET learner_id=? WHERE learner_id=?", (account_id, guest_id))
        conn.execute("UPDATE attempt SET learner_id = ? WHERE learner_id = ?", (account_id, guest_id))
        conn.execute("UPDATE review_log SET learner_id = ? WHERE learner_id = ?", (account_id, guest_id))
        # 知识点掌握度简单取「有记录的优先并入」，重复的不叠加
        rows = conn.execute("SELECT * FROM kp_state WHERE learner_id = ?", (guest_id,)).fetchall()
        for r in rows:
            exist = conn.execute(
                "SELECT seen FROM kp_state WHERE learner_id = ? AND kp_id = ?", (account_id, r["kp_id"])
            ).fetchone()
            if exist is None:
                conn.execute(
                    "INSERT INTO kp_state(learner_id, kp_id, seen, correct, streak, last_seen, due_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (account_id, r["kp_id"], r["seen"], r["correct"], r["streak"], r["last_seen"], r["due_at"]),
                )
            else:
                conn.execute(
                    "UPDATE kp_state SET seen = seen + ?, correct = correct + ? WHERE learner_id = ? AND kp_id = ?",
                    (r["seen"], r["correct"], account_id, r["kp_id"]),
                )
        conn.execute("DELETE FROM kp_state WHERE learner_id = ?", (guest_id,))
    return n
