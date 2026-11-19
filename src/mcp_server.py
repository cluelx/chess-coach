"""棋课本地工具服务（MCP stdio）。

由 CodeBuddy CLI 通过 --mcp-config 拉起，在一次 Agent 运行里提供只读能力：
本地教程检索、PGN/FEN 解析、棋盘图识别、Stockfish 局面分析。
只输出 JSON-RPC 一行一条，日志一律走 stderr。
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chess
from fastapi import HTTPException

from src import db, engine, knowledge, learning, openings

PROTOCOL = "2025-06-18"

STAGES = {
    "search_local_materials": "正在检索本地教程…",
    "parse_pgn_or_fen": "正在解析棋谱…",
    "recognize_board_image": "正在识别棋盘图…",
    "analyse_position": "正在用 Stockfish 分析局面…",
}

TOOLS = [
    {
        "name": "search_local_materials",
        "description": "检索棋课站内资料：知识点、已发布课程、经典开局和题库战术主题。返回 id 与站内链接。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "中文或英文关键词，例如「底线杀」「牵制」「fork」"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 6},
            },
            "required": ["query"],
        },
    },
    {
        "name": "parse_pgn_or_fen",
        "description": "校验并解析 PGN 或完整 FEN，返回起始局面和逐手走法（san/uci）。解析失败说明棋谱不合法。",
        "inputSchema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "完整 FEN（六段）或含走法的 PGN"}},
            "required": ["content"],
        },
    },
    {
        "name": "recognize_board_image",
        "description": "用本地 Fenshot 识别二维棋盘截图，返回棋子摆放。只描述摆放，不判断轮到谁走。",
        "inputSchema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "棋盘截图的 https 直链（png/jpg/webp）"}},
            "required": ["url"],
        },
    },
    {
        "name": "analyse_position",
        "description": "用本地 Stockfish 分析一个合法局面，返回前三候选着法、评分与主变化。cp 为白方视角厘兵分。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fen": {"type": "string", "description": "完整 FEN"},
                "depth": {"type": "integer", "minimum": 6, "maximum": 22, "default": 12},
            },
            "required": ["fen"],
        },
    },
]


def _log(message):
    path = os.environ.get("CHESS_COACH_MCP_LOG")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf8") as handle:
            handle.write(str(message) + "\n")
    except OSError:
        pass


def _haystack(*values):
    return " ".join(str(value or "") for value in values).casefold()


def _public_url(url):
    parsed = urlsplit(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username:
        raise ValueError("需要一个不带账号信息的 https 图片直链")
    host = parsed.hostname
    if host in ("localhost",) or host.endswith(".local"):
        raise ValueError("不接受本机地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return parsed.geturl()
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise ValueError("不接受内网地址")
    return parsed.geturl()


def search_local_materials(query="", limit=6):
    text = str(query or "").strip().casefold()
    if not text:
        raise ValueError("请提供检索关键词")
    limit = max(1, min(10, int(limit or 6)))
    items = []

    for kp in knowledge.VISIBLE_KPS:
        if text in _haystack(kp["name"], kp["summary"], kp["group"]):
            items.append({"id": "kp-" + kp["id"], "kind": "知识点", "title": kp["name"],
                          "summary": kp["summary"], "link": "#/library?kp=" + kp["id"]})

    for lesson in knowledge.PUBLISHED_LESSONS:
        if text in _haystack(lesson["title"], lesson["intro"]):
            items.append({"id": "lesson-" + lesson["id"], "kind": "课程", "title": lesson["title"],
                          "summary": lesson["intro"], "link": "#/lesson/" + lesson["id"]})

    for opening in openings.OPENINGS:
        if text in _haystack(opening["name"], opening["summary"]):
            items.append({"id": "opening-" + opening["id"], "kind": "开局", "title": opening["name"],
                          "summary": opening["summary"], "link": "#/openings/" + opening["id"]})

    themes = db.query("SELECT theme, COUNT(*) c FROM puzzle_theme GROUP BY theme ORDER BY c DESC")
    for row in themes:
        theme = row["theme"]
        if text in _haystack(theme, knowledge.THEME_CN.get(theme, "")):
            items.append({"id": "theme-" + theme, "kind": "题库主题",
                          "title": knowledge.THEME_CN.get(theme, theme), "theme": theme,
                          "summary": f"本地题库 {row['c']} 道",
                          "link": "#/library?theme=" + theme})

    result = {"items": items[:limit]}
    if not knowledge.TUTORIALS_PUBLISHED:
        result["note"] = "教程正文正在校对，知识点与课程暂未公开；开局与题库主题可用。"
    return result


def parse_pgn_or_fen(content=""):
    try:
        return learning.position(learning.PositionIn(content=str(content or "")))
    except HTTPException as exc:
        raise ValueError(str(exc.detail)) from exc


def recognize_board_image(url=""):
    link = _public_url(url)
    data = learning.public_asset(link, 5000000)
    try:
        boards = learning.recognize_image(data)
    except (OSError, ValueError) as exc:
        raise ValueError("识图失败，请换一张清晰的二维棋盘图") from exc
    if not boards:
        raise ValueError("图片中没有识别到可用棋盘")
    return {"positions": [{"placement": board["placement"]} for board in boards],
            "note": "识图只表示棋子摆放，不表示轮到谁走。"}


def analyse_position(fen="", depth=12):
    try:
        board = chess.Board(str(fen or "").strip())
    except ValueError as exc:
        raise ValueError("局面不是合法 FEN") from exc
    if not board.is_valid():
        raise ValueError("局面不合法")
    depth = max(6, min(22, int(depth or 12)))
    if not engine.available():
        raise ValueError("本机没有 Stockfish，无法分析局面")
    rows = engine.analyse_positions([board.fen()], depth=depth, multipv=3)
    if not rows:
        raise ValueError("引擎没有返回分析结果")
    return {"fen": board.fen(), "lines": rows, "note": "cp 为白方视角厘兵分，mate 为将杀步数。"}


def call_tool(name, arguments):
    handlers = {
        "search_local_materials": search_local_materials,
        "parse_pgn_or_fen": parse_pgn_or_fen,
        "recognize_board_image": recognize_board_image,
        "analyse_position": analyse_position,
    }
    handler = handlers.get(name)
    if not handler:
        return None, "没有这个工具：" + str(name)
    args = arguments if isinstance(arguments, dict) else {}
    try:
        return handler(**args), None
    except TypeError as exc:
        return None, "参数不正确：" + str(exc)
    except (ValueError, OSError) as exc:
        return None, str(exc)


def handle(request):
    if not isinstance(request, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "chess-coach", "version": "1.0.0"},
        }}
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = request.get("params") or {}
        payload, problem = call_tool(params.get("name"), params.get("arguments"))
        if problem is not None:
            return {"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": problem}], "isError": True}}
        return {"jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "isError": False}}
    if request_id is None:
        return None
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": "Method not found: " + str(method)}}


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            print("跳过无法解析的输入", file=sys.stderr, flush=True)
            continue
        try:
            _log("request " + str(request.get("method") if isinstance(request, dict) else None))
            reply = handle(request)
        except Exception as exc:  # noqa: BLE001
            print("处理失败：" + repr(exc), file=sys.stderr, flush=True)
            reply = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                     "error": {"code": -32603, "message": "Internal error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
