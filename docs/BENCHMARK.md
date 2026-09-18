# Benchmark

Reproduce with:

```bash
python -m ballast.cli eval \
  --arms naive,ballast,no_offload,no_compaction,no_context_control,tight_budget,no_budget,hierarchical,defective,noisy,bloated \
  --reps 3 --out bench/results/eval.md
```

The numbers below were produced by that command on the current commit, with the
offline surrogate policy and **zero API calls**. Read `README.md#the-honest-limits`
before quoting any of them: they measure the harness, not any language model.

---

_generated 2026-09-19T03:51:58 · provider `surrogate` · 561 runs over 11 arms_

## Headline

| arm | success | 95% CI | mean cost | mean prompt tok | peak ctx | calls | offloads | compactions | guardrails |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| `naive` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0389 | 19214 | 6405 | 9.9 | 0 | 0 | 3 |
| `ballast` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0431 | 22266 | 7770 | 10.1 | 6 | 3 | 3 |
| `bloated` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0503 | 25914 | 7770 | 11.0 | 9 | 3 | 3 |
| `defective` | 23.5% (12/51) | [14.0%, 36.8%] | 0.0314 | 16606 | 7793 | 8.5 | 6 | 3 | 81 |
| `hierarchical` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0443 | 22918 | 7842 | 10.1 | 6 | 3 | 3 |
| `no_budget` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0431 | 22266 | 7770 | 10.1 | 6 | 3 | 3 |
| `no_compaction` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0428 | 22122 | 7797 | 10.0 | 6 | 0 | 3 |
| `no_context_control` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0402 | 21046 | 6610 | 9.9 | 0 | 0 | 3 |
| `no_offload` | 100.0% (51/51) | [93.0%, 100.0%] | 0.0402 | 21046 | 6610 | 9.9 | 0 | 0 | 3 |
| `noisy` | 76.5% (39/51) | [63.2%, 86.0%] | 0.0539 | 26721 | 8038 | 13.1 | 6 | 6 | 3 |
| `tight_budget` | 88.2% (45/51) | [76.6%, 94.5%] | 0.0270 | 14035 | 6669 | 8.5 | 6 | 6 | 3 |

## Reliability (pass^k on repeat draws)

| arm | pass^1 | pass^2 | pass^3 |
|---|---:|---:|---:|
| `naive` | 100.0% | 100.0% | 100.0% |
| `ballast` | 100.0% | 100.0% | 100.0% |
| `bloated` | 100.0% | 100.0% | 100.0% |
| `defective` | 23.5% | 5.5% | 1.3% |
| `hierarchical` | 100.0% | 100.0% | 100.0% |
| `no_budget` | 100.0% | 100.0% | 100.0% |
| `no_compaction` | 100.0% | 100.0% | 100.0% |
| `no_context_control` | 100.0% | 100.0% | 100.0% |
| `no_offload` | 100.0% | 100.0% | 100.0% |
| `noisy` | 76.5% | 58.5% | 44.7% |
| `tight_budget` | 88.2% | 77.9% | 68.7% |

## Cost / quality frontier

| arm | mean cost | success | dominates |
|---|---:|---:|---|
| `naive` | 0.0389 | 100.0% | `ballast`, `no_offload`, `no_compaction`, `no_context_control`, `no_budget`, `hierarchical`, `noisy`, `bloated` |
| `ballast` | 0.0431 | 100.0% | `hierarchical`, `noisy`, `bloated` |
| `bloated` | 0.0503 | 100.0% | `noisy` |
| `defective` | 0.0314 | 23.5% | — |
| `hierarchical` | 0.0443 | 100.0% | `noisy`, `bloated` |
| `no_budget` | 0.0431 | 100.0% | `hierarchical`, `noisy`, `bloated` |
| `no_compaction` | 0.0428 | 100.0% | `ballast`, `no_budget`, `hierarchical`, `noisy`, `bloated` |
| `no_context_control` | 0.0402 | 100.0% | `ballast`, `no_compaction`, `no_budget`, `hierarchical`, `noisy`, `bloated` |
| `no_offload` | 0.0402 | 100.0% | `ballast`, `no_compaction`, `no_budget`, `hierarchical`, `noisy`, `bloated` |
| `noisy` | 0.0539 | 76.5% | — |
| `tight_budget` | 0.0270 | 88.2% | `defective`, `noisy` |

## Paired comparisons vs reference arm

Paired on identical scenarios against `ballast` (McNemar exact on discordant pairs):

| comparison | Δ success | discordant b/c | p (exact) | effect h | cost ratio [95% CI] |
|---|---:|---|---:|---:|---|
| `naive` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.90 [0.81, 0.97] |
| `bloated` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.17 [1.04, 1.45] |
| `defective` vs `ballast` | -0.765 | 0/13 | 0.0002 | -2.13 | 0.73 [0.44, 1.02] |
| `hierarchical` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.03 [1.02, 1.04] |
| `no_budget` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 1.00 [1.00, 1.00] |
| `no_compaction` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.99 [0.98, 1.00] |
| `no_context_control` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.93 [0.84, 1.00] |
| `no_offload` vs `ballast` | +0.000 | 0/0 | 1.0000 | +0.00 | 0.93 [0.84, 1.00] |
| `noisy` vs `ballast` | -0.235 | 0/4 | 0.1250 | -1.01 | 1.25 [0.68, 1.97] |
| `tight_budget` vs `ballast` | -0.118 | 0/2 | 0.5000 | -0.70 | 0.63 [0.40, 1.00] |

## Where failures come from

| arm | agent faults | runtime faults | environment faults | top codes |
|---|---:|---:|---:|---|
| `naive` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `ballast` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `bloated` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `defective` | 0 | 0 | 3 | upstream_timeout×3 |
| `hierarchical` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `no_budget` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `no_compaction` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `no_context_control` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `no_offload` | 18 | 0 | 6 | loop_detected×18, upstream_timeout×6 |
| `noisy` | 303 | 0 | 3 | unknown_argument×126, missing_required_argument×117, loop_detected×60 |
| `tight_budget` | 3 | 6 | 6 | upstream_timeout×6, budget_exhausted×6, loop_detected×3 |

## Per-scenario outcome

| scenario | `naive` | `ballast` | `bloated` | `defective` | `hierarchical` | `no_budget` | `no_compaction` | `no_context_control` | `no_offload` | `noisy` | `tight_budget` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S01_inwindow_refund | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S02_window_closed | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S03_quality_with_shipping | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S04_missing_item | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S05_non_returnable | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S06_high_risk | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S07_approval_line | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S08_address_change | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S09_address_locked | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S10_phone_lookup | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| S12_coupon_within_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S13_coupon_over_cap | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S14_flaky_upstream | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| S15_context_bloat | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| S16_queue_dig | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| S17_fat_order | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ |
| S18_batch_queue | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
