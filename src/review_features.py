"""Deterministic static witnesses for the lab's 21 supported concepts.

The original boolean rules and engine caches are unchanged. Features enumerate
both sides, including diagnostics beyond early exits; scores retain each rule's
own units, filtering, caps and grouping.
"""
from __future__ import annotations

import functools
import hashlib
import json

import chess

from .review_evidence import library, NAMES
from .concept_help import concept_descriptions

DEFERRED = frozenset((8, 14, 17, 18, 23, 24, 25, 28, 30))
VERSION = "static-witnesses-v1"


def sqs(items):
    return [chess.square_name(s) for s in sorted(set(items))]


def rr(s, c):
    return chess.square_rank(s) if c else 7 - chess.square_rank(s)


@functools.lru_cache(maxsize=21)
def namespace(number):
    if number in DEFERRED:
        raise ValueError("候选走法类概念尚未可视化")
    ns = {}
    exec(compile(library()[number - 1]["source"], f"original-static-rule-{number}", "exec"), ns)
    return ns


class Features:
    def __init__(self, board, color):
        self.b, self.c, self.items, self.metrics = board, color, [], {}

    def relation(self, source, target, kind=None):
        p, q = self.b.piece_at(source), self.b.piece_at(target)
        if not p:
            return None
        kind = kind or ("protect" if q and q.color == p.color else "attack" if q else "control")
        return dict(type=kind, side=chess.COLOR_NAMES[p.color], piece=chess.piece_name(p.piece_type),
                    source=chess.square_name(source), target=chess.square_name(target),
                    target_side=chess.COLOR_NAMES[q.color] if q else None,
                    target_piece=chess.piece_name(q.piece_type) if q else None)

    def links(self, target, exclude_king=False):
        return [self.relation(a, target) for c in (chess.WHITE, chess.BLACK)
                for a in self.b.attackers(c, target)
                if not exclude_king or self.b.piece_type_at(a) != chess.KING]

    def add(self, kind, squares, label, score=None, counted=True, highlight=True, relations=None, **details):
        item = dict(id=len(self.items), type=kind, side=chess.COLOR_NAMES[self.c], squares=sqs(squares),
                    label=label, score=score, counted_in_feature_score=counted,
                    highlight=highlight, relations=relations or [], details=details)
        self.items.append(item)
        return item

    def target(self, kind, square, label, **kw):
        return self.add(kind, [square], label, relations=self.links(square), **kw)


def passed(b, c, s):
    return not any(abs(chess.square_file(p) - chess.square_file(s)) <= 1 and rr(p, c) > rr(s, c)
                   for p in b.pieces(chess.PAWN, not c))


def pawn_structure(f, ns):
    b, c = f.b, f.c
    pawns = list(b.pieces(chess.PAWN, c))
    files = {chess.square_file(s) for s in pawns}
    if not pawns:
        f.add("no_pawns", [], "无兵", score=-1)
        return -1
    for s in pawns:
        file, rank, rel = chess.square_file(s), chess.square_rank(s), rr(s, c)
        is_passed = passed(b, c, s)
        if is_passed:
            value = 1 + .55 * max(0, rel - 2)
            support = ns["_pawn_support"](b, s, c)
            value += .5 if support else 0
            front = s + (8 if c else -8)
            blocked = 0 <= front < 64 and b.piece_at(front) and b.color_at(front) != c
            value -= .4 if blocked else 0
            f.target("passed_pawn", s, "通路兵", score=value, pawn_support=support,
                     front=chess.square_name(front) if 0 <= front < 64 else None, blocked=bool(blocked))
        isolated = file - 1 not in files and file + 1 not in files
        blocked_file = any(chess.square_file(p) == file and rr(p, c) > rel for p in b.pieces(chess.PAWN, not c))
        if isolated:
            f.target("isolated_pawn", s, "孤兵", score=-1)
        elif not blocked_file:
            attackers = b.attackers(not c, s) & b.pieces(chess.PAWN, not c)
            if attackers and ns["_pawn_support"](b, s, c) < len(attackers):
                f.target("pawn_under_pressure", s, "敌兵压力超过兵保护", score=-.7)
    for file in sorted(files):
        group = [s for s in pawns if chess.square_file(s) == file]
        if len(group) > 1:
            f.add("doubled_pawns", group, f"{chess.FILE_NAMES[file]}路叠兵", score=-.8 * (len(group) - 1), file=chess.FILE_NAMES[file])
    islands, current = [], []
    for file in sorted(files):
        if current and file != current[-1] + 1:
            islands.append(current)
            current = []
        current.append(file)
    islands.append(current)
    for index, group in enumerate(islands):
        f.add("pawn_island", [s for s in pawns if chess.square_file(s) in group], "兵岛", score=0 if index == 0 else -.4,
              highlight=False, files=[chess.FILE_NAMES[x] for x in group])
    value = ns["_score"](b, c)
    assert abs(sum(x["score"] for x in f.items) - value) < 1e-8
    return value


def permanent_holes(f, ns):
    b, c = f.b, f.c
    top = [-1] * 8
    for p in b.pieces(chess.PAWN, not c):
        file = chess.square_file(p)
        top[file] = max(top[file], rr(p, c))
    total = 0
    for file in range(1, 7):
        for rel in range(4, 7):
            if top[file - 1] > rel or top[file + 1] > rel:
                continue
            s = chess.square(file, rel if c else 7 - rel)
            p = b.piece_at(s)
            if p and (p.color != c or p.piece_type == chess.PAWN):
                continue
            ours, theirs = b.attackers(c, s), b.attackers(not c, s)
            occupied_bonus = int(p is not None)
            if not ours or len(ours) + occupied_bonus < len(theirs):
                continue
            weight = 1 + bool(ours & b.pieces(chess.PAWN, c)) + (rel >= 5)
            counted = total < 14
            if counted:
                total += weight
            f.target("permanent_hole", s, "本方控制的对方阵营永久弱格（规则近似）", score=weight,
                     counted=counted, own_control=len(ours), enemy_control=len(theirs), occupied_bonus=occupied_bonus)
    assert total == ns["_holes"](b, c)
    f.metrics["complete_target_count"] = len(f.items)
    f.metrics["scoring_stops_at"] = 14
    return total


def weak_king_squares(f, ns):
    b, c = f.b, f.c
    zone = ns["_zone"](b, not c)
    f.add("enemy_king_zone", zone, "对方王区检查范围", counted=False, highlight=False)
    for s in zone:
        attackers = [a for a in b.attackers(c, s) if b.piece_type_at(a) != chess.KING]
        guards = [a for a in b.attackers(not c, s) if b.piece_type_at(a) != chess.KING]
        if attackers:
            f.add("king_weak_square" if not guards else "king_pressure_square", [s],
                  "无非王保护的王区弱格" if not guards else "有非王保护的王区受压格",
                  score=len(attackers), relations=f.links(s, True), attackers=sqs(attackers), guards=sqs(guards),
                  weak=not guards, king_excluded=True)
    report = ns["_report"](b, c, not c)
    assert sum(x["score"] or 0 for x in f.items) == report[0]
    f.metrics.update(pressure=report[0], weak_squares=report[1], distinct_attackers=report[2])
    return report[0]


def weak_pawn_pressure(f, ns):
    b, c = f.b, f.c
    total = 0
    for s in b.pieces(chess.PAWN, not c):
        rel = rr(s, not c)
        attackers, guards = b.attackers(c, s), b.attackers(not c, s)
        if rel > 4 or not attackers:
            continue
        pawn_guard = bool(guards & b.pieces(chess.PAWN, not c))
        structural = rel >= 2 and not ns["_can_be_pawn_guarded"](b, s, not c)
        under = len(attackers) > len(guards) and not pawn_guard
        weight = int(structural) + 2 * under
        heavy = bool(weight and any(b.piece_type_at(a) in (chess.ROOK, chess.QUEEN) and chess.square_file(a) == chess.square_file(s) for a in attackers))
        weight += heavy
        if weight:
            f.target("weak_pawn", s, "被本方施压并计分的对方弱兵", score=weight,
                     structural=structural, underdefended=under, heavy_file_pressure=heavy, pawn_guard=pawn_guard)
            total += weight
    harass = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for s in b.pieces(pt, not c):
            if b.attackers(c, s) & b.pieces(chess.PAWN, c):
                counted = harass < 2
                f.target("pawn_harassed_piece", s, "受本方兵攻击的对方棋子（附加项）", score=1, counted=counted)
                harass += 1
    value = total + min(harass, 2)
    assert value == ns["_pressure"](b, c)
    return value


def minor_quality(f, ns):
    b, c = f.b, f.c
    enemy_pawn_attacks = ns["_pawn_att"](b, not c)
    scores = []
    for pt in (chess.KNIGHT, chess.BISHOP):
        for s in b.pieces(pt, c):
            available = [t for t in b.attacks(s) if b.color_at(t) != c and t not in enemy_pawn_attacks]
            value = ns["_quality"](b, s, c, enemy_pawn_attacks)
            scores.append(value)
            details = dict(available_squares=sqs(available), estimated_mobility=len(available), bad=value <= 1,
                           home_rank=rr(s, c) == 0, rim=chess.square_file(s) in (0, 7), mobility_is_legal=False)
            if pt == chess.BISHOP:
                parity = (chess.square_file(s) + chess.square_rank(s)) % 2
                same = [p for p in b.pieces(chess.PAWN, c) if (chess.square_file(p) + chess.square_rank(p)) % 2 == parity]
                details.update(same_color_pawns=sqs(same), blocked_same_color_pawns=sqs(p for p in same if 0 <= p + (8 if c else -8) < 64 and b.piece_at(p + (8 if c else -8))))
            f.target("bad_minor" if value <= 1 else "minor_quality", s, "规则评分较低的轻子" if value <= 1 else "轻子活动评分",
                     score=value, highlight=value <= 1, **details)
    return min(scores) if scores else None


def defence_duty(f, ns):
    b, c = f.b, f.c
    duty = {}
    for s, p in sorted(b.piece_map().items()):
        if p.color != c or p.piece_type == chess.KING or not b.attackers(not c, s):
            continue
        guards = b.attackers(c, s)
        for g in guards:
            if b.piece_type_at(g) != chess.PAWN and (p.piece_type == chess.PAWN or len(guards) == 1):
                duty.setdefault(g, []).append(s)
    for g, targets in sorted(duty.items()):
        f.add("defensive_duty", [g], "保护受攻击兵或担任唯一保护者", relations=[f.relation(g, t, "protect") for t in targets], protected=sqs(targets))
    step = 8 if not c else -8
    blockers = set()
    for p in b.pieces(chess.PAWN, not c):
        front = p + step
        if 0 <= front < 64 and b.color_at(front) == c and b.piece_type_at(front) != chess.PAWN and ns["_is_passed"](b, not c, p):
            blockers.add(front)
            f.add("passer_blockader", [front, p], "阻挡对方通路兵", blockader=chess.square_name(front), pawn=chess.square_name(p))
    own = [s for s, p in sorted(b.piece_map().items()) if p.color == c]
    links = [f.relation(a, t) for t in chess.SQUARES if b.piece_at(t) for a in b.attackers(c, t)]
    f.add("all_attack_defence", own, "本方所有对已占据格的攻击与保护关系", counted=False, relations=links)
    value = len(set(duty) | blockers)
    assert value == ns["_duty"](b, c)
    return value


def advanced_passers(f, ns):
    b, c = f.b, f.c
    all_passers = [s for s in b.pieces(chess.PAWN, c) if passed(b, c, s)]
    candidates = [s for s in all_passers if 2 <= rr(s, c) <= 6]
    files = {chess.square_file(s) for s in candidates}
    best = 0
    for s in all_passers:
        eligible = s in candidates
        value = None
        if eligible:
            file = chess.square_file(s)
            value = ns["_value"](b, s, c, 1 if c else -1, not c)
            value += .75 if file - 1 in files or file + 1 in files else 0
            best = max(best, value)
        path = list(range(s + (8 if c else -8), 64 if c else -1, 8 if c else -8))
        front = path[0] if path else None
        f.target("advanced_passer" if eligible else "passed_pawn_auxiliary", s, "评分范围内的通路兵" if eligible else "通路兵（原规则评分范围外）",
                 score=value, counted=eligible, promotion_path=sqs(path), front=chess.square_name(front) if front is not None else None,
                 front_relations=f.links(front) if front is not None else [], highest=False)
    for item in f.items:
        item["details"]["highest"] = item["score"] is not None and item["score"] == best
    assert abs(best - ns["_best"](b, c)) < 1e-8
    return best


def overextended(f, ns):
    b, c = f.b, f.c
    count = 0
    for s in b.pieces(chess.PAWN, c):
        rel = rr(s, c)
        if rel < 4 or ns["_supported"](b, s, c):
            continue
        attack, defend = b.attackers(not c, s), b.attackers(c, s)
        if not attack:
            continue
        front = s + (8 if c else -8)
        blocked = True
        if rel < 7:
            p = b.piece_at(front)
            blocked = p.color != c if p else len(b.attackers(not c, front)) > len(b.attackers(c, front))
        if len(attack) > len(defend) or blocked:
            f.target("overextended_pawn", s, "本方推进过深且受攻击的兵", score=1,
                     blocked=blocked, outnumbered=len(attack) > len(defend), front=chess.square_name(front) if 0 <= front < 64 else None,
                     front_relations=f.links(front) if 0 <= front < 64 else [])
            count += 1
    assert count == ns["_count"](b, c, not c)
    return count


def color_complex(f, ns):
    b, c = f.b, f.c
    cover = ns["_pcover"](b, not c)
    groups = []
    for color in (0, 1):
        bishops = ns["_bish"](b, c, color)
        if not bishops or ns["_bish"](b, not c, color) or ns["_pawns_col"](b, not c, color) > 3:
            continue
        holes, grip = [], 0
        for s in chess.SQUARES:
            if ns["_col"](s) != color or not 2 <= rr(s, not c) <= 4:
                continue
            p = b.piece_at(s)
            if p and p.color != c and p.piece_type == chess.PAWN or s in cover:
                continue
            gain = 2 if p and p.color == c else int(any(s in b.attacks(bs) for bs in bishops))
            holes.append((s, gain))
            grip += gain
        qualifying = len(holes) >= 6 and grip >= 2
        groups.append(dict(color=color, bishops=bishops, holes=holes, grip=grip, qualifying=qualifying,
                           score=len(holes) + grip if qualifying else 0))
    best = max((g["score"] for g in groups), default=0)
    selected = next((g for g in groups if best > 0 and g["score"] == best), None)
    for g in groups:
        for s, gain in g["holes"]:
            f.add("color_complex_hole", [s], "对方阵营同色候选弱格（缺少兵控制）", score=1 + gain,
                     relations=[f.relation(bs, s) for bs in g["bishops"] if s in b.attacks(bs)],
                     counted=g is selected, color_complex="dark" if g["color"] == 0 else "light",
                     bishops=sqs(g["bishops"]), occupied_by_us=b.color_at(s) == c,
                     bishop_control=[chess.square_name(bs) for bs in g["bishops"] if s in b.attacks(bs)],
                     grip=gain, group_qualifying=g["qualifying"])
    assert best == ns["_complex_score"](b, c, not c)
    f.metrics["complexes"] = [{k: sqs(v) if k == "bishops" else v for k, v in g.items() if k != "holes"} for g in groups]
    return best


def pressure_points(f, ns):
    b, c = f.b, f.c
    items, load = [], {}
    for s, p in sorted(b.piece_map().items()):
        if p.color == c or p.piece_type == chess.KING:
            continue
        attackers, guards = list(b.attackers(c, s)), list(b.attackers(not c, s))
        if not attackers:
            continue
        value, cheap = ns["_V"][p.piece_type], ns["_cheap"](b, attackers)
        items.append((s, value, attackers, guards, cheap))
        if len(guards) == 1 and value >= 3:
            load[guards[0]] = load.get(guards[0], 0) + 1
    total = 0
    for s, value, attackers, guards, cheap in items:
        tags, score, reason = [], 0, None
        pinned = b.is_pinned(not c, s)
        if not guards:
            tags.append("unprotected")
            score, reason = (3 if value >= 3 else 1), "unprotected"
        elif cheap < value:
            score, reason = 3, "cheaper_attacker"
        elif len(attackers) > len(guards) and cheap <= value:
            score, reason = 2, "outnumbered"
        elif value >= 3 and pinned:
            score, reason = 2, "pinned"
        elif len(guards) == 1 and value >= 3:
            g = guards[0]
            if load.get(g, 0) >= 2 or b.is_pinned(not c, g):
                score, reason = 2, "overloaded_or_pinned_guard"
            elif b.piece_type_at(g) != chess.KING and len(b.attackers(c, g)) > len(b.attackers(not c, g)):
                score, reason = 1, "unstable_guard"
        if pinned:
            tags.append("pinned")
        if cheap < value:
            tags.append("cheaper_attacker")
        if len(attackers) > len(guards):
            tags.append("outnumbered")
        if score or tags:
            f.target("pressure_target", s, "本方施压的对方具体目标", score=score, tags=tags,
                     applied_reason=reason, cheapest_attacker=cheap, target_value=value,
                     sole_guard=chess.square_name(guards[0]) if len(guards) == 1 else None)
        total += score
    # Pins without an attack are diagnostics, not pressure-score contributors.
    recorded = {s for x in f.items for s in x["squares"]}
    for s, p in sorted(b.piece_map().items()):
        if p.color != c and p.piece_type != chess.KING and b.is_pinned(not c, s) and chess.square_name(s) not in recorded:
            f.target("pin_auxiliary", s, "被钉住但未进入本规则受攻击目标清单", counted=False, score=0)
    assert total == ns["_pressure"](b, c, not c)
    return total


def trapped_pieces(f, ns):
    b, c = f.b, f.c
    total = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for s in b.pieces(pt, c):
            value, available = ns["_V"][pt], []
            for t in b.attacks(s):
                p = b.piece_at(t)
                if p and p.color == c:
                    continue
                gain = ns["_V"][p.piece_type] if p else 0
                attackers = b.attackers(not c, t)
                if not attackers or gain >= value - .4 or (ns["_cheap"](b, not c, t) >= value - .4 and b.attackers(c, t)):
                    available.append(t)
            limited = len(available) < 2
            assert min(len(available), 2) == ns["_free"](b, s, c, not c, value)
            score = ns["_RW"][pt] * (2 - len(available)) if limited else 0
            attack, defend = b.attackers(not c, s), b.attackers(c, s)
            cheap = bool(attack and ns["_cheap"](b, not c, s) + .5 < value)
            risk = 1.2 if attack and (not defend or cheap) else .5 if len(attack) > len(defend) else 0
            score += risk
            tags = (["restricted"] if limited else []) + (["attacked_unprotected"] if attack and not defend else []) + (["unprotected"] if not defend else []) + (["cheaper_attacker"] if cheap else [])
            if limited or attack or not defend:
                f.target("restricted_or_hanging", s, "本方活动受限或受压棋子", score=score,
                     counted=score > 0, highlight=score > 0 or not defend, tags=tags, available_squares=sqs(available),
                         capped_mobility=min(len(available), 2), complete_estimated_mobility=len(available),
                         mobility_is_legal=False, attacked=bool(attack), protected=bool(defend))
            total += score
    assert abs(total - ns["_trouble"](b, not c, c)) < 1e-8
    return total


def shelter(f, ns, number):
    b, c = f.b, f.c
    king = b.king(c)
    kf, kr = chess.square_file(king), chess.square_rank(king)
    shield, missing = [], []
    for file in range(max(0, kf - 1), min(7, kf + 1) + 1):
        candidates = [chess.square(file, kr + d * (1 if c else -1)) for d in (1, 2) if 0 <= kr + d * (1 if c else -1) < 8]
        found = next((s for s in candidates if b.piece_type_at(s) == chess.PAWN and b.color_at(s) == c), None)
        if found is not None:
            shield.append(found)
        else:
            missing.extend(candidates)
    f.add("king_location", [king], "本方王的位置", relative_rank=rr(king, c))
    f.add("king_pawn_shield", shield, "本方王的兵掩护")
    f.add("missing_king_shield", missing, "本方王前方缺少兵掩护的检查格", counted=False)
    if number == 5:
        zone = ns["_king_zone"](king)
        swarm = set()
        links = []
        for target in zone:
            for a in b.attackers(not c, target):
                if b.piece_type_at(a) not in (chess.PAWN, chess.KING):
                    swarm.add(a)
                    links.append(f.relation(a, target))
        f.add("king_zone_pressure", zone, "本方王区及敌方围攻棋子", relations=links, attackers=sqs(swarm))
        for file in range(max(0, kf - 1), min(7, kf + 1) + 1):
            if any(chess.square_file(p) == file for p in b.pieces(chess.PAWN, c)):
                continue
            open_file = not any(chess.square_file(p) == file for p in b.pieces(chess.PAWN, not c))
            heavy = [p for pt in (chess.ROOK, chess.QUEEN) for p in b.pieces(pt, not c) if chess.square_file(p) == file]
            f.add("king_open_file", [chess.square(file, r) for r in range(8)], "王附近开放路" if open_file else "王附近半开放路",
                  heavy_pieces=sqs(heavy), note="同路重子不等于已经直接攻击王")
        return ns["_king_danger"](b, c)
    back = [s for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for s in b.pieces(pt, c) if rr(s, c) == 0]
    minors = [s for s in back if b.piece_type_at(s) in (chess.KNIGHT, chess.BISHOP)]
    f.add("undeveloped_minor", minors, "尚在底线的轻子")
    f.add("back_rank_congestion", back, "底线棋子", highlight=len(back) > 2, congestion_penalty=.4 * max(0, len(back) - 2))
    lag = ns["_king_lag"](b, c)
    if lag > 0:
        for s in b.pieces(chess.ROOK, c):
            free = [t for t in b.attacks(s) if b.color_at(t) != c]
            if rr(s, c) == 0 and len(free) <= 1:
                f.target("boxed_rook", s, "底线活动受限的车", available_squares=sqs(free))
    f.metrics.update(king_lag=lag, minor_lag=ns["_minor_lag"](b, c),
                     castle_rights=bool(b.has_castling_rights(c)), note="易位相关检查不等同于当前可合法易位")
    return ns["_lag"](b, c, lag)


def infiltration(f, ns):
    b, c = f.b, f.c
    total = 0
    for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for s in b.pieces(pt, c):
            rel, value = rr(s, c), ns["_V"][pt]
            if rel < 4 or not ns["_safe"](b, s, c, value):
                continue
            free, hits = [], []
            for t in b.attacks(s):
                p = b.piece_at(t)
                if p is None:
                    if not ns["_pawn_hits"](b, t, not c) and not any(ns["_V"][b.piece_type_at(a)] < value for a in b.attackers(not c, t)):
                        free.append(t)
                elif p.color != c and p.piece_type != chess.PAWN:
                    hits.append(t)
            if len(free) < 2 and not hits:
                continue
            score = rel - 3 + bool(hits) + ns["_pawn_hits"](b, s, c)
            score += int(pt in (chess.KNIGHT, chess.BISHOP) and ns["_no_pawn_ever"](b, s, c))
            score += int(pt in (chess.ROOK, chess.QUEEN) and rel >= 6)
            f.target("safe_infiltrator", s, "已经安全深入的本方棋子（规则估计）", score=score,
                     available_squares=sqs(free), targets=sqs(hits), destination_is_searched=False)
            total += score
    assert total == ns["_score"](b, c)
    return total


def space(f, ns):
    b, c = f.b, f.c
    total = 0
    for s in b.pieces(chess.PAWN, c):
        rel, file = rr(s, c), chess.square_file(s)
        if rel >= 3:
            weight = (2 if rel >= 4 else 1) * (2 if 2 <= file <= 5 else 1)
            f.target("advanced_space_pawn", s, "推进争空间的兵", score=weight,
                     central=2 <= file <= 5, overattacked=len(b.attackers(not c, s)) > len(b.attackers(c, s)))
            total += weight
        targets = [t for t in b.attacks(s) if rr(t, c) >= 4]
        if targets:
            f.add("pawn_space_control", targets, "本方兵控制的对方半场格", score=len(targets),
                  relations=[f.relation(s, t) for t in targets], pawn=chess.square_name(s))
            total += len(targets)
    expected, count = ns["_space"](b, c)
    assert total == expected
    f.metrics["advanced_pawn_count"] = count
    return total


def camp_safety(f, ns):
    b, c = f.b, f.c
    values = ns["_V"]
    dangers = 0
    for s, p in sorted(b.piece_map().items()):
        if p.color != c:
            continue
        attack, defend = b.attackers(not c, s), b.attackers(c, s)
        tags = []
        if p.piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
            if b.is_pinned(c, s):
                tags.append("pinned")
            if attack:
                if min(values[b.piece_type_at(a)] for a in attack) < values[p.piece_type]:
                    tags.append("cheaper_attacker")
                if not defend:
                    tags.append("attacked_unprotected")
                if len(attack) > len(defend):
                    tags.append("outnumbered")
        elif p.piece_type == chess.PAWN and len(attack) >= 2 and len(attack) > len(defend):
            tags.append("pawn_ganged_up")
        if attack or tags:
            f.target("camp_piece_danger" if tags else "attacked_piece", s, "本方阵营危险项目" if tags else "本方受攻击棋子（不自动判危险）",
                     tags=tags, dangerous=bool(tags), counted=bool(tags))
            dangers += bool(tags)
    for s, p in sorted(b.piece_map().items()):
        if p.color == c or p.piece_type == chess.KING:
            continue
        limit = 2 if p.piece_type == chess.PAWN else 3
        if rr(s, c) <= limit and not b.attackers(c, s):
            f.target("unchallenged_intruder", s, "本方阵营内未受本方攻击的敌方侵入子")
            dangers += 1
    king = b.king(c)
    ring = b.attacks(king)
    attackers = [s for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN) for s in b.pieces(pt, not c) if b.attacks(s) & ring]
    if attackers:
        f.add("enemy_king_ring_presence", attackers, "控制本方王邻格的敌子", score=len(attackers),
              relations=[f.relation(a, t) for a in attackers for t in b.attacks(a) & ring])
    f.metrics.update(dangerous_items=dangers, king_ring_enemy_units=len(attackers))
    return None


def positional(f, ns):
    b, c = f.b, f.c
    values = ns["_feat"](b, c)
    names = ("material", "average_mobility", "passed_pawn_score", "weak_pawns", "space", "rook_files", "bishop_pair", "central_control", "outposts")
    f.metrics.update(dict(zip(names, values)))
    for s in b.pieces(chess.PAWN, c):
        if passed(b, c, s):
            f.target("passed_pawn", s, "综合位置评分中的通路兵", score=max(1, rr(s, c) - 1))
    own_files = {chess.square_file(s) for s in b.pieces(chess.PAWN, c)}
    for file in sorted(own_files):
        group = [s for s in b.pieces(chess.PAWN, c) if chess.square_file(s) == file]
        if len(group) > 1:
            f.add("doubled_pawns", group, "综合位置评分中的叠兵")
        if file - 1 not in own_files and file + 1 not in own_files:
            f.add("isolated_pawns", group, "综合位置评分中的孤兵")
    for target in ns["CTR"]:
        own = b.attackers(c, target)
        bonus = b.color_at(target) == c
        f.add("central_control", [target], "中心控制", score=len(own) + bonus, relations=[f.relation(a, target) for a in own], occupied_bonus=bonus)
    control = set()
    for pt in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for s in b.pieces(pt, c):
            control.update(t for t in b.attacks(s) if rr(t, c) >= 4)
            if pt in (chess.KNIGHT, chess.BISHOP) and rr(s, c) >= 4 and b.attackers(c, s) & b.pieces(chess.PAWN, c):
                if not any(abs(chess.square_file(p) - chess.square_file(s)) == 1 and rr(p, c) > rr(s, c) for p in b.pieces(chess.PAWN, not c)):
                    f.target("outpost", s, "兵保护且敌兵难以驱逐的前哨轻子")
            if pt == chess.ROOK and chess.square_file(s) not in own_files:
                enemy_pawn = any(chess.square_file(p) == chess.square_file(s) for p in b.pieces(chess.PAWN, not c))
                f.target("rook_file", s, "半开放路上的车" if enemy_pawn else "开放路上的车")
    f.add("space_squares", control, "本方控制的对方半场格", counted=False)
    bishops = list(b.pieces(chess.BISHOP, c))
    if len(bishops) >= 2:
        f.add("bishop_pair", bishops, "双象")
    return list(values)


def multiple_weaknesses(f, ns):
    b, c = f.b, f.c
    mine, opposing = ns["_pmap"](b, c), ns["_pmap"](b, not c)
    pawn_count = 0
    for file in sorted(mine):
        if file in opposing:
            continue
        ranks = mine[file]
        group = [chess.square(file, rank) for rank in ranks]
        if file - 1 not in mine and file + 1 not in mine or len(ranks) > 1:
            f.add("weak_pawn_file", group, "半开放路上的孤兵/叠兵目标（按路计数）", score=1, file=chess.FILE_NAMES[file])
            pawn_count += 1
            continue
        for rank in ranks:
            s = chess.square(file, rank)
            if b.attackers(c, s) & b.pieces(chess.PAWN, c):
                continue
            back = all((ar - rank) * (1 if c else -1) > 0 for af in (file - 1, file + 1) for ar in mine.get(af, ()))
            if back:
                f.target("backward_pawn_target", s, "缺少兵保护的落后兵目标", score=1)
                pawn_count += 1
    hot = set()
    for pt in ns["PIECES"]:
        for s in b.pieces(pt, c):
            atk, dfn = b.attackers(not c, s), b.attackers(c, s)
            if atk and (not dfn or len(atk) > len(dfn) or any(ns["VALS"].get(b.piece_type_at(a), 99) < ns["VALS"][pt] for a in atk)):
                hot.add(s)
    step = 1 if not c else -1
    for pawn in b.pieces(chess.PAWN, not c):
        file, rank = chess.square_file(pawn), chess.square_rank(pawn)
        if not (0 <= rank + step < 8 and 0 <= rank + 2 * step < 8):
            continue
        front = chess.square(file, rank + step)
        if b.piece_at(front) or b.attackers(c, front) & b.pieces(chess.PAWN, c):
            continue
        for af in (file - 1, file + 1):
            if 0 <= af < 8:
                target = chess.square(af, rank + 2 * step)
                if b.color_at(target) == c and b.piece_type_at(target) in ns["PIECES"]:
                    hot.add(target)
    for s in sorted(hot):
        f.target("hot_piece", s, "本方受压或潜在兵压目标（规则静态近似）", score=1)
    king_score = ns["_king_target"](b, c)
    if king_score:
        f.target("weak_king_target", b.king(c), "缺少掩护或居中的王目标", score=king_score)
    assert pawn_count == ns["_pawn_targets"](b, c)
    assert len(hot) == ns["_hot"](b, c)
    f.metrics.update(pawn_targets=pawn_count, hot_pieces=len(hot), king_targets=king_score,
                     kinds=sum(v > 0 for v in (pawn_count, len(hot), king_score)))
    return pawn_count + len(hot) + king_score


def piece_imbalance(f, ns):
    b, c = f.b, f.c
    mine, theirs = ns["_counts"](b, c), ns["_counts"](b, not c)
    total, locked, wings = ns["_structure"](b)
    open_position, closed = total <= 12 and locked <= 1, total >= 12 and locked >= 2
    for pt in range(1, 6):
        f.add("army_composition", b.pieces(pt, c), f"本方{NAMES[pt]}组合", count=mine[pt], opponent_count=theirs[pt], highlight=pt != chess.PAWN and mine[pt] != theirs[pt])
    for s in b.pieces(chess.PAWN, chess.WHITE):
        if s + 8 < 64 and b.color_at(s + 8) == chess.BLACK and b.piece_type_at(s + 8) == chess.PAWN:
            f.add("locked_pawn_pair", [s, s + 8], "相互顶住的兵", counted=False)
    my_minors, their_minors = mine[2] + mine[3], theirs[2] + theirs[3]
    my_pieces, their_pieces = my_minors + mine[4] + mine[5], their_minors + theirs[4] + theirs[5]
    my_npm, their_npm = ns["_non_pawn_material"](mine), ns["_non_pawn_material"](theirs)
    score, reasons = 0., []
    if mine[3] >= 2 and theirs[3] <= 1:
        gain = 1. if open_position else .6 if total <= 13 and locked <= 2 else 0
        gain += .3 if wings and open_position else 0
        score += gain
        reasons.append(dict(type="bishop_pair", score=gain))
    if my_minors > their_minors and theirs[1] - mine[1] >= 3 and (their_npm >= 6 or my_npm >= 9):
        score += 1
        reasons.append(dict(type="minors_vs_pawns", score=1))
    if my_minors - their_minors >= 1 and theirs[4] - mine[4] >= 1 and my_pieces > their_pieces and my_npm + their_npm >= 20:
        score += 1
        reasons.append(dict(type="minors_vs_rook", score=1))
    if closed and mine[2] > theirs[2] and theirs[3] > mine[3]:
        score += 1
        reasons.append(dict(type="knights_closed_position", score=1))
    if open_position and mine[3] > theirs[3] and theirs[2] > mine[2]:
        gain = 1 + .3 * wings
        score += gain
        reasons.append(dict(type="bishops_open_position", score=gain))
    if mine[5] > theirs[5] and their_pieces > my_pieces and total <= 10:
        score += .6
        reasons.append(dict(type="queen_vs_scattered_pieces", score=.6))
    f.metrics.update(locked_pairs=locked, total_pawns=total, open_position=open_position, closed_position=closed,
                     both_wings=wings, scoring_reasons=reasons)
    return score


def active_king(f, ns):
    b, c = f.b, f.c
    king, enemy = b.king(c), b.king(not c)
    pawns = sorted(list(b.pieces(chess.PAWN, chess.WHITE)) + list(b.pieces(chess.PAWN, chess.BLACK)))
    center = ns["_cen"](king)
    nearest = [s for s in ns["_CTR"] if chess.square_distance(king, s) == center]
    f.add("king_centralization", [king, *nearest], "王与最近中心格（距离参考）", center_distance=center)
    own_sum = enemy_sum = closer = farther = 0
    for pawn in pawns:
        own_distance, enemy_distance = chess.square_distance(king, pawn), chess.square_distance(enemy, pawn)
        f.add("king_pawn_distance", [king, pawn], "本方王与兵的距离参考（不是合法路径）",
              counted=False, king=chess.square_name(king), pawn=chess.square_name(pawn),
              distance=own_distance, opponent_distance=enemy_distance)
        own_sum += own_distance
        enemy_sum += enemy_distance
        closer += own_distance < enemy_distance
        farther += enemy_distance < own_distance
    zone = [king, *b.attacks(king)]
    danger = [s for s in zone if b.attackers(not c, s)]
    f.add("king_danger_zone", danger, "王周围受攻击格", relations=[f.relation(a, s) for s in danger for a in b.attackers(not c, s)])
    avg = own_sum / len(pawns) if pawns else None
    other_avg = enemy_sum / len(pawns) if pawns else None
    points = [center + 1 <= ns["_cen"](enemy), bool(pawns and avg + .6 <= other_avg), closer >= farther + 2,
              rr(king, c) >= 2 and rr(enemy, not c) <= 1]
    f.metrics.update(center_distance=center, mean_pawn_distance=avg, closer_pawns=closer, danger_squares=len(danger), checks=points)
    return sum(points)


BUILDERS = {2: positional, 3: permanent_holes, 4: pawn_structure, 6: infiltration, 7: space,
            9: camp_safety, 11: weak_king_squares, 12: weak_pawn_pressure, 13: minor_quality,
            15: defence_duty, 16: advanced_passers, 19: overextended, 20: multiple_weaknesses,
            21: piece_imbalance, 22: color_complex, 26: pressure_points, 27: trapped_pieces, 29: active_king}


def build_side(number, board, color, ns):
    f = Features(board, color)
    if number == 1:
        score = 0
        for pt, value in ns["_VALUES"].items():
            group = list(board.pieces(pt, color))
            f.add("material_group", group, f"本方{NAMES[pt]}子力", score=len(group) * value, piece_value=value, count=len(group))
            score += len(group) * value
    elif number in (5, 10):
        score = shelter(f, ns, number)
    else:
        score = BUILDERS[number](f, ns)
    f.items.sort(key=lambda x: (x["type"], x["squares"], x["label"]))
    for index, item in enumerate(f.items):
        item["id"] = f"r{number}-{chess.COLOR_NAMES[color]}-{index}"
        unique = {json.dumps(r, sort_keys=True): r for r in item["relations"] if r}
        item["relations"] = [unique[key] for key in sorted(unique)]
    return dict(score=score, metrics=f.metrics, features=f.items, complete=True)


def relation_text(record):
    side = "白" if record["side"] == "white" else "黑"
    pieces = dict(zip(chess.PIECE_NAMES[1:], ("兵", "马", "象", "车", "后", "王")))
    verb = {"attack": "攻击", "protect": "保护", "control": "控制"}[record["type"]]
    target = (("白" if record["target_side"] == "white" else "黑") + " " + pieces[record["target_piece"]] + " ") if record["target_piece"] else "空格 "
    return f"{side} {pieces[record['piece']]} {record['source']} {verb} {target}{record['target']}"


@functools.lru_cache(maxsize=48)
def inspect_static(fen):
    board = chess.Board(fen)
    if not board.is_valid():
        raise ValueError("局面非法")
    rules = []
    for number, motif in enumerate(library(), 1):
        result = dict(id=number, name=motif["name"], description=concept_descriptions()[motif["name"]], visualization_status="deferred_moves" if number in DEFERRED else "ready")
        if number in DEFERRED:
            result.update(reason="尚未可视化：涉及候选步或走法，本轮暂不处理", white=None, black=None,
                          matched={"white": None, "black": None})
        else:
            ns = namespace(number)
            result["matched"] = {}
            for color in (chess.WHITE, chess.BLACK):
                side = chess.COLOR_NAMES[color]
                probe = board.copy(stack=False)
                probe.turn = color
                result["matched"][side] = ns["motif"](probe.fen())
                result[side] = build_side(number, board, color, ns)
                for feature in result[side]["features"]:
                    feature["relation_text"] = [relation_text(r) for r in feature["relations"]]
            if isinstance(result["white"]["score"], (int, float)) and isinstance(result["black"]["score"], (int, float)):
                result["white_minus_black"] = result["white"]["score"] - result["black"]["score"]
        rules.append(result)
    return dict(version=VERSION, fen=board.fen(), rules=rules,
                library_sha256=hashlib.sha256(json.dumps(library(), sort_keys=True).encode()).hexdigest(),
                supported_count=21, deferred_ids=sorted(DEFERRED),
                feature_scope="双方完整静态诊断。counted_in_feature_score仅表示计入特征分，不代表原规则通过所有前置条件。")
