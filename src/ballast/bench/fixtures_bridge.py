"""Thin bridge so `memory.promotion` and the CLI share one way to pick a suite."""

from __future__ import annotations

from ..env.fixtures import Scenario, holdout_slice, scenarios, train_slice


def load_suite(name: str = "train") -> list[Scenario]:
    if name == "train":
        return train_slice()
    if name == "holdout":
        return holdout_slice()
    if name == "all":
        return scenarios()
    raise ValueError(f"unknown suite '{name}'; expected train | holdout | all")
