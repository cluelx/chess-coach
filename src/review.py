"""复盘管线：PGN → 关键节点 → 知识点。

全部是可判定的规则推理，没有模型参与：
  · 引擎负责的部分用确定性检测替代（一次杀、送子、叉子、牵制、底线）
  · 输出不是“你该走 X”，而是“这一步属于哪个概念”，再接到题库
"""

from __future__ import annotations

import io
import time
from typing import Iterable

import chess
import chess.pgn

from . import db, engine, knowledge
from .motifs import (
    PIECE_CN,
    back_rank_exposed,
    balance,
    heavy_on_home_rank,
    knight_rim,
    mate_in_1,
    pinning_moves,
    pinned_pieces,
    safe_fork_move,
    sq_name,
    value,
    worst_capture_delta,
    fork_targets_after,
)

SEVERITY_LABEL = {
    range(90, 200): "致命",
    range(60, 90): "严重",
    range(40, 60): "明显",
    range(25, 40): "轻微",
    range(0, 25): "提示",
}


def severity_label(s: int) -> str:
    for r, label in SEVERITY_LABEL.items():
        if s in r:
            return label
    return "提示"


# --------------------------------------------------------------------------
# 单步检测
# --------------------------------------------------------------------------

def analyze_move(board: chess.Board, move: chess.Move, player: bool, ply: int) -> list[dict]:
    """board 是走这步之前的局面（board.turn == player）。"""
    findings: list[dict] = []
    fen_before = board.fen()
    san = board.san(move)
    move_no = board.fullmove_number
    mover_piece = board.piece_at(move.from_square)
    mover_type = mover_piece.piece_type if mover_piece else None
    base = balance(board, player)

    def add(motif, kp_id, severity, title, detail, better=None):
        findings.append(
            {
                "ply": ply,
                "move_no": move_no,
                "side": "white" if player else "black",
                "san": san,
                "from": sq_name(move.from_square),
                "to": sq_name(move.to_square),
                "uci": move.uci(),
                "fen_before": fen_before,
                "motif": motif,
                "kp_id": kp_id,
                "severity": severity,
                "level": severity_label(severity),
                "title": title,
                "detail": detail,
                "better": better,
            }
        )

    # ---- 走之前：有没有被漏掉的好棋 ----
    m1 = mate_in_1(board)
    if m1 is not None and m1 != move:
        add(
            "missed_mate", "k03", 100,
            "错过一步杀",
            f"这个局面里 {board.san(m1)} 直接终结棋局，实战走了 {san}。",
            {"san": board.san(m1), "uci": m1.uci(), "fen": fen_before},
        )

    fork_before = safe_fork_move(board, min_total=900)
    if fork_before is not None and fork_before != move and m1 is None:
        tg = fork_targets_after(board, fork_before)
        if len(tg) >= 2:
            add(
                "missed_fork", "k06", 56,
                "错过一个叉子",
                f"{board.san(fork_before)} 可以同时攻击 "
                + "、".join(f"{t['square']} 的{t['piece']}" for t in tg[:3])
                + "，实战没走。",
                {"san": board.san(fork_before), "uci": fork_before.uci(), "fen": fen_before},
            )

    # 漏掉免费子
    lost_before, cap_before = worst_capture_delta(board, not player)
    if cap_before is not None and lost_before <= -300 and not board.is_capture(move):
        victim = board.piece_at(cap_before.to_square)
        add(
            "missed_capture", "k08", 46,
            "漏掉一个免费子",
            f"这个局面里可以白吃 {sq_name(cap_before.to_square)} 的"
            f"{PIECE_CN.get(victim.piece_type, '子') if victim else '子'}，实战走了别的。",
            {"san": board.san(cap_before), "uci": cap_before.uci(), "fen": fen_before},
        )

    pin_before = pinning_moves(board, player, min_value=320)
    if pin_before is not None and pin_before != move:
        add(
            "missed_pin", "k07", 40,
            "错过一个牵制",
            f"{board.san(pin_before)} 可以立刻把对方一个值钱的子钉在中线上。",
            {"san": board.san(pin_before), "uci": pin_before.uci(), "fen": fen_before},
        )

    # ---- 走完之后 ----
    pins_own_before = pinned_pieces(board, player, min_value=320)
    board.push(move)
    fen_after = board.fen()
    try:
        opp = not player

        om1 = mate_in_1(board)
        if om1 is not None:
            add(
                "allowed_mate", "k02", 95,
                "让对方形成一步杀",
                f"走完 {san} 之后，对方 {board.san(om1)} 就是杀。",
                {"san": board.san(om1), "uci": om1.uci(), "fen": fen_after},
            )

        delta, cap_move = worst_capture_delta(board, player)
        # 用“子力变化 − 对方可取得的收益”衡量真实损失，正常兑子不会被误报
        delta = (balance(board, player) - base) + delta
        if delta <= -400:
            victim = board.piece_at(cap_move.to_square) if cap_move is not None else None
            what = PIECE_CN.get(victim.piece_type, "子") if victim else "子"
            sev = min(92, 58 + (-delta) // 60)
            add(
                "hanging", "k08", sev,
                f"送掉一个{what}",
                f"走完 {san} 之后，对方有强制吃子，兑完净亏约 {abs(delta) // 100} 个兵。",
                None,
            )
        elif delta <= -180:
            add(
                "hanging", "k08", 46,
                "丢一个交换或轻子",
                f"这笔交换净亏约 {abs(delta) // 100} 个兵，实战没有算清。",
                None,
            )

        if back_rank_exposed(board, player) and heavy_on_home_rank(board, player):
            add(
                "backrank", "k10", 48,
                "底线留下后门",
                "王在最底排、前面三个兵一步没动，对方重子已经能沿这条横线进来。",
                None,
            )

        # 只有“这步走出来的”对方叉子才算到这一步头上
        pre = board.copy(stack=False)
        pre.turn = not player
        of_before = safe_fork_move(pre, min_total=900)
        of = safe_fork_move(board, min_total=900)
        if of is not None and delta > -180 and (of_before is None or of.uci() != of_before.uci()):
            tg = fork_targets_after(board, of)
            if len(tg) >= 2:
                add(
                    "allowed_fork", "k06", 50,
                    "让对方可以叉子",
                    f"对方 {board.san(of)} 可以同时攻击 "
                    + "、".join(t["square"] for t in tg[:3]) + "。",
                    {"san": board.san(of), "uci": of.uci(), "fen": fen_after},
                )

        pins_own_after = pinned_pieces(board, player, min_value=320)
        new_pins = pins_own_after - pins_own_before
        if new_pins:
            sq = sorted(new_pins, key=lambda s: -value(board.piece_at(s)))[0]
            add(
                "allowed_pin", "k07", 38,
                "被牵制住一个子",
                f"{sq_name(sq)} 上的子被钉住了，动它会暴露身后的目标。",
                None,
            )

        if mover_type == chess.KNIGHT:
            rims = [s for s in knight_rim(board, player) if s == move.to_square]
            if rims:
                add(
                    "knight_rim", "k17", 24,
                    "把马走到边线",
                    f"{sq_name(move.to_square)} 的马能控制的格子只剩两三个，价值缩水。",
                    None,
                )
    finally:
        board.pop()

    return findings


def _opening_notes(board: chess.Board, prev_move: chess.Move | None, move: chess.Move, player: bool) -> list[dict]:
    if prev_move is None or prev_move.from_square != move.from_square:
        return []
    return [
        {
            "ply": 0,
            "move_no": board.fullmove_number,
            "side": "white" if player else "black",
            "san": board.san(move),
            "from": sq_name(move.from_square),
            "to": sq_name(move.to_square),
            "uci": move.uci(),
            "fen_before": board.fen(),
            "motif": "opening_principle",
            "kp_id": "k09",
            "severity": 26,
            "level": "轻微",
            "title": "同一只子连走两步",
            "detail": "开局阶段重复动同一只子，等于把出子的时间让给对方。",
            "better": None,
        }
    ]


# --------------------------------------------------------------------------
# 整局
# --------------------------------------------------------------------------

def analyze_pgn(
    pgn_text: str,
    player_color: str = "auto",
    learner_id: str = "demo",
    learner_level: int = 1,
    engine_time: float = 0.0,
    engine_depth: int = 16,
) -> dict:
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise ValueError("无法解析这盘棋的 PGN")
    if game.errors:
        first = game.errors[0]
        raise ValueError(f"棋谱第 {getattr(first, 'move_number', '?')} 步有问题：{first}")

    if player_color == "auto":
        player = chess.WHITE
        try:
            we = int(game.headers.get("WhiteElo", "0") or 0)
            be = int(game.headers.get("BlackElo", "0") or 0)
            player = chess.WHITE if we >= be else chess.BLACK
        except Exception:
            player = chess.WHITE
    else:
        player = player_color == "white"

    board = game.board()
    timeline = []
    findings: list[dict] = []
    history: list[chess.Move] = []
    ply = 0

    for move in game.mainline_moves():
        ply += 1
        is_player = board.turn == player
        timeline.append(
            {
                "ply": ply,
                "move_no": board.fullmove_number,
                "side": "white" if board.turn == chess.WHITE else "black",
                "san": board.san(move),
                "uci": move.uci(),
                "from": sq_name(move.from_square),
                "to": sq_name(move.to_square),
                "fen": board.fen(),
                "is_player": is_player,
            }
        )
        board.push(move)
        history.append(move)

    findings = _dedupe(findings)
    final_fen = board.fen()

    # ---- 引擎层：评估曲线 + 每步最优解 ----
    eng_meta = {"used": False, "name": None, "depth": engine_depth, "per_move": engine_time}
    eval_curve: list[dict] = []
    turning: list[dict] = []
    avg_loss = None
    if (engine_depth or engine_time) and engine.available():
        rows = engine.analyse_positions(
            [m["fen"] for m in timeline] + [final_fen],
            per_move=engine_time,
            depth=engine_depth or None,
        )
        if len(rows) == len(timeline) + 1:
            _attach_eval(timeline, rows, player)
            eval_curve = [{"ply": i, "cp": r["cp"], "mate": r["mate"]} for i, r in enumerate(rows)]
            findings = verified_findings(timeline)
            turning = _turning_points(timeline, findings, player)
            losses = [m["loss"] for m in timeline if m["is_player"] and m.get("loss") is not None]
            if losses:
                avg_loss = int(sum(max(0, x) for x in losses) / len(losses))
            eng_meta = {
                "used": True,
                "name": (engine.info().get("name") or "Stockfish"),
                "depth": engine_depth,
                "per_move": engine_time,
            }

    if not eng_meta["used"]:
        # 没有引擎时，用规则检测器的结果当转折点，播放器仍可用
        turning = _rule_points(findings, timeline)


    by_kp: dict[str, dict] = {}
    for f in findings:
        kp = f["kp_id"]
        slot = by_kp.setdefault(
            kp,
            {
                "kp_id": kp,
                "count": 0,
                "severity": 0,
                "samples": [],
                "title": knowledge.KP_BY_ID[kp]["name"],
            },
        )
        slot["count"] += 1
        slot["severity"] = max(slot["severity"], f["severity"])
        if len(slot["samples"]) < 3:
            slot["samples"].append(
                {"ply": f["ply"], "move_no": f["move_no"], "side": f["side"], "san": f["san"], "title": f["title"]}
            )

    ranked = sorted(by_kp.values(), key=lambda x: (-x["severity"], -x["count"]))
    try:
        progress = db.kp_progress(learner_id)
    except Exception:
        progress = {}
    studied = set(progress.keys())

    picked: list[dict] = [r for r in ranked if r["kp_id"] in studied][:2]
    for r in ranked:
        if len(picked) >= 2:
            break
        if all(r["kp_id"] != p["kp_id"] for p in picked):
            picked.append(r)
    review_kps = picked[:2]

    new_kp = None
    for r in ranked:
        if all(r["kp_id"] != p["kp_id"] for p in review_kps):
            new_kp = r
            break
    if new_kp is None:
        for kp in knowledge.kps_for_level(learner_level):
            if kp["id"] not in studied and kp["themes"]:
                new_kp = {"kp_id": kp["id"], "count": 0, "severity": 0, "title": kp["name"], "samples": []}
                break

    blunders = sum(1 for m in timeline if m.get("tag") == "blunder")
    mistakes = sum(1 for m in timeline if m.get("tag") == "mistake")
    inacc = sum(1 for m in timeline if m.get("tag") == "inaccuracy")

    return {
        "headers": {k: v for k, v in game.headers.items()},
        "result": game.headers.get("Result", "*"),
        "player": "white" if player else "black",
        "plies": len(timeline),
        "moves": timeline,
        "final_fen": final_fen,
        "eval_curve": eval_curve,
        "turning_points": turning,
        "engine": eng_meta,
        "avg_loss": avg_loss,
        "findings": sorted(findings, key=lambda f: (-f["severity"], f["ply"])),
        "by_kp": ranked,
        "focus": {"review": review_kps[0] if review_kps else None,
                  "new": new_kp},
        "stats": {
            "critical": sum(1 for f in findings if f["severity"] >= 90),
            "serious": sum(1 for f in findings if 60 <= f["severity"] < 90),
            "notable": sum(1 for f in findings if 40 <= f["severity"] < 60),
            "blunders": blunders,
            "mistakes": mistakes,
            "inaccuracies": inacc,
        },
        "analyzed_at": time.time(),
    }


# --------------------------------------------------------------------------
# 引擎层：评估曲线、转折点
# --------------------------------------------------------------------------

LOSS_BLUNDER = 250
LOSS_MISTAKE = 120
LOSS_INACCURACY = 50


def _fmt_cp(cp: int | None, mate: int | None = None) -> str:
    if cp is None:
        return "—"
    if mate is not None:
        return ("+M%d" if mate > 0 else "-M%d") % abs(mate)
    if abs(cp) >= 9000:
        # 引擎判定的必胜/必败（已结束或强制杀）
        return "胜势" if cp > 0 else "败势"
    return "%+.1f" % (cp / 100.0)


def _classify(loss: int) -> str | None:
    if loss >= LOSS_BLUNDER:
        return "blunder"
    if loss >= LOSS_MISTAKE:
        return "mistake"
    if loss >= LOSS_INACCURACY:
        return "inaccuracy"
    if loss <= -120:
        return "great"
    return None


def _attach_eval(timeline: list[dict], rows: list[dict], player: bool) -> None:
    """把每个局面的分数差挂到「走这一步」上。cp 为白方视角。"""
    for i, m in enumerate(timeline):
        before, after = rows[i], rows[i + 1]
        sign = 1 if m["side"] == "white" else -1
        m["cp_before"] = before["cp"]
        m["cp_after"] = after["cp"]
        m["eval_before"] = _fmt_cp(before["cp"], before.get("mate"))
        m["eval_after"] = _fmt_cp(after["cp"], after.get("mate"))
        best = None
        if before.get("best_uci"):
            best = {
                "uci": before["best_uci"],
                "san": before.get("best_san"),
                "pv": before.get("pv_san") or [],
                "pv_uci": before.get("pv_uci") or [],
            }
            best["from"] = best["uci"][:2]
            best["to"] = best["uci"][2:4]
        m["best"] = best
        m["best_is_played"] = bool(best and best["uci"] == m["uci"])
        m["mate_before"] = before.get("mate")
        m["mate_after"] = after.get("mate")
        m["pv_after"] = after.get("pv_uci") or []
        if before["cp"] is None or after["cp"] is None:
            continue
        loss = int((before["cp"] - after["cp"]) * sign)
        if m["best_is_played"]:
            loss = 0
        m["loss"] = max(-1200, min(1200, loss))
        m["tag"] = _classify(m["loss"])


def _kp_guess(move: dict) -> str | None:
    """引擎发现了失误、但规则检测器没覆盖时，按最优着的性质猜一个知识点。"""
    best = move.get("best")
    if not best or not best.get("uci"):
        return None
    try:
        board = chess.Board(move["fen"])
        mv = chess.Move.from_uci(best["uci"])
        if mv not in board.legal_moves:
            return None
        board.push(mv)
        if board.is_checkmate():
            return "k03"
    except Exception:
        return None
    return None


def _clear_material_win(board: chess.Board, pv_uci: list[str]) -> bool:
    """Conservative capture evidence: immediate, not recapturable, persists in PV."""
    if len(pv_uci) < 5:
        return False
    side = board.turn
    first = chess.Move.from_uci(pv_uci[0])
    victim = board.piece_at(first.to_square)
    if first not in board.legal_moves or not victim or victim.piece_type not in (
        chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN
    ):
        return False
    values = {chess.PAWN:1, chess.KNIGHT:3, chess.BISHOP:3, chess.ROOK:5, chess.QUEEN:9}
    def material():
        return sum(n*(len(board.pieces(pt,side))-len(board.pieces(pt,not side))) for pt,n in values.items())
    base = material()
    board.push(first)
    try:
        for reply in list(board.legal_moves):
            board.push(reply)
            try:
                if material() - base < 2 or board.is_checkmate():
                    return False
            finally:
                board.pop()
        pushed = 0
        try:
            for uci in pv_uci[1:]:
                board.push_uci(uci)
                pushed += 1
            return material() - base >= 2 and not board.is_checkmate()
        finally:
            for _ in range(pushed):
                board.pop()
    finally:
        board.pop()


def verified_findings(timeline: list[dict]) -> list[dict]:
    """Publish only motifs with direct legal-move evidence."""
    from .similar import proves_mate
    out = []
    for m in timeline:
        if not m["is_player"] or m.get("tag") not in ("mistake", "blunder"):
            continue
        board = chess.Board(m["fen"])
        best = m.get("best")
        if not best or m.get("best_is_played"):
            continue
        ply = m["ply"]
        board.push_uci(m["uci"])
        if board.is_game_over():
            continue
        replies = []
        for reply in list(board.legal_moves):
            board.push(reply)
            if board.is_checkmate():
                replies.append(reply)
            board.pop()
        board.pop()
        query = {"fen": m["fen"], "uci": best["uci"]}
        if _kp_guess(m) == "k03":
            sign = 1 if board.turn else -1
            # A slower winning mate remains a winning mate.
            if (m.get("mate_after") or 0) * sign > 0:
                continue
            title, detail, kp, motif = "错过一步杀", f"{best['san']} 可立即将杀。", "k03", "missed_mate"
        elif replies:
            # Verify that the alternative avoids immediate mate.
            board.push_uci(best["uci"])
            avoids = True
            for reply in list(board.legal_moves):
                board.push(reply)
                avoids &= not board.is_checkmate()
                board.pop()
            if not avoids:
                continue
            post = chess.Board(m["fen"])
            post.push_uci(m["uci"])
            query = {"fen": post.fen(), "uci": replies[0].uci()}
            title, detail, kp, motif = "允许对手一步杀", "实战着之后对手可以立即将杀；引擎推荐着不会立刻被杀。", "k02", "allowed_mate"
        elif (m.get("mate_before") or 0) * (1 if board.turn else -1) in (2, 3) and (
                (m.get("mate_after") or 0) * (1 if board.turn else -1) <= 0):
            n = abs(m["mate_before"])
            if not proves_mate(board, chess.Move.from_uci(best["uci"]), 2*n-1):
                continue
            title, detail, kp, motif = "错过强制将杀", f"{best['san']} 可在 {n} 步内强制将杀。", "k25", "missed_short_mate"
            query["pv"] = best.get("pv_uci")
        elif (m.get("mate_after") or 0) * (1 if board.turn else -1) in (-2, -3) and (
                (m.get("mate_before") or 0) * (1 if board.turn else -1) >= 0) and m.get("pv_after"):
            post = board.copy()
            post.push_uci(m["uci"])
            pv = m["pv_after"]
            n = abs(m["mate_after"])
            if not proves_mate(post, chess.Move.from_uci(pv[0]), 2*n-1):
                continue
            title, detail, kp, motif = "允许对手强制将杀", f"实战着之后，对手可在 {n} 步内强制将杀。", "k02", "allowed_short_mate"
            query = {"fen": post.fen(), "uci": pv[0], "pv": pv}
        elif (m.get("mate_before") is None and m.get("mate_after") is None
              and m["loss"] >= 200 and not board.is_capture(chess.Move.from_uci(m["uci"]))
              and _clear_material_win(board, best.get("pv_uci") or [])):
            title, detail, kp, motif = ("错过得子机会", f"{best['san']} 吃子后，对手不能立即夺回子力；引擎主变化中也保留了子力收益。",
                                         "k08", "verified_capture")
            query = None
        else:
            continue
        out.append({**m, "ply": ply, "kp_id": kp, "motif": motif, "title": title,
                    "detail": detail, "similar_query": query, "severity": 70 if motif == "verified_capture" else 95,
                    "level": "明显" if motif == "verified_capture" else "关键", "better": best})
    return out


def _turning_points(timeline: list[dict], findings: list[dict], player: bool) -> list[dict]:
    by_ply: dict[int, list[dict]] = {}
    for f in findings:
        by_ply.setdefault(f["ply"], []).append(f)

    out: list[dict] = []
    for m in timeline:
        if not m.get("is_player"):
            continue
        tag = m.get("tag")
        if tag not in ("blunder", "mistake"):
            continue
        fs = sorted(by_ply.get(m["ply"], []), key=lambda x: -x["severity"])
        rule = fs[0] if fs else None
        kp_ids: list[str] = []
        for f in fs:
            if f["kp_id"] not in kp_ids:
                kp_ids.append(f["kp_id"])
        kp_id = rule["kp_id"] if rule else None
        if kp_id and kp_id not in kp_ids:
            kp_ids.insert(0, kp_id)

        best = m.get("best")
        suggest = ""
        if best and best.get("san") and not m.get("best_is_played"):
            suggest = f" 引擎认为 {best['san']} 更好。"

        if rule and rule["severity"] >= 55:
            # 规则检测器和引擎都指向这一步：用规则给出的具体说法
            title = rule["title"]
            explain = rule["detail"] + suggest
        else:
            title = "致命失误" if tag == "blunder" else "明显失误"
            explain = ""
            if rule:
                explain += f"（程序另外检测到：{rule['title']}）"

        out.append(
            {
                "ply": m["ply"],
                "move_no": m["move_no"],
                "side": m["side"],
                "san": m["san"],
                "uci": m["uci"],
                "from": m["from"],
                "to": m["to"],
                "fen": m["fen"],
                "loss": m["loss"],
                "tag": tag,
                "eval_before": m["eval_before"],
                "eval_after": m["eval_after"],
                "best": m.get("best"),
                "best_is_played": m.get("best_is_played"),
                "kp_id": kp_id,
                "kp_ids": kp_ids,
                "title": title,
                "similar_query": rule.get("similar_query") if rule else None,
                "explain": explain,
                "rule": ({"motif": rule["motif"], "severity": rule["severity"], "detail": rule["detail"]} if rule else None),
            }
        )

    # 转折点太少时，把最亏的几步「不精确」也补进来（标签仍然区分，不冒充重大失误）
    need = 3 - len(out)
    if need > 0:
        done = {x["ply"] for x in out}
        soft = [
            m for m in timeline
            if m.get("is_player") and m.get("tag") == "inaccuracy" and m["ply"] not in done
        ]
        for m in sorted(soft, key=lambda x: -x["loss"])[:need]:
            fs = sorted(by_ply.get(m["ply"], []), key=lambda x: -x["severity"])
            rule = fs[0] if fs else None
            out.append(
                {
                    "ply": m["ply"], "move_no": m["move_no"], "side": m["side"],
                    "san": m["san"], "uci": m["uci"], "from": m["from"], "to": m["to"],
                    "fen": m["fen"], "loss": m["loss"], "tag": "inaccuracy",
                    "eval_before": m["eval_before"], "eval_after": m["eval_after"],
                    "best": m.get("best"), "best_is_played": m.get("best_is_played"),
                    "kp_id": (rule["kp_id"] if rule else None),
                    "kp_ids": [rule["kp_id"]] if rule else [],
                    "title": rule["title"] if rule else "这一步不够精确",
                    "explain": rule["detail"] if rule else "",
                    "rule": ({"motif": rule["motif"], "severity": rule["severity"], "detail": rule["detail"]} if rule else None),
                }
            )
    out.sort(key=lambda x: x["ply"])

    if len(out) > 14:
        keep = sorted(sorted(out, key=lambda x: -x["loss"])[:14], key=lambda x: x["ply"])
        out = keep
    return out


def _rule_points(findings: list[dict], timeline: list[dict]) -> list[dict]:
    """没有引擎时的降级路径：规则检测器报出的点，直接当转折点。"""
    by_ply = {m["ply"]: m for m in timeline}
    out = []
    for f in sorted(findings, key=lambda x: x["ply"]):
        m = by_ply.get(f["ply"]) or {}
        better = f.get("better")
        best = None
        if better and better.get("uci"):
            best = {
                "uci": better["uci"],
                "san": better.get("san"),
                "from": better["uci"][:2],
                "to": better["uci"][2:4],
                "pv": [],
            }
        out.append(
            {
                "ply": f["ply"],
                "move_no": f["move_no"],
                "side": f["side"],
                "san": f["san"],
                "uci": f["uci"],
                "from": f["from"],
                "to": f["to"],
                "fen": f["fen_before"],
                "loss": f["severity"] * 4,
                "tag": "rule",
                "eval_before": None,
                "eval_after": None,
                "best": best,
                "best_is_played": False,
                "kp_id": f["kp_id"],
                "kp_ids": [f["kp_id"]],
                "title": f["title"],
                "explain": f["detail"],
                "rule": {"motif": f["motif"], "severity": f["severity"], "detail": f["detail"]},
                "is_player": m.get("is_player", True),
            }
        )
    return out[:14]


def _dedupe(findings: Iterable[dict]) -> list[dict]:
    """同一步同一检测项只留一条；同一建议在 8 个半回合内不重复报。"""
    seen = set()
    out = []
    last_suggest: dict[str, int] = {}
    once_only = {"backrank", "knight_rim", "opening_principle"}
    done_once: set[str] = set()
    for f in sorted(findings, key=lambda x: x["ply"]):
        key = (f["ply"], f["motif"])
        if key in seen:
            continue
        if f["motif"] in once_only:
            if f["motif"] in done_once:
                continue
            done_once.add(f["motif"])
        better = f.get("better")
        if better and f["motif"] in ("missed_pin", "missed_fork", "missed_capture"):
            sig = f["motif"] + ":" + better["uci"]
            prev = last_suggest.get(sig)
            if prev is not None and f["ply"] - prev < 16:
                continue
            last_suggest[sig] = f["ply"]
        seen.add(key)
        out.append(f)
    return out
