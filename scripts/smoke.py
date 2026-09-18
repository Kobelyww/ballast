import sys
sys.path.insert(0, "src")
from ballast.env.fixtures import scenarios
from ballast.bench.runner import resolve_arm, run_scenario

arms = sys.argv[1:] or ["ballast"]
fails = 0
for arm_name in arms:
    arm = resolve_arm(arm_name)
    print(f"===== ARM {arm_name}")
    for s in scenarios():
        try:
            row, g, ex = run_scenario(s, arm)
        except Exception as exc:
            print(f"  {s.id:32s} EXC  {type(exc).__name__}: {exc}")
            fails += 1
            continue
        mark = "ok  " if row.ok else "FAIL"
        extra = "" if row.ok else " :: " + " | ".join(row.failed_checks)[:150]
        err = (" ERR:" + ex["result"].error.splitlines()[0][:90]) if ex["result"].error else ""
        print(f"  {s.id:32s} {mark} {row.status:14s} cost={row.cost:.4f} tok={row.prompt_tokens_total:6d} calls={row.calls:2d} gr={row.guardrail_blocks} off={row.offloads} cmp={row.compactions}{err}{extra}")
        if not row.ok:
            fails += 1
print(f"\n{fails} failing")
