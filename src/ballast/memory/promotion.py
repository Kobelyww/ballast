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

    reasons: list[str] = []
    if b == 0:
        reasons.append("no task went from failure to success: the card changed nothing")
    if c > 0:
        reasons.append(f"{c} task(s) regressed: the card is net harmful")
    if b > 0 and p > alpha:
        reasons.append(f"improvement not significant (exact McNemar p={p:.4f} > {alpha}) with n={len(shared)}")
    if not ratio.crosses(max_cost_ratio) and ratio.low > max_cost_ratio:
        reasons.append(f"cost ratio {ratio.point:.2f} [{ratio.low:.2f}, {ratio.high:.2f}] exceeds the {max_cost_ratio:.2f} ceiling")

    verdict = GateVerdict(
        skill_id=skill.id,
        skill_name=skill.name,
        promoted=not reasons,
        reasons=reasons or [f"promoted: {b} fixed, {c} regressed, p={p:.4f}, cost ratio {ratio.point:.2f}"],
        pairs=pairs,
        p_value=p,
        p_adjusted=p,
        success_delta=delta,
        cost_ratio=ratio,
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
) -> list[GateVerdict]:
    """One candidate at a time — a card's value is measured against the library it joins."""
    suite = list(holdout or load_suite("holdout"))
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
