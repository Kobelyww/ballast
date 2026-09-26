#!/usr/bin/env python3
"""Measure pass^k decay through the real HTTP transport — not estimated from a formula.

The offline surrogate is deterministic, so every repeat of a task is a copy and measured
`pass^k` is flat by construction. That is stated in the README as a limitation, and this
script is the counter-check: the same runner, the same graders, but the model is reached
over a real socket (`scripts/mock_openai_server.py`, loopback only) with seeded variance,
so draws genuinely differ.

If `pass^3` does not fall below `pass^1` here, the metric is not measuring anything.

Usage:  python scripts/measure_http_reliability.py [--reps 30] [--flaky-rate 0.35]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import mock_openai_server as mock  # noqa: E402

from ballast.bench.runner import resolve_arm, run_scenario  # noqa: E402
from ballast.bench.stats import pass_k, pass_k_measured  # noqa: E402
from ballast.env.fixtures import by_id  # noqa: E402

# The mock server implements one procedure — read the ticket, derive the refund, pay,
# close — so these are the tasks it can actually complete. Verified by running all 32:
# any task outside this list is a mock limitation, not a harness failure.
TASKS = (
    "S01_inwindow_refund",
    "S02_window_closed",
    "S03_quality_with_shipping",
    "S04_missing_item",
    "S15_context_bloat",
    "S17_fat_order",
    "S20_oversized_manifest",
)


def measure(reps: int, rate: float, seed: int, arm_name: str) -> dict[str, float]:
    """Run each task `reps` times over HTTP and return pass^k for k = 1..5."""
    server, thread = mock.serve(0)  # ephemeral loopback port
    port = server.server_address[1]
    os.environ["BALLAST_LLM_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["BALLAST_LLM_API_KEY"] = "mock"
    mock.set_variance(rate, seed)
    arm = resolve_arm(arm_name)
    per_task: dict[str, list[bool]] = {t: [] for t in TASKS}
    try:
        for rep in range(reps):
            for tid in TASKS:
                _row, grade, _extras = run_scenario(by_id(tid), arm, rep=rep, provider_kind="openai-compat")
                per_task[tid].append(bool(grade.ok))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        mock.set_variance(0.0)
        os.environ.pop("BALLAST_LLM_BASE_URL", None)
        os.environ.pop("BALLAST_LLM_API_KEY", None)
    draws = list(per_task.values())
    return {f"pass^{k}": pass_k_measured(draws, k) for k in (1, 2, 3, 5)} | {
        "pass^1 rate": sum(sum(d) for d in draws) / sum(len(d) for d in draws)
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument("--flaky-rate", type=float, default=0.35)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--arm", default="ballast")
    parser.add_argument("--out", type=Path, default=ROOT / "bench/results/reliability-http.md")
    args = parser.parse_args(argv)

    varied = measure(args.reps, args.flaky_rate, args.seed, args.arm)
    stable = measure(args.reps, 0.0, args.seed, args.arm)
    rate = varied["pass^1 rate"]

    lines = [
        "# Reliability measured over real HTTP",
        "",
        f"Runner, arms and graders are the production ones; the model is "
        f"`scripts/mock_openai_server.py` on loopback, so this costs nothing and leaves no "
        f"machine. {args.reps} repeats × {len(TASKS)} tasks on the `{args.arm}` arm.",
        "",
        "| k | measured, variance injected | i.i.d. estimate | measured, deterministic provider |",
        "|---:|---:|---:|---:|",
    ]
    for k in (1, 2, 3, 5):
        key = f"pass^{k}"
        lines.append(
            f"| {k} | {varied[key]:.1%} | {pass_k(round(rate * args.reps * len(TASKS)), args.reps * len(TASKS), k):.1%} "
            f"| {stable[key]:.1%} |"
        )
    lines += [
        "",
        f"With a deterministic provider every repeat is a copy, so measured pass^k is flat at "
        f"{stable['pass^1']:.1%} — the limitation the README states. Inject an early-give-up rate "
        f"of {args.flaky_rate:.0%} and the measurement decays on its own: "
        f"{varied['pass^1']:.1%} → {varied['pass^3']:.1%} at k=3. "
        "The metric measures; the flat column was the surrogate, not the arithmetic.",
        "",
        f"Reproduce: `python scripts/measure_http_reliability.py --reps {args.reps} "
        f"--flaky-rate {args.flaky_rate} --seed {args.seed}`",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
