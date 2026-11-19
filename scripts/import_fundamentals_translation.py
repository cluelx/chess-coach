"""Render the translated Markdown and inline FEN diagrams."""
import argparse
import html
import json
import io
import re
from collections import defaultdict
from pathlib import Path

import chess
import chess.svg
import chess.pgn
import markdown

DEST = Path(__file__).resolve().parents[1] / "web/tutorials/fundamentals/translation.html"
BOARD_BLOCK = re.compile(r"^```chessboard[ \t]*\n(.*?)^\x60{3}[ \t]*$", re.M | re.S)
SECTION = re.compile(r"^#{2,6} .*?（(Example\s+\d+|Game\s+\d+:)[^）]*）[^\n]*$", re.M | re.I)
STUDIES = DEST.parents[3] / "data/fundamentals/studies"


def read_games(path):
    with path.open(encoding="utf-8-sig") as stream:
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors:
                raise ValueError(f"{path}: {game.errors}")
            yield game


def move_tree(game):
    nodes = []

    def visit(position, board, parent=None, san=""):
        index = len(nodes)
        move = position.move
        node = {"fen": board.fen(), "san": san, "parent": parent,
                "comment": position.comment, "startingComment": position.starting_comment,
                "nags": sorted(position.nags)}
        if move:
            node.update({"from": chess.square_name(move.from_square),
                         "to": chess.square_name(move.to_square)})
        nodes.append(node)
        children = []
        for child in position.variations:
            if not board.is_legal(child.move):
                raise ValueError(f'{game.headers["ChapterName"]}: illegal move {child.move}')
            notation = board.san(child.move)
            board.push(child.move)
            children.append(visit(child, board, index, notation))
            board.pop()
        node["children"] = children
        return index

    # The source is standard chess. Some study FENs carry stale castling flags.
    board = chess.Board(game.board().fen())
    board.castling_rights = board.clean_castling_rights()
    visit(game, board)
    return nodes


def study_replays(directory):
    game_numbers = {}
    for game in read_games(DEST.with_name("03-已校验棋谱.pgn")):
        book_id = game.headers.get("BookID", "")
        url = game.headers.get("Source", "").split(" / ")[-1]
        if match := re.fullmatch(r"GAME(\d+)", book_id):
            game_numbers[url] = f"game {int(match[1])}"

    replays = defaultdict(list)
    for filename in ("uL7pPw98.pgn", "k3M5fqR7.pgn"):
        for game in read_games(directory / filename):
            title = game.headers["ChapterName"]
            url = game.headers["ChapterURL"]
            if match := re.fullmatch(r"Example\s+(\d+)\s*[a-z]?", title, re.I):
                key = f"example {int(match[1])}"
                # This chapter is labeled Example 53 in Study, but its moves
                # match Example 52 (Capablanca–Blanco) in the book.
                if url.endswith("/xRV9zUvp"):
                    key = "example 52"
                    title = "Example 52 · 简版"
            else:
                key = game_numbers[url]
            replays[key].append({"title": title, "url": url, "nodes": move_tree(game),
                                 "orientation": game.headers.get("Orientation", "white")})
    replays["example 52"].sort(key=lambda chapter: chapter["title"] != "Example 52")
    return replays


def render(source):
    rendered = 0

    def board_block(match):
        nonlocal rendered
        fen = re.search(r"^fen:[ \t]*(.+)$", match[1], re.M)
        if not fen:
            return match[0]
        try:
            board = chess.Board(fen[1].strip())
        except ValueError:
            return match[0]
        rendered += 1
        svg = chess.svg.board(board, size=380)
        svg = re.sub(r'((?:id|href)="#?)([^"]+)"',
                     lambda ref: f'{ref[1]}diagram-{rendered}-{ref[2]}"', svg)
        metadata = html.escape(match[1][:fen.start()] + match[1][fen.end():].lstrip("\n"))
        return (f'\n<figure class="translated-board">{svg}'
                f'<details><summary>棋图说明</summary><pre>{metadata}</pre></details></figure>\n')

    prepared = BOARD_BLOCK.sub(board_block, source)
    return markdown.markdown(prepared, extensions=["tables", "fenced_code"]), rendered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--studies", type=Path, default=STUDIES)
    args = parser.parse_args()
    source = args.source.read_text(encoding="utf-8-sig")
    replays = study_replays(args.studies)
    source = apply_review_corrections(source, replays)

    def attach_replay(match):
        key = " ".join(match[1].lower().rstrip(":").split())
        if key not in replays:
            return match[0] + "\n\n> 两套 Lichess Study 暂无此例的棋谱。\n"
        return match[0] + replay_placeholder(key)

    start = source.index("# 第二部分")
    source = source[:start] + SECTION.sub(attach_replay, source[start:])
    # The book leaves the Marshall–Rosenthal example unnumbered.
    fen_59 = re.escape(replays["example 59"][0]["nodes"][0]["fen"])
    source = BOARD_BLOCK.sub(
        lambda block: block[0] + replay_placeholder("example 59")
        if re.search(rf"^fen: {fen_59}$", block[1], re.M) else block[0],
        source,
    )
    body, rendered = render(source)
    data = json.dumps(replays, ensure_ascii=False).replace("<", "\\u003c")
    DEST.write_text(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>卡帕布兰卡《国际象棋基础》中文译本</title>
<link rel="stylesheet" href="../../styles.css">
<link rel="stylesheet" href="book.css">
<link rel="stylesheet" href="study-replay.css">
<style>
.translated-book {{ max-width: 780px; overflow-wrap: anywhere; }}
.translated-book pre {{ white-space: pre-wrap; }}
.translated-book table {{ display: block; overflow-x: auto; }}
.translated-board {{ margin: 18px 0; }}
.translated-board svg {{ display: block; width: min(100%, 380px); height: auto; }}
</style></head><body><main class="translated-book">
<a href="../../../#/courses">返回教程</a> · <a href="index.html">中文导读</a>
{body}
</main>
<script type="application/json" id="study-replays">{data}</script>
<script src="../../vendor/chess.min.js"></script>
<script src="../../js/board.js"></script>
<script src="study-replay.js"></script>
</body></html>""", encoding="utf-8")
    print(f"{rendered} diagrams rendered, {len(BOARD_BLOCK.findall(source)) - rendered} blocks preserved")


def replay_placeholder(key):
    return (f'\n\n<div class="study-replay" data-study="{key}">'
            '正在加载棋盘…</div>\n')


def apply_review_corrections(source, replays):
    changes = {
        "如果此时黑王走 Ke4": "如果此时黑王走 Ke5",
        "5.Qe6 Kh5, 6.Kf4 Qh6#": "5.Qe6 Kh5, 6.Kf4 Kh4, 7.Qh6#",
        "在这个局面中，白方走 f6 无法取胜，因为黑方不会走 gxf6（那样会输），而是走 Kf8；如果再走 gxf6，黑方就走 Kxf6，形成和棋。": "在这个局面中，白方走 f6 无法取胜，因为黑方不会走 gxf6（那样会输），而是走 Kg8；如果黑再走 gxf6，白方走 Kxf6，形成和棋。",
        "4.Bcf6#": "4.Bxf6#",
        "5.dxe6 dxe5, 6.Qd5": "5.dxe5 dxe5, 6.Qd5",
        "变例 4...dxe5 会丢一兵。": "变例 4...dxe5 会丢一兵。换后以后白方可以多吃一个兵。",
        "如果走变例 6...Nf6, 7.Qb3，白方赢得一兵。": "如果走变例 6...Nf6, 7.Qb3，白方赢得一兵，之后可以吃 b7 的兵。",
        "2.Qe5+ Kh7!, 3.kg5 Ra7!": "2.Qe5+ Kh7!, 3.Kg5 Ra7!",
        "1.Qg5+ Kg8, 2.Qd8+ Kg7": "1.Qg5+ Kh8, 2.Qd8+ Kg7",
    }
    for old, new in changes.items():
        if old not in source:
            raise ValueError(f"Missing review text: {old}")
        source = source.replace(old, new)
    for fragment in (
        "〔待核对：末着原文作 4.Bxf6#，按 python-chess 该记法非法；正确的记法应为 4.Bxf6#，且确为将杀。原文用字未改。〕",
        "〔待核对：原文 5.dxe6 按局面应为 5.dxe5；原文未改。〕",
        "〔待核对：原文 1.Bh7+ Kxb7 与该 FEN 不符——白象在 b5，无法走到 h7；黑王也不能“Kxb7”吃 h7 的棋子。FEN 疑为沿用上例而误植；原文未改，见待核对清单。〕",
        '〔待核对:原文 "3.kg5" 中的 "k" 为小写,疑为 "3.Kg5"(白王 g5);原文记号照录,见待核对。〕',
        "〔待核对:经 python-chess 校验,此主线首着黑方应手 1...Kg8 不合法——白后 g5 控制 g8;同书另一分支(第1631行)作 1...Kh8。原文记号照录,见待核对。〕",
    ):
        source = source.replace(fragment, "")

    def section(number, transform):
        nonlocal source
        pattern = re.compile(rf"(^##### 例 {number}（Example {number}）.*?)(?=^##### 例 \d+（Example|^## |^# |\Z)", re.M | re.S)
        source, count = pattern.subn(lambda match: transform(match[0]), source, count=1)
        if count != 1:
            raise ValueError(f"Missing Example {number}")

    section(39, lambda s: s.replace("1.Ke2 Ke7", "1.Ke2 Kd7", 1))
    section(15, lambda s: s.replace("\n\n", "\n\n> 此例原棋图有误，待修正。\n\n", 1))
    section(21, lambda s: s.replace("\n\n", "\n\n> 此例待核对：尚未展示黑马吃 e5 后的局面。\n\n", 1))
    section(22, lambda s: s.replace("\n\n", "\n\n> 此例的引擎变例为 AI 给出的最优变化参考。\n\n", 1))
    section(23, lambda s: s.replace("\n\n", "\n\n> 承接例 22 时，引擎最优应对可能形成和棋，可用引擎分析继续验证。\n\n", 1))
    section(17, lambda s: s.replace(
        "这是一步非常有力的着法，把我们带入了中局阶段，因为已经可以看到一个通过 Bxc3 迅速取胜的战术组合。这一威胁使黑方无法继续同样的路线。经验表明，他现在被迫走 7...Bxc3，这样就有三点值得注意。",
        "原书指出，一段较长的分析显示，若黑方也走 …Bg4，黑方应当会输。因此作者认为黑方被迫走 7...Bxc3。你提供的引擎建议为马走 e7，具体着法请结合该局面核验。这样有三点值得注意。"))
    def fix28(s):
        start = s.index("兵的阵形使白方无法")
        end = s.index("**主线:** 1... Kd2", start)
        return s[:start] + ("若白方走 1.Kf1，白方因自己位于 f3 的兵而无法继续保持对安全至关重要的横向对王，之后变成例 6 的情况输掉。\n\n"
                            "**变例：** 1.Kf1 Kd2 2.Kf2 g4 3.Kg2 gxf3+ 4.Kxf3 Kd3 5.Kf2 e4 6.Ke1 Ke3\n\n") + s[end:]
    section(28, fix28)
    section(42, lambda s: s + "\n\n> 审核进度：已检查至例 42。\n\n")
    def remove_reviewed_boards(match):
        number = int(match[1])
        content = match[0]
        return content if number == 32 else BOARD_BLOCK.sub("", content)
    source = re.sub(r"^##### 例 (\d+)（Example \d+）.*?(?=^##### 例 \d+（Example|^## |^# |\Z)",
                    lambda m: remove_reviewed_boards(m) if 1 <= int(m[1]) <= 42 else m[0],
                    source, flags=re.M | re.S)
    source = source.replace("id: board-0013\nfen: 待还原", "id: board-0013\nfen: 8/8/8/8/8/8/8/2KR3R b - - 1 1")
    additions = {
        4: ('8/8/8/4k3/8/8/8/4K2Q w - - 0 1',
            '1. Qc6 Kd4 2. Kd2 Ke5 3. Ke3 Kf5 4. Qd6 Kg5 (4... Kg4 5. Qg6+) 5. Qe6 Kh4 (5... Kh5 6. Kf4 Kh4 7. Qh6#) 6. Qg6 Kh3 7. Kf3 Kh4 8. Qg4# *'),
        28: ('8/8/8/4p1p1/8/5P2/6K1/3k4 w - - 0 1',
             '1. Kf1 Kd2 2. Kf2 g4 3. Kg2 gxf3+ 4. Kxf3 Kd3 5. Kf2 e4 6. Ke1 Ke3 *'),
    }
    for number, (fen, moves) in additions.items():
        pgn = f'[Event "用户提供的变化"]\n[SetUp "1"]\n[FEN "{fen}"]\n\n{moves}'
        game = chess.pgn.read_game(io.StringIO(pgn))
        if game.errors:
            raise ValueError(f"Example {number}: {game.errors}")
        replays[f"example {number}"].insert(0, {
            "title": "用户提供的棋谱", "url": "", "nodes": move_tree(game), "orientation": "white"
        })
    return source


if __name__ == "__main__":
    main()
