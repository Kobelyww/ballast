#!/usr/bin/env python3
"""Sweep the offload threshold over the payload-heavy tasks and report what each costs.

Offloading is the one context control whose value is *assumed* rather than measured in
most agent frameworks: move a big tool result out of the window, hand back a handle, and
trust that the agent will only pay to bring it back when it needs it. This script asks
what that assumption is worth, on the tasks whose payloads are large enough to trigger
it at all.

It is a question about the harness, so it runs offline: same surrogate, same worlds,
same graders, no API key.

Usage:  python scripts/offload_sweep.py
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ballast.bench.runner import resolve_arm, run_scenario  # noqa: E402
from ballast.env.fixtures import scenarios  # noqa: E402

VARIANTS: list[tuple[str, dict[str, object]]] = [
    ("off", {"enable_offload": False}),
    ("1200", {"offload_threshold": 1_200, "enable_offload": True}),
    ("2000", {"offload_threshold": 2_000, "enable_offload": True}),
    ("3000", {"offload_threshold": 3_000, "enable_offload": True}),
    ("6000", {"offload_threshold": 6_000, "enable_offload": True}),
    ("9000", {"offload_threshold": 9_000, "enable_offload": True}),
]


def heavy_tasks() -> list[object]:
    """Train tasks whose payloads can crowd out a window — the only ones where the
    threshold can matter. Selected by tag, not by hand, so the set cannot drift."""
    return [s for s in scenarios() if not s.holdout and {"bloat", "long_horizon"} & set(s.tags or [])]


def main() -> int:
    base = resolve_arm("ballast")
    tasks = heavy_tasks()
    if not tasks:
        print("no payload-heavy tasks in the train slice", file=sys.stderr)
        return 1
    print(f"{len(tasks)} payload-heavy train tasks, arm `ballast` with the threshold varied\n")
    print(f"{'threshold':>10} {'pass':>8} {'cost':>8} {'prompt tok':>11} {'calls':>7} {'offloads':>9}  failures")
    for label, context in VARIANTS:
        arm = dataclasses.replace(base, name=f"ballast@{label}", context={**base.context, **context})
        passed = 0
        cost = tokens = calls = offloads = 0
        failed: list[str] = []
        for scenario in tasks:
            row, grade, _extras = run_scenario(scenario, arm)
            passed += int(grade.ok)
            cost += row.cost
            tokens += row.prompt_tokens_total
            calls += row.calls
            offloads += row.offloads
            if not grade.ok:
                failed.append(f"{scenario.id}:{row.status}")
        note = ", ".join(failed) or "—"
        print(f"{label:>10} {passed:>5}/{len(tasks)} {cost:>8.2f} {tokens / 1e6:>10.2f}M {calls:>7} {offloads:>9}  {note}")
    print(
        "\nReading: a threshold that fires below the window's own budget converts one big read\n"
        "into a pinned re-fetch the run then carries forever — which is why the low settings\n"
        "cost more than turning the mechanism off. What this suite cannot yet show is the case\n"
        "the mechanism exists for: a single result larger than the whole window, where an\n"
        "inline read is not merely expensive but impossible. That needs field-scoped re-reads\n"
        "(offset/limit paging that stays parseable), tracked as a follow-up."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
