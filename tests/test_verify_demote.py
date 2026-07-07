"""Slice B (v2阻断2) — demote 通路 contract tests.

Per Plan v2 binding: when ``verify_*_result.jsonl`` exist, run_pipeline filters
存疑 verdicts out of coarse/semantic results and out of ``classified_idx``
BEFORE ``_build_main_results`` so they fall naturally into
``remaining_unmatched → flight_and_special``. Each demoted row's special-table
log must read「二次复核认为可能有误：<原因>」(bypassing the LOG_SPECIAL_UNMATCHED fallback).

These tests exercise the demote layer in isolation (pure functions + the
``flight_and_special`` ``demoted_map`` parameter) so the agent dispatch need
not run for CI.
"""

from __future__ import annotations

from scripts.constants import FLIGHT_BATCH, LOG_SPECIAL_UNMATCHED
from scripts.models import DaglubenRow, MatchResult
from scripts.run_pipeline import _build_main_results
from scripts.stage3_edges import flight_and_special
from scripts.verify_judgment import DEMOTE_LOG_PREFIX, filter_demoted


def _dl(idx: int, school: str, major: str, batch: str = "4.常规批") -> DaglubenRow:
    return DaglubenRow(
        src_row_idx=idx, school=school, school_cat="", major=major,
        stripped=major, core=major, subject="物理", batch=batch,
    )


def _match(idx: int, school: str, major: str, log: str, j: float = 80.0) -> MatchResult:
    return MatchResult(
        src_row_idx=idx, school=school, school_cat="", major=major,
        matched=True, J=j, T=1.0, log=log,
    )


# ---------------------------------------------------------------------------
# filter_demoted — removes 存疑 idx from coarse/semantic results + classified
# ---------------------------------------------------------------------------


def test_filter_demoted_removes_uncertain_from_coarse_and_classified() -> None:
    """Given a 存疑 verdict, filter_demoted drops that idx from coarse_results
    AND from classified_idx (so it falls through to special)."""
    coarse = [
        _match(1, "甲大学", "投资学(量化投资)", "核心名匹配：核心专业名相同"),
        _match(2, "甲大学", "会计学", "核心名匹配：核心专业名相同"),
    ]
    classified = {1, 2, 5}
    verdict_by_idx = {1: "存疑", 2: "确定"}

    out_coarse, out_classified, demoted_map = filter_demoted(
        coarse, classified, verdict_by_idx, reasons_by_idx={1: "方向不同"},
    )
    assert [r["src_row_idx"] for r in out_coarse] == [2]  # idx 1 removed
    assert 1 not in out_classified
    assert 2 in out_classified
    assert demoted_map == {1: "方向不同"}


def test_filter_demoted_no_verdicts_returns_unchanged() -> None:
    coarse = [_match(1, "甲", "a", "核心名匹配：核心专业名相同")]
    out_coarse, out_classified, demoted_map = filter_demoted(
        coarse, {1}, {}, reasons_by_idx={},
    )
    assert out_coarse == coarse
    assert out_classified == {1}
    assert demoted_map == {}


def test_filter_demoted_passes_semantic_too() -> None:
    """filter_demoted works on any MatchResult list (coarse or semantic)."""
    semantic = [
        _match(10, "乙", "量子", "agent 语义匹配：方向对齐", j=50.0),
    ]
    out_sem, out_classified, demoted_map = filter_demoted(
        semantic, {10}, {10: "存疑"}, reasons_by_idx={10: "理由"},
    )
    assert out_sem == []
    assert 10 not in out_classified
    assert demoted_map == {10: "理由"}


# ---------------------------------------------------------------------------
# flight_and_special — demoted_map overrides the log
# ---------------------------------------------------------------------------


def test_flight_and_special_demoted_log_overrides_fallback() -> None:
    """A demoted row routed to special gets「二次复核认为可能有误：<原因>」, NOT the generic
    LOG_SPECIAL_UNMATCHED fallback (v2阻断2 关键)."""
    d = _dl(1, "甲大学", "投资学(量化投资)")
    edges = flight_and_special([], [d], demoted_map={1: "方向不同：量化投资≠投资学"})
    assert len(edges) == 1
    assert edges[0]["src_row_idx"] == 1
    assert edges[0]["log"].startswith(DEMOTE_LOG_PREFIX)
    assert "方向不同" in edges[0]["log"]
    assert LOG_SPECIAL_UNMATCHED not in edges[0]["log"]


def test_flight_and_special_no_demoted_map_uses_fallback() -> None:
    """Without demoted_map, normal unmatched rows get the generic log."""
    d = _dl(1, "甲大学", "未知专业")
    edges = flight_and_special([], [d])
    assert "未能匹配" in edges[0]["log"] or "没找到" in edges[0]["log"]


def test_flight_and_special_demoted_for_flight_row() -> None:
    d = _dl(2, "飞院", "飞行", batch=FLIGHT_BATCH)
    edges = flight_and_special([d], [], demoted_map={2: "存疑原因"})
    # demoted_map applies regardless of flight/other bucket
    assert edges[0]["log"].startswith(DEMOTE_LOG_PREFIX)


# ---------------------------------------------------------------------------
# Integration: _build_main_results with demoted filtering applied upstream
# ---------------------------------------------------------------------------


def test_build_main_results_excludes_demoted_row(tmp_path) -> None:
    """End-to-end demote: after filter_demoted strips idx 1 from coarse +
    classified, _build_main_results routes idx 1 to the unmatched (special)
    bucket, NOT the matched bucket."""
    dagluben = [_dl(1, "甲大学", "投资学(量化投资)"), _dl(2, "甲大学", "会计学")]
    coarse = [
        _match(1, "甲大学", "投资学(量化投资)", "核心名匹配：核心专业名相同"),
        _match(2, "甲大学", "会计学", "核心名匹配：核心专业名相同"),
    ]
    classified = {1, 2}

    # Apply demote upstream (as run_pipeline does).
    coarse_filtered, classified_filtered, _ = filter_demoted(
        coarse, classified, {1: "存疑", 2: "确定"},
        reasons_by_idx={1: "方向不同"},
    )

    main = _build_main_results(
        dagluben, [], coarse_filtered, [], {}, set(),
        classified_idx=classified_filtered,
    )
    by_idx = {r["src_row_idx"]: r for r in main}
    # idx 2 stays matched (verdict 确定).
    assert by_idx[2]["matched"] is True
    # idx 1 is NOT matched (it was demoted out of coarse → falls to special).
    assert by_idx[1]["matched"] is False


def test_build_main_results_accepts_classified_idx_override() -> None:
    """_build_main_results must accept an optional classified_idx parameter
    so the demote step can shrink the classified set before main-table build."""
    dagluben = [_dl(1, "甲", "a"), _dl(2, "甲", "b")]
    coarse = [
        _match(1, "甲", "a", "核心名匹配：核心专业名相同"),
        _match(2, "甲", "b", "核心名匹配：核心专业名相同"),
    ]
    # If we pass classified_idx missing idx 1, idx 1 should fall to special.
    main = _build_main_results(
        dagluben, [], coarse, [], {}, set(), classified_idx={2},
    )
    by_idx = {r["src_row_idx"]: r for r in main}
    assert by_idx[2]["matched"] is True
    assert by_idx[1]["matched"] is False
