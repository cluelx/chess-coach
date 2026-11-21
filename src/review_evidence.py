"""Read-only evidence for the laboratory, executing the original local rule sources.

AST wrappers observe executed comparisons/returns, and a Board subclass observes
attack queries. Neither changes returned values or production rule definitions.
"""
from __future__ import annotations

import ast
import functools
import json
from pathlib import Path
import sys

import chess

LIBRARY = Path(__file__).resolve().parents[1] / "vendor/binprop/binary_properties/motifs/chess/claude-opus-5.json"
NAMES = {1: "兵", 2: "马", 3: "象", 4: "车", 5: "后", 6: "王"}
MAX_RECORDS = 20000


@functools.lru_cache(maxsize=1)
def library():
    return json.loads(LIBRARY.read_text(encoding="utf-8"))["motifs"]


def squares(items):
    return [chess.square_name(s) for s in items]


def relations(board, target):
    p = board.piece_at(target)
    return dict(square=chess.square_name(target), piece=("白" if p.color else "黑") + NAMES[p.piece_type] if p else "空格",
                white=squares(board.attackers(chess.WHITE, target)),
                black=squares(board.attackers(chess.BLACK, target)), owner=chess.COLOR_NAMES[p.color] if p else None)


class Observer(ast.NodeTransformer):
    def __init__(self, source):
        self.source, self.function = source, ""

    def visit_FunctionDef(self, node):
        previous, self.function = self.function, node.name
        node = self.generic_visit(node)
        self.function = previous
        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "chess" and node.func.attr == "Board":
            node.func = ast.Name(id="_evidence_board", ctx=ast.Load())
        return node

    def visit_Compare(self, node):
        source = ast.get_source_segment(self.source, node) or ast.unparse(node)
        node = self.generic_visit(node)
        return ast.copy_location(ast.Call(func=ast.Name(id="_observe_compare", ctx=ast.Load()),
            args=[node, ast.Constant(source), ast.Constant(node.lineno), ast.Constant(self.function),
                  ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])], keywords=[]), node)

    def visit_If(self, node):
        source = "if " + (ast.get_source_segment(self.source, node.test) or ast.unparse(node.test))
        node = self.generic_visit(node)
        node.test = ast.copy_location(ast.Call(func=ast.Name(id="_observe_compare", ctx=ast.Load()),
            args=[node.test, ast.Constant(source), ast.Constant(node.lineno), ast.Constant(self.function),
                  ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])], keywords=[]), node.test)
        return node

    def visit_Return(self, node):
        node = self.generic_visit(node)
        return ast.copy_location(ast.Return(value=ast.Call(func=ast.Name(id="_observe_return", ctx=ast.Load()),
            args=[node.value or ast.Constant(None), ast.Constant(node.lineno), ast.Constant(self.function),
                  ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])], keywords=[])), node)

    def visit_AugAssign(self, node):
        expression = ast.get_source_segment(self.source, node) or ast.unparse(node)
        node = self.generic_visit(node)
        event = ast.Expr(value=ast.Call(func=ast.Name(id="_observe_change", ctx=ast.Load()),
            args=[ast.Constant(expression), ast.Constant(node.lineno), ast.Constant(self.function),
                  ast.Call(func=ast.Name(id="locals", ctx=ast.Load()), args=[], keywords=[])], keywords=[]))
        return [node, ast.copy_location(event, node)]


def compact(value):
    if isinstance(value, chess.Board):
        return None
    if isinstance(value, chess.SquareSet):
        return squares(value)
    if isinstance(value, chess.Move):
        return value.uci()
    if isinstance(value, chess.Piece):
        return ("白" if value.color else "黑") + NAMES[value.piece_type]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)) and len(value) <= 64:
        return [compact(v) for v in value]
    if isinstance(value, dict) and len(value) <= 64:
        return {str(k): compact(v) for k, v in value.items()}
    return f"{type(value).__name__}({len(value) if hasattr(value, '__len__') else '?'})"


class Recorder:
    def __init__(self, initial, arguments):
        self.initial, self.records, self.query_keys = initial, [], set()
        self.arguments = arguments
        self.omitted = 0

    def add(self, record):
        if len(self.records) < MAX_RECORDS or record.get("function") == "motif":
            record["id"] = len(self.records)
            self.records.append(record)
        else:
            self.omitted += 1

    def context(self, values):
        board = next((v for v in values.values() if isinstance(v, chess.Board)), None)
        # Comprehensions and numeric helpers may not retain the board in locals.
        # Find the owning rule frame while it still holds the actual trial position.
        frame, steps = sys._getframe(1), 0
        while board is None and frame is not None and steps < 16:
            if frame.f_code.co_filename == "observed-local-rule":
                board = next((v for v in frame.f_locals.values() if isinstance(v, chess.Board)), None)
            frame, steps = frame.f_back, steps + 1
        return board.fen() if board is not None else self.initial

    def compare(self, result, expression, line, function, values):
        self.add(dict(kind="condition", function=function, line=line, expression=expression,
                      value=bool(result), fen=self.context(values), locals={k: compact(v) for k, v in values.items()
                      if not k.startswith("_") and not isinstance(v, chess.Board)}))
        return result

    def returned(self, result, line, function, values):
        self.add(dict(kind="return", function=function, line=line, value=compact(result),
                      caller=sys._getframe(2).f_code.co_name,
                      arguments={k: compact(values[k]) for k in self.arguments.get(function, [])
                                 if k in values and not isinstance(values[k], chess.Board)},
                      fen=self.context(values), locals={k: compact(v) for k, v in values.items()
                      if not k.startswith("_") and not isinstance(v, chess.Board)}))
        return result

    def changed(self, expression, line, function, values):
        self.add(dict(kind="score", function=function, line=line, expression=expression,
                      fen=self.context(values), locals={k: compact(v) for k, v in values.items()
                      if not k.startswith("_") and not isinstance(v, chess.Board)}))

    def board_class(self):
        recorder = self

        class EvidenceBoard(chess.Board):
            def attackers(self, color, square, occupied=None):
                answer = super().attackers(color, square, occupied)
                frame = sys._getframe(1)
                key = self.fen(), frame.f_code.co_name, frame.f_lineno, color, square
                if key not in recorder.query_keys:
                    recorder.query_keys.add(key)
                    # The displayed relation uses the same optional occupancy as this query.
                    recorder.add(dict(kind="attackers", function=frame.f_code.co_name, line=frame.f_lineno,
                        fen=self.fen(), color=chess.COLOR_NAMES[color], target=chess.square_name(square),
                        sources=squares(answer), occupied=occupied,
                        pinned=[chess.square_name(s) for s in answer if super(EvidenceBoard, self).is_pinned(color, s)]))
                return answer

            def attacks(self, square):
                answer = super().attacks(square)
                frame = sys._getframe(1)
                key = self.fen(), frame.f_code.co_name, frame.f_lineno, "attacks", square
                if key not in recorder.query_keys:
                    recorder.query_keys.add(key)
                    recorder.add(dict(kind="coverage", function=frame.f_code.co_name, line=frame.f_lineno,
                        fen=self.fen(), source=chess.square_name(square), targets=squares(answer)))
                return answer

            def is_pinned(self, color, square):
                answer = super().is_pinned(color, square)
                frame = sys._getframe(1)
                recorder.add(dict(kind="pin", function=frame.f_code.co_name, line=frame.f_lineno,
                    fen=self.fen(), color=chess.COLOR_NAMES[color], target=chess.square_name(square), value=answer))
                return answer

        return EvidenceBoard


def material(board, values, perspective):
    rows = []
    totals = {"white": 0, "black": 0}
    for pt in range(1, 6):
        v = values[pt]
        white, black = squares(board.pieces(pt, chess.WHITE)), squares(board.pieces(pt, chess.BLACK))
        rows.append(dict(piece=NAMES[pt], value=v, white=white, black=black))
        totals["white"] += len(white) * v
        totals["black"] += len(black) * v
    return dict(rows=rows, **totals, difference=totals[perspective] - totals["black" if perspective == "white" else "white"])


@functools.lru_cache(maxsize=1)
def exchange_namespace():
    namespace = {}
    exec(compile(library()[13]["source"], "rule14-original", "exec"), namespace)
    return namespace


def capture_scores(board):
    """Reproduce rule14's target grouping, fixed-attacker SEE and null-move reply."""
    ns = exchange_namespace()
    values = ns["_V"]
    rows = []
    targets = {}
    for n, move in enumerate(board.generate_legal_captures(), 1):
        if n > 90:
            break
        pt = board.piece_type_at(move.to_square)
        victim = 1 if pt is None else values[pt]
        attacker = values[board.piece_type_at(move.from_square)]
        if move.promotion:
            victim += 8
            attacker = 9
        key = move.to_square, bool(move.promotion)
        if key not in targets or attacker < targets[key][0]:
            targets[key] = attacker, victim, move
    for (target, promotion), (attacker, victim, move) in targets.items():
        side = board.turn
        mine_squares = list(board.attackers(side, target))
        mine = sorted(values[board.piece_type_at(s)] for s in mine_squares)
        theirs = sorted(values[board.piece_type_at(s)] for s in board.attackers(not side, target))
        if attacker in mine:
            mine.remove(attacker)
        gains, occ, ui, ti, other = [victim], attacker, 0, 0, True
        steps = [dict(side=chess.COLOR_NAMES[side], taken=victim, cumulative=victim, attacker=attacker)]
        cumulative = victim
        while True:
            sequence, index = (theirs, ti) if other else (mine, ui)
            if index >= len(sequence):
                break
            nxt = sequence[index]
            if other:
                ti += 1
            else:
                ui += 1
            cumulative += -occ if other else occ
            steps.append(dict(side=chess.COLOR_NAMES[not side if other else side], taken=occ,
                              cumulative=cumulative, attacker=nxt))
            gains.append(occ - gains[-1])
            occ, other = nxt, not other
        forward = gains.copy()
        for i in range(len(gains) - 1, 0, -1):
            gains[i - 1] = min(gains[i - 1], -gains[i])
        score = ns["_see"](board, target, side, attacker, victim)
        assert gains[0] == score
        rows.append(dict(fen=board.fen(), uci=move.uci(), san=board.san(move), target=chess.square_name(target),
                         source=chess.square_name(move.from_square), side=chess.COLOR_NAMES[side],
                         attackers=squares(mine_squares), defenders=squares(board.attackers(not side, target)),
                         attacker_value=attacker, victim_value=victim, gain=score, promotion=promotion,
                         en_passant=board.is_en_passant(move), steps=steps, forward=forward, backed=gains))
    best = max([0, *(r["gain"] for r in rows)])
    assert best == ns["_best_gain"](board, board.turn)
    return dict(best=best, candidates=sorted(rows, key=lambda r: r["gain"], reverse=True))


@functools.lru_cache(maxsize=24)
def inspect_rule(fen, color, name):
    original = chess.Board(fen)
    if not original.is_valid():
        raise ValueError("待检查局面非法")
    rule = next((m for m in library() if m["name"] == name), None)
    if rule is None:
        raise ValueError("未知概念")
    original.turn = color == "white"
    effective = original.fen()
    parsed = ast.parse(rule["source"])
    recorder = Recorder(effective, {fn.name: [a.arg for a in fn.args.args] for fn in parsed.body if isinstance(fn, ast.FunctionDef)})
    namespace = dict(_evidence_board=recorder.board_class(), _observe_compare=recorder.compare,
                     _observe_return=recorder.returned, _observe_change=recorder.changed)
    tree = ast.fix_missing_locations(Observer(rule["source"]).visit(parsed))
    exec(compile(tree, "observed-local-rule", "exec"), namespace)
    matched = namespace["motif"](effective)
    # Compare with an untouched invocation, so an observer failure cannot masquerade as rule evidence.
    plain = {}
    exec(compile(rule["source"], "original-local-rule", "exec"), plain)
    expected = plain["motif"](effective)
    if type(matched) is not bool or matched != expected:
        raise RuntimeError("可视化执行与原始规则结果不一致")
    values = None
    for key in ("_VALUES", "PV", "_PV", "_V", "V", "VAL", "VALS", "_VAL", "PIECE_VALUE"):
        candidate = plain.get(key)
        if isinstance(candidate, dict) and all(p in candidate for p in range(1, 6)):
            values = candidate
            break
    if values is None and "_VW" in plain:
        values = dict(plain["_VW"])
    standard = {1: 1, 2: 3, 3: 3, 4: 5, 5: 9}
    board = chess.Board(effective)
    own = capture_scores(board)
    board.push(chess.Move.null())
    opponent = capture_scores(board)
    board.pop()
    positions = {effective: [relations(board, s) for s in chess.SQUARES]}
    # Every observed query owns its actual hypothetical position, never the starting board's geometry.
    return dict(rule=name, matched=matched, consistent=True, source=rule["source"], color=color, fen=effective,
                input_fen=fen, records=recorder.records, omitted=recorder.omitted,
                material=material(board, values or standard, color), material_uses_rule_values=values is not None,
                captures=dict(own=own, opponent=opponent, difference=own["best"] - opponent["best"]),
                relations=positions[effective])
