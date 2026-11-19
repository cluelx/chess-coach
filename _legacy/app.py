import io
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import chess
import chess.engine
import chess.pgn
import chess.svg
from coach import model_json, reconstruct, teach
import subprocess


def pack(node):
    board = node.board()
    return dict(fen=board.fen(), move=node.san() if node.parent else "起始局面",
                uci=node.move.uci() if node.parent else None, original=True,
                comment=node.comment, children=[pack(child) for child in node.variations])


def analyze(board, move=None):
    if board.is_game_over():
        return []
    path = os.getenv("STOCKFISH_PATH", r"D:\stockfish\stockfish-windows-x86-64-avx2.exe")
    with chess.engine.SimpleEngine.popen_uci(path, timeout=8) as engine:
        limit = chess.engine.Limit(depth=15, time=0.75)
        results = engine.analyse(board, limit, multipv=3)
        if move and all(not r.get("pv") or r["pv"][0] != move for r in results):
            results += engine.analyse(board, limit, multipv=1, root_moves=[move])
    lines = []
    for result in results:
        pv = result.get("pv", [])[:8]
        if not pv:
            continue
        replay = board.copy()
        steps = []
        for step in pv:
            if step not in replay.legal_moves:
                raise ValueError("引擎变化未通过合法性检查")
            san = replay.san(step)
            capture = replay.is_capture(step)
            replay.push(step)
            steps.append(dict(san=san, uci=step.uci(), fen=replay.fen(),
                              capture=capture, check=replay.is_check(), mate=replay.is_checkmate()))
        score = result["score"].white()
        value = f"白方视角 {score.score()/100:+.2f}" if not score.is_mate() else f"白方视角将杀 {score.mate():+d}"
        lines.append(dict(steps=steps, score=value, actual=pv[0] == move))
    return lines


def review(data):
    board = reconstruct(data)
    mode = data["mode"]
    question = data.get("question", "")[:1200]
    history = [str(item)[:350] for item in data.get("context", [])[-4:]]
    if mode == "hint":
        return teach(board, [{}], question, hint=True)
    move = None
    if mode == "last":
        if not board.move_stack:
            raise ValueError("该节点没有上一手")
        move = board.pop()
        question = "解释上一手实战走法及对方可能的应对"
    elif mode == "ask":
        try:
            plan = model_json(
                "识别棋局问题。仅返回 {"
                "\"anchor\":\"current 或 last\",\"moves\":[],\"clarify\":\"\"}。"
                "last 指上一手走之前的局面。moves 只填写用户明确指定的连续 SAN 走法。"
                "不补猜任何一方走法，指代或前提不足时填写 clarify。",
                dict(question=question, fen=board.fen(), previous=board.peek().uci() if board.move_stack else None,
                     context=history),
                {"anchor": str, "moves": list, "clarify": str},
            )
        except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
            return dict(text="暂时无法识别追问。可以在棋盘上走出变例，再点击分析当前局面。", lines=[])
        if plan["clarify"]:
            return dict(text="请明确要比较的走法，以及这步从哪个局面开始。", lines=[])
        if plan["anchor"] == "last" and board.move_stack:
            move = board.pop()
        if plan["moves"]:
            if len(plan["moves"]) > 8 or any(not isinstance(s, str) for s in plan["moves"]):
                raise ValueError("请提供最多八步的连续走法")
            first = board.parse_san(plan["moves"][0])
            trial = board.copy()
            for san in plan["moves"]:
                step = trial.parse_san(san)
                if step not in trial.legal_moves:
                    raise ValueError("变化中存在非法走法")
                trial.push(step)
            if len(plan["moves"]) == 1:
                move = first
            else:
                board, move = trial, None
    else:
        question = "解释当前局面的候选和下一步应注意的威胁"
    if move is not None and move not in board.legal_moves:
        raise ValueError("比较走法不合法")
    result = teach(board, analyze(board, move), question, history)
    replay = board.root()
    result["anchor"] = []
    for step in board.move_stack:
        san = replay.san(step)
        replay.push(step)
        result["anchor"].append(dict(san=san, fen=replay.fen(), uci=step.uci()))
    return result


def scan_game(data):
    final = reconstruct(data)
    board = final.root()
    moves = final.move_stack
    path = os.getenv("STOCKFISH_PATH", r"D:\stockfish\stockfish-windows-x86-64-avx2.exe")
    swings = []
    previous = None
    with chess.engine.SimpleEngine.popen_uci(path, timeout=8) as engine:
        for ply in range(len(moves) + 1):
            score = engine.analyse(board, chess.engine.Limit(time=0.035))["score"].white().score(mate_score=10000)
            if previous is not None:
                loss = (previous - score) * (1 if ply % 2 != int(final.root().turn == chess.BLACK) else -1)
                if loss >= 90:
                    swings.append((loss, ply))
            if ply < len(moves):
                board.push(moves[ply])
            previous = score
    points = []
    for _, ply in sorted(swings, reverse=True)[:3]:
        position = final.root()
        for move in moves[:ply - 1]:
            position.push(move)
        lines = analyze(position, moves[ply - 1])
        actual = next((line for line in lines if line["actual"]), None)
        if not actual:
            continue
        reply = actual["steps"][1] if len(actual["steps"]) > 1 else None
        lesson = ("这步之后，对手可立即将死。落子前先检查对方的将军。"
                  if reply and reply["mate"] else
                  "对照实战走法与备选，先看对方的应手，再判断这一步的代价。")
        points.append(dict(ply=ply, move=position.san(moves[ply - 1]), lines=lines, lesson=lesson))
    return sorted(points, key=lambda item: item["ply"])


def dispatch(action, data):
    if action == "/coach":
        return review(data)
    if action == "/scan":
        return scan_game(data)
    if action == "/import":
        games = []
        if data["kind"] == "fen":
            board = chess.Board(data["text"].strip())
            if not board.is_valid():
                raise ValueError("FEN 局面无效")
            games.append(dict(title="FEN 局面", root=pack(chess.pgn.Game.from_board(board))))
        else:
            stream = io.StringIO(data["text"])
            while (game := chess.pgn.read_game(stream)) is not None:
                if game.errors or not game.board().is_valid() or not game.variations:
                    raise ValueError("PGN 无法完整解析，请检查原始棋谱")
                games.append(dict(title=f'{game.headers["White"]} — {game.headers["Black"]}', root=pack(game)))
        if not games:
            raise ValueError("未找到对局")
        return games
    board = chess.Board(data["fen"])
    if not board.is_valid():
        raise ValueError("局面无效")
    if action == "/board":
        moves = {m.uci(): board.san(m) for m in board.legal_moves}
        last = chess.Move.from_uci(data["last"]) if data.get("last") else None
        arrows = [chess.svg.Arrow(last.from_square, last.to_square, color="#1b7fbaaa")] if last else []
        return dict(svg=chess.svg.board(board, flipped=data.get("flip", False),
                                       lastmove=last, arrows=arrows,
                                       coordinates=False), moves=moves)
    if action == "/move":
        move = board.parse_uci(data["move"])
        san = board.san(move)
        board.push(move)
        return dict(fen=board.fen(), move=san, children=[], comment="")
    if action == "/analyze":
        move = board.parse_san(data["move"]) if data.get("move") else None
        return analyze(board, move)
    raise ValueError("未知请求")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        payload = Path(__file__).with_name("index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        try:
            if self.headers.get("Origin") not in (None, "http://127.0.0.1:8765"):
                raise ValueError("仅接受本地应用发起的请求")
            if self.headers.get_content_type() != "application/json":
                raise ValueError("请求必须为 JSON")
            size = int(self.headers["Content-Length"])
            if not 0 < size <= 2_000_000:
                raise ValueError("输入大小超限")
            result = dispatch(self.path, json.loads(self.rfile.read(size)))
            status = 200
        except (ValueError, KeyError, TypeError, OSError, chess.engine.EngineError, TimeoutError) as error:
            result, status = {"error": str(error)}, 400
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(result, ensure_ascii=False).encode())


if __name__ == "__main__":
    print("打开 http://127.0.0.1:8765")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()


