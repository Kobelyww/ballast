# Reliability measured over real HTTP

Runner, arms and graders are the production ones; the model is `scripts/mock_openai_server.py` on loopback, so this costs nothing and leaves no machine. 20 repeats × 7 tasks on the `ballast` arm.

| k | measured, variance injected | i.i.d. estimate | measured, deterministic provider |
|---:|---:|---:|---:|
| 1 | 57.1% | 70.7% | 100.0% |
| 2 | 28.6% | 50.0% | 100.0% |
| 3 | 28.6% | 35.4% | 100.0% |
| 5 | 0.0% | 17.7% | 100.0% |

With a deterministic provider every repeat is a copy, so measured pass^k is flat at 100.0% — the limitation the README states. Inject an early-give-up rate of 35% and the measurement decays on its own: 57.1% → 28.6% at k=3. The metric measures; the flat column was the surrogate, not the arithmetic.

Reproduce: `python scripts/measure_http_reliability.py --reps 20 --flaky-rate 0.35 --seed 3`
