"""Reliability measured end-to-end over a real socket.

`tests/test_reliability.py` proves the metric responds to variance injected in-process.
This goes one step further: the model is reached through the actual OpenAI-compatible
transport — real HTTP, real serialisation, real retry path — against the bundled mock
server on loopback. Nothing leaves the machine and no key is involved.

The claim under test is narrow and, until now, unproven: that a *measured* pass^k decays
when a model's draws genuinely differ, while a deterministic provider stays flat.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from ballast.bench.runner import resolve_arm, run_scenario
from ballast.bench.stats import pass_k_measured
from ballast.env.fixtures import by_id

ROOT = Path(__file__).resolve().parents[1]


def _load_mock():
    path = ROOT / "scripts" / "mock_openai_server.py"
    spec = importlib.util.spec_from_file_location("ballast_mock_server", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# The tasks `scripts/mock_openai_server.py` can actually complete (checked against the
# whole train slice). Seven, because `pass^1` is the share of tasks passing their first
# draw — with three tasks that statistic is coarse enough to hide real variance.
TASKS = (
    "S01_inwindow_refund",
    "S02_window_closed",
    "S03_quality_with_shipping",
    "S04_missing_item",
    "S15_context_bloat",
    "S17_fat_order",
    "S20_oversized_manifest",
)


def _run_reps(mock, port: int, reps: int, rate: float, seed: int) -> list[list[bool]]:
    """`reps` draws of each task through the transport, as per-task draw lists."""
    mock.set_variance(rate, seed)
    os.environ["BALLAST_LLM_BASE_URL"] = f"http://127.0.0.1:{port}"
    os.environ["BALLAST_LLM_API_KEY"] = "mock"
    arm = resolve_arm("ballast")
    draws: dict[str, list[bool]] = {t: [] for t in TASKS}
    for rep in range(reps):
        for tid in TASKS:
            _row, grade, _extras = run_scenario(by_id(tid), arm, rep=rep, provider_kind="openai-compat")
            draws[tid].append(bool(grade.ok))
    return list(draws.values())


@pytest.fixture
def mock_server():
    mock = _load_mock()
    server, thread = mock.serve(0)
    try:
        yield mock, server.server_address[1]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        mock.set_variance(0.0)
        os.environ.pop("BALLAST_LLM_BASE_URL", None)
        os.environ.pop("BALLAST_LLM_API_KEY", None)


class TestReliabilityOverHttp:
    def test_a_deterministic_model_is_flat_at_every_k_through_the_transport(self, mock_server) -> None:
        """Same procedure as the surrogate case, but over a socket: no variance, no decay."""
        mock, port = mock_server
        draws = _run_reps(mock, port, reps=3, rate=0.0, seed=1)
        assert pass_k_measured(draws, 1) == 1.0
        assert pass_k_measured(draws, 3) == 1.0

    def test_a_varying_model_decays_and_the_measurement_is_not_the_estimate(self, mock_server) -> None:
        """The point of the module.

        With 40% of conversations giving up on their first turn, three consecutive draws
        succeed far less often than one — and the decay that comes out is not the
        `p̂^k` curve, which is the whole reason the report prints both columns.
        """
        from ballast.bench.stats import pass_k

        mock, port = mock_server
        reps = 8
        draws = _run_reps(mock, port, reps=reps, rate=0.40, seed=5)
        flat = pass_k_measured(draws, 1)
        triple = pass_k_measured(draws, 3)
        assert flat < 1.0, "the injected variance never reached the outcome"
        assert triple < flat, "measured pass^3 must fall below pass^1 when draws differ"

        successes = sum(sum(d) for d in draws)
        total = sum(len(d) for d in draws)
        assert triple != pytest.approx(pass_k(successes, total, 3), abs=1e-9), (
            "measured and modelled agreeing exactly would mean one of them is not doing "
            "what it says"
        )
