"""The `ballast` command line: every subcommand, with zero API keys and no network."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from ballast.bench.runner import DEFAULT_ARMS
from ballast.cli import main
from ballast.kernel.checkpoint import Checkpointer
from ballast.memory.skills import Skill, SkillLibrary


@pytest.fixture
def data(tmp_path: Path) -> list[str]:
    """A `--data-dir` that keeps every run, cache and skill db out of the repo."""
    root = tmp_path / "state"
    root.mkdir(parents=True, exist_ok=True)
    return ["--data-dir", str(root)]


def out(capspec: pytest.CaptureFixture[str]) -> str:
    return capspec.readouterr().out


class TestArgParsing:
    def test_a_command_is_required(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main([])
        assert excinfo.value.code == 2
        assert "required" in out(capsys) or "invalid choice" in out(capsys)

    def test_unknown_arm_is_a_usage_error(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main([*data, "run", "S01_inwindow_refund", "--arm", "made_up"])
        assert excinfo.value.code == 2

    def test_unknown_scenario_is_reported(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        with pytest.raises(StopIteration):
            main([*data, "run", "S99_does_not_exist"])

    def test_the_console_script_is_wired(self) -> None:
        entry = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        assert 'ballast = "ballast.cli:main"' in entry


class TestArms:
    def test_lists_every_arm_with_its_note(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "arms"]) == 0
        text = out(capsys)
        for name in DEFAULT_ARMS:
            assert re.search(rf"^{name}\s", text, re.M), name
        assert "no context control" in text and "skips the mandatory computation" in text


class TestRun:
    def test_a_passing_scenario_exits_zero(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "run", "S01_inwindow_refund", "--arm", "ballast"]) == 0
        text = out(capsys)
        assert "grade: PASS" in text
        assert '"ok": true' in text
        assert re.search(r"status=ok cost=0\.\d+ steps=\d+ calls=\d+", text)
        assert "prompt_tokens_total=" in text and "offloads=" in text

    def test_the_trace_flag_prints_the_event_stream(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "run", "S06_high_risk", "--arm", "ballast", "--trace"]) == 0
        text = out(capsys)
        assert "run_start" in text and "tool_call" in text and "escalate_ticket" in text
        assert "grade: PASS" in text

    def test_a_failing_grade_exits_one(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "run", "S01_inwindow_refund", "--arm", "defective"]) == 1
        text = out(capsys)
        assert "grade: FAIL" in text and "✗" in text

    def test_the_row_is_printed_as_json(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        main([*data, "run", "S08_address_change"])
        text = out(capsys)
        payload = json.loads(text[: text.rindex("}") + 1])
        assert payload["scenario_id"] == "S08_address_change" and payload["ok"] is True
        assert payload["faults"]["total"] == 0

    def test_a_replay_without_recordings_fails(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        # `--replay` must never fall back to the network: it is the CI mode.
        from ballast.llm.replay import ReplayMiss

        with pytest.raises(ReplayMiss):
            main(["--data-dir", str(tmp_path), "run", "S01_inwindow_refund", "--replay"])


class TestEval:
    def test_eval_writes_markdown_and_json(self, capsys: pytest.CaptureFixture[str], data: list[str], tmp_path: Path) -> None:
        target = tmp_path / "report.md"
        assert main([*data, "eval", "--arms", "ballast,naive", "--reps", "1", "--out", str(target)]) == 0
        assert target.exists() and target.with_suffix(".json").exists()
        text = target.read_text(encoding="utf-8")
        assert "## Headline" in text and "`ballast`" in text and "`naive`" in text
        payload = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
        assert payload["provider"] == "surrogate" and payload["reps"] == 1
        assert {r["arm"] for r in payload["rows"]} == {"ballast", "naive"}
        assert all(r["cost"] > 0 for r in payload["rows"])
        assert "wrote" in out(capsys)

    def test_unknown_arm_names_itself(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "eval", "--arms", "ballast,not_an_arm"]) == 2
        assert "unknown arms" in capsys.readouterr().err

    def test_the_ci_invocation_needs_no_key(self, capsys: pytest.CaptureFixture[str], data: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        for variable in ("BALLAST_LLM_API_KEY", "DEEPSEEK_API_KEY", "BALLAST_LLM_BASE_URL"):
            monkeypatch.delenv(variable, raising=False)
        target = tmp_path / "ci.md"
        assert main([*data, "eval", "--arms", "ballast,naive,defective", "--reps", "1", "--out", str(target), "--workers", "2"]) == 0
        summary = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))["summary"]
        assert summary["defective"]["success_rate"] < summary["ballast"]["success_rate"]
        assert summary["ballast"]["runs"] == len(summary["ballast"]["pass_by_task"])
        assert "api_key" not in out(capsys)


class TestReport:
    def test_a_stored_report_renders_with_a_baseline(self, capsys: pytest.CaptureFixture[str], data: list[str], tmp_path: Path) -> None:
        target = tmp_path / "eval.md"
        main([*data, "eval", "--arms", "naive,ballast", "--out", str(target)])
        capsys.readouterr()
        assert main([*data, "report", str(target.with_suffix(".json")), "--baseline", "naive", "--reference", "ballast"]) == 0
        text = out(capsys)
        assert "## Paired comparisons vs reference arm" in text
        assert "`naive` vs `ballast`" in text

    def test_a_missing_report_path_falls_back_to_the_results_dir(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        with pytest.raises(IndexError):
            main([*data, "report"])  # no bench/results/eval-*.json in a clean checkout


class TestTraceAndApprovals:
    def test_trace_of_an_unknown_run_is_exit_one(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "trace", "nope"]) == 1
        assert "no checkpoints" in capsys.readouterr().err

    def test_trace_walks_the_checkpoints_of_a_real_run(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True, exist_ok=True)
        checkpointer = Checkpointer(root / "runs.db")
        checkpointer.save("run-7", {"status": "running", "events": [{"type": "tool_call", "payload": {"name": "get_ticket"}} for _ in range(5)]})
        checkpointer.save("run-7", {"status": "ok", "events": [{"type": "final", "payload": {"text": "done"}}]})
        checkpointer.close()
        assert main(["--data-dir", str(root), "trace", "run-7"]) == 0
        text = out(capsys)
        assert "--- seq 1 status=running events=5" in text
        assert "--- seq 2 status=ok" in text and "final" in text

    def test_approvals_list_is_json(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "approvals", "list"]) == 0
        assert json.loads(out(capsys)) == []

    def test_a_parked_run_shows_up_in_the_queue(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        from ballast.bench.faults import attribute  # noqa: F401  (keeps the import hot if reordered)
        from ballast.env.fixtures import by_id
        from ballast.bench.runner import resolve_arm

        root = tmp_path / "state"
        root.mkdir(parents=True, exist_ok=True)
        # Park a real run: the harness interrupts at the approval gate and checkpoints.
        from ballast.kernel.agent import Agent, AgentConfig
        from ballast.kernel.budget import RunBudget
        from ballast.kernel.events import RunContext
        from ballast.kernel.toolkit import Toolkit
        from ballast.llm.surrogate import ScriptedModel
        from ballast.tools.desk import build_desk_tools

        from conftest import s03_plan

        scenario = by_id("S03_quality_with_shipping")
        world = scenario.build_world()
        kb = resolve_arm("ballast") and scenario.build_world() and __import__("ballast.env.knowledge", fromlist=["KnowledgeBase"]).KnowledgeBase.from_dir()
        ctx = RunContext(task_id=scenario.id, arm="cli", world=world, sop=kb, hitl_mode="interrupt", hitl_script={})
        agent = Agent(
            AgentConfig(
                provider=ScriptedModel(s03_plan()),
                toolkit=Toolkit(build_desk_tools(ctx)),
                budget=RunBudget(),
                checkpointer=Checkpointer(root / "runs.db"),
            ),
            world=world,
            kb=kb,
        )
        result = agent.run(scenario.brief, task_id=scenario.id, arm="cli", ctx=ctx)
        assert result.status == "interrupted"

        assert main(["--data-dir", str(root), "approvals", "list"]) == 0
        pending = json.loads(out(capsys))
        assert len(pending) == 1 and pending[0]["run_id"] == result.run_id
        assert pending[0]["interrupt"]["tool"] == "issue_refund"

        assert main(["--data-dir", str(root), "approvals", "resolve", "--run-id", result.run_id, "--approved"]) == 0
        assert "resolved" in out(capsys) and "Agent.resume()" in out(capsys)

    def test_resolve_needs_a_run_id(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "approvals", "resolve"]) == 2
        assert "--run-id is required" in capsys.readouterr().err


class TestSkills:
    def test_empty_library_lists_nothing(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "skills", "list"]) == 0
        assert out(capsys) == ""

    def test_distill_then_list_then_gate(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True, exist_ok=True)
        argv = ["--data-dir", str(root)]
        # one candidate keeps the gate cheap: it is evaluated over the holdout slice twice
        library = SkillLibrary(root / "skills.db")
        library.add(
            Skill(
                id="seeded",
                name="refund_window: seeded card",
                when_to_use="处理 refund_window 类售后工单时套用：先核定政策再动钱。 TRIGGER:force_compute_refund",
                procedure=["读取工单", "检索政策", "compute_refund", "按核定金额放款"],
                tools=["get_ticket", "search_sop", "compute_refund", "issue_refund"],
                keywords="refund 退款 窗口 compute_refund",
                status="candidate",
            )
        )
        library.close()
        assert main([*argv, "skills", "list"]) == 0
        assert "[candidate ] seeded" in out(capsys)

        assert main([*argv, "skills", "gate", "--baseline-arm", "defective"]) == 0
        text = out(capsys)
        verdicts = json.loads(text[: text.rindex("]") + 1])
        assert len(verdicts) == 1 and verdicts[0]["skill_id"] == "seeded"
        assert verdicts[0]["promoted"] is True, verdicts[0]["reasons"]
        assert verdicts[0]["cost_ratio"]["point"] > 0
        assert "promoted" in text.splitlines()[-1]
        assert main([*argv, "skills", "list"]) == 0
        assert "[active   ] seeded" in out(capsys)

    def test_gate_without_candidates_tells_you_so(self, capsys: pytest.CaptureFixture[str], data: list[str]) -> None:
        assert main([*data, "skills", "gate"]) == 1
        assert "no candidates" in out(capsys)

    def test_distill_seeds_the_library_from_passing_runs(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        root = tmp_path / "state"
        root.mkdir(parents=True, exist_ok=True)
        assert main(["--data-dir", str(root), "skills", "distill", "--suite", "holdout"]) == 0
        text = out(capsys)
        made = int(re.search(r"distilled (\d+) candidate cards", text).group(1))
        assert made >= 5 and "skip duplicate" in text
        library = SkillLibrary(root / "skills.db")
        assert library.count(status="candidate") == made
        assert all(s.status == "candidate" for s in library.all(status=None))
        assert any("TRIGGER:force_compute_refund" in s.when_to_use for s in library.all(status=None))


class TestProcessEntry:
    def test_module_main_returns_the_status_code(self) -> None:
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, "-m", "ballast.cli", "arms"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).resolve().parents[1]),
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        )
        assert completed.returncode == 0, completed.stderr
        assert "ballast" in completed.stdout and "defective" in completed.stdout
