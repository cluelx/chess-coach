"""Local review laboratory. Run: python scripts/review_lab.py --port 8770.

Independent cache and server; the production database is opened read-only.
Each continuation ply uses a fresh single-PV depth search with full history.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import queue
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import chess
import chess.engine
import chess.pgn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from src.engine import find_binary
from src.move_explanation import _CONCEPTS

DIRECTORY = ROOT / "data/review-lab"
CACHE = DIRECTORY / "cache.sqlite3"
LIBRARY = ROOT / "vendor/binprop/binary_properties/motifs/chess/claude-opus-5.json"
VERSION = "lab-v1-full-history-cold-single-pv"
DEPTHS = (10, 12, 16, 19)
SCHEMES = {"main": (0, 0), "old8": (8, 0), "3x2": (3, 2), "5x3": (5, 3)}


def dump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def connection():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(CACHE, timeout=60)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=60000")
    return c


def initialize():
    with connection() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS searches(id TEXT PRIMARY KEY,depth INTEGER,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS results(game TEXT,ply INTEGER,depth INTEGER,payload TEXT NOT NULL,
          PRIMARY KEY(game,ply,depth));
        CREATE TABLE IF NOT EXISTS progress(depth INTEGER PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS notes(game TEXT,ply INTEGER,depth INTEGER,payload TEXT NOT NULL,
          PRIMARY KEY(game,ply,depth));
        """)


@functools.lru_cache(maxsize=1)
def snapshot():
    with sqlite3.connect(f"file:{(ROOT / 'data/chess_coach.db').as_posix()}?mode=ro", uri=True) as c:
        row = c.execute("SELECT review_id,pgn,analysis FROM review_detail ORDER BY review_id DESC LIMIT 1").fetchone()
    if not row:
        raise RuntimeError("数据库没有保存棋谱")
    game = chess.pgn.read_game(io.StringIO(row[1]))
    if game is None or game.errors:
        raise RuntimeError(f"PGN读取失败: {getattr(game, 'errors', None)}")
    analysis = json.loads(row[2])
    binary = find_binary()
    if not binary:
        raise RuntimeError("没有找到Stockfish")
    engine_hash = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    library_hash = hashlib.sha256(LIBRARY.read_bytes()).hexdigest()
    identity = hashlib.sha256((VERSION + row[1] + engine_hash + library_hash).encode()).hexdigest()[:24]
    board = game.board()
    initial, moves = board.fen(), []
    turns = {x["ply"] for x in analysis.get("turning_points", [])}
    for ply, move in enumerate(game.mainline_moves(), 1):
        moves.append(dict(ply=ply, fen=board.fen(), uci=move.uci(), san=board.san(move),
                          move_no=board.fullmove_number, side=chess.COLOR_NAMES[board.turn],
                          turning=ply in turns))
        board.push(move)
    payload = dict(id=identity, review_id=row[0], pgn=row[1], initial=initial, moves=moves,
                   engine_sha256=engine_hash, library_sha256=library_hash, version=VERSION,
                   library_count=len(json.loads(LIBRARY.read_text(encoding="utf-8"))["motifs"]),
                   depths=DEPTHS, schemes=list(SCHEMES), max_rounds=12,
                   search_policy="每手独立冷启动搜索，保留完整历史；仅使用PV第一着；Threads=1 Hash=96MB")
    with connection() as c:
        c.execute("INSERT OR IGNORE INTO games VALUES(?,?)", (identity, dump(payload)))
    return payload


def update_progress(depth, **values):
    values.update(depth=depth, updated=time.time())
    with connection() as c:
        c.execute("INSERT OR REPLACE INTO progress VALUES(?,?)", (depth, dump(values)))


class Paused(Exception):
    pass


class ColdUCI:
    """Synchronous UCI pipes avoid the host's hanging asyncio subprocess transport."""
    def __init__(self):
        self.process = subprocess.Popen([find_binary()], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.output = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.output.put(line.strip())
            self.output.put(None)
        threading.Thread(target=read, daemon=True).start()
        self.send("uci")
        self.until("uciok", 20)
        self.send("setoption name Threads value 1")
        self.send("setoption name Hash value 96")

    def send(self, command):
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def receive(self, timeout):
        try:
            line = self.output.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("Stockfish未及时返回；本次搜索不记为成功") from exc
        if line is None:
            raise RuntimeError("Stockfish进程意外退出")
        return line

    def until(self, marker, timeout):
        deadline = time.monotonic() + timeout
        while not self.receive(max(.01, deadline - time.monotonic())).startswith(marker):
            pass

    def analyse(self, board, depth, multipv):
        self.send(f"setoption name MultiPV value {multipv}")
        self.send("ucinewgame")  # Clear hash before every uncached query.
        self.send("isready")
        self.until("readyok", 30)
        history = " ".join(m.uci() for m in board.move_stack)
        self.send(f"position fen {board.root().fen()}" + (f" moves {history}" if history else ""))
        self.send(f"go depth {depth}")
        latest = {}
        deadline = time.monotonic() + 3600
        while True:
            line = self.receive(max(.01, deadline - time.monotonic()))
            if line.startswith("bestmove"):
                break
            if not line.startswith("info ") or " pv " not in line or " score " not in line:
                continue
            info = chess.engine._parse_uci_info(line[5:], board, chess.engine.INFO_ALL)
            latest[info.get("multipv", 1)] = info
        return [latest[k] for k in sorted(latest)]

    def quit(self):
        try:
            self.send("quit")
            self.process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.process.kill()
            self.process.wait(timeout=5)


class Calculator:
    def __init__(self, game, depth):
        self.game, self.depth = game, depth
        self.engine = ColdUCI()
        self.engine_hash = game["engine_sha256"]
        self.ply = 0
        sys.path.insert(0, str(ROOT / "vendor/binprop"))
        from binary_properties.games.chess import compile_motif
        from binary_properties.io import load_library
        self.motifs = [(m, compile_motif(m.source)) for m in load_library(LIBRARY).motifs]
        self.concept_cache = {}

    def check_pause(self):
        with connection() as c:
            row = c.execute("SELECT value FROM settings WHERE key='paused'").fetchone()
        if row and row[0] == "1":
            raise Paused()

    def search(self, board, multipv=1):
        self.check_pause()
        key = hashlib.sha256(dump([VERSION, self.engine_hash, self.depth, multipv,
                                  board.root().fen(), [m.uci() for m in board.move_stack]]).encode()).hexdigest()
        with connection() as c:
            row = c.execute("SELECT payload FROM searches WHERE id=?", (key,)).fetchone()
        if row:
            return key, json.loads(row[0])
        update_progress(self.depth, status="running", ply=self.ply, multipv=multipv,
                        fen=board.fen(), message="搜索新局面", search_started=time.time())
        started = time.perf_counter()
        infos = self.engine.analyse(board, self.depth, multipv)
        seconds = time.perf_counter() - started
        if isinstance(infos, dict):
            infos = [infos]
        rows = []
        for info in infos:
            if not info.get("pv"):
                continue
            score = info["score"].white()
            rows.append(dict(uci=info["pv"][0].uci(), cp=score.score(), mate=score.mate(),
                             depth=info.get("depth"), seldepth=info.get("seldepth"),
                             nodes=info.get("nodes", 0), engine_seconds=info.get("time", 0),
                             lowerbound=bool(info.get("lowerbound")), upperbound=bool(info.get("upperbound"))))
        if not rows or any((r["depth"] or 0) < self.depth and r["mate"] is None for r in rows):
            raise RuntimeError("搜索未达到请求深度，未写入成功缓存")
        payload = dict(seconds=seconds, multipv=multipv, rows=rows, fen=board.fen(),
                       history=[m.uci() for m in board.move_stack], root=board.root().fen(),
                       requested_depth=self.depth, cold=True)
        with connection() as c:
            c.execute("INSERT OR IGNORE INTO searches VALUES(?,?,?)", (key, self.depth, dump(payload)))
        return key, payload

    def concepts(self, fen, color):
        key = fen, color
        if key not in self.concept_cache:
            self.concept_cache[key] = [m.name for m, compiled in self.motifs if compiled.evaluate(fen, color)]
        return self.concept_cache[key]

    def line(self, root, prefix, references):
        board = root.copy()
        path, searches = list(prefix), list(references)
        for uci in prefix:
            board.push_uci(uci)
        while len(path) < 24 and not board.is_game_over():
            key, info = self.search(board, 1)
            uci = info["rows"][0]["uci"]
            path.append(uci)
            searches.append(key)
            board.push_uci(uci)
        replay, frames, san, checks, captures = root.copy(), [root.fen()], [], [], []
        balance = lambda b: sum(v * (len(b.pieces(p, root.turn)) - len(b.pieces(p, not root.turn)))
                               for p, v in ((1, 1), (2, 3), (3, 3), (4, 5), (5, 9)))
        material = [balance(replay)]
        mover, opponent = chess.COLOR_NAMES[root.turn], chess.COLOR_NAMES[not root.turn]
        rounds = []
        for n, uci in enumerate(path, 1):
            move = replay.parse_uci(uci)
            side = chess.COLOR_NAMES[replay.turn]
            if replay.is_capture(move):
                piece = chess.PAWN if replay.is_en_passant(move) else replay.piece_type_at(move.to_square)
                captures.append(dict(ply=n, side=side, target=piece))
            check = replay.gives_check(move)
            san.append(replay.san(move))
            replay.push(move)
            if check:
                checks.append(dict(ply=n, side=side, kind="mate" if replay.is_checkmate() else "check"))
            frames.append(replay.fen())
            material.append(balance(replay))
            if n % 2 == 0:
                rounds.append(dict(round=n // 2, own=self.concepts(replay.fen(), mover),
                                   opponent=self.concepts(replay.fen(), opponent)))
        return dict(uci=path, san=san, frames=frames, rounds=rounds, checks=checks,
                    captures=captures, material=material, searches=list(dict.fromkeys(searches)),
                    terminal=replay.is_game_over(), outcome=replay.result() if replay.is_game_over() else None)

    def calculate(self, move):
        self.ply = move["ply"]
        self.check_pause()
        root = chess.Board(self.game["initial"])
        for previous in self.game["moves"][:self.ply - 1]:
            root.push_uci(previous["uci"])
        started = time.perf_counter()
        root_key, best = self.search(root)
        recommended = best["rows"][0]["uci"]
        data = dict(ply=self.ply, depth=self.depth, recommended=recommended, played=move["uci"],
                    roots={}, root_search=root_key, created=time.time(), concept_errors=[], complete=False)
        # A scheme is committed independently so a long MultiPV search doesn't hide completed lines.
        for first in dict.fromkeys([recommended, move["uci"]]):
            group = dict(lines={}, schemes={})
            data["roots"][first] = group
            def save_line(prefix, refs):
                line_id = " ".join(prefix)
                if line_id not in group["lines"]:
                    group["lines"][line_id] = self.line(root, prefix, refs)
                return line_id
            main_id = save_line([first], [root_key])
            group["schemes"]["main"] = [main_id]
            self.save(data, started)
            after = root.copy()
            after.push_uci(first)
            if after.is_game_over():
                for scheme in ("3x2", "old8", "5x3"):
                    group["schemes"][scheme] = [main_id]
                self.save(data, started)
                continue
            for scheme in ("3x2", "old8", "5x3"):
                count, second_count = SCHEMES[scheme]
                key, candidates = self.search(after, count)
                choices = [r["uci"] for r in candidates["rows"]]
                if scheme == "old8":
                    # Reproduce the old implementation: force single-PV best into the first eight.
                    best_reply = group["lines"][main_id]["uci"][1]
                    choices = list(dict.fromkeys([best_reply, *choices]))[:8]
                ids = []
                for reply in choices:
                    if scheme == "old8" and reply == group["lines"][main_id]["uci"][1]:
                        ids.append(main_id)
                        continue
                    prefix, refs = [first, reply], [root_key, key]
                    next_board = after.copy()
                    next_board.push_uci(reply)
                    if second_count and not next_board.is_game_over():
                        own_key, own = self.search(next_board)
                        own_move = own["rows"][0]["uci"]
                        prefix.append(own_move)
                        refs.append(own_key)
                        next_board.push_uci(own_move)
                        if not next_board.is_game_over():
                            second_key, second = self.search(next_board, second_count)
                            ids += [save_line([*prefix, r["uci"]], [*refs, second_key]) for r in second["rows"]]
                            continue
                    ids.append(save_line(prefix, refs))
                group["schemes"][scheme] = ids
                self.save(data, started)
        data["complete"] = True
        self.save(data, started)
        update_progress(self.depth, status="running", ply=self.ply, message="本局面全部方案已完成")

    def save(self, data, started):
        data["build_seconds"] = time.perf_counter() - started
        with connection() as c:
            c.execute("INSERT OR REPLACE INTO results VALUES(?,?,?,?)",
                      (self.game["id"], self.ply, self.depth, dump(data)))


def worker(depth):
    initialize()
    game = snapshot()
    calc = None
    try:
        calc = Calculator(game, depth)
        # First make late tactical turning points available, then all remaining plies.
        order = sorted(game["moves"], key=lambda m: (not m["turning"], -m["ply"]))
        for move in order:
            with connection() as c:
                row = c.execute("SELECT payload FROM results WHERE game=? AND ply=? AND depth=?",
                                (game["id"], move["ply"], depth)).fetchone()
            if row and json.loads(row[0]).get("complete"):
                continue
            calc.calculate(move)
        update_progress(depth, status="complete", message="整盘所有方案已完成")
    except Paused:
        update_progress(depth, status="paused", message="已暂停；搜索缓存已保存")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        update_progress(depth, status="error", message=f"{type(exc).__name__}: {exc}")
    finally:
        if calc:
            calc.engine.quit()


initialize()
app = FastAPI(title="复盘测试实验室")
processes = {}
process_lock = threading.Lock()


@app.get("/")
def index():
    return FileResponse(ROOT / "web/review-lab/index.html")


@app.get("/api/game")
def get_game():
    return snapshot()


@app.get("/api/status")
def status():
    game = snapshot()
    with connection() as c:
        results = [dict(ply=r["ply"], depth=r["depth"], complete=json.loads(r["payload"]).get("complete", False),
                        schemes={k: list(v["schemes"]) for k, v in json.loads(r["payload"])["roots"].items()})
                   for r in c.execute("SELECT ply,depth,payload FROM results WHERE game=?", (game["id"],))]
        progress = [json.loads(r[0]) for r in c.execute("SELECT payload FROM progress")]
        searches = [dict(r) for r in c.execute("SELECT depth,count(*) AS count FROM searches GROUP BY depth")]
    for p in progress:
        if p["depth"] in processes and processes[p["depth"]].poll() is not None and p["status"] == "running":
            p.update(status="interrupted", message="计算进程已退出，可续算")
    return dict(results=results, progress=progress, searches=searches, target=len(game["moves"]) * 4)


@app.get("/api/result/{ply}/{depth}")
def result(ply: int, depth: int):
    game = snapshot()
    with connection() as c:
        row = c.execute("SELECT payload FROM results WHERE game=? AND ply=? AND depth=?", (game["id"], ply, depth)).fetchone()
    if not row:
        raise HTTPException(404, "尚未计算这个局面")
    payload = json.loads(row[0])
    keys = set([payload["root_search"]])
    for group in payload["roots"].values():
        for line in group["lines"].values():
            keys.update(line["searches"])
    with connection() as c:
        payload["searches"] = {key: json.loads(row[0]) for key in keys
                               if (row := c.execute("SELECT payload FROM searches WHERE id=?", (key,)).fetchone())}
    return payload


@app.get("/api/concepts")
def concepts():
    return dict(translations=_CONCEPTS, motifs=[dict(name=m["name"], delta=m["delta"], description=m["description"])
                                             for m in json.loads(LIBRARY.read_text(encoding="utf-8"))["motifs"]])


class EvidenceIn(BaseModel):
    fen: str = Field(max_length=120)
    color: str = Field(pattern="^(white|black)$")
    rule: str = Field(max_length=180)


@app.post("/api/evidence")
def evidence(body: EvidenceIn):
    from src.review_evidence import inspect_rule
    try:
        return inspect_rule(body.fen, body.color, body.rule)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class RelationsIn(BaseModel):
    fen: str = Field(max_length=120)


@app.post("/api/evidence/relations")
def evidence_relations(body: RelationsIn):
    import chess
    from src.review_evidence import relations
    try:
        board = chess.Board(body.fen)
        return [relations(board, sq) for sq in chess.SQUARES]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/static-features")
def static_features(body: RelationsIn):
    from src.review_features import inspect_static
    try:
        return inspect_static(body.fen)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class ComputeIn(BaseModel):
    depths: list[int] = Field(default_factory=lambda: list(DEPTHS))


@app.post("/api/start")
def start(body: ComputeIn):
    if any(d not in DEPTHS for d in body.depths):
        raise HTTPException(400, "只支持10、12、16、19")
    with process_lock:
        with connection() as c:
            c.execute("INSERT OR REPLACE INTO settings VALUES('paused','0')")
        for depth in body.depths:
            if depth in processes and processes[depth].poll() is None:
                continue
            log = open(DIRECTORY / f"depth-{depth}.log", "a", encoding="utf-8")
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            try:
                processes[depth] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--worker", str(depth)],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            finally:
                log.close()
            update_progress(depth, status="starting", message="准备计算或断点续算")
    return {"status": "started"}


@app.post("/api/pause")
def pause():
    with connection() as c:
        c.execute("INSERT OR REPLACE INTO settings VALUES('paused','1')")
    return {"status": "pausing", "message": "当前一次深度搜索结束后暂停"}


class NoteIn(BaseModel):
    payload: dict


@app.put("/api/notes/{ply}/{depth}")
def note(ply: int, depth: int, body: NoteIn):
    game = snapshot()
    with connection() as c:
        c.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?,?)", (game["id"], ply, depth, dump(body.payload)))
    return {"status": "saved"}


@app.get("/api/notes/{ply}/{depth}")
def get_note(ply: int, depth: int):
    game = snapshot()
    with connection() as c:
        row = c.execute("SELECT payload FROM notes WHERE game=? AND ply=? AND depth=?", (game["id"], ply, depth)).fetchone()
    return json.loads(row[0]) if row else {}


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=int, choices=DEPTHS)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--compute", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
    else:
        if args.compute:
            start(ComputeIn())
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port)
