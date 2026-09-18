# Contributing

Everything runs offline, so a useful contribution needs no API key.

```bash
git clone https://github.com/Kobelyww/ballast && cd ballast
pip install -e ".[dev]"
python -m pytest tests -q                                  # no network, no keys
python -m ballast.cli eval --arms ballast,naive --reps 2    # ~20s
```

## Three ways to help

**Add a scenario** (`env/fixtures.py`). The suite's value is its traps: cases where the
correct action is *not* acting. Declare `expect` independently of the policy engine and
`tests/test_invariants.py` will fail if the two disagree, so a scenario cannot quietly
become "whatever the engine says".

**Add an arm** (`bench/runner.py`). A runtime choice worth pricing becomes a dict of
context/budget/runtime overrides. If it is a real mechanism, add the toggle to the
constructor first — a mechanism that cannot be turned off cannot be measured.

**Report a scoring bug.** The grader reads world state only. If you can construct a run
that passes a grade while the world is wrong, that is a bug in `bench/graders.py` or
`kernel/verify.py`, and it matters more than any agent failure.

## Rules

- **No runtime dependencies.** `pyproject.toml` lists zero. If you think you need one,
  the mechanism is probably ~40 stdlib lines and worth keeping legible.
- **Determinism is the contract.** New behaviour must be testable with `ScriptedModel`
  or the surrogate. Anything that makes CI require a key will be rejected.
- **Never trim the suite to raise a score.** Two long-horizon tasks (`S17`, `S18`) are
  known to fail and stay in. Fixing them is a contribution; hiding them is not.
- Claims in docs and READMEs need a row in `bench/results/` that produced them.

Tests for a module live beside its behaviour, not its filename: read
`tests/test_context_engine.py` for the compaction invariants and
`tests/test_invariants.py` for the whole-suite property checks.
