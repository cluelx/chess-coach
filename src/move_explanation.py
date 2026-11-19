"""Compare an engine recommendation with the move played in review."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import chess

from . import engine

_RUNNER = Path(__file__).resolve().parents[1] / "vendor/binprop/run_chess_review.py"

_CONCEPTS = {
    "material advantage for the side to move": "我方至少多一个兵的子力",
    "positional dominance without material deficit": "我方综合位置更好，且子力未落后",
    "permanent holes in the enemy camp": "我方控制对方阵营里的更多永久弱格",
    "superior pawn structure and passed pawn edge": "我方兵形和通路兵占优",
    "enemy king stranded without shelter": "对方王缺少掩护，容易受到攻击",
    "safe piece infiltration in enemy territory": "我方棋子更能安全进入对方阵营",
    "space-gaining pawn wedge in the centre": "我方中央兵链争得更多空间",
    "opponent starved of forcing resources": "我方有更多将军、得子等强制手段",
    "own camp free of enemy pressure": "我方阵营较少受到直接威胁",
    "opponent lags in mobilization and king shelter": "对方出子较慢，王也缺少掩护",
    "pressure on weak squares around the enemy king": "我方对敌王周围的弱格施压更大",
    "pressure on the opponent weak pawns": "我方对对方弱兵施压更大",
    "opponent saddled with a bad minor piece": "对方有活动受限的马或象",
    "winning capture with no counter-strike": "我方存在得子的交换，对方难以追回同等子力",
    "opponent pieces tied to passive defence": "对方更多棋子被牵制在被动防守上",
    "dangerous advanced passed pawn": "我方有更具威胁的先进通路兵",
    "opponent moves keep walking into loss of material": "对方较多走法会导致丢子",
    "checking initiative against the enemy king": "我方有更多安全的将军手段",
    "enemy pawn over-extended into our camp": "对方推进过深的兵成为攻击目标",
    "opponent burdened with two different kinds of weakness": "对方同时存在多种可攻击的弱点",
    "favorable piece imbalance without a material lead": "子力总值接近时，我方棋子组合更适合这个局面",
    "grip on the opponent weak colour complex": "我方更能控制对方阵营的一组同色弱格",
    "true material edge hidden without a visible lead": "账面子力接近，但我方实际得子条件更好",
    "enemy queen harassed with tempo": "我方能安全地攻击对方的后，赢得一步先手",
    "stronger double attack threat with nothing hanging": "我方有更强的双重威胁，自己的棋子也较安全",
    "enemy camp riddled with concrete pressure points": "我方对对方被钉住或保护不足的棋子施压更多",
    "opponent pieces cornered and hanging": "对方更多棋子活动受限或缺少保护",
    "tempo-gaining threat creation dominance": "我方有更多可以安全制造新威胁的走法",
    "more active king in a simplified position": "简化后的局面里，我方王更加活跃",
    "line pressure with pins and x-rays": "我方借助钉住和穿透攻击形成更强的线控",
}


_PIECE_VALUE = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9}
_PIECE_NAME = {chess.PAWN: "兵", chess.KNIGHT: "马", chess.BISHOP: "象",
               chess.ROOK: "车", chess.QUEEN: "后"}


def _line_events(fen, sans, *, terminal=False):
    board = chess.Board(fen)

    def balance():
        return sum(value * (len(board.pieces(piece, chess.WHITE)) -
                            len(board.pieces(piece, chess.BLACK)))
                   for piece, value in _PIECE_VALUE.items())

    balances = [balance()]
    captures, events = [], []
    pending = False
    for ply, san in enumerate(sans, 1):
        move = board.parse_san(san)
        side = chess.COLOR_NAMES[board.turn]
        if board.is_capture(move):
            target = chess.PAWN if board.is_en_passant(move) else board.piece_type_at(move.to_square)
            captures.append((ply, side, target))
        check = board.gives_check(move)
        board.push(move)
        balances.append(balance())
        if check:
            round_no = (ply + 1) // 2
            pending |= (not terminal and round_no <= engine.CONCEPT_START_ROUNDS
                        and 2 * (round_no + engine.CONCEPT_FOLLOWUP_ROUNDS) > len(sans))
            events.append({"kind": "mate" if board.is_checkmate() else "check",
                           "ply": ply, "side": side})

    for ply, side, target in captures:
        round_no = (ply + 1) // 2
        deadline = 2 * (round_no + engine.CONCEPT_FOLLOWUP_ROUNDS)
        if round_no > engine.CONCEPT_START_ROUNDS:
            continue
        sign = 1 if side == "white" else -1
        baseline = max(sign * balances[0], sign * balances[ply - 1])
        gain = min(sign * value for value in balances[ply:deadline + 1]) - baseline
        if deadline > len(sans):
            pending |= not terminal and gain > 0
        elif gain > 0:
            events.append({"kind": "capture_gain", "ply": ply, "side": side,
                           "target": _PIECE_NAME[target], "gain": gain})
    return sorted(events, key=lambda event: event["ply"]), pending


def _material_difference(preferred, reference, side):
    def gains(line):
        return (item for item in line["events"]
                if item["kind"] == "capture_gain" and item["side"] == side)

    baseline = max((item["gain"] for item in gains(reference)), default=0)
    event = max(gains(preferred), key=lambda item: (item["gain"], -item["ply"]), default=None)
    if event and event["gain"] > baseline:
        return {**event, "forced": False, "branches": [preferred["san"]]}
    return None


def _ranked_concepts(samples):
    env = {
        key: os.environ[key]
        for key in ("SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
        if key in os.environ
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        process = subprocess.run(
            [sys.executable, str(_RUNNER)],
            input=json.dumps({
                "groups": samples, "start_limit": engine.CONCEPT_START_ROUNDS,
                "followup": engine.CONCEPT_FOLLOWUP_ROUNDS,
            }),
            capture_output=True,
            encoding="utf-8",
            env=env,
            cwd=_RUNNER.parent,
            timeout=100,
            check=True,
        )
        ranked = json.loads(process.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        logging.getLogger(__name__).exception("BinProp review analysis failed")
        ranked = {"evaluated": 0, "motifs": []}

    return ranked


def explain(fen: str, recommended: str, played: str, *,
            initial: str | None = None, history: list[str] | None = None,
            depth: int = engine.REVIEW_REPLY_DEPTH) -> dict:
    groups = engine.comparison_positions(
        fen, recommended, played, initial=initial, history=history, depth=depth
    )
    if groups is None:
        return {"status": "unavailable"}
    recommended_group, played_group = groups["positive"], groups["negative"]
    positive, negative = (len(group["branches"]) for group in (recommended_group, played_group))
    result = {
        "positive_count": positive,
        "negative_count": negative,
        "positive_example": recommended_group["main"]["san"],
        "negative_example": played_group["main"]["san"],
        "motifs": [],
    }

    samples = {side: group["branches"] for side, group in groups.items()}
    main_lines = [recommended_group["main"], played_group["main"]]
    line_groups = {**samples, "main": main_lines}
    ranked = _ranked_concepts(line_groups)
    pending = [
        line_groups[side][index]
        for side, indexes in ranked.get("pending", {}).items() for index in indexes
    ]
    for rows in line_groups.values():
        for row in rows:
            if _line_events(fen, row["san"], terminal=row["terminal"])[1]:
                pending.append(row)
    pending.extend(group["main"] for group in groups.values()
                   if group["forced_mate"] or group.get("forced_loss"))
    if engine.extend_review_lines(fen, pending, initial=initial, history=history, depth=depth):
        ranked = _ranked_concepts(line_groups)
    result["positive_example"], result["negative_example"] = (row["san"] for row in main_lines)
    concepts = ranked.get("events", {})
    result["round_events"] = {}
    for side, rows in line_groups.items():
        result["round_events"][side] = []
        for index, row in enumerate(rows):
            found = concepts[side][index] if side in concepts else []
            result["round_events"][side].append({
                "san": row["san"],
                "events": _line_events(fen, row["san"], terminal=row["terminal"])[0],
                "concepts": [
                    {"text": _CONCEPTS.get(item["name"], item["name"]), "rounds": item["rounds"]}
                    for item in found
                ],
            })

    best_win, played_win = (group["forced_mate"] for group in (recommended_group, played_group))
    best_loss, played_loss = (group.get("forced_loss", False) for group in (recommended_group, played_group))
    result["status"] = "ok"
    if best_win and played_win:
        result["mate_outcome"] = "both_win"
        return result
    if best_loss and played_loss:
        result["mate_outcome"] = "both_lose"
        return result

    def mate_examples(group):
        return [row["san"] for row in group["branches"] if row["checkmate"]]

    winning = mate_examples(recommended_group)
    actual = mate_examples(played_group)
    if best_win:
        result["mate"] = {
            "forced": True, "main": result["positive_example"],
            "branches": winning, "played_hits": len(actual),
        }
    if played_loss:
        result["opponent_reply"] = {
            "kind": "mate", "forced": True, "branches": [result["negative_example"]],
        }
    if played_win:
        result["mate_outcome"] = "played_win"
    elif best_loss:
        result["mate_outcome"] = "recommended_lose"
    if best_win or played_loss or played_win or best_loss:
        return result

    best_line, played_line = result["positive_example"], result["negative_example"]
    best_events, played_events = result["round_events"]["main"]
    mover = recommended_group["main"]["color"]
    opponent = "black" if mover == "white" else "white"
    reply = _material_difference(played_events, best_events, opponent)
    gain = _material_difference(best_events, played_events, mover)
    if reply or gain:
        if reply:
            result["opponent_reply"] = reply
        if gain:
            result["material_gain"] = gain
        return result

    mate_intent = (negative >= 2 and len(winning) >= 2
                   and 2 * len(winning) >= positive and 4 * len(actual) <= negative)

    def add_mate_intent():
        result["mate"] = {
            "forced": False, "main": best_line, "branches": winning,
            "played_hits": len(actual),
        }

    if min(positive, negative) < 2:
        result["status"] = "insufficient"
        return result

    stable = [item for item in ranked["motifs"] if item.get("main_difference")]
    if mate_intent and not stable:
        add_mate_intent()
        return result
    result["motifs"] = [
        {
            "text": _CONCEPTS.get(item["name"], item["name"]),
            "positive_hits": len(item["positive_indices"]),
            "negative_hits": item["negative_hits"],
            "stable": bool(stable),
            "branches": list({tuple(line): line for line in (
                ([best_line] if stable else []) +
                [samples["positive"][i]["san"] for i in item["positive_indices"]]
            )}.values()),
        }
        for item in (stable or ranked["motifs"])
    ]
    result["status"] = (
        "ok" if result["motifs"] else "no_match" if ranked["evaluated"] else "unavailable"
    )
    return result
