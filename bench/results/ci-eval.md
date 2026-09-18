_generated 2026-09-19T03:46:33 · provider `surrogate` · 102 runs over 3 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (34/34) | [89.8%, 100.0%] | 0.0389 | 19214 | 6405 | 9.9 | 0 | 0 | 2 |
| `ballast` | 88.2% (30/34) | [73.4%, 95.3%] | 0.0459 | 24989 | 8025 | 10.9 | 40 | 10 | 2 |
| `defective` | 23.5% (8/34) | [12.4%, 40.0%] | 0.0386 | 21105 | 8025 | 9.9 | 40 | 8 | 54 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 88.2% | 77.9% | 68.7% |
| `defective` | 23.5% | 5.5% | 1.3% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.0389 | 100.0% | `ballast` |
| `ballast` | 0.0459 | 88.2% | — |
| `defective` | 0.0386 | 23.5% | — |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.118 | 2/0 | 0.5000 | +0.70 | 0.85 [0.68, 1.04] |
| `defective` vs `ballast` | -0.647 | 0/11 | 0.0010 | -1.43 | 0.84 [0.62, 1.02] |

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 12 | 0 | 4 | loop_detected×12, upstream_timeout×4 |
| `ballast` | 6 | 0 | 4 | loop_detected×6, upstream_timeout×4 |
| `defective` | 4 | 0 | 2 | loop_detected×4, upstream_timeout×2 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `defective` |
|---|---|---|---|
| S01_inwindow_refund | ✅ | ✅ | ❌ |
| S02_window_closed | ✅ | ✅ | ❌ |
| S03_quality_with_shipping | ✅ | ✅ | ❌ |
| S04_missing_item | ✅ | ✅ | ❌ |
| S05_non_returnable | ✅ | ✅ | ❌ |
| S06_high_risk | ✅ | ✅ | ❌ |
| S07_approval_line | ✅ | ✅ | ❌ |
| S08_address_change | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ❌ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ❌ |
| S15_context_bloat | ✅ | ✅ | ❌ |
| S16_queue_dig | ✅ | ✅ | ❌ |
| S17_fat_order | ✅ | ❌ | ❌ |
| S18_batch_queue | ✅ | ❌ | ❌ |
