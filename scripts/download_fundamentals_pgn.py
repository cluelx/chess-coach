"""Download both public Chess Fundamentals studies with annotations and variations."""

import argparse
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

import chess.pgn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)

    for study in ("uL7pPw98", "k3M5fqR7"):
        request = Request(
            f"https://lichess.org/api/study/{study}.pgn?variations=true&comments=true&orientation=true",
            headers={"User-Agent": "chess-coach", "Accept": "application/x-chess-pgn"},
        )
        with urlopen(request, timeout=45) as response:
            if response.headers.get_content_type() not in ("application/x-chess-pgn", "text/plain"):
                raise ValueError(f"{study}: expected a PGN response")
            raw = response.read()
        stream = StringIO(raw.decode("utf-8-sig"))
        chapters = 0
        while (game := chess.pgn.read_game(stream)) is not None:
            if game.errors or not game.headers.get("ChapterName"):
                raise ValueError(f"{study}: invalid chapter at record {chapters + 1}")
            chapters += 1
        if not chapters:
            raise ValueError(f"{study}: export contains no chapters")
        target = output / f"{study}.pgn"
        temp = target.with_suffix(".pgn.tmp")
        temp.write_bytes(raw)
        temp.replace(target)
        print(f"{study}: {chapters} chapters -> {target.resolve()}")


if __name__ == "__main__":
    main()
