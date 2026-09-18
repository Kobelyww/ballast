"""Thin bridge so `memory.promotion` and the CLI share one way to pick a suite."""

from __future__ import annotations

from ..env.fixtures import Scenario, holdout_slice, scenarios, train_slice
from ..env.incident_fixtures import scenarios as incident_scenarios


def load_suite(name: str = "train") -> list[Scenario]:
    if name == "train":
        return train_slice()
    if name == "holdout":
        return holdout_slice()
    if name == "all":
        return scenarios() + incident_scenarios()
    if name in ("ops", "ops_train"):
        return [x for x in incident_scenarios() if not x.holdout]
    if name == "ops_holdout":
        return [x for x in incident_scenarios() if x.holdout]
    raise ValueError(f"unknown suite '{name}'; expected train | holdout | ops | ops_holdout | all")
