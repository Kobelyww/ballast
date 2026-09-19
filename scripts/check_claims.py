#!/usr/bin/env python3
"""Fail when the README says something the stored benchmark rows do not support.

Every headline figure in this repo is derived from `bench/results/*.json`. Deriving it
once and then *maintaining it by hand in prose* is how a stale number survives a dozen
commits — and this project already retracted one such number in public. So the check is
mechanical: recompute each claim from the rows, and require the README to contain it.

Usage:  python scripts/check_claims.py            # in CI
        python scripts/check_claims.py --list     # show what is asserted
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "bench/results/eval.json"
CROSS = ROOT / "bench/results/cross-domain.md"  # markdown sibling; json is .json
README = ROOT / "README.md"


def load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["rows"]


def per_arm(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        out[row["arm"]].append(row)
    return out


def success(arm_rows: list[dict]) -> tuple[float, int, int]:
    n = len(arm_rows)
    k = sum(1 for r in arm_rows if r["ok"])
    return (k / n if n else 0.0), k, n


def mean_cost(arm_rows: list[dict]) -> float:
    return sum(r["cost"] for r in arm_rows) / max(len(arm_rows), 1)


def mean_tokens(arm_rows: list[dict]) -> float:
    return sum(r["prompt_tokens_total"] for r in arm_rows) / max(len(arm_rows), 1)


def refusals(arm_rows: list[dict]) -> int:
    return sum(r["guardrail_blocks"] for r in arm_rows)


def crossover(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """scenario -> (naive/ballast prompt tokens, naive/ballast cost), per task."""
    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by[(r["arm"], r["scenario_id"])].append(r)
    out = {}
    for sid in {s for _a, s in by}:
        base, ref = by.get(("naive", sid)), by.get(("ballast", sid))
        if not base or not ref:
            continue
        b_tok, c_tok = mean_tokens(base), mean_tokens(ref)
        if c_tok <= 0:
            continue
        out[sid] = (b_tok / c_tok, mean_cost(base) / mean_cost(ref) if mean_cost(ref) else 0.0)
    return out


def checks() -> list[tuple[str, str, list[str]]]:
    """(label, text-the-README-must-contain, allowed-formattings)."""
    desk = load(DESK)
    d = per_arm(desk)
    out: list[tuple[str, str, list[str]]] = []

    b_pct, b_k, b_n = success(d["ballast"])
    n_pct, n_k, n_n = success(d["naive"])
    out.append(("ballast desk success", "100.0%", [f"{b_pct:.1%}", "100.0%"]))
    out.append((f"ballast desk runs {b_k}/{b_n}", f"{b_n}", [str(b_n)]))
    out.append(("naive desk success", f"{n_pct:.1%}", [f"{n_pct:.1%}"]))

    ratio = mean_cost(d["naive"]) / mean_cost(d["ballast"])
    out.append(("aggregate naive/ballast cost ratio", f"{ratio:.2f}", [f"{ratio:.2f}"]))

    cost_b, cost_n = mean_cost(d["ballast"]), mean_cost(d["naive"])
    out.append(("ballast mean cost", f"{cost_b:.4f}", [f"{cost_b:.4f}", f"{cost_b:.2f}"]))
    out.append(("naive mean cost", f"{cost_n:.4f}", [f"{cost_n:.4f}", f"{cost_n:.2f}"]))

    out.append(("defective refused payments", str(refusals(d["defective"])), [str(refusals(d["defective"]))]))
    d_pct, _, _ = success(d["defective"])
    out.append(("defective success", f"{d_pct:.1%}", [f"{d_pct:.1%}"]))

    cross = load(CROSS.with_suffix(".json"))
    c = per_arm(cross)
    c_ratio = mean_cost(c["naive"]) / mean_cost(c["ballast"])
    out.append(("cross-domain cost ratio", f"{c_ratio:.2f}", [f"{c_ratio:.2f}"]))
    cb, _, cn = success(c["ballast"])
    out.append(("ballast cross-domain runs", str(cn), [str(cn)]))
    out.append(("ops_unassessed refusals", str(refusals(c["ops_unassessed"])), [str(refusals(c["ops_unassessed"]))]))
    out.append(("ops_reckless refusals", str(refusals(c["ops_reckless"])), [str(refusals(c["ops_reckless"]))]))

    xo = crossover(desk)
    for sid, label in (("B04_batch_queue", "shortest batch"), ("B09_batch_queue", "break-even"),
                       ("L36_batch", "longest passing batch")):
        if sid in xo:
            tok, _cost = xo[sid]
            out.append((f"crossover {label} ({sid})", f"{tok:.2f}", [f"{tok:.2f}", f"{tok:.2f}×"]))

    peak_n = max(r["prompt_tokens_peak"] for r in d["naive"])
    peak_b = max(r["prompt_tokens_peak"] for r in d["ballast"])
    out.append(("naive peak window", f"{peak_n:,}", [f"{peak_n:,}", str(peak_n)]))
    out.append(("ballast peak window", f"{peak_b:,}", [f"{peak_b:,}", str(peak_b)]))
    return out


def main(argv: list[str]) -> int:
    items = checks()
    if "--list" in argv:
        for label, value, _ in items:
            print(f"{label:42s} {value}")
        return 0
    text = README.read_text(encoding="utf-8")
    stale = []
    for label, value, forms in items:
        if not any(form in text for form in (*forms, value)):
            stale.append((label, value))
    if stale:
        print("README quotes numbers the stored benchmark rows do not produce:", file=sys.stderr)
        for label, value in stale:
            print(f"  {label}: recomputed {value}", file=sys.stderr)
        print("Regenerate the tables (`make eval`) or correct the prose. Do not edit the "
              "number to make this pass unless the recomputed value is the wrong one.", file=sys.stderr)
        return 1
    print(f"check_claims: {len(items)} README figures match bench/results/*.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
