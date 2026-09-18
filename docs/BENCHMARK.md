# Benchmark

Reproduce with:

```bash
python -m ballast.cli eval \
  --arms naive,ballast,no_offload,no_compaction,no_context_control,static_briefing,tight_budget,no_budget,hierarchical,defective,noisy,bloated \
  --reps 3 --out bench/results/eval.md
```

648 runs on the current commit, offline surrogate, **zero API calls**. Read
`README.md#the-honest-limits` first: these characterise the harness, not a language
model, and the cost ratio between `ballast` and `naive` is inside its own confidence
interval. To read the long-horizon result, compare the `S19_batch_twelve` row across the
`ballast`, `no_compaction` and `no_offload` arms — that comparison is what localized the
bug described in the README.

---

_generated 2026-09-19T04:40:20 · provider `surrogate` · 648 runs over 12 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0917 | 43007 | 10203 | 13.1 | 0 | 0 | 3 |
| `ballast` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0816 | 40569 | 7775 | 13.3 | 6 | 6 | 3 |
| `bloated` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0884 | 44024 | 7775 | 14.2 | 9 | 6 | 3 |
| `defective` | 22.2% (12/54) | [13.2%, 34.9%] | 0.0370 | 19773 | 8279 | 8.9 | 9 | 12 | 87 |
| `hierarchical` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0833 | 41554 | 7847 | 13.3 | 6 | 6 | 3 |
| `no_budget` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0816 | 40569 | 7775 | 13.3 | 6 | 6 | 3 |
| `no_compaction` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0960 | 46446 | 10387 | 13.2 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0935 | 45423 | 10387 | 13.1 | 0 | 0 | 3 |
| `no_offload` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0797 | 39861 | 7585 | 13.2 | 0 | 3 | 3 |
| `noisy` | 72.2% (39/54) | [59.1%, 82.4%] | 0.0594 | 30468 | 8996 | 12.6 | 12 | 33 | 3 |
| `static_briefing` | 100.0% (54/54) | [93.4%, 100.0%] | 0.0805 | 38492 | 7586 | 13.3 | 6 | 6 | 3 |
| `tight_budget` | 94.4% (51/54) | [84.9%, 98.1%] | 0.0628 | 33084 | 7775 | 12.6 | 6 | 57 | 3 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `bloated` | 100.0% | 100.0% | 100.0% |
| `defective` | 22.2% | 4.9% | 1.1% |
| `hierarchical` | 100.0% | 100.0% | 100.0% |
| `no_budget` | 100.0% | 100.0% | 100.0% |
| `no_compaction` | 100.0% | 100.0% | 100.0% |
| `no_context_control` | 100.0% | 100.0% | 100.0% |
| `no_offload` | 100.0% | 100.0% | 100.0% |
| `noisy` | 72.2% | 52.2% | 37.7% |
| `static_briefing` | 100.0% | 100.0% | 100.0% |
| `tight_budget` | 94.4% | 89.2% | 84.2% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.0917 | 100.0% | `no_compaction`, `no_context_control` |
| `ballast` | 0.0816 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `hierarchical`, `bloated` |
| `bloated` | 0.0884 | 100.0% | `naive`, `no_compaction`, `no_context_control` |
| `defective` | 0.0370 | 22.2% | — |
| `hierarchical` | 0.0833 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `bloated` |
| `no_budget` | 0.0816 | 100.0% | `naive`, `no_compaction`, `no_context_control`, `hierarchical`, `bloated` |
| `no_compaction` | 0.0960 | 100.0% | — |
| `no_context_control` | 0.0935 | 100.0% | `no_compaction` |
| `no_offload` | 0.0797 | 100.0% | `naive`, `ballast`, `no_compaction`, `no_context_control`, `static_briefing`, `no_budget`, `hierarchical`, `bloated` |
| `noisy` | 0.0594 | 72.2% | — |
| `static_briefing` | 0.0805 | 100.0% | `naive`, `ballast`, `no_compaction`, `no_context_control`, `no_budget`, `hierarchical`, `bloated` |
| `tight_budget` | 0.0628 | 94.4% | — |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.12 [0.87, 1.25] |
| `bloated` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.08 [1.02, 1.40] |
| `defective` vs `ballast` | -0.778 | 0/14 | 0.0001 | -2.16 | 0.45 [0.18, 1.39] |
| `hierarchical` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.02 [1.02, 1.04] |
| `no_budget` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.00 [1.00, 1.00] |
| `no_compaction` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.18 [1.00, 1.27] |
| `no_context_control` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.15 [0.90, 1.26] |
| `no_offload` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.98 [0.90, 1.00] |
| `noisy` vs `ballast` | -0.278 | 0/5 | 0.0625 | -1.11 | 0.73 [0.22, 2.57] |
| `static_briefing` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.96, 1.00] |
| `tight_budget` vs `ballast` | -0.056 | 0/1 | 1.0000 | -0.48 | 0.77 [0.65, 1.00] |

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `ballast` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `bloated` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `defective` | 3 | 0 | 3 | upstream_timeout×3, loop_detected×3 |
| `hierarchical` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_budget` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_compaction` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_context_control` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `no_offload` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `noisy` | 279 | 0 | 3 | unknown_argument×114, missing_required_argument×102, loop_detected×63 |
| `static_briefing` | 36 | 0 | 6 | loop_detected×36, upstream_timeout×6 |
| `tight_budget` | 42 | 3 | 6 | loop_detected×42, upstream_timeout×6, budget_exhausted×3 |

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
| S18_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| S19_batch_twelve | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
