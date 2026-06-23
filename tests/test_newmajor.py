"""Pure-function TDD for Stage 3 新增专业 graded-fallback estimation.

Spec §6 Stage 3 新增专业:
    退化0: 同校 + 选科集合包含 的历史专业 `统计线差` 均值
    退化1: 同校无同选科 → 同校全部有统计线差者的均值
    退化2: 整校无历史 → value=None, 无法估算

Plan v2 binding (overrides the bare-tuple signature in the older plan):
    estimate(...) -> EstimateResult{value, level, log, n}

选科集合包含判定 (grilling Q3: 37.5% of 近三年 rows are multi-valued across
years, joined by ` | `):
    近三年 subject `物理 | 物理和化学` splits on ` | ` into year variants;
    any variant (itself split on 「和」 into subject atoms) ⊇ 新专业选科
    (split on 「和」) ⇒ compatible.
"""

from __future__ import annotations

from scripts.models import DaglubenRow, EstimateResult, HistoryRow
from scripts.stage3_newmajor import estimate, select_kit_compatible


# ---------------------------------------------------------------------------
# select_kit_compatible — pure-function cases (Plan v2 binding spec)
# ---------------------------------------------------------------------------


def test_select_kit_compatible_year_variant_overlap_is_true() -> None:
    # 近三年 multi-year `物理 | 物理和化学`; the 物理和化学 year-variant ⊇ the
    # new major's 物理和化学 requirement.
    assert select_kit_compatible("物理和化学", "物理 | 物理和化学") is True


def test_select_kit_compatible_disjoint_subject_is_false() -> None:
    # 历史行是历史选科轨道，与物理和化学 无交集 → 不包含。
    assert select_kit_compatible("物理和化学", "历史") is False


def test_select_kit_compatible_superset_history_is_true() -> None:
    # 历史 variant 物理和化学和生物 ⊇ 物理和化学 → True.
    assert select_kit_compatible("物理和化学", "物理和化学和生物") is True


def test_select_kit_compatible_partial_history_is_false() -> None:
    # 历史只要求物理，新专业要求物理和化学 — 历史 variant 不 ⊇ 新专业 → False.
    assert select_kit_compatible("物理和化学", "物理") is False


def test_select_kit_compatible_empty_new_subject_matches_anything() -> None:
    # 新专业选科为空（不限）→ 空集 ⊆ 任意集合 → True.
    assert select_kit_compatible("", "物理") is True


def test_select_kit_compatible_single_year_history_no_pipe() -> None:
    # 历史行无 ` | `（单一年份口径），直接按「和」拆分比较。
    assert select_kit_compatible("物理", "物理") is True
    assert select_kit_compatible("物理和化学", "物理和化学") is True


# ---------------------------------------------------------------------------
# estimate — graded fallback TDD (three-level small-sample fixtures)
# ---------------------------------------------------------------------------


def _dagluben(school: str, subject: str) -> DaglubenRow:
    return DaglubenRow(school=school, subject=subject, major="新专业X")


def _hist(
    school: str, subject: str, j: float | None, *, cat: str = ""
) -> HistoryRow:
    return HistoryRow(
        school=school,
        school_cat=cat,
        subject=subject,
        J=j,
        major="历史专业",
    )


def test_estimate_level0_same_school_same_subject_average() -> None:
    # 退化0: 同校 + 同选科集合包含 → J 均值。
    new_major = _dagluben("示例大学", "物理和化学")
    history = [
        _hist("示例大学", "物理 | 物理和化学", 80.0),  # compatible
        _hist("示例大学", "物理和化学和生物", 100.0),  # compatible (superset)
        _hist("示例大学", "历史", 50.0),               # not compatible
        _hist("其他大学", "物理和化学", 999.0),        # other school
        _hist("示例大学", "物理 | 物理和化学", None),  # compatible but no J
    ]
    result = estimate(new_major, history)

    assert result["level"] == 0
    assert result["value"] == 90.0  # mean(80, 100)
    assert result["n"] == 2
    assert "同校同选科" in result["log"]
    assert "90" in result["log"]


def test_estimate_level1_no_same_subject_falls_back_to_whole_school() -> None:
    # 退化1: 同校有历史但无同选科 → 同校全部有 J 者均值。
    new_major = _dagluben("示例大学", "物理和化学")
    history = [
        _hist("示例大学", "历史", 50.0),
        _hist("示例大学", "政治", 70.0),
        _hist("示例大学", "历史", None),  # no J, excluded
        _hist("其他大学", "物理和化学", 999.0),
    ]
    result = estimate(new_major, history)

    assert result["level"] == 1
    assert result["value"] == 60.0  # mean(50, 70)
    assert result["n"] == 2
    assert "同校全专业" in result["log"]
    assert "60" in result["log"]


def test_estimate_level2_school_has_no_history() -> None:
    # 退化2: 整校无历史 → value=None, level=2.
    new_major = _dagluben("全新大学", "物理和化学")
    history = [
        _hist("其他大学", "物理和化学", 80.0),
    ]
    result = estimate(new_major, history)

    assert result["level"] == 2
    assert result["value"] is None
    assert result["n"] == 0
    assert "无法估算" in result["log"]


def test_estimate_level2_empty_history_list() -> None:
    new_major = _dagluben("全新大学", "物理和化学")
    result = estimate(new_major, [])
    assert result["level"] == 2
    assert result["value"] is None


def test_estimate_level0_skips_history_rows_without_j() -> None:
    # 同选科的历史行全无 J → level0 退化到 level1（同校全专业），
    # 但若同校也无任何 J 则进一步退化到 level2.
    new_major = _dagluben("示例大学", "物理和化学")
    # 同选科兼容但 J=None；同校另一专业有 J → level1.
    history = [
        _hist("示例大学", "物理和化学", None),
        _hist("示例大学", "历史", 70.0),
    ]
    result = estimate(new_major, history)
    assert result["level"] == 1
    assert result["value"] == 70.0
    assert result["n"] == 1


def test_estimate_level0_prefers_level0_when_both_available() -> None:
    # 同选科与同校全专业都有 → 取 level0（更精准口径）。
    new_major = _dagluben("示例大学", "物理和化学")
    history = [
        _hist("示例大学", "物理和化学", 80.0),  # level0 candidate
        _hist("示例大学", "历史", 200.0),        # would skew level1
    ]
    result = estimate(new_major, history)
    assert result["level"] == 0
    assert result["value"] == 80.0
    assert result["n"] == 1


def test_estimate_returns_typed_dict_with_all_fields() -> None:
    new_major = _dagluben("示例大学", "物理和化学")
    history = [_hist("示例大学", "物理和化学", 80.0)]
    result: EstimateResult = estimate(new_major, history)
    # TypedDict total=False allows .get, but the estimator must populate all
    # four keys so downstream writers can rely on them.
    assert set(result.keys()) >= {"value", "level", "log", "n"}
