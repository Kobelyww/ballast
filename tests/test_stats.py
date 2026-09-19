"""The statistics that decide whether an agent actually got better."""

from __future__ import annotations

import math

import pytest

from ballast.bench.stats import (
    Interval,
    cohen_h,
    mcnemar_exact,
    multiple_comparisons,
    paired_ratio_ci,
    pass_k,
    pass_k_measured,
    success_rate_ci,
    wilson_interval,
)


class TestWilson:
    def test_empty_sample_is_maximally_uncertain(self) -> None:
        assert wilson_interval(0, 0) == (0.0, 1.0)

    def test_interval_brackets_the_point_estimate(self) -> None:
        low, high = wilson_interval(6, 8)
        assert 0.0 <= low < 0.75 < high <= 1.0

    def test_all_successes_still_leaves_room_for_doubt(self) -> None:
        low, high = wilson_interval(8, 8)
        assert high == 1.0 and low > 0.6

    def test_zero_successes_is_bounded_above(self) -> None:
        low, high = wilson_interval(0, 8)
        assert low == 0.0 and 0.0 < high < 0.5

    def test_n_is_visibly_weak_at_small_samples(self) -> None:
        small = wilson_interval(1, 2)
        large = wilson_interval(500, 1000)
        assert (small[1] - small[0]) > (large[1] - large[0])

    def test_bounds_are_clipped(self) -> None:
        for successes, n in [(0, 1), (1, 1), (0, 10_000), (10_000, 10_000)]:
            low, high = wilson_interval(successes, n)
            assert 0.0 <= low <= high <= 1.0

    def test_z_widens_the_interval(self) -> None:
        assert wilson_interval(6, 8, z=2.576)[0] < wilson_interval(6, 8, z=1.0)[0]

    def test_success_rate_ci_wraps_it(self) -> None:
        interval = success_rate_ci(6, 8)
        assert interval.point == 0.75
        assert interval.low <= 0.75 <= interval.high
        assert interval.as_dict()["point"] == 0.75


class TestPassK:
    def test_single_draw_is_the_success_rate(self) -> None:
        assert pass_k(6, 8) == 0.75

    def test_reliability_decays_with_repetitions(self) -> None:
        assert pass_k(6, 8, k=2) == pytest.approx(0.75**2)
        assert pass_k(6, 8, k=3) < pass_k(6, 8, k=2) < pass_k(6, 8, k=1)

    def test_a_fully_reliable_arm_stays_reliable(self) -> None:
        assert pass_k(8, 8, k=5) == 1.0

    def test_no_data_is_no_claim(self) -> None:
        assert pass_k(0, 0, k=3) == 0.0


class TestMcNemar:
    def test_no_discordance_is_no_evidence(self) -> None:
        assert mcnemar_exact([(1, 1), (0, 0)]) == (1.0, 0, 0)
        assert mcnemar_exact([]) == (1.0, 0, 0)

    def test_only_discordant_pairs_count(self) -> None:
        pairs = [(1, 1), (0, 0), (1, 1), (0, 1), (0, 1)]
        p, b, c = mcnemar_exact(pairs)
        assert (b, c) == (2, 0)
        assert p == pytest.approx(2 * (1 / 2**2))

    def test_direction_of_the_difference(self) -> None:
        treatment_wins = [(0, 1)] * 6 + [(1, 0)] * 1
        control_wins = [(1, 0)] * 6 + [(0, 1)] * 1
        assert mcnemar_exact(treatment_wins)[1] == 6 and mcnemar_exact(treatment_wins)[2] == 1
        assert mcnemar_exact(control_wins)[1] == 1 and mcnemar_exact(control_wins)[2] == 6
        assert mcnemar_exact(treatment_wins)[0] == mcnemar_exact(control_wins)[0]  # two-sided

    def test_a_balanced_split_is_not_significant(self) -> None:
        p, b, c = mcnemar_exact([(0, 1)] * 4 + [(1, 0)] * 4)
        assert (b, c) == (4, 4) and p == pytest.approx(1.0)

    def test_many_discordant_pairs_in_one_direction_is_significant(self) -> None:
        p, b, c = mcnemar_exact([(0, 1)] * 12 + [(1, 0)] * 1)
        assert p < 0.01

    def test_p_value_is_capped_at_one(self) -> None:
        for n in range(1, 12):
            p, _, _ = mcnemar_exact([(0, 1)] * n)
            assert 0.0 <= p <= 1.0


class TestPairedRatio:
    def test_identical_costs_centre_on_one(self) -> None:
        costs = [0.4, 0.5, 0.6, 0.3]
        interval = paired_ratio_ci(costs, costs)
        assert interval.point == pytest.approx(1.0)
        assert interval.low == pytest.approx(1.0) and interval.high == pytest.approx(1.0)

    def test_a_uniform_saving_moves_the_point(self) -> None:
        base = [1.0, 2.0, 3.0, 4.0]
        interval = paired_ratio_ci(base, [b * 0.5 for b in base])
        assert interval.point == pytest.approx(0.5)
        assert interval.crosses(0.5) and not interval.crosses(1.0)

    def test_a_single_cheap_run_cannot_invent_a_saving(self) -> None:
        # One task out of ten gets much cheaper: the point estimate says 9x, but the
        # bootstrap over tasks refuses to let anyone claim the saving is settled.
        base = [1.0] * 9 + [100.0]
        treat = [1.0] * 9 + [1.0]
        interval = paired_ratio_ci(base, treat)
        assert interval.point == pytest.approx(10.0 / 109.0, abs=1e-3)
        assert interval.low == pytest.approx(0.0326, abs=0.01) and interval.high == pytest.approx(1.0)
        # "no change at all" sits inside the interval, so the saving is unproven even
        # though the point estimate looks like a 91% cut.
        assert interval.crosses(1.0)

    def test_deterministic_given_a_seed(self) -> None:
        a = paired_ratio_ci([1, 2, 3, 4, 5], [2, 3, 4, 5, 6], seed=42)
        b = paired_ratio_ci([1, 2, 3, 4, 5], [2, 3, 4, 5, 6], seed=42)
        assert a == b
        assert a == paired_ratio_ci([1, 2, 3, 4, 5], [2, 3, 4, 5, 6], seed=42, iters=2000)

    def test_a_different_seed_shuffles_the_bounds(self) -> None:
        base, treat = [1.0, 3.0, 0.4, 9.0, 2.0, 5.0], [2.0, 1.0, 0.9, 4.0, 6.0, 1.0]
        first = paired_ratio_ci(base, treat, seed=1)
        second = paired_ratio_ci(base, treat, seed=999)
        assert (first.low, first.high) != (second.low, second.high)

    def test_confidence_level_widens_the_interval(self) -> None:
        base, treat = [1.0, 2.0, 3.0, 1.5, 0.5], [2.0, 1.0, 4.0, 1.0, 1.0]
        wide = paired_ratio_ci(base, treat, confidence=0.99)
        narrow = paired_ratio_ci(base, treat, confidence=0.5)
        assert wide.high - wide.low >= narrow.high - narrow.low

    def test_zero_baseline_is_not_a_division_by_zero(self) -> None:
        assert paired_ratio_ci([0.0, 0.0], [0.0, 0.0]).point == 1.0
        inf = paired_ratio_ci([0.0, 0.0], [0.0, 1.0])
        assert math.isinf(inf.point) and inf.point > 0

    @pytest.mark.parametrize(
        "baseline,treatment",
        [([], []), ([1.0], []), ([], [1.0]), ([1.0, 2.0], [1.0])],
    )
    def test_mismatched_samples_are_rejected(self, baseline: list[float], treatment: list[float]) -> None:
        with pytest.raises(ValueError, match="equal length and non-empty"):
            paired_ratio_ci(baseline, treatment)


class TestEffectSize:
    def test_zero_for_no_difference(self) -> None:
        assert cohen_h(0.5, 0.5) == 0.0

    def test_sign_follows_the_direction(self) -> None:
        assert cohen_h(0.25, 0.75) > 0 > cohen_h(0.75, 0.25)

    def test_a_small_absolute_gap_at_the_tails_is_a_big_effect(self) -> None:
        tail = cohen_h(0.0, 0.125)
        middle = cohen_h(0.5, 0.625)
        assert abs(tail) > abs(middle)

    def test_inputs_are_clipped(self) -> None:
        assert cohen_h(-1.0, 2.0) == cohen_h(0.0, 1.0)

    def test_1_vs_2_in_eight_is_not_an_effect(self) -> None:
        assert abs(cohen_h(1 / 8, 2 / 8)) < 0.4


class TestMultipleComparisons:
    def test_empty_input(self) -> None:
        assert multiple_comparisons([]) == []

    def test_single_hypothesis_is_unchanged(self) -> None:
        assert multiple_comparisons([0.03]) == [0.03]

    def test_adjustment_never_lowers_a_p_value(self) -> None:
        raw = [0.001, 0.02, 0.04, 0.3, 0.9]
        adjusted = multiple_comparisons(raw)
        assert all(a >= r for a, r in zip(adjusted, raw))
        assert all(a <= 1.0 for a in adjusted)

    def test_order_is_preserved(self) -> None:
        raw = [0.04, 0.001, 0.3, 0.02]
        adjusted = multiple_comparisons(raw)
        assert sorted(range(len(raw)), key=lambda i: raw[i]) == sorted(range(len(raw)), key=lambda i: adjusted[i])

    def test_bh_kills_a_mined_significance(self) -> None:
        # Twelve ablations, one "significant" at 0.04: under BH it no longer clears 0.05.
        raw = [0.04] + [0.5] * 11
        adjusted = multiple_comparisons(raw)
        assert adjusted[0] > 0.05

    def test_a_clear_win_survives_twelve_comparisons(self) -> None:
        raw = [1e-5] + [0.5] * 11
        adjusted = multiple_comparisons(raw)
        assert adjusted[0] < 0.05

    def test_known_bh_example(self) -> None:
        # Fisher's tea-tasting style table: eight raw p-values, three of them under 0.05.
        raw = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
        adjusted = multiple_comparisons(raw)
        assert adjusted == pytest.approx([0.008, 0.032, 0.0672, 0.0672, 0.0672, 0.08, 0.08457, 0.205], abs=1e-4)
        # BH keeps the two clear wins and drops the three borderline ones under 0.05.
        assert adjusted[0] < 0.05 and adjusted[1] < 0.05
        assert all(a > 0.05 for a in adjusted[2:5])
        pairs = sorted(zip(raw, adjusted))
        assert [a for _, a in pairs] == sorted(a for _, a in pairs)


class TestInterval:
    def test_crossing_is_inclusive(self) -> None:
        interval = Interval(point=1.02, low=0.9, high=1.1)
        assert interval.crosses(1.0) and interval.crosses(0.9) and interval.crosses(1.1)
        assert not interval.crosses(1.2) and not interval.crosses(0.5)

    def test_dict_rounding_is_display_facing(self) -> None:
        assert Interval(1.23456789, 0.987654321, 1.5).as_dict() == {"point": 1.2346, "low": 0.9877, "high": 1.5}


def test_measured_pass_k_refuses_to_invent_a_decay() -> None:
    """A deterministic agent repeats itself, so repetition proves nothing.

    `pass_k` assumes independent draws and is a *model*; `pass_k_measured` counts tasks
    that pass all of their first k draws and is a *measurement*. Under this repo's offline
    surrogate they disagree by construction, and the report prints both because hiding that
    is how a fabricated reliability curve ended up in a README once.
    """
    draws = [[True] * 5, [False] * 5, [True] * 5, [False] * 5]
    assert pass_k_measured(draws, 1) == pytest.approx(0.5)
    assert pass_k_measured(draws, 3) == pytest.approx(0.5)  # no decay: the draws are copies
    assert pass_k(2, 4, 3) == pytest.approx(0.5**3)  # the same data, modelled: a curve appears
    assert pass_k_measured([[True, False], [True, True]], 2) == pytest.approx(0.5)
    assert pass_k_measured([[True]], 2) == 0.0  # a task with too few draws cannot pass k of them
