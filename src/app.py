"""chess-coach 本地服务：本地档案 + 教程 + 题库 + PGN 复盘。

纯前后端。复盘里的「更优走法」由本地 Stockfish 引擎给出（传统搜索引擎，不是语言模型）；
没有引擎文件时会自动退回纯规则检测。
"""

from __future__ import annotations

import logging
import os
import time
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import coach, db, demos, engine, knowledge, motifs, openings, puzzles, review, similar
from . import learning, move_explanation

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


def _configure_logging():
    """Agent 排错日志写到 data/logs，按大小滚动，避免无限增长。"""
    log_dir = os.path.join(ROOT, "data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("chess_coach")
    if any(getattr(handler, "_chess_coach_handler", False) for handler in logger.handlers):
        return
    handler = RotatingFileHandler(os.path.join(log_dir, "agent.log"),
                                  maxBytes=2 * 1024 * 1024, backupCount=3,
                                  encoding="utf-8")
    handler._chess_coach_handler = True
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


_configure_logging()
app = FastAPI(title="chess-coach")
app.include_router(learning.router)
db.init_db()
coach.init()
db.ensure_learner(db.local_learner_id())


class AttemptIn(BaseModel):
    puzzle_id: str
    correct: bool
    ms: int = 0
    kp_ids: list[str] = []


class LevelIn(BaseModel):
    level: int


class ReviewIn(BaseModel):
    pgn: str
    color: str = "auto"
    depth: int = 16


# ---------------------------------------------------------------- 学员画像


@app.get("/api/bootstrap")
def bootstrap():
    learner_id = db.local_learner_id()
    learner = db.ensure_learner(learner_id)
    progress = db.kp_progress(learner_id)
    read_lessons = {r["lesson_id"] for r in db.query("SELECT lesson_id FROM lesson_read WHERE learner_id=?", (learner_id,))}
    lessons = []
    for lv in knowledge.LEVELS:
        lessons.append(
            {
                **lv,
                "lessons": [
                    {
                        "id": l["id"],
                        "title": l["title"],
                        "order": l["order"],
                        "kps": l["kps"],
                        "intro": l["intro"],
                        "done": l["id"] in read_lessons,
                    }
                    for l in knowledge.lessons_for_level(lv["id"])
                ],
            }
        )
    return {
        "learner": learner,
        "tutorials_published": knowledge.TUTORIALS_PUBLISHED,
        "practice_themes": [row["theme"] for row in db.query(
            "SELECT DISTINCT theme FROM puzzle_theme ORDER BY theme"
        )],
        "levels": lessons,
        "progress": progress,
        "stats": db.stats(learner_id),
        "kps": [
            {k: v for k, v in kp.items() if k in ("id", "name", "level", "group", "summary", "prereq", "themes")}
            for kp in knowledge.VISIBLE_KPS
        ],
        "puzzle_total": (db.one("SELECT COUNT(*) c FROM puzzle") or {"c": 0})["c"],
        "engine": engine.info(),
    }


@app.post("/api/level")
def set_level(body: LevelIn):
    if body.level not in (1, 2, 3):
        raise HTTPException(400, "level 必须是 1/2/3")
    lid = db.local_learner_id()
    db.ensure_learner(lid)
    db.set_level(lid, body.level)
    return {"learner": db.ensure_learner(lid, body.level)}


# ---------------------------------------------------------------- 课程


@app.get("/api/lessons/{lesson_id}")
def lesson(lesson_id: str):
    meta = knowledge.LESSON_BY_ID.get(lesson_id)
    if not meta:
        raise HTTPException(404, "没有这一课")
    lid = db.local_learner_id()
    learner = db.ensure_learner(lid)
    level = learner["level"]

    demo = None if lesson_id in {"l1-7","l2-7","l3-2","l3-3","l3-4"} else demos.for_lesson(lesson_id)
    out_meta = dict(meta)
    if demo:
        out_meta["example"] = demo

    quiz_spec = meta.get("quiz") or {}
    quiz = []
    if quiz_spec.get("count"):
        # 同一课、同一档的验收题是固定的，讲解与题目才对得上
        skip = [demo["source"]["puzzle_id"]] if demo else []
        quiz = puzzles.pick(
            quiz_spec.get("kps") or meta["kps"],
            level,
            limit=quiz_spec["count"],
            exclude=skip,
            seed=f"{lesson_id}:{level}",
        )
    return {
        "lesson": out_meta,
        "kps": [knowledge.KP_BY_ID[k] for k in meta["kps"]],
        "quiz": quiz,
        "level": level,
    }


@app.get("/api/practice")
def practice(level: int = 1, kp: str = "", count: int = 8):
    lid = db.local_learner_id()
    kp_ids = [k for k in kp.split(",") if k] or [k["id"] for k in knowledge.kps_for_level(level)]
    if not kp_ids:
        raise HTTPException(400, "没有可用的知识点")
    studied = db.studied_puzzles(lid)
    items = puzzles.pick(kp_ids, level, limit=count, exclude=studied if count < 12 else ())
    return {"puzzles": items, "kp_ids": kp_ids, "level": level}


@app.get("/api/puzzles/{puzzle_id}")
def get_puzzle(puzzle_id: str):
    item = puzzles.by_id(puzzle_id)
    if not item:
        raise HTTPException(404, "没有这道题")
    kp_ids = []
    for t in item["themes"]:
        kp_ids.extend(knowledge.THEME_TO_KPS.get(t, []))
    item["kp_ids"] = sorted(set(kp_ids))
    return item


@app.post("/api/attempt")
def attempt(body: AttemptIn):
    lid = db.local_learner_id()
    kp_ids = body.kp_ids
    if not kp_ids:
        item = puzzles.by_id(body.puzzle_id)
        if item:
            for t in item["themes"]:
                kp_ids.extend(knowledge.THEME_TO_KPS.get(t, []))
    progress = db.record_attempt(lid, body.puzzle_id, body.correct, body.ms, sorted(set(kp_ids)))
    return {"ok": True, "progress": progress, "stats": db.stats(lid)}


# ---------------------------------------------------------------- 复盘


@app.post("/api/review")
def do_review(body: ReviewIn):
    lid = db.local_learner_id()
    learner = db.ensure_learner(lid)
    if not body.pgn.strip():
        raise HTTPException(400, "PGN 是空的")
    depth = max(10, min(19, body.depth))
    try:
        result = review.analyze_pgn(
            body.pgn,
            body.color,
            lid,
            learner["level"],
            engine_depth=depth,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"解析失败：{exc}")

    focus = result["focus"]
    for slot in ("review", "new"):
        entry = focus.get(slot)
        if not entry:
            continue
        entry["kp"] = knowledge.VISIBLE_KP_BY_ID.get(entry["kp_id"])
        entry["puzzles"] = puzzles.sample_for_review(entry["kp_id"], learner["level"], lid, 3)

    for f in result["findings"]:
        f["kp_name"] = knowledge.KP_BY_ID[f["kp_id"]]["name"]
    for t in result["turning_points"]:
        query = t.get("similar_query")
        if not query and t.get("best"):
            best = t["best"]
            query = {"fen": t["fen"], "uci": best["uci"], "pv": best.get("pv_uci")}
        t["similar_puzzles"] = similar.recommend(**query) if query else []
        if t.get("kp_id") and t["kp_id"] in knowledge.KP_BY_ID:
            t["kp_name"] = knowledge.KP_BY_ID[t["kp_id"]]["name"]
        else:
            t["kp_name"] = None

    review_id = db.save_review(lid, {
        "headers": result["headers"],
        "result": result["result"],
        "stats": result["stats"],
        "opening": openings.identify(result["moves"]),
        "player": result["player"],
        "verified_topics": sorted({f["kp_id"] for f in result["findings"]}),
        "focus": [f.get("kp_id") for f in [result["focus"].get("review"), result["focus"].get("new")] if f],
    }, body.pgn, body.color, depth, result)
    result["id"] = review_id
    return result


@app.get("/api/review/recent")
def recent():
    lid = db.local_learner_id()
    return {"items": db.recent_reviews(lid, 8)}


@app.get("/api/review/saved")
def saved_reviews():
    return {"items": db.saved_reviews(db.local_learner_id())}


@app.get("/api/review/saved/{review_id}")
def saved_review(review_id: int):
    entry = db.saved_review(db.local_learner_id(), review_id)
    if entry is None:
        raise HTTPException(404, "没有这盘复盘")
    if not knowledge.TUTORIALS_PUBLISHED:
        for focus in (entry["res"].get("focus") or {}).values():
            if isinstance(focus, dict):
                focus.pop("kp", None)
    return entry


class ReviewPlyIn(BaseModel):
    ply: int = Field(ge=0)


@app.post("/api/review/saved/{review_id}/position")
def save_review_position(review_id: int, body: ReviewPlyIn):
    if not db.update_review_ply(db.local_learner_id(), review_id, body.ply):
        raise HTTPException(404, "没有这盘复盘")
    return {"ok": True}


@app.delete("/api/review/saved/{review_id}")
def delete_review(review_id: int):
    if not db.delete_review(db.local_learner_id(), review_id):
        raise HTTPException(404, "没有这盘复盘")
    return {"ok": True}


# ---------------------------------------------------------------- 杂项


@app.get("/api/engine")
def engine_info():
    return engine.info()


@app.get("/api/health")
def health():
    total = db.one("SELECT COUNT(*) c FROM puzzle")
    return {"ok": True, "puzzles": total["c"], "engine": engine.info()["available"], "time": time.time()}


class BranchIn(BaseModel):
    initial: str = Field(max_length=120)
    history: list[str] = Field(max_length=800)
    depth: int = Field(default=19, ge=10, le=19)


@app.post("/api/analysis/position")
def position(body: BranchIn):
    try:
        return engine.analyse_branch(body.initial, body.history, depth=body.depth)
    except ValueError as exc:
        raise HTTPException(400, "局面或变化走法非法") from exc


class MoveExplanationIn(BaseModel):
    fen: str = Field(max_length=120)
    recommended: str = Field(min_length=4, max_length=5)
    played: str = Field(min_length=4, max_length=5)
    initial: str | None = Field(default=None, max_length=120)
    history: list[str] = Field(default_factory=list, max_length=800)
    depth: int = Field(default=19, ge=10, le=19)


@app.post("/api/analysis/explain-move")
def explain_move(body: MoveExplanationIn):
    try:
        return move_explanation.explain(
            body.fen, body.recommended, body.played, initial=body.initial, history=body.history, depth=body.depth
        )
    except ValueError as exc:
        raise HTTPException(400, "局面或走法非法，且两手走法必须不同") from exc


class PositionDecodeIn(BranchIn):
    candidate: str | None = Field(default=None, max_length=16)


@app.post("/api/analysis/decode-position")
def decode_position(body: PositionDecodeIn):
    try:
        return move_explanation.explain_position(
            body.initial, body.history, body.candidate, body.depth
        )
    except ValueError as exc:
        raise HTTPException(400, "局面、棋步历史或候选着非法") from exc


class StaticFeaturesIn(BaseModel):
    fen: str = Field(max_length=120)


@app.post("/api/static-features")
def static_review_features(body: StaticFeaturesIn):
    from .review_features import inspect_static
    try:
        return inspect_static(body.fen)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class SimilarIn(BaseModel):
    fen: str = Field(max_length=120)
    uci: str = Field(max_length=5)
    pv: list[str] = Field(default_factory=list,max_length=8)


@app.post("/api/analysis/similar")
def similar_positions(body: SimilarIn):
    try:
        return {"puzzles": similar.recommend(body.fen, body.uci, body.pv)}
    except ValueError as exc:
        raise HTTPException(400, "局面或走法非法") from exc


@app.get("/api/openings")
def opening_list():
    return openings.PUBLISHED_OPENINGS


@app.get("/api/library")
def library(kp: str = "", theme: str = "",
            opening: str = "", studied: str = "", lo: int = 0, hi: int = 4000,
            after: str = "", limit: int = Query(24, ge=1, le=80)):
    filters = ["p.rating BETWEEN ? AND ?"]
    args = [lo, hi]
    if kp:
        tags = puzzles.themes_for_kps([kp])
        if not tags:
            return {"items": [], "next": None, "total": 0}
        marks = ",".join("?" for _ in tags)
        filters.append(f"EXISTS (SELECT 1 FROM puzzle_theme t WHERE t.puzzle_id=p.id AND t.theme IN ({marks}))")
        args.extend(tags)
    if theme:
        filters.append("EXISTS (SELECT 1 FROM puzzle_theme t WHERE t.puzzle_id=p.id AND t.theme=?)")
        args.append(theme)
    if opening.strip():
        filters.append("instr(lower(p.opening_tags), lower(?))>0")
        args.append(opening.strip())
    if studied in ("seen", "new"):
        prefix = "NOT " if studied == "new" else ""
        filters.append(prefix + "EXISTS (SELECT 1 FROM attempt a WHERE a.puzzle_id=p.id AND a.learner_id=?)")
        args.append(db.local_learner_id())
    where = " AND ".join(filters)
    total = db.one(f"SELECT COUNT(*) c FROM puzzle p WHERE {where}", args)["c"]
    rows = db.query(f"SELECT p.* FROM puzzle p WHERE {where} AND p.id>? ORDER BY p.id LIMIT ?",
                    (*args, after, limit+1))
    return {"items": [{k: r[k] for k in ("id","rating","themes","opening_tags")} for r in rows[:limit]],
            "next": rows[limit-1]["id"] if len(rows)>limit else None,"total":total}


@app.get("/api/knowledge/{kp_id}")
def concept(kp_id: str):
    item = knowledge.VISIBLE_KP_BY_ID.get(kp_id)
    if not item:
        raise HTTPException(404, "没有这个知识点")
    return {"kp": item, "lessons": [l for l in coach.catalog() if kp_id in l["kps"]]}


class CoachIn(BaseModel):
    message: str = Field(min_length=1,max_length=1500)


class TaskIn(BaseModel):
    task_id: str
    done: bool


@app.get("/api/coach")
def coach_state():
    if not knowledge.TUTORIALS_PUBLISHED:
        return {"tutorials_published": False, "ai_available": False}
    return {**coach.load(db.local_learner_id()), "ai_available": coach.available(), "ai_provider": coach.provider()}


@app.post("/api/coach")
def coach_message(body: CoachIn):
    if not knowledge.TUTORIALS_PUBLISHED:
        raise HTTPException(409, "课程推荐暂时关闭")
    if not body.message.strip():
        raise HTTPException(400, "请输入学习需求")
    return coach.request(db.local_learner_id(), body.message)


@app.post("/api/coach/task")
def coach_task(body: TaskIn):
    if not knowledge.TUTORIALS_PUBLISHED:
        raise HTTPException(409, "课程推荐暂时关闭")
    try:
        return coach.complete(db.local_learner_id(), body.task_id, body.done)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@app.post("/api/lessons/{lesson_id}/read")
def mark_read(lesson_id: str, body: LevelIn):
    if lesson_id not in knowledge.LESSON_BY_ID:
        raise HTTPException(404,"没有这一课")
    lid = db.local_learner_id()
    db.execute("INSERT OR IGNORE INTO lesson_read VALUES(?,?,?)", (lid,lesson_id,time.time()))
    return {"ok":True}


@app.post("/api/coach/resume")
def resume_coach(body: LevelIn):
    if not knowledge.TUTORIALS_PUBLISHED:
        raise HTTPException(409, "课程推荐暂时关闭")
    try:
        return coach.resume(db.local_learner_id())
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@app.delete("/api/coach/memory")
def clear_coach():
    db.execute("DELETE FROM coach_state WHERE learner_id=?", (db.local_learner_id(),))
    return {"ok":True}


INDEX = os.path.join(WEB, "index.html")


@app.get("/")
def index():
    return FileResponse(INDEX)


app.mount("/static", StaticFiles(directory=WEB), name="static")
