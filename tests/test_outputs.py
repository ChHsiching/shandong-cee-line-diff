"""Tests for scripts.write_outputs — hierarchical + flat output writers."""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from scripts import write_outputs
from scripts.constants import LOG_STRICT
from scripts.models import MatchResult


# --- helpers ---------------------------------------------------------------

def _read_sheet(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


# --- hierarchical output ---------------------------------------------------

def test_hierarchical_preserves_all_rows_and_appends_three_columns(
    minimal_hierarchical_dagluben, tmp_path
):
    # Capture the original 6 rows (header + 批次头 + 小标题 + 学校 + 2专业).
    orig_rows = _read_sheet(minimal_hierarchical_dagluben)
    assert len(orig_rows) == 6
    orig_width = len([c for c in orig_rows[0] if c is not None])

    results = [
        MatchResult(src_row_idx=5, school="示例大学", school_cat="普通计划",
                    major="计算机科学与技术", matched=True,
                    J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, school="示例大学", school_cat="普通计划",
                    major="英语", matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(
        minimal_hierarchical_dagluben, results, out
    )

    rows = _read_sheet(out)
    # All 6 original rows preserved.
    assert len(rows) == 6
    # Width grew by exactly 3 (J/T/log); original 12 cols intact.
    assert len(rows[0]) == 12 + 3
    # Original columns are NOT overwritten (header still 1-12).
    assert rows[0][:12] == orig_rows[0][:12]
    # The 3 new header cells.
    assert rows[0][12] == "近三年统计线差"
    assert rows[0][13] == "近三年线差标准差"
    assert rows[0][14] == "匹配日志"


def test_hierarchical_only_major_rows_filled_others_blank(
    minimal_hierarchical_dagluben, tmp_path
):
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(
        minimal_hierarchical_dagluben, results, out
    )
    rows = _read_sheet(out)

    # Row 1 header: new cells carry the three header labels.
    assert rows[0][12:] == ["近三年统计线差", "近三年线差标准差", "匹配日志"]
    # Row 2 批次头: new cells empty.
    assert rows[1][12:] == [None, None, None]
    # Row 3 小标题: new cells empty.
    assert rows[2][12:] == [None, None, None]
    # Row 4 学校行: new cells empty.
    assert rows[3][12:] == [None, None, None]
    # Row 5 专业行 (matched): J/T/log filled.
    assert rows[4][12] == 60.0
    assert rows[4][13] == 5.0
    assert rows[4][14] == LOG_STRICT
    # Row 6 专业行 (unmatched): J/T empty, log set.
    assert rows[6 - 1][12] is None
    assert rows[6 - 1][13] is None
    assert rows[6 - 1][14] == "未命中"


def test_hierarchical_original_columns_not_overwritten(
    minimal_hierarchical_dagluben, tmp_path
):
    """Original 12 columns must be byte-identical to the source workbook."""
    orig_rows = _read_sheet(minimal_hierarchical_dagluben)
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(
        minimal_hierarchical_dagluben, results, out
    )
    rows = _read_sheet(out)
    for i, orig in enumerate(orig_rows):
        # Each original cell preserved (pad row to original width for compare).
        for j in range(12):
            assert rows[i][j] == orig[j], f"row {i} col {j} changed"


def test_hierarchical_missing_result_leaves_major_row_blank(
    minimal_hierarchical_dagluben, tmp_path
):
    """A专业行 with no result entry (defensive) leaves J/T/log blank."""
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        # row 6 deliberately omitted
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(
        minimal_hierarchical_dagluben, results, out
    )
    rows = _read_sheet(out)
    assert rows[5][12] is None
    assert rows[5][13] is None
    assert rows[5][14] is None


# --- flat output -----------------------------------------------------------

def test_flat_keeps_only_major_rows_with_all_fields(
    minimal_hierarchical_dagluben, tmp_path
):
    results = [
        MatchResult(src_row_idx=5, school="示例大学", school_cat="普通计划",
                    major="计算机科学与技术", matched=True,
                    J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, school="示例大学", school_cat="普通计划",
                    major="英语", matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "flat.xlsx"
    write_outputs.write_flat(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)

    # 1 header + 2 major rows = 3 total (no 批次头/小标题/学校行).
    assert len(rows) == 3
    # Flat schema: 12 original + 招生类别 already in col B... we add J/T/log.
    header = rows[0]
    assert "近三年统计线差" in header
    assert "近三年线差标准差" in header
    assert "匹配日志" in header

    # First major row carries full original fields + J/T/log.
    assert rows[1][5] == "计算机科学与技术"  # 名称 (F)
    assert rows[1][12] == 60.0
    assert rows[1][14] == LOG_STRICT

    # Second major row (unmatched).
    assert rows[2][5] == "英语"
    assert rows[2][12] is None
    assert rows[2][14] == "未命中"
