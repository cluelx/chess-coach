"""Import a WorkBuddy Chess Fundamentals package into the local tutorial."""
import argparse
import html
import json
import re
from pathlib import Path
from shutil import copyfile

import chess.pgn
import chess.svg
import markdown

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "web" / "tutorials" / "fundamentals"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    source = parser.parse_args().source
    guide = (source / "01-中文导读.md").read_text(encoding="utf-8-sig")
    figures = json.loads((source / "02-棋图与例局.json").read_text(encoding="utf-8-sig"))["figures"]
    games = {}
    lines = []
    with (source / "03-已校验棋谱.pgn").open(encoding="utf-8-sig") as stream:
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors:
                raise ValueError(str(game.errors))
            board = game.board()
            positions = [{"fen": board.fen(), "san": "起始局面"}]
            for move in game.mainline_moves():
                san = board.san(move)
                board.push(move)
                positions.append({"fen": board.fen(), "san": san,
                                  "from": chess.square_name(move.from_square),
                                  "to": chess.square_name(move.to_square)})
            key = game.headers.get("BookID", "")
            line = {
                "title": f'{game.headers.get("BookID", "")} · {game.headers.get("Event", "")}',
                "positions": positions,
            }
            games.setdefault(key, []).append(len(lines))
            lines.append(line)

    sections = re.split(r"(?=^#### )", guide.split("## 逐节讲解", 1)[1], flags=re.M)
    figures_by_id = {figure["ID"]: figure for figure in figures}
    contents = []
    for section in sections:
        if not section.startswith("#### "):
            continue
        heading, _, body = section.partition("\n")
        title = heading[5:].strip()
        game_match = re.match(r"第\s*(\d+)\s*局", title)
        section_game = f"GAME{int(game_match[1]):02}" if game_match else ""
        ids = list(dict.fromkeys(re.findall(r"FIG\d{3}", body)))
        cards = []
        for figure_id in ids:
            figure = figures_by_id.get(figure_id)
            if not figure:
                continue
            fen = figure.get("FEN")
            if not fen:
                cards.append(f'<p>{figure_id} · 棋图待核对</p>')
                continue
            try:
                board = chess.Board(fen)
            except ValueError:
                cards.append(f'<p>{figure_id} · 棋图数据待核对</p>')
                continue
            key = section_game or figure.get("例号或对局号", "").replace("Example ", "Example")
            button = ""
            for line_index in games.get(key, []):
                replay = lines[line_index]
                target = fen.split()[:2]
                for step, position in enumerate(replay["positions"]):
                    if position["fen"].split()[:2] == target:
                        button = f'<button class="figure-replay" data-line="{line_index}" data-step="{step}">从此局面回放</button>'
                        break
                if button:
                    break
            image = chess.svg.board(board, size=340)
            label = html.escape(f'{figure_id} · 原书 p.{figure.get("页码", "?")}')
            cards.append(f'<article class="figure"><h5>{label}</h5>{image}{button}</article>')
        if section_game in games:
            cards.insert(0, f'<p><button class="figure-replay" data-line="{games[section_game][0]}" data-step="0">回放本局</button></p>')
        contents.append(markdown.markdown(section, extensions=["tables", "fenced_code"]) +
                        ('<div class="figures">' + "".join(cards) + "</div>" if cards else ""))

    data = json.dumps(lines, ensure_ascii=False).replace("<", "\\u003c")
    page = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>国际象棋基础 · 卡帕布兰卡</title>
<link rel="stylesheet" href="../../styles.css"><link rel="stylesheet" href="book.css">
</head><body><main><a href="../../../#/courses">返回教程</a>
<h1>国际象棋基础</h1><p>卡帕布兰卡 · 中文导读与棋谱</p>
<p>本资料由 dpsk 整理，棋图与讲解尚需继续核对。覆盖记录列出了 11 张待核对棋图和变例缺口。</p>
<p><a href="04-覆盖与待核对.md">查看覆盖记录</a> · <a href="03-已校验棋谱.pgn" download>下载棋谱</a> · <a href="01-中文导读.md" download>下载中文导读</a></p>
<details><summary>棋谱回放</summary><div id="replay"></div></details>
<nav id="contents"><h2>目录</h2></nav><div id="chapters">""" + "".join(contents) + """</div>
<script type="application/json" id="book-data">""" + data + """</script>
<script src="../../vendor/chess.min.js"></script><script src="../../js/board.js"></script>
<script src="book.js"></script></main></body></html>"""
    DEST.mkdir(parents=True, exist_ok=True)
    for name in ("01-中文导读.md", "02-棋图与例局.json", "03-已校验棋谱.pgn", "04-覆盖与待核对.md"):
        copyfile(source / name, DEST / name)
    (DEST / "index.html").write_text(page, encoding="utf-8")
    print(f"{len(contents)} sections, {len(figures)} figures, {len(lines)} PGN games")


if __name__ == "__main__":
    main()
