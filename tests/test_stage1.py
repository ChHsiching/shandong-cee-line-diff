"""Tests for scripts.stage1_strict — Stage 1 strict matching.

Per Plan v2: small-sample 1-hit + 1-miss is the RED判据; the ~57.8%
real-batch hit rate is smoke (asserted in a separate class, not part of RED).
"""

from __future__ import annotations

from pathlib import Path


from scripts import stage1_strict
from scripts.constants import LOG_STRICT
from scripts.models import DaglubenRow, HistoryRow


def _hist(**kw) -> HistoryRow:
    base: HistoryRow = dict(  # type: ignore[assignment]
        school="", school_cat="", major="", stripped="", core="",
        subject="", J=None, T=None, source_table="常规批一段线",
    )
    base.update(kw)  # type: ignore[arg-type]
    return base


def _dl(**kw) -> DaglubenRow:
    base: DaglubenRow = dict(  # type: ignore[assignment]
        school="", school_cat="", major="", stripped="", core="",
        subject="", batch="4.常规批", src_row_idx=0,
    )
    base.update(kw)  # type: ignore[arg-type]
    return base


# --- match_strict: pure function, RED --------------------------------------

def test_match_strict_one_hit_one_miss():
    history = [
        _hist(school="示例大学", school_cat="", major="计算机科学与技术",
              stripped="计算机科学与技术", J=60.0, T=5.0),
        _hist(school="示例大学", school_cat="", major="数学",
              stripped="数学", J=70.0, T=None),
    ]
    dagluben = [
        _dl(school="示例大学", school_cat="普通计划",
            major="计算机科学与技术", stripped="计算机科学与技术",
            core="计算机科学与技术", src_row_idx=5),
        _dl(school="示例大学", school_cat="普通计划",
            major="天文学", stripped="天文学",
            core="天文学", src_row_idx=6),
    ]
    results = stage1_strict.match_strict(dagluben, history)
    assert len(results) == 2

    hit = next(r for r in results if r["matched"])
    miss = next(r for r in not_matched(results))

    assert hit["src_row_idx"] == 5
    assert hit["J"] == 60.0
    assert hit["T"] == 5.0
    assert hit["log"] == LOG_STRICT
    assert hit["major"] == "计算机科学与技术"

    assert miss["src_row_idx"] == 6
    assert miss["matched"] is False
    assert miss["J"] is None
    assert miss["T"] is None
    assert miss["log"] == "未命中"


def not_matched(results):
    return [r for r in results if not r["matched"]]


def test_match_strict_key_requires_school_and_cat_and_stripped():
    """Strict key = (基础校名, 招生类别, stripped). Different category -> miss."""
    history = [
        _hist(school="X大学", school_cat="中外合作办学",
              stripped="英语", J=40.0, T=2.0),
    ]
    # dagluben has cat "普通计划" -> different key -> miss
    dagluben = [
        _dl(school="X大学", school_cat="普通计划", stripped="英语",
            src_row_idx=1),
    ]
    results = stage1_strict.match_strict(dagluben, history)
    assert results[0]["matched"] is False


def test_match_strict_distinguishes_stripped_names_same_school():
    history = [
        _hist(school="Y大学", stripped="数学", J=55.0),
    ]
    dagluben = [
        _dl(school="Y大学", stripped="应用数学", src_row_idx=1),
    ]
    results = stage1_strict.match_strict(dagluben, history)
    assert results[0]["matched"] is False


def test_match_strict_uses_history_dagluben_cat_mapping():
    """大绿本 cat '普通计划' aligns with history cat '' (empty = 普通轨道).

    Per spec §5.2: the普通计划 track is the default; near-three-year rows
    without an explicit category suffix are普通. A非-empty category on one
    side and empty on the other is normalised before keying so普通 matches.
    """
    history = [
        _hist(school="Z大学", school_cat="", stripped="英语", J=50.0),
    ]
    dagluben = [
        _dl(school="Z大学", school_cat="普通计划", stripped="英语",
            src_row_idx=1),
    ]
    results = stage1_strict.match_strict(dagluben, history)
    assert results[0]["matched"] is True
    assert results[0]["J"] == 50.0


# --- V5-1: single-year history T=None annotation (Slice A Task A2) ----------

SINGLE_YEAR_NOTE = "（仅一年数据，无标准差）"


def test_match_strict_single_year_history_adds_no_stddev_note():
    """A strict match whose history row has T=None must append the
    「(仅一年数据，无标准差)」note to the log (V5-1)."""
    history = [
        _hist(school="S大学", school_cat="", stripped="数学", J=55.0, T=None),
    ]
    dagluben = [
        _dl(school="S大学", school_cat="普通计划", stripped="数学",
            src_row_idx=1),
    ]
    results = stage1_strict.match_strict(dagluben, history)
    assert results[0]["matched"] is True
    assert results[0]["T"] is None
    assert SINGLE_YEAR_NOTE in results[0]["log"]


def test_match_strict_multi_year_history_does_not_add_note():
    """A strict match whose history row carries a T must NOT get the note."""
    history = [
        _hist(school="M大学", school_cat="", stripped="数学", J=55.0, T=7.3),
    ]
    dagluben = [
        _dl(school="M大学", school_cat="普通计划", stripped="数学",
            src_row_idx=1),
    ]
    results = stage1_strict.match_strict(dagluben, history)
    assert results[0]["matched"] is True
    assert SINGLE_YEAR_NOTE not in results[0]["log"]


# --- Real-workbook smoke: ~57.8% strict hit rate ---------------------------

class TestStage1Smoke:
    """Smoke层: real regular-batch strict hit rate. Plan v2 binding: assert
    55%-61% (prototype observed 57.8%). Not part of RED."""

    def test_smoke_regular_batch_hit_rate(self, repo_root: Path):
        from scripts import io_source, stage0_merge

        wb = io_source.load_source(repo_root / "data" / "近三年学校批次专业线差统计.xlsx")
        hist = stage0_merge.build_history_regular(wb["统计结果"].iter_rows(values_only=True))
        wb.close()

        wb = io_source.load_source(repo_root / "data" / "山东省2026年大绿本招生计划.xlsx")
        dl = stage0_merge.build_dagluben_regular(wb[wb.sheetnames[0]].iter_rows(values_only=True))
        wb.close()

        results = stage1_strict.match_strict(dl, hist)
        hits = sum(1 for r in results if r["matched"])
        rate = hits / len(results)
        # Plan: 57.8% observed; allow 55%-61% band.
        assert 0.55 <= rate <= 0.61, f"hit rate {rate:.4f} outside 55%-61%"
