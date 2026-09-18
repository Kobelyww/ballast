"""The promotion gate: a skill is active only if it wins on a holdout slice.

Voyager and Reflexion both accept self-generated knowledge on the strength of the
agent's own verification. That is the part that makes "the agent learned" unfalsifiable.
Here a candidate must clear four checks on scenarios it was never distilled from:

1. at least one task goes failure → success and none goes success → failure (paired);
2. McNemar's exact test on the discordant pairs clears `alpha`;
3. cost does not rise beyond a bootstrap confidence bound;
4. the same must hold after Benjamini-Hochberg correction across concurrent candidates.

Failing any one of them retires the card. The gate is deterministic given a seed, so
CI can assert both halves of the claim: a card that helps is promoted, a card that
does not is rejected — no API key involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from ..bench.fixtures_bridge import load_suite
from ..bench.runner import Arm, resolve_arm, run_scenario
from ..bench.stats import Interval, mcnemar_exact, multiple_comparisons, paired_ratio_ci
from ..env.fixtures import Scenario
from ..memory.skills import Skill, SkillLibrary


@dataclass(slots=True)
class GateVerdict:
    skill_id: str
    skill_name: str
    promoted: bool
    reasons: list[str] = field(default_factory=list)
    pairs: list[tuple[int, int]] = field(default_factory=list)
    p_value: float = 1.0
    p_adjusted: float = 1.0
    success_delta: float = 0.0
    cost_ratio: Interval | None = None
    cost_ratio_per_attempt: Interval | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "promoted": self.promoted,
            "reasons": self.reasons,
            "discordant_b_c": [sum(1 for b, t in self.pairs if not b and t), sum(1 for b, t in self.pairs if b and not t)],
            "p_value": round(self.p_value, 5),
            "p_adjusted": round(self.p_adjusted, 5),
            "success_delta": self.success_delta,
            "cost_ratio": self.cost_ratio.as_dict() if self.cost_ratio else None,
            "cost_ratio_per_attempt": self.cost_ratio_per_attempt.as_dict() if self.cost_ratio_per_attempt else None,
        }


def evaluate_candidate(
    skill: Skill,
    *,
    holdout: Sequence[Scenario],
    baseline_arm: str = "defective",
    treatment_runtime: dict[str, Any] | None = None,
    provider_kind: str = "surrogate",
    library: SkillLibrary | None = None,
) -> GateVerdict:
    base_arm = resolve_arm(baseline_arm)
    treat_arm = Arm(
        name=f"{baseline_arm}+skill",
        note="same policy, one skill card injected into the prompt",
        context=dict(base_arm.context),
        budget=dict(base_arm.budget),
        runtime={**base_arm.runtime, "enable_skills": True, **(treatment_runtime or {})},
        profile=dict(base_arm.profile),
    )
    # Evaluate the card as if it were live: the whole point of the gate is that
    # "active" is a status a card has to earn, not one it starts with. The card is
    # written to a throwaway library; the real one only changes in `apply_verdicts`.
    lib = library or SkillLibrary()
    lib.add(replace(skill, status="active"))

    baseline_rows, treatment_rows = [], []
    for scenario in holdout:
        base_row, base_grade, _ = run_scenario(scenario, base_arm, provider_kind=provider_kind, skills=None)
        treat_row, treat_grade, _ = run_scenario(scenario, treat_arm, provider_kind=provider_kind, skills=lib)
        baseline_rows.append((scenario.id, base_grade.ok, base_row.cost))
        treatment_rows.append((scenario.id, treat_grade.ok, treat_row.cost))

    return judge(
        skill,
        baseline=baseline_rows,
        treatment=treatment_rows,
        alpha=0.05,
        max_cost_ratio=1.35,
    )


def judge(
    skill: Skill,
    *,
    baseline: Sequence[tuple[str, bool, float]],
    treatment: Sequence[tuple[str, bool, float]],
    alpha: float = 0.05,
    max_cost_ratio: float = 1.35,
) -> GateVerdict:
    base = {sid: (ok, cost) for sid, ok, cost in baseline}
    treat = {sid: (ok, cost) for sid, ok, cost in treatment}
    shared = [sid for sid in base if sid in treat]
    pairs = [(int(base[s][0]), int(treat[s][0])) for s in shared]
    p, b, c = mcnemar_exact(pairs)
    ratio = paired_ratio_ci([base[s][1] or 1e-9 for s in shared], [treat[s][1] or 1e-9 for s in shared])
    delta = (sum(treat[s][0] for s in shared) - sum(base[s][0] for s in shared)) / max(1, len(shared))

    # Price *success*, not attempts. A card that fixes a run which was previously
    # refused-and-aborted costs more per attempt by construction — comparing raw
    # attempt cost rewards the cheap failure and would veto every real improvement.
    rate_base = sum(base[s][0] for s in shared) / max(1, len(shared))
    rate_treat = sum(treat[s][0] for s in shared) / max(1, len(shared))
    mean_base = sum(base[s][1] or 1e-9 for s in shared) / max(1, len(shared))
    mean_treat = sum(treat[s][1] or 1e-9 for s in shared) / max(1, len(shared))
    cps_base = mean_base / rate_base if rate_base else float("inf")
    cps_treat = mean_treat / rate_treat if rate_treat else float("inf")
    cps_ratio = None
    if cps_base != float("inf") and cps_treat != float("inf") and cps_base > 0:
        cps_ratio = paired_ratio_ci(
            [(base[s][1] or 1e-9) / rate_base for s in shared],
            [(treat[s][1] or 1e-9) / rate_treat for s in shared],
        )

    reasons: list[str] = []
    if b == 0:
        reasons.append("no task went from failure to success: the card changed nothing")
    if c > 0:
        reasons.append(f"{c} task(s) regressed: the card is net harmful")
    if b > 0 and p > alpha:  # noqa: SIM108
        reasons.append(f"improvement not significant (exact McNemar p={p:.4f} > {alpha}) with n={len(shared)}")
    if rate_base == 0 and b > 0:
        # Cost per success is undefined when the baseline never succeeded, and attempt
        # cost is the wrong yardstick against a run that was refused and aborted cheap.
        # Say so, rather than silently picking whichever ratio happens to pass.
        # No cost-per-success exists to compare, so the attempt ratio is reported for
        # transparency and a hard absolute ceiling still applies: a card that fixes
        # everything at 5x the spend still needs a human to sign off on the bill.
        hard_ceiling = max_cost_ratio * 3
        if ratio.low > hard_ceiling:
            reasons.append(
                f"cost ratio {ratio.point:.2f} [{ratio.low:.2f}, {ratio.high:.2f}] exceeds the hard "
                f"ceiling {hard_ceiling:.2f}; baseline never succeeded, so cost per success is undefined"
            )
        else:
            reasons.append(
                f"cost basis reported, not enforced: baseline succeeded on 0/{len(shared)} held-out tasks, "
                f"so cost-per-success is undefined; attempt cost ratio {ratio.point:.2f} is within the hard ceiling"
            )
    if cps_ratio is not None and cps_ratio.low > max_cost_ratio:
        reasons.append(
            f"cost per success rose {cps_ratio.point:.2f}x [{cps_ratio.low:.2f}, {cps_ratio.high:.2f}] "
            f"against a {max_cost_ratio:.2f} ceiling"
        )

    blocking = [r for r in reasons if not r.startswith("cost basis reported")]
    verdict = GateVerdict(
        skill_id=skill.id,
        skill_name=skill.name,
        promoted=not blocking,
        reasons=(
            blocking
            or [
                f"promoted: {b} fixed, {c} regressed, p={p:.4f}, "
                + (f"cost per success {cps_ratio.point:.2f}x" if cps_ratio else f"cost per success undefined (baseline never passed); attempt cost {ratio.point:.2f}x")
            ]
        ),
        pairs=pairs,
        p_value=p,
        p_adjusted=p,
        success_delta=delta,
        cost_ratio=cps_ratio or ratio,
        cost_ratio_per_attempt=ratio,
    )
    return verdict


def gate_library(
    *,
    candidates: Sequence[Skill],
    holdout: Sequence[Scenario] | None = None,
    alpha: float = 0.05,
    baseline_arm: str = "defective",
    library: SkillLibrary | None = None,
    provider_kind: str = "surrogate",
    suite_name: str = "holdout",
) -> list[GateVerdict]:
    """One candidate at a time — a card's value is measured against the library it joins."""
    suite = list(holdout or load_suite(suite_name))
    lib = library or SkillLibrary()
    verdicts = [
        evaluate_candidate(skill, holdout=suite, baseline_arm=baseline_arm, library=lib, provider_kind=provider_kind)
        for skill in candidates
    ]
    adjusted = multiple_comparisons([v.p_value for v in verdicts])
    for verdict, padj in zip(verdicts, adjusted):
        verdict.p_adjusted = padj
        if verdict.promoted and padj > alpha:
            verdict.promoted = False
            verdict.reasons.append(f"does not survive multiple-comparison correction (p_adj={padj:.4f})")
    return verdicts


def apply_verdicts(library: SkillLibrary, verdicts: Sequence[GateVerdict]) -> dict[str, int]:
    counts = {"promoted": 0, "retired": 0}
    for verdict in verdicts:
        evidence = {k: v for k, v in verdict.as_dict().items() if k not in {"skill_id", "skill_name"}}
        if verdict.promoted:
            library.promote(verdict.skill_id, evidence=evidence)
            counts["promoted"] += 1
        else:
            library.reject(verdict.skill_id, evidence=evidence)
            counts["retired"] += 1
    return counts


__all__ = ["GateVerdict", "apply_verdicts", "evaluate_candidate", "gate_library", "judge"]
