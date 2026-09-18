_generated 2026-09-19T04:09:53 · provider `surrogate` · 648 runs over 12 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0917 | 42995 | 10133 | 13.5 | 0 | 0 | 3 |
| `ballast` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0716 | 35823 | 7770 | 12.7 | 6 | 6 | 3 |
| `bloated` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0804 | 40347 | 7770 | 13.7 | 12 | 6 | 3 |
| `defective` | 22.2% (12/54) | [13.2%, 34.9%] | 0.0316 | 16780 | 7793 | 8.6 | 6 | 3 | 87 |
| `hierarchical` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0722 | 36222 | 7842 | 12.7 | 6 | 6 | 3 |
| `no_budget` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0716 | 35823 | 7770 | 12.7 | 6 | 6 | 3 |
| `no_compaction` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0961 | 46508 | 10317 | 13.6 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0936 | 45492 | 10317 | 13.5 | 0 | 0 | 3 |
| `no_offload` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0689 | 34671 | 7607 | 12.6 | 0 | 3 | 3 |
| `noisy` | 72.2% (39/54) | [59.1%, 82.4%] | 0.0511 | 25340 | 8038 | 12.4 | 6 | 6 | 3 |
| `static_briefing` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0707 | 33817 | 7592 | 12.7 | 6 | 3 | 3 |
| `tight_budget` | 88.9% (48/54) | [77.8%, 94.8%] | 0.0487 | 25182 | 7770 | 11.2 | 6 | 9 | 3 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 94.4% | 89.2% | 84.2% |
| `bloated` | 94.4% | 89.2% | 84.2% |
| `defective` | 22.2% | 4.9% | 1.1% |
| `hierarchical` | 94.4% | 89.2% | 84.2% |
| `no_budget` | 94.4% | 89.2% | 84.2% |
| `no_compaction` | 100.0% | 100.0% | 100.0% |
| `no_context_control` | 100.0% | 100.0% | 100.0% |
| `no_offload` | 94.4% | 89.2% | 84.2% |
| `noisy` | 72.2% | 52.2% | 37.7% |
| `static_briefing` | 94.4% | 89.2% | 84.2% |
| `tight_budget` | 88.9% | 79.0% | 70.2% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.0917 | 100.0% | `no_compaction`, `no_context_control` |
| `ballast` | 0.0716 | 94.4% | `hierarchical`, `bloated` |
| `bloated` | 0.0804 | 94.4% | — |
| `defective` | 0.0316 | 22.2% | — |
| `hierarchical` | 0.0722 | 94.4% | `bloated` |
| `no_budget` | 0.0716 | 94.4% | `hierarchical`, `bloated` |
| `no_compaction` | 0.0961 | 100.0% | — |
| `no_context_control` | 0.0936 | 100.0% | `no_compaction` |
| `no_offload` | 0.0689 | 94.4% | `ballast`, `static_briefing`, `no_budget`, `hierarchical`, `bloated` |
| `noisy` | 0.0511 | 72.2% | — |
| `static_briefing` | 0.0707 | 94.4% | `ballast`, `no_budget`, `hierarchical`, `bloated` |
| `tight_budget` | 0.0487 | 88.9% | `noisy` |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.056 | 1/0 | 1.0000 | +0.48 | 1.28 [0.84, 1.58] |
| `bloated` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.12 [1.05, 1.38] |
| `defective` vs `ballast` | -0.722 | 0/13 | 0.0002 | -1.68 | 0.44 [0.22, 1.00] |
| `hierarchical` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.01 [0.99, 1.04] |
| `no_budget` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.00 [1.00, 1.00] |
| `no_compaction` vs `ballast` | +0.056 | 1/0 | 1.0000 | +0.48 | 1.34 [0.99, 1.61] |
| `no_context_control` vs `ballast` | +0.056 | 1/0 | 1.0000 | +0.48 | 1.31 [0.87, 1.60] |
| `no_offload` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.96 [0.87, 1.00] |
| `noisy` vs `ballast` | -0.222 | 0/4 | 0.1250 | -0.63 | 0.71 [0.29, 1.92] |
| `static_briefing` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.95, 1.00] |
| `tight_budget` vs `ballast` | -0.056 | 0/1 | 1.0000 | -0.20 | 0.68 [0.46, 1.00] |

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `ballast` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `bloated` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `defective` | 0 | 0 | 3 | upstream_timeout×3 |
| `hierarchical` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_budget` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_compaction` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_context_control` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_offload` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `noisy` | 303 | 0 | 3 | unknown_argument×126, missing_required_argument×117, loop_detected×60 |
| `static_briefing` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `tight_budget` | 30 | 0 | 6 | loop_detected×30, upstream_timeout×6 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `bloated` | `defective` | `hierarchical` | `no_budget` | `no_compaction` | `no_context_control` | `no_offload` | `noisy` | `static_briefing` | `tight_budget` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S01_inwindow_refund | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S02_window_closed | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S04_missing_item | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S05_non_returnable | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S06_high_risk | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S07_approval_line | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S15_context_bloat | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S16_queue_dig | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S17_fat_order | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S18_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| S19_batch_twelve | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
