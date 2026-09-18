_generated 2026-09-19T04:26:43 · provider `surrogate` · 648 runs over 12 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0899 | 42140 | 10133 | 13.1 | 0 | 0 | 3 |
| `ballast` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0698 | 34887 | 7770 | 12.3 | 6 | 6 | 3 |
| `bloated` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0784 | 39365 | 7770 | 13.3 | 12 | 6 | 3 |
| `defective` | 22.2% (12/54) | [13.2%, 34.9%] | 0.0307 | 16326 | 7793 | 8.3 | 6 | 3 | 87 |
| `hierarchical` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0703 | 35254 | 7842 | 12.2 | 6 | 6 | 3 |
| `no_budget` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0698 | 34887 | 7770 | 12.3 | 6 | 6 | 3 |
| `no_compaction` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0942 | 45572 | 10317 | 13.2 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0918 | 44556 | 10317 | 13.1 | 0 | 0 | 3 |
| `no_offload` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0671 | 33735 | 7607 | 12.1 | 0 | 3 | 3 |
| `noisy` | 72.2% (39/54) | [59.1%, 82.4%] | 0.0421 | 20847 | 8038 | 11.1 | 6 | 6 | 3 |
| `static_briefing` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0688 | 32963 | 7592 | 12.3 | 6 | 3 | 3 |
| `tight_budget` | 88.9% (48/54) | [77.8%, 94.8%] | 0.0468 | 24246 | 7770 | 10.7 | 6 | 9 | 3 |

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
| `naive` | 0.0899 | 100.0% | `no_compaction`, `no_context_control` |
| `ballast` | 0.0698 | 94.4% | `hierarchical`, `bloated` |
| `bloated` | 0.0784 | 94.4% | — |
| `defective` | 0.0307 | 22.2% | — |
| `hierarchical` | 0.0703 | 94.4% | `bloated` |
| `no_budget` | 0.0698 | 94.4% | `hierarchical`, `bloated` |
| `no_compaction` | 0.0942 | 100.0% | — |
| `no_context_control` | 0.0918 | 100.0% | `no_compaction` |
| `no_offload` | 0.0671 | 94.4% | `ballast`, `static_briefing`, `no_budget`, `hierarchical`, `bloated` |
| `noisy` | 0.0421 | 72.2% | — |
| `static_briefing` | 0.0688 | 94.4% | `ballast`, `no_budget`, `hierarchical`, `bloated` |
| `tight_budget` | 0.0468 | 88.9% | — |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.056 | 1/0 | 1.0000 | +0.48 | 1.29 [0.83, 1.59] |
| `bloated` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.12 [1.05, 1.41] |
| `defective` vs `ballast` | -0.722 | 0/13 | 0.0002 | -1.68 | 0.44 [0.22, 1.04] |
| `hierarchical` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.01 [0.99, 1.04] |
| `no_budget` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.00 [1.00, 1.00] |
| `no_compaction` vs `ballast` | +0.056 | 1/0 | 1.0000 | +0.48 | 1.35 [0.99, 1.62] |
| `no_context_control` vs `ballast` | +0.056 | 1/0 | 1.0000 | +0.48 | 1.32 [0.86, 1.61] |
| `no_offload` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.96 [0.86, 1.00] |
| `noisy` vs `ballast` | -0.222 | 0/4 | 0.1250 | -0.63 | 0.60 [0.25, 1.67] |
| `static_briefing` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.95, 1.01] |
| `tight_budget` vs `ballast` | -0.056 | 0/1 | 1.0000 | -0.20 | 0.67 [0.45, 1.00] |

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
| `noisy` | 249 | 0 | 3 | unknown_argument×105, missing_required_argument×96, loop_detected×48 |
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
