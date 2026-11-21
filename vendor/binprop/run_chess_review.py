"""Evaluate concepts at each completed round and verify three further rounds."""

import json
import sys
from pathlib import Path

from binary_properties.io import load_library, position_from_dict
from binary_properties.runtime import evaluate_source


def _confirmed(values, start_limit, followup, terminal):
    starts = []
    for index in range(min(len(values), start_limit)):
        window = values[index:index + followup + 1]
        if len(window) == followup + 1 and all(window):
            starts.append(index + 1)
    pending = not terminal and (
        len(values) < start_limit
        or any(all(values[index:]) for index in range(
            max(0, len(values) - followup), min(len(values), start_limit)
        ))
    )
    return starts, pending


def select_fallback(candidates):
    """Choose one tier globally; never mix fallback concepts into a higher tier."""
    ordered = sorted(candidates, key=lambda item: item[:3], reverse=True)
    for tier, flag in (("strict", "strict_qualified"),
                       ("branch_gap", "gap_qualified"),
                       ("mainline", "main_difference")):
        selected = [dict(item[3], tier=tier) for item in ordered if item[3][flag]]
        if selected:
            return tier, selected
    return None, []


def main():
    data = json.load(sys.stdin)
    groups = data["groups"]
    start_limit, followup = data["start_limit"], data["followup"]
    library = load_library(
        Path(__file__).parent / "binary_properties/motifs/chess/claude-opus-5.json"
    )
    positions, unique, indexes = [], {}, {}
    pending_rows = {side: set() for side in groups}
    events = {side: [[] for _ in rows] for side, rows in groups.items()}
    for side, rows in groups.items():
        indexes[side] = []
        for row in rows:
            line = []
            for fen in row["checkpoints"]:
                key = fen, row["color"]
                if key not in unique:
                    unique[key] = len(positions)
                    positions.append(position_from_dict(
                        {"fen": fen, "color": row["color"]}, "chess"
                    ))
                line.append(unique[key])
            indexes[side].append(line)

    before_index = None
    if data.get("before_fen"):
        before_index = len(positions)
        positions.append(position_from_dict({"fen": data["before_fen"], "color": "white" if data["before_fen"].split()[1] == "w" else "black"}, "chess"))
    before = {}
    motifs = []
    evaluated = 0
    for motif in library.motifs if positions else ():
        try:
            values = evaluate_source("chess", motif.source, positions, timeout=3.0).values
        except Exception:
            continue
        evaluated += 1
        if before_index is not None:
            before[motif.name] = bool(values[before_index])
        verdicts = {}
        for side, lines in indexes.items():
            verdicts[side] = []
            for i, line in enumerate(lines):
                rounds, pending = _confirmed(
                    [values[index] for index in line], start_limit, followup, groups[side][i]["terminal"]
                )
                verdicts[side].append((bool(rounds), pending))
                if pending:
                    pending_rows[side].add(i)
                true_rounds = [r + 1 for r, index in enumerate(line) if values[index]]
                if true_rounds:
                    events[side][i].append({"name": motif.name, "rounds": rounds, "true_rounds": true_rounds})

        positives, negatives = verdicts["positive"], verdicts["negative"]
        hits = [i for i, (hit, _) in enumerate(positives) if hit]
        missed = sum(hit for hit, _ in negatives)
        unknown = sum(pending and not hit for hit, pending in negatives)
        strict = (bool(negatives) and len(hits) >= 2 and len(hits) * 2 >= len(positives)
                  and (missed + unknown) * 4 <= len(negatives))
        main = verdicts.get("main", [])
        main_difference = len(main) == 2 and main[0][0] and not any(main[1])
        gap = bool(negatives) and len(hits) - missed >= 2
        if strict or main_difference or gap:
            contrast = (len(hits) / len(positives) if positives else 0) - (
                (missed + unknown) / len(negatives) if negatives else 0)
            motifs.append((main_difference, contrast, motif.delta, {
                "name": motif.name, "positive_indices": hits, "negative_hits": missed,
                "negative_pending": unknown, "main_difference": main_difference,
                "strict_qualified": strict, "gap_qualified": gap,
            }))

    tier, selected = select_fallback(motifs)
    print(json.dumps({"evaluated": evaluated, "before": before, "tier": tier, "motifs": selected, "events": events,
                      "pending": {side: sorted(rows) for side, rows in pending_rows.items()}}))


if __name__ == "__main__":
    main()
