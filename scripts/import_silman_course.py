"""Copy the reviewed Silman video course into the coach's static tutorial files."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
from shutil import copyfile

import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "chess-video-lab" / "collections"
DESTINATION = ROOT / "web" / "tutorials" / "silman"
SOURCE_INDEX = "BV189otBuEKc-transcript-index.html"
PREVIEW = re.compile(r"BV189otBuEKc-p(\d+)-[\w-]+/preview\.html")
ATTACHMENT = re.compile(r"BV189otBuEKc-p\d+-[\w-]+/[\w.-]+\.pgn")
PLACEMENT = re.compile(r"<code>([prnbqkPRNBQK1-8/]+)</code>")


class CourseLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.previews = {}
        self.attachments = set()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if preview := PREVIEW.fullmatch(href):
            part = int(preview[1])
            previous = self.previews.setdefault(part, href)
            if previous != href:
                raise ValueError(f"Conflicting previews for episode {part}")
        elif ATTACHMENT.fullmatch(href):
            self.attachments.add(href)


def replay_lines(paths):
    lines = []
    for path in paths:
        with path.open(encoding="utf-8-sig") as source:
            while (game := chess.pgn.read_game(source)) is not None:
                if game.errors:
                    raise ValueError(f"Invalid PGN in {path}: {game.errors}")
                start = game.board()
                pending = [(game, [{"fen": start.fen(), "san": "起始局面"}])]
                while pending:
                    node, positions = pending.pop()
                    if not node.variations:
                        if len(positions) > 1:
                            lines.append({"title": game.headers["Event"], "positions": positions})
                        continue
                    for child in reversed(node.variations):
                        move = child.move
                        pending.append((child, [*positions, {
                            "fen": child.board().fen(), "san": child.san(),
                            "from": chess.square_name(move.from_square),
                            "to": chess.square_name(move.to_square),
                        }]))
    return lines


def write_preview(source, target, attachments):
    page = source.read_text(encoding="utf-8")
    lines = replay_lines(attachments)
    if lines:
        page = PLACEMENT.sub(r'<span hidden data-placement="\1"></span>', page)
        data = json.dumps(lines, ensure_ascii=False).replace("<", "\\u003c")
        page = page.replace("</main>", f"""
<section id="replay" aria-label="棋谱回放"></section>
<script type="application/json" id="replay-data">{data}</script>
</main>""", 1)
        page = page.replace("</head>", """
<link rel="stylesheet" href="../../../styles.css">
<link rel="stylesheet" href="../replay.css">
</head>""", 1)
        page = page.replace("</body>", """
<script src="../../../vendor/chess.min.js"></script>
<script src="../../../js/board.js"></script>
<script src="../replay.js"></script>
</body>""", 1)
    else:
        page = PLACEMENT.sub("", page)
        page = page.replace("</h1>", "</h1><p>本集展示已识别的棋盘局面。</p>", 1)
    target.write_text(page, encoding="utf-8")


def main():
    index = (SOURCE / SOURCE_INDEX).read_text(encoding="utf-8")
    links = CourseLinks()
    links.feed(index)
    if set(links.previews) != set(range(1, 25)):
        raise ValueError("The course index must link all 24 episode previews")

    files = sorted({*links.previews.values(), *links.attachments, "COVERAGE.md"})
    for name in files:
        if not (SOURCE / name).is_file():
            raise FileNotFoundError(SOURCE / name)
    for name in files:
        target = DESTINATION / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith("/preview.html"):
            attachments = sorted(
                SOURCE / href for href in links.attachments
                if Path(href).parent == Path(name).parent
            )
            write_preview(SOURCE / name, target, attachments)
        else:
            copyfile(SOURCE / name, target)

    course_index = index.replace(
        "<body><main>", '<body><main><a href="/#/courses">返回 chess-coach 教程</a>', 1
    )
    (DESTINATION / "index.html").write_text(course_index, encoding="utf-8")
    print(f"Imported {len(links.previews)} previews and {len(links.attachments)} PGN files")


if __name__ == "__main__":
    main()
