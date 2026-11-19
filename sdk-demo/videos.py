"""Collect video diagrams and recover a verified opening prefix when possible."""
import base64
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import chess
import chess.pgn

LAB = Path(__file__).resolve().parents[2] / "chess-video-lab"
PLATFORMS = {
    "bilibili.com": r"/(?:video/(?:BV[0-9A-Za-z]+|av\d+)|bangumi/play/ep\d+)/?",
    "b23.tv": r"/[0-9A-Za-z]+/?",
    "douyin.com": r"/video/\d+/?",
    "ixigua.com": r"/\d+/?",
    "v.qq.com": r"/x/(?:cover/[^/]+/|page/)[^/]+\.html",
    "youku.com": r"/v_show/id_.+\.html",
    "iqiyi.com": r"/v_.+\.html",
}


class VideoCollectionError(RuntimeError):
    def __init__(self, phase, message, *, timed_out=False):
        super().__init__(message)
        self.phase = phase
        self.timed_out = timed_out


def domestic_platform(host):
    return next((domain for domain in PLATFORMS
                 if host == domain or host.endswith("." + domain)), None)


def video_priority(url):
    platform = domestic_platform(urlsplit(url).hostname or "")
    if platform in ("bilibili.com", "b23.tv"):
        return 0
    return 1 if platform else 2


def single_video(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host == "youtube.com" or host.endswith(".youtube.com"):
        if parts.path == "/watch":
            return bool(parse_qs(parts.query).get("v"))
        return parts.path.startswith(("/shorts/", "/live/", "/embed/"))
    if host == "v.douyin.com":
        return bool(re.fullmatch(r"/[0-9A-Za-z]+/?", parts.path))
    platform = domestic_platform(host)
    if platform:
        return bool(re.fullmatch(PLATFORMS[platform], parts.path))
    return parts.path not in ("", "/")


def video_start(url):
    query = parse_qs(urlsplit(url).query)
    for key in ("t", "start", "start_progress"):
        value = query.get(key, [""])[0].removesuffix("s")
        if value.isascii() and value.isdecimal() and len(value) <= 7:
            return int(value) // (1000 if key == "start_progress" else 1)
    return None


def timestamp_url(url, seconds):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if not any(host == site or host.endswith("." + site)
               for site in ("youtube.com", "youtu.be", "bilibili.com")):
        return url
    query = parse_qs(parts.query)
    query.pop("start_progress", None)
    query.pop("start", None)
    query["t"] = [str(int(seconds))]
    return urlunsplit(parts._replace(query=urlencode(query, doseq=True)))


def matching_moves(board, placement, plies):
    for move in list(board.legal_moves):
        board.push(move)
        if plies == 1:
            if board.board_fen() == placement:
                yield (move,)
        else:
            for tail in matching_moves(board, placement, plies - 1):
                yield (move, *tail)
        board.pop()


def opening_prefix(candidates):
    board = chess.Board()
    anchor = None
    pending = None
    seen = {board.board_fen()}
    moves = []
    for row in candidates:
        if row["simultaneous"]:
            if anchor:
                break
            continue
        placement = row["piece_placement"]
        if anchor is None:
            if placement == chess.STARTING_BOARD_FEN:
                anchor = row
            continue
        if placement == board.board_fen():
            pending = None
            continue
        if placement in seen:
            break
        # Allow a brief drag animation before treating an unmatched frame as a discontinuity.
        if pending is not None and row["frame_s"] - pending > 3:
            break
        # Use a copy so each search leaves the accepted position untouched.
        paths = list(matching_moves(board.copy(stack=False), placement, 1))
        if not paths:
            paths = list(matching_moves(board.copy(stack=False), placement, 2))
        if len(paths) > 1:
            break
        if not paths:
            pending = row["frame_s"] if pending is None else pending
            continue
        for move in paths[0]:
            san = board.san(move)
            board.push(move)
            seen.add(board.board_fen())
            moves.append({"san": san, "uci": move.uci(), "fen": board.fen(),
                          "observed_at_s": row["frame_s"] if move == paths[0][-1] else None})
        pending = None
    return anchor, moves


def collect_video(item, output):
    url = item["url"]
    start = video_start(url)
    folder = output.parent / f"{output.stem}-video-{uuid4().hex[:12]}"
    deadline = time.monotonic() + 150

    def scan(media, destination, begin, end, interval, mode, *, first_board=False):
        stage = (destination / "stage.txt").resolve()

        def phase():
            marker = stage.read_text(encoding="utf-8") if stage.is_file() else ""
            return {"download": "下载", "recognize": "识盘"}.get(marker, "采集启动")

        command = [sys.executable, str(LAB / "collect.py"), media,
                   "--title", item["title"], "--source-url", url, "--mode", mode,
                   "--interval", str(interval), "--start", str(begin), "--end", str(end),
                   "--output", str(destination.resolve()), "--stage-file", str(stage)]
        if first_board:
            command.append("--first-board")
        try:
            result = subprocess.run(command, cwd=LAB, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace",
                                    timeout=max(1, deadline - time.monotonic()))
            if result.returncode:
                messages = result.stderr.strip().splitlines()
                detail = next((line for line in reversed(messages) if line.startswith("ERROR:")),
                              messages[-1] if messages else f"采集进程退出 {result.returncode}")
                raise VideoCollectionError(phase(), detail)
            return json.loads((destination / "candidates.json").read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired as exc:
            raise VideoCollectionError(phase(), f"阶段超过 {exc.timeout:.0f} 秒", timed_out=True) from exc
        except (OSError, ValueError) as exc:
            raise VideoCollectionError(phase(), str(exc)) from exc
        finally:
            stage.unlink(missing_ok=True)

    if start is None:
        # Find a likely board segment without spending dense passes on a long introduction.
        with TemporaryDirectory(prefix="video-probe-", dir=output.parent.resolve()) as temporary:
            probe = Path(temporary) / "probe"
            package = scan(url, probe, 0, 600, 6, "board-change", first_board=True)
            if package["candidates"]:
                start = max(0, int(package["candidates"][0]["frame_s"]) - 18)
                media = str(probe / package["source"]["media"])
                package = scan(media, folder, start, start + 100, 0.5, "board-change")
            else:
                probe.rename(folder.resolve())
    else:
        package = scan(url, folder, start, start + 180, 0.5, "board-change")
    rows = package["candidates"]
    counts = {}
    for row in rows:
        stamp = row["frame_s"]
        counts[stamp] = counts.get(stamp, 0) + 1
    candidates = [{**row, "simultaneous": counts[row["frame_s"]] > 1} for row in rows]
    artifacts = f"{folder.name}/candidates.json"
    anchor, moves = opening_prefix(candidates)

    def card(row, explanation, **extra):
        return {**item, "fen": row["piece_placement"], "explanation": explanation,
                "frame_s": row["frame_s"], "source_at": timestamp_url(url, row["frame_s"]),
                "candidates_file": artifacts, "candidate_count": len(rows),
                "original_png": base64.b64encode((folder / row["board_crop"]).read_bytes()).decode("ascii"),
                **extra}

    if moves:
        game = chess.pgn.Game()
        game.headers.update(Event=" ".join(item["title"].replace('"', "'").split()),
                            Site=timestamp_url(url, anchor["frame_s"]))
        node = game
        for step in moves:
            node = node.add_variation(chess.Move.from_uci(step["uci"]))
            if step["observed_at_s"] is None:
                node.comment = "Inferred between video frames"
        pgn = str(game) + "\n"
        (folder / "clip.pgn").write_text(pgn, encoding="utf-8")
        cards = [card(anchor, "从标准初始局面提取的开局片段。标记为推断的走法来自相邻画面之间的唯一短路径。",
                      fen=chess.STARTING_FEN, moves=moves, pgn=pgn, pgn_file=f"{folder.name}/clip.pgn")]
    else:
        distinct = {}
        for row in candidates:
            distinct.setdefault(row["piece_placement"], row)
        cards = [card(row, "视频画面中的候选局面，行棋方待确认。")
                 for row in list(distinct.values())[:3]]
    return cards, package["sampling"], len(rows), artifacts
