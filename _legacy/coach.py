"""Bounded CodeBuddy calls and evidence-based review."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import chess
import chess.engine


def model_json(instruction, payload, schema):
    binary = shutil.which("codebuddy.cmd" if os.name == "nt" else "codebuddy")
    if not binary:
        raise RuntimeError("未找到 CodeBuddy CLI")
    model = os.getenv("CHESS_COACH_MODEL", "deepseek-v4.1-flash")
    if not model or not all(c.isascii() and (c.isalnum() or c in "-_.") for c in model):
        raise RuntimeError("模型 ID 无效")
    # User input travels exclusively over stdin, never through a Windows batch command.
    prompt = instruction + "\n仅返回 JSON。以下是数据：" + json.dumps(payload, ensure_ascii=False)
    cwd = Path(__file__).with_name('.model-workspace')
    cwd.mkdir(exist_ok=True)
    result = subprocess.run(
        [binary, "-p", "--model", model, "--output-format", "json", "--tools=",
         "--strict-mcp-config", "--permission-mode", "dontAsk", "--setting-sources", "user"],
        cwd=cwd, input=prompt.encode(), capture_output=True, timeout=45,
    )
    if result.returncode:
        raise RuntimeError("CodeBuddy 调用失败，请检查登录、模型与网络")
    envelope = json.loads(result.stdout)
    if isinstance(envelope, list):
        envelope = next((event for event in reversed(envelope)
                         if isinstance(event, dict) and event.get("type") == "result"), None)
    if not isinstance(envelope, dict) or envelope.get("is_error"):
        raise RuntimeError("CodeBuddy 未返回有效结果")
    value = envelope.get("structured_output") or envelope.get("result")
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("```json") and value.endswith("```"):
            value = value[7:-3].strip()
        value = json.loads(value)
    if not isinstance(value, dict) or set(value) != set(schema):
        raise ValueError("模型输出字段不符合约定")
    if any(type(value[key]) is not kind for key, kind in schema.items()):
        raise ValueError("模型输出类型不符合约定")
    return value


def reconstruct(data):
    board = chess.Board(data["start"])
    if not board.is_valid() or len(data["history"]) > 600:
        raise ValueError("起始局面或走法历史无效")
    for san in data["history"]:
        move = board.parse_san(san)
        if move not in board.legal_moves:
            raise ValueError("走法历史包含非法走法")
        board.push(move)
    return board


def teach(board, lines, question, history=(), hint=False):
    if hint:
        return dict(text="先检查行棋方有没有将军、吃子或直接威胁。选一个候选，再想对方最强的应对。", lines=[])
    if not lines:
        return dict(text="当前没有可供分析的候选走法。", lines=[])
    actual = next((line for line in lines if line["actual"]), None)
    lead = (f"实战走法 {actual['steps'][0]['san']}，{actual['score']}。"
            if actual else "先看本次搜索的候选与应对。")
    if actual and len(actual["steps"]) > 1:
        reply = actual["steps"][1]
        lead += f" 本次搜索给出的应对是 {reply['san']}。"
        if reply["mate"]:
            lead += "这一步直接将死。"
    evidence = []
    for number, line in enumerate(lines, 1):
        moves = " ".join(step["san"] for step in line["steps"])
        evidence.append(dict(id=number, moves=moves, score=line["score"],
                             actual=line["actual"], facts=line["steps"]))
    try:
        answer = model_json(
            "你是中文国际象棋教练。回答 question。只能依据局面和证据，历史问题仅用于消解指代。"
            "输出 {\"explanation\":\"不超过180字\",\"evidence\":[1]}。"
            "正文用「实战走法」「候选一」等引用变化，禁止写具体棋步、格子或分数，"
            "禁止声称强制、唯一、必胜。证据不足请直说。引用编号必须来自输入。",
            dict(question=question, fen=board.fen(), evidence=evidence, history=history),
            {"explanation": str, "evidence": list},
        )
        ids, prose = answer["evidence"], answer["explanation"].strip()
        if not ids or any(type(i) is not int or not 1 <= i <= len(lines) for i in ids):
            raise ValueError("讲解引用无效")
        if not prose or len(prose) > 400 or re.search(r"[a-h][1-8]|[0-9]|O-O|必然|必胜|强制|唯一", prose):
            raise ValueError("讲解含未经验证的具体断言")
        return dict(text=lead + "\n" + prose, lines=lines, evidence=ids, model=True)
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        return dict(text=lead, lines=lines, model=False,
                    notice="模型讲解未通过调用或校验，已保留引擎证据。")


