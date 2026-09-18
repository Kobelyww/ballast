"""`ballast` command line.

Stdlib argparse, no framework. The subcommands mirror the lifecycle of an agent
project: run one task, ablate a suite, inspect a trace, resolve a pending approval,
grow and audit the skill library.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .bench.fixtures_bridge import load_suite
from .bench.report import markdown as render_markdown
from .bench.runner import DEFAULT_ARMS, resolve_arm, run_scenario, run_suite
from .env.fixtures import by_id, scenarios
from .kernel.checkpoint import Checkpointer
from .llm.base import Pricing
from .memory.distill import distill
from .memory.promotion import apply_verdicts, gate_library
from .memory.skills import Skill, SkillLibrary

RESULTS = Path("bench/results")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ballast", description="Budget-aware agent runtime + cost/quality benchmark")
    parser.add_argument("--data-dir", default=".ballast", help="state directory (cache, checkpoint db, skills db)")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="run one scenario and print the trace")
    run_p.add_argument("scenario")
    run_p.add_argument("--arm", default="ballast", choices=sorted(DEFAULT_ARMS))
    run_p.add_argument("--provider", default="surrogate", help="surrogate | deepseek | openai-compat")
    run_p.add_argument("--model", default="deepseek-chat")
    run_p.add_argument("--replay", action="store_true", help="read responses from the on-disk cache and never call out")
    run_p.add_argument("--trace", action="store_true", help="print every event")

    eval_p = sub.add_parser("eval", help="run the suite across arms")
    eval_p.add_argument("--arms", default="naive,ballast,no_context_control,tight_budget,defective,noisy,bloated")
    eval_p.add_argument("--suite", default="train", choices=["train", "holdout", "all"])
    eval_p.add_argument("--reps", type=int, default=1)
    eval_p.add_argument("--workers", type=int, default=4)
    eval_p.add_argument("--provider", default="surrogate")
    eval_p.add_argument("--model", default="deepseek-chat")
    eval_p.add_argument("--record", action="store_true", help="cache real responses for later replay")
    eval_p.add_argument("--out", default="", help="write JSON report to this path")

    report_p = sub.add_parser("report", help="render a stored JSON report as markdown")
    report_p.add_argument("path", nargs="?", default="")
    report_p.add_argument("--baseline", default="naive")
    report_p.add_argument("--reference", default="ballast")

    sub.add_parser("arms", help="list runtime arms")

    trace_p = sub.add_parser("trace", help="inspect a checkpointed run")
    trace_p.add_argument("run_id")

    approvals_p = sub.add_parser("approvals", help="list or resolve parked runs")
    approvals_p.add_argument("action", nargs="?", default="list", choices=["list", "resolve"])
    approvals_p.add_argument("--run-id", default="")
    approvals_p.add_argument("--approved", action="store_true")

    skills_p = sub.add_parser("skills", help="distill, gate and list skill cards")
    skills_p.add_argument("action", nargs="?", default="list", choices=["list", "distill", "gate"])
    skills_p.add_argument("--suite", default="train", choices=["train", "holdout", "all"])
    skills_p.add_argument("--baseline-arm", default="defective")

    args = parser.parse_args(argv)
    data = Path(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)

    if args.command == "arms":
        for name, arm in DEFAULT_ARMS.items():
            print(f"{name:20s} {arm.note}")
        return 0

    if args.command == "run":
        return _cmd_run(args, data)
    if args.command == "eval":
        return _cmd_eval(args, data)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "trace":
        return _cmd_trace(args, data)
    if args.command == "approvals":
        return _cmd_approvals(args, data)
    if args.command == "skills":
        return _cmd_skills(args, data)
    return 2


def _cmd_run(args: argparse.Namespace, data: Path) -> int:
    try:
        scenario = by_id(args.scenario)
    except StopIteration:
        known = ", ".join(sc.id for sc in scenarios())
        print(f"no scenario '{args.scenario}'. available: {known}", file=sys.stderr)
        return 2
    arm = resolve_arm(args.arm)
    provider_kind = args.provider
    if args.replay:
        provider_kind = "replay"
    row, grade, extras = run_scenario(
        scenario,
        arm,
        provider_kind=provider_kind,
        cache_dir=data / "cache",
        model=args.model,
    )
    result = extras["result"]
    print(json.dumps(row.as_dict(), ensure_ascii=False, indent=2)[:4000])
    print(f"\nstatus={result.status} cost={result.cost:.4f} steps={result.steps} calls={result.calls}")
    print(f"prompt_tokens_total={result.context['prompt_tokens']} peak={result.context['peak_prompt_tokens']} offloads={result.context['offloads']}")
    print("grade:", "PASS" if grade.ok else "FAIL")
    for check in grade.checks:
        print(f"  {'✓' if check.ok else '✗'} {check.detail}")
    if args.trace:
        for event in result.events:
            payload = event["payload"]
            label = payload.get("name") or payload.get("reason") or payload.get("dimension") or ""
            print(f"  [{event['step']:>2}] {event['type']:<18} {label}")
    return 0 if grade.ok else 1


def _cmd_eval(args: argparse.Namespace, data: Path) -> int:
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arms if a not in DEFAULT_ARMS]
    if unknown:
        print(f"unknown arms: {unknown}; see `ballast arms`", file=sys.stderr)
        return 2
    cache_dir = data / "cache" if (args.record or args.provider == "replay") else None
    result = run_suite(
        suite=load_suite(args.suite),
        arms=arms,
        reps=args.reps,
        workers=args.workers,
        provider_kind=args.provider,
        cache_dir=cache_dir,
        model=args.model,
        progress=lambda arm, sid, ok: print(f"  {arm:20s} {sid:28s} {'ok' if ok else 'FAIL'}", file=sys.stderr),
    )
    text = render_markdown(result, baseline=args.baseline if hasattr(args, "baseline") else "naive")
    out = Path(args.out) if args.out else RESULTS / f"eval-{result.generated_at.replace(':', '')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    result.to_json(out.with_suffix(".json"))
    print(text)
    print(f"\nwrote {out} and {out.with_suffix('.json')}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    path = Path(args.path) if args.path else sorted(RESULTS.glob("eval-*.json"))[-1]
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    from .bench.runner import RunRecordRow, SuiteResult

    rows = [RunRecordRow(**r) for r in payload["rows"]]
    result = SuiteResult(generated_at=payload["generated_at"], provider=payload["provider"], model=payload["model"], reps=payload["reps"], rows=rows, arms=payload["arms"])
    print(render_markdown(result, baseline=args.baseline, reference=args.reference))
    return 0


def _cmd_trace(args: argparse.Namespace, data: Path) -> int:
    cp = Checkpointer(data / "runs.db")
    latest = cp.latest(args.run_id)
    if latest is None:
        print(f"no checkpoints for {args.run_id}", file=sys.stderr)
        return 1
    for checkpoint in cp.history(args.run_id):
        events = checkpoint.state.get("events", [])
        print(f"--- seq {checkpoint.seq} status={checkpoint.state.get('status')} events={len(events)}")
        for event in events[-3:]:
            print(f"    {event['type']}: {json.dumps(event['payload'], ensure_ascii=False)[:160]}")
    return 0


def _cmd_approvals(args: argparse.Namespace, data: Path) -> int:
    cp = Checkpointer(data / "runs.db")
    pending = cp.pending_interrupts()
    if args.action == "list":
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return 0
    if not args.run_id:
        print("--run-id is required to resolve", file=sys.stderr)
        return 2
    print(f"resolved {args.run_id} approved={args.approved}; call Agent.resume() with the verdict to continue the run")
    return 0


def _cmd_skills(args: argparse.Namespace, data: Path) -> int:
    library = SkillLibrary(data / "skills.db")
    if args.action == "list":
        for skill in library.all(status=None):
            print(f"[{skill.status:9s}] {skill.id} uses={skill.use_count} wins={skill.win_rate:.0%} :: {skill.name}")
        return 0

    if args.action == "distill":
        suite = load_suite(args.suite)
        made = []
        for scenario in suite:
            row, grade, extras = run_scenario(scenario, resolve_arm("ballast"))
            if not grade.ok:
                continue
            skill = distill(
                {
                    "events": extras["result"].events,
                    "scenario_id": scenario.id,
                    "run_id": row.scenario_id,
                    "guardrails": [],
                    "task": scenario.brief,
                },
                family=scenario.skill_family,
                task_text=scenario.brief,
            )
            if skill is None:
                continue
            similar = library.find_similar(skill)
            if similar:
                print(f"  skip duplicate of {similar.id} ({similar.name})")
                continue
            library.add(skill)
            made.append(skill)
        print(f"distilled {len(made)} candidate cards; library={library.count(status=None)} total")
        return 0

    # gate: holdout-every candidate, promote only what wins
    candidates = library.candidates()
    if not candidates:
        print("no candidates; run `ballast skills distill` first")
        return 1
    verdicts = gate_library(candidates=candidates, library=library, baseline_arm=args.baseline_arm)
    print(json.dumps([v.as_dict() for v in verdicts], ensure_ascii=False, indent=2))
    counts = apply_verdicts(library, verdicts)
    print(f"GATE candidates={len(verdicts)} promoted={counts['promoted']} retired={counts['retired']}")
    # Nothing surviving the gate when cards were produced means retrieval or grading
    # silently stopped working, which is exactly what CI is here to catch.
    return 0 if counts["promoted"] else 1


__all__ = ["Pricing", "Skill", "main"]

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
