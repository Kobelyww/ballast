"""Statistics that decide whether an agent actually learned something.

The self-improvement literature is full of "the agent got better", where the evidence
is one more run that happened to succeed. These are the three tests that make that
sentence falsifiable:

* `pass_k` — reliability, not just capability: k consecutive successes on the same
  task, with a Wilson interval so n=8 is visibly weak.
* `mcnemar_exact` — paired binary outcomes on identical tasks. Only the discordant
  pairs matter, which is exactly the comparison an A/B of two agent arms should be.
* `paired_ratio_ci` — cost ratios under the same tasks, bootstrapped over tasks so a
  single cheap run cannot invent a 40% saving.

All deterministic given a seed; the bootstrap uses `random.Random(seed)`, not globals.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from itertools import combinations_with_replacement
from typing import Sequence

Pair = tuple[int, int]  # (baseline_success, treatment_success) on the same task


@dataclass(slots=True)
class Interval:
    point: float
    low: float
    high: float

    def as_dict(self) -> dict[str, float]:
        return {"point": round(self.point, 4), "low": round(self.low, 4), "high": round(self.high, 4)}

    def crosses(self, value: float = 1.0) -> bool:
        return self.low <= value <= self.high


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    ph = successes / n
    denom = 1 + z * z / n
    centre = (ph + z * z / (2 * n)) / denom
    margin = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def pass_k(successes: int, n: int, k: int = 1) -> float:
    """P(all k draws succeed) under an i.i.d. per-draw success rate (tau-bench's pass^k)."""
    if n == 0:
        return 0.0
    return (successes / n) ** k


def pass_k_measured(draws: Sequence[Sequence[bool]], k: int) -> float:
    """Fraction of tasks that pass *every* of their first k draws.

    The honest sibling of `pass_k`, which assumes draws are independent. That assumption
    is not cosmetic: with a deterministic stand-in policy every draw of a task is
    identical, so the measured value equals pass^1 and any decay it predicts is a property
    of the model, not of the agent. Report the measurement; label the estimate.
    """
    usable = [d for d in draws if len(d) >= k]
    if not usable:
        return 0.0
    return sum(1 for d in usable if all(d[:k])) / len(usable)


def success_rate_ci(successes: int, n: int) -> Interval:
    low, high = wilson_interval(successes, n)
    return Interval(successes / n if n else 0.0, low, high)


def mcnemar_exact(pairs: Sequence[Pair]) -> tuple[float, int, int]:
    """Two-sided exact binomial test on discordant pairs. Returns (p_value, b, c)."""
    b = sum(1 for base, treat in pairs if base == 0 and treat == 1)
    c = sum(1 for base, treat in pairs if base == 1 and treat == 0)
    n = b + c
    if n == 0:
        return 1.0, 0, 0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(1.0, 2 * tail), b, c


def paired_ratio_ci(baseline: Sequence[float], treatment: Sequence[float], *, iters: int = 2000, seed: int = 11, confidence: float = 0.95) -> Interval:
    """Bootstrap CI for mean(treatment) / mean(baseline) over paired tasks."""
    if len(baseline) != len(treatment) or not baseline:
        raise ValueError("paired samples must be equal length and non-empty")
    base_mean = sum(baseline) / len(baseline)
    treat_mean = sum(treatment) / len(treatment)
    if base_mean == 0:
        return Interval(float("inf") if treat_mean else 1.0, 1.0, 1.0)
    rng = random.Random(seed)
    n = len(baseline)
    ratios = []
    for _ in range(iters):
        idx = [rng.randrange(n) for _ in range(n)]
        b = sum(baseline[i] for i in idx) / n
        t = sum(treatment[i] for i in idx) / n
        if b > 0:
            ratios.append(t / b)
    ratios.sort()
    if not ratios:
        return Interval(treat_mean / base_mean, 1.0, 1.0)
    alpha = (1 - confidence) / 2
    return Interval(
        treat_mean / base_mean,
        ratios[min(len(ratios) - 1, int(alpha * len(ratios)))],
        ratios[min(len(ratios) - 1, int((1 - alpha) * len(ratios)))],
    )


def cohen_h(p1: float, p2: float) -> float:
    """Effect size for two proportions; tells a 1/8 vs 2/8 difference from a real one."""

    def h(p: float) -> float:
        return 2 * math.asin(math.sqrt(min(1.0, max(0.0, p))))

    return h(p2) - h(p1)


def multiple_comparisons(p_values: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values, so running 12 ablations cannot mine a 0.05."""
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        raw = p_values[idx] * m / (m - rank + 1)
        prev = min(prev, raw)
        adjusted[idx] = min(1.0, prev)
    return adjusted


__all__ = [
    "Interval",
    "Pair",
    "cohen_h",
    "mcnemar_exact",
    "multiple_comparisons",
    "paired_ratio_ci",
    "pass_k",
    "success_rate_ci",
    "wilson_interval",
]
