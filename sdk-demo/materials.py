"""Evidence adapters and offline rendering for the material search demo."""
import html
import io
import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import chess
import chess.pgn
import chess.svg

DB = Path(__file__).resolve().parents[1] / "data" / "chess_coach.db"
FEN = re.compile(r"\b(?:[prnbqkPRNBQK1-8]+/){7}[prnbqkPRNBQK1-8]+ [wb] (?:[KQkq]+|-) (?:[a-h][36]|-) \d+ \d+\b")


def source_kind(url):
    p = urlsplit(url)
    host = p.hostname or ""
    for domain in ("youtube.com", "youtu.be", "bilibili.com", "b23.tv", "vimeo.com",
                   "douyin.com", "tiktok.com", "dailymotion.com", "ixigua.com",
                   "v.qq.com", "youku.com", "iqiyi.com"):
        if host == domain or host.endswith("." + domain):
            return "video"
    if host in ("lichess.org", "www.lichess.org") and re.fullmatch(r"/training/[A-Za-z0-9]{5}/?", p.path):
        return "puzzle"
    return "article"


def position(text):
    for value in FEN.findall(text):
        try:
            board = chess.Board(value)
        except ValueError:
            continue
        if board.is_valid():
            return board.fen()
    return None


def puzzle(row, require_checking_fork=False, already_started=False):
    board = chess.Board(row["fen"])
    moves = row["moves"].split()
    if len(moves) < (1 if already_started else 2) or not board.is_valid():
        raise ValueError("题目缺少合法局面或解法")
    if not already_started:
        board.push_uci(moves.pop(0))
    fen = board.fen()
    first = board.parse_uci(moves[0])
    targets = []
    if board.piece_type_at(first.from_square) == chess.KNIGHT and board.gives_check(first):
        after = board.copy()
        after.push(first)
        enemy_king = after.king(after.turn)
        attacked = after.attacks(first.to_square) & after.occupied_co[after.turn]
        if enemy_king in attacked:
            targets = [enemy_king, *(sq for sq in attacked if after.piece_type_at(sq) in
                                      (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT))]
    if require_checking_fork and len(targets) < 2:
        return None
    keys = [chess.square_name(sq) for sq in [first.from_square, first.to_square, *targets]]
    line = []
    for uci in moves:
        move = board.parse_uci(uci)
        san = board.san(move)
        board.push(move)
        line.append({"san": san, "fen": board.fen()})
    explanation = "请找出题库给出的战术着法，完成后可以展开答案逐手核对。"
    if len(targets) > 1:
        victims = "、".join(chess.square_name(sq) for sq in targets[1:])
        explanation = f"{line[0]['san']} 同时将军并攻击 {victims} 的棋子。注意对方应将后，这些目标是否还能被马吃到。"
    return {"kind": "puzzle", "title": "Lichess 练习题 " + row["id"], "fen": fen,
            "url": "https://lichess.org/training/" + row["id"], "moves": line,
            "key_squares": keys, "explanation": explanation, "rating": row["rating"]}


def online_puzzle(payload, expected_id):
    info = payload["puzzle"]
    if info["id"] != expected_id:
        raise ValueError("在线题目 ID 不一致")
    fen = info.get("fen")
    if not fen:
        game = chess.pgn.read_game(io.StringIO(payload["game"]["pgn"]))
        if not game or game.errors:
            raise ValueError("Lichess PGN 不合法")
        board = game.board()
        for move in game.mainline_moves():
            if board.ply() >= info["initialPly"]:
                break
            board.push(move)
        if board.ply() != info["initialPly"]:
            raise ValueError("PGN 未到指定出题位置")
        fen = board.fen()
    return puzzle({"id": expected_id, "fen": fen, "moves": " ".join(info["solution"]),
                   "rating": info["rating"]}, already_started=True)


def local_puzzles(puzzle_id=None):
    if not DB.exists():
        return []
    with sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        if puzzle_id:
            rows = conn.execute("SELECT * FROM puzzle WHERE id=?", (puzzle_id,))
        else:
            rows = conn.execute("""SELECT p.* FROM puzzle_theme t JOIN puzzle p ON p.id=t.puzzle_id
                                  WHERE t.theme='fork' AND p.rating BETWEEN 600 AND 1250 LIMIT 4000""")
        for row in rows:
            try:
                item = puzzle(row, require_checking_fork=not puzzle_id)
            except ValueError:
                continue
            if item:
                return [item]
    return []


def save(output, question, cards, links):
    e = html.escape
    def artifact(path, label):
        return f'<a href="{e(path)}">{label}</a>'

    parts = []
    for item in cards:
        board = chess.Board(None)
        board.set_board_fen(item["fen"].split()[0])
        marks = chess.SquareSet(chess.parse_square(sq) for sq in item.get("key_squares", []))
        is_puzzle = item["kind"] == "puzzle"
        diagram = chess.svg.board(board, squares=None if is_puzzle else marks, size=380)
        moves = item.get("moves", [])
        answer = ""
        if moves:
            turn = "白方" if chess.Board(item["fen"]).turn else "黑方"
            frames = "".join(f'<template>{chess.svg.board(chess.Board(step["fen"]), size=380)}</template>' for step in moves)
            rating = f" · 难度 {item['rating']}" if is_puzzle else ""
            summary = "显示答案与逐手回放" if is_puzzle else "逐手回放"
            move_text = " ".join(
                step["san"] + ("（推断）" if item["kind"] == "video" and step["observed_at_s"] is None else "")
                for step in moves)
            opened = " open" if item["kind"] == "article" else ""
            answer = (f"<p>{turn}行棋{rating}</p>"
                      f"<details{opened}><summary>{summary}</summary><p>{e(item['explanation'])}</p>"
                      f"<p>{e(move_text)}</p>"
                      f'<button type="button" data-step="-1">上一步</button> '
                      f'<button type="button" data-step="1">下一步</button> '
                      f'<button type="button" data-step="reset">重置</button> <output>0 / {len(moves)}</output>'
                      f"<template>{diagram}</template>{frames}</details>")
        else:
            answer = f"<p>{e(item['explanation'])}</p>"
        original = item.get("original_png")
        if original:
            answer += ('<details><summary>核对原图</summary><img alt="来源棋盘" '
                       f'src="data:image/png;base64,{original}"></details>')
        if item["kind"] == "video":
            minutes, seconds = divmod(int(item["frame_s"]), 60)
            answer += f"<p>画面 {minutes}:{seconds:02d} · 共 {item['candidate_count']} 个候选"
            answer += " · " + artifact(item["candidates_file"], "候选 JSON")
            if item.get("pgn_file"):
                answer += " · " + artifact(item["pgn_file"], "下载 PGN")
            answer += "</p>"
        parts.append(f'<article><h2>{e(item["title"])}</h2><div class="grid"><div class="board">{diagram}</div>'
                     f'<div>{answer}<a href="{e(item.get("source_at", item["url"]))}">打开原始资料</a></div></div></article>')
    resources = "".join(f'<li><a href="{e(r["url"])}">{e(r["title"])}</a>'
                        f' · {e(r["note"])}'
                        + (" · " + artifact(r["candidates_file"], "候选 JSON") if r.get("candidates_file") else "")
                        + "</li>" for r in links)
    if resources:
        parts.append(f"<article><h2>相关链接</h2><ul>{resources}</ul></article>")
    page = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>棋课资料</title>
<style>body{margin:0;background:#f4f6f2;color:#17231c;font:16px/1.65 system-ui}
main{max-width:1000px;margin:3rem auto;padding:0 1rem}article{background:white;padding:1.2rem;
border:1px solid #d9dfd6;border-radius:1rem;margin-bottom:1rem}.grid{display:grid;
grid-template-columns:minmax(0,380px) minmax(0,1fr);gap:1.5rem}svg,img{width:100%;height:auto}
a{color:#145842}details{margin-bottom:1rem}@media(max-width:700px){.grid{grid-template-columns:1fr}}</style>
"""
    page += f"<main><h1>{e(question)}</h1>{''.join(parts) or '<p>没有取得可用资料。</p>'}</main>"
    page += """<script>
for (const card of document.querySelectorAll('article')) {
  const frames = [...card.querySelectorAll('template')];
  let index = 0;
  for (const button of card.querySelectorAll('[data-step]')) {
    button.addEventListener('click', () => {
      index = button.dataset.step === 'reset'
        ? 0 : Math.max(0, Math.min(frames.length - 1, index + Number(button.dataset.step)));
      card.querySelector('.board').replaceChildren(frames[index].content.cloneNode(true));
      card.querySelector('output').value = index + ' / ' + (frames.length - 1);
    });
  }
}
</script></html>"""
    payload = {"question": question, "materials": cards, "links": links}
    for path, content in [(output.with_suffix(".json"), json.dumps(payload, ensure_ascii=False, indent=2)),
                          (output, page)]:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
