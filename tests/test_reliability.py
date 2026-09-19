"""Does the reliability metric measure anything when draws actually vary?

This repo's own `pass^k` column is flat, and the reason is on the record: the offline
surrogate is deterministic, so every repeat of a task is a copy of the first and there is
no run-to-run variance to see. That is an honest limitation, but it is not a test — a
metric that cannot detect decay when decay is present is decoration.

So these tests drive the same harness with a provider that *does* vary, and check that
`pass_k_measured` responds to it. Nothing here talks to a network or a model: the variance
is injected at the provider boundary, which is exactly where a real temperature > 0 would
enter.
"""

from __future__ import annotations

import random
from typing import Any

import pytest

from ballast.bench.graders import grade
from ballast.llm.base import ChatResponse, Usage
from ballast.llm.surrogate import ScriptedModel
from conftest import Harness, s03_plan

SCENARIO = "S03_quality_with_shipping"


class StochasticModel(ScriptedModel):
    """The same script, but some draws abandon the task mid-flight.

    `failure_rate` is the per-draw probability, not a fixed count, so the sequence of
    outcomes is genuinely variable across reps — which is the property being tested.
    """

    name = "stochastic"

    def __init__(self, steps: list[ChatResponse], rng: random.Random, failure_rate: float) -> None:
        super().__init__(steps)
        self.rng = rng
        self.failure_rate = failure_rate
        self.abandoned = False

    def chat(self, request: Any) -> ChatResponse:
        if self.index == 0 and not self.abandoned and self.rng.random() < self.failure_rate:
            self.abandoned = True
        if self.abandoned:
            self.index = len(self.steps)  # the harness sees a final, tool-free turn
            return ChatResponse(content="信息不足，先挂起等待人工。", usage=Usage(calls=1), finish_reason="stop")
        return super().chat(request)


def draws(failure_rate: float, reps: int, *, seed: int = 7) -> list[bool]:
    """Run the same task `reps` times under one provider and grade each run."""
    rng = random.Random(seed)
    outcomes: list[bool] = []
    for _rep in range(reps):
        harness = Harness(SCENARIO, provider=StochasticModel(s03_plan(), rng, failure_rate))
        result = harness.run()
        g = grade(harness.scenario, harness.world, sop_ids=harness.kb.section_ids(), events=result.events)
        outcomes.append(g.ok)
    return outcomes


class TestTheMetricDetectsRealVariance:
    def test_a_deterministic_provider_is_flat_at_every_k(self) -> None:
        """The surrogate case, reproduced on purpose.

        With no per-draw variance, measured pass^k equals pass^1 exactly — the fact the
        README now states instead of papering over with an independence assumption.
        """
        from ballast.bench.stats import pass_k_measured

        outcomes = draws(0.0, 5)
        assert all(outcomes), "a correct script under a stable provider must pass every draw"
        per_task = [outcomes]
        assert pass_k_measured(per_task, 1) == pass_k_measured(per_task, 3) == 1.0

    def test_measured_pass_k_decays_when_draws_differ(self) -> None:
        """The point of the whole module: the metric moves when reality moves.

        120 runs of one task, grouped into 40 blocks of three consecutive draws. If the
        provider varies, `pass^3` — three in a row, no recovery — must fall below `pass^1`,
        and it should land near the independent-draws prediction, because here the draws
        really are independent.
        """
        from ballast.bench.stats import pass_k, pass_k_measured

        outcomes = draws(0.35, 120)
        p1 = sum(outcomes) / len(outcomes)
        assert 0.0 < p1 < 1.0, "the injected variance did not reach the outcome"

        triples = [outcomes[i : i + 3] for i in range(0, len(outcomes) - 2, 3)]
        assert pass_k_measured(triples, 1) == pytest.approx(p1, abs=0.05)
        assert pass_k_measured(triples, 3) < pass_k_measured(triples, 1), "three in a row is harder than once"
        assert pass_k_measured(triples, 3) == pytest.approx(pass_k(sum(outcomes), len(outcomes), 3), abs=0.18)

    def test_the_estimate_is_legitimate_exactly_when_draws_are_independent(self) -> None:
        """`p̂^k` is not wrong; it answers a different question, and the difference is testable.

        For genuinely independent draws the measurement converges on the estimate. That is
        the condition under which the report's i.i.d. column is real data — and the reason
        it is labelled rather than printed alone: the failure this repo actually shipped was
        quoting the estimate under a heading that said the draws had been repeated.
        """
        from ballast.bench.stats import pass_k_measured

        rng = random.Random(11)
        outcomes = [rng.random() > 0.3 for _ in range(4000)]
        pairs = [[outcomes[i], outcomes[i + 1]] for i in range(0, len(outcomes) - 1, 2)]
        p1 = sum(1 for p in pairs if p[0]) / len(pairs)
        measured = pass_k_measured(pairs, 2)
        assert measured == pytest.approx(p1 * p1, abs=0.02), (measured, p1)

    def test_abandonment_is_visible_in_the_world_not_just_the_grade(self) -> None:
        """A draw that bails must leave the ticket open, or the grade is fiction."""
        harness = Harness(SCENARIO, provider=StochasticModel(s03_plan(), random.Random(3), 1.0))
        result = harness.run()
        assert result.status == "ok", "the run finished — it just finished by giving up"
        assert harness.world.get_ticket("T1044")["status"] == "open"
        assert harness.world.state()["refunds"] == []
        g = grade(harness.scenario, harness.world, sop_ids=harness.kb.section_ids(), events=result.events)
        assert not g.ok
