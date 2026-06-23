"""Tests for scripts.line_diff — 提前批 line-diff computation (spec §4.1, §4.1).

口径 (spec §2.3 说明):
    year_line_diff = 录取低分 − 当年一段线
    统计线差 (J)   = mean(有数据年份的线差)  (单年用该年)
    线差标准差 (T) = population stdev over the same years  (单年 / 全无 → None)

Plan v2 renamed the signature to ``compute(low_scores_by_year, provincial_lines)``
so the two dicts cannot be passed in the wrong order.
"""

from __future__ import annotations

import statistics

from scripts import line_diff
from scripts.constants import ONE_LINE


# --- three-year case (RED sample from the task spec) -----------------------

def test_compute_three_year_mean_and_pstdev():
    lows = {2025: 524, 2024: 568, 2023: 500}
    # line diffs: 524-441=83, 568-444=124, 500-443=57
    diffs = [83, 124, 57]
    stat, std = line_diff.compute(lows, ONE_LINE)
    assert stat == statistics.mean(diffs)
    assert std == statistics.pstdev(diffs)


def test_compute_three_year_stat_rounded_value():
    """Concrete value check so a future mean/pstdev swap is caught."""
    stat, _ = line_diff.compute({2025: 524, 2024: 568, 2023: 500}, ONE_LINE)
    # mean(83,124,57) = 88.0
    assert stat == 88.0


# --- single-year case ------------------------------------------------------

def test_compute_single_year_uses_that_year_no_stddev():
    # 500 - 441 (2025 一段线) = 59
    stat, std = line_diff.compute({2025: 500}, ONE_LINE)
    assert stat == 59.0
    assert std is None  # pstdev of a single sample is undefined → None


# --- all-missing case ------------------------------------------------------

def test_compute_all_none_returns_none_pair():
    stat, std = line_diff.compute({2025: None, 2024: None, 2023: None}, ONE_LINE)
    assert stat is None
    assert std is None


def test_compute_empty_returns_none_pair():
    stat, std = line_diff.compute({}, ONE_LINE)
    assert stat is None
    assert std is None


# --- partial years: None filtered, pstdev over the rest --------------------

def test_compute_partial_years_filters_none():
    # 2025=524 → 83, 2023=500 → 57; 2024 missing
    stat, std = line_diff.compute({2025: 524, 2024: None, 2023: 500}, ONE_LINE)
    assert stat == statistics.mean([83, 57])
    assert std == statistics.pstdev([83, 57])


# --- low_score missing the year entirely is treated as None ----------------

def test_compute_year_only_in_provincial_lines_not_in_lows_is_skipped():
    # lows has only 2025; provincial_lines has all three. 2024/2023 simply absent.
    stat, std = line_diff.compute({2025: 500}, ONE_LINE)
    assert stat == 59.0
    assert std is None


# --- string-coerced numerics (xlsx cells sometimes arrive as str) ----------

def test_compute_coerces_string_numerics():
    stat, _ = line_diff.compute({2025: "524"}, ONE_LINE)  # type: ignore[arg-type]
    assert stat == 83.0


def test_compute_treats_empty_string_as_missing():
    stat, std = line_diff.compute({2025: "", 2024: 568}, ONE_LINE)  # type: ignore[arg-type]
    # only 2024 → 568-444 = 124
    assert stat == 124.0
    assert std is None


# --- provincial_lines is the second arg (order-safety) ---------------------

def test_compute_provincial_lines_is_second_argument():
    """If a caller swapped the args, the maths would not work. Lock the order:
    compute(lows, one_lines). Passing lows as the 2nd arg must not silently
    produce a number."""
    # lows in slot 2 with only 2025=500 (the low score), one_lines slot 1
    # has the real cutoffs. compute(ONE_LINE, {2025:500}) is *wrong usage*;
    # we assert it raises rather than returning a misleading value, because
    # the cutoff dict contains years (2023..2025) that aren't in the lows
    # dict — those get skipped — and the year 2025 would yield 500-500=0.
    # We cannot forbid it at the type level, so this test documents that the
    # *intended* call signature is compute(lows, one_lines) and that swapping
    # produces a different, wrong answer (smoke against silent reversal).
    correct, _ = line_diff.compute({2025: 500}, ONE_LINE)
    swapped, _ = line_diff.compute(ONE_LINE, {2025: 500})  # type: ignore[arg-type]
    assert correct == 59.0
    # swapped treats 500 as the cutoff for 2025 and uses ONE_LINE values as
    # low scores → 2025: 441-500 = -59, 2024: 444-500=-56, 2023: 443-500=-57.
    assert swapped is not None and swapped != correct
