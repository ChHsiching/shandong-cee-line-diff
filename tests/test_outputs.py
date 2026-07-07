"""Tests for scripts.write_outputs — hierarchical + flat output writers.

iteration-3 (structured-columns): the main table now ends each row with **7
columns** instead of 3 — ``[近三年统计线差, 近三年线差标准差, 匹配方式, 仅一年数据,
选科要求跨年变化, 二次复核, 原因说明]``. The single legacy「匹配日志」column is gone.
Original 12 columns + 7 row-end = 19 total. The 5 structured columns are
populated via :func:`scripts.structured_log.split_log` over the legacy log
string carried by each :class:`MatchResult`.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

from scripts import write_outputs
from scripts.constants import LOG_STRICT
from scripts.models import MatchResult
from scripts.structured_log import split_log


# --- helpers ---------------------------------------------------------------

def _read_sheet(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


# Row-end column layout (1-based within an output row):
#   13 近三年统计线差  14 近三年线差标准差  15 匹配方式
#   16 仅一年数据        17 选科要求跨年变化          18 二次复核
#   19 原因说明
EXPECTED_HEADER_TAIL = [
    write_outputs.HEADER_J,
    write_outputs.HEADER_T,
    write_outputs.HEADER_STAGE,
    write_outputs.HEADER_SINGLE_YEAR,
    write_outputs.HEADER_DRIFT,
    write_outputs.HEADER_VERIFIED,
    write_outputs.HEADER_NOTE,
]


def _norm(v):
    """openpyxl reads back empty-string cells as None — normalise both to
    ``""`` so a structured column that holds "" still compares equal."""
    return "" if v is None else v


def _expected_row_end(res: MatchResult) -> list:
    """Compute the expected 7 row-end cells for a MatchResult."""
    structured = split_log(res.get("log", "") or "")
    return [res.get("J"), res.get("T")] + list(structured.values())


def _row_end(row: list) -> list:
    """Read the 7 row-end cells (0-based 12..18). J/T keep their None
    (matched values are floats; unmatched are genuinely None); the 5
    structured columns normalise None→"" because openpyxl reads "" cells as
    None."""
    jt = list(row[12:14])
    structured = [_norm(v) for v in row[14:19]]
    return jt + structured


# --- hierarchical output: structure (19 columns) --------------------------

def test_hierarchical_header_row_has_exactly_19_columns(
    minimal_hierarchical_dagluben, tmp_path
):
    """Plan v2 修订 binding: HEADER row must carry 19 cells (12 original +
    7 row-end)."""
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(minimal_hierarchical_dagluben, [], out)
    rows = _read_sheet(out)
    assert len(rows[0]) == 19
    # Original 12 headers untouched.
    assert rows[0][:12] == _read_sheet(minimal_hierarchical_dagluben)[0][:12]
    # Tail 7 header labels in the fixed structured-column order.
    assert rows[0][12:] == EXPECTED_HEADER_TAIL


def test_hierarchical_data_rows_are_19_columns_wide(
    minimal_hierarchical_dagluben, tmp_path
):
    """Every written row (header + data) is exactly 19 cells wide."""
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)
    for i, r in enumerate(rows):
        assert len(r) == 19, f"row {i} has {len(r)} cells, expected 19"


def test_hierarchical_original_columns_not_overwritten(
    minimal_hierarchical_dagluben, tmp_path
):
    """Original 12 columns byte-identical to the source workbook."""
    orig_rows = _read_sheet(minimal_hierarchical_dagluben)
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)
    for i, orig in enumerate(orig_rows):
        for j in range(12):
            assert rows[i][j] == orig[j], f"row {i} col {j} changed"


def test_hierarchical_only_major_rows_filled_others_blank(
    minimal_hierarchical_dagluben, tmp_path
):
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)

    # Row 2 批次头 / Row 3 小标题 / Row 4 学校行: 7 row-end cells all blank.
    for non_major_idx in (1, 2, 3):
        assert _row_end(rows[non_major_idx]) == [None] * 2 + [""] * 5, non_major_idx

    # Row 5 专业行 (matched): 7 row-end cells filled per split_log.
    assert _row_end(rows[4]) == _expected_row_end(results[0])
    # Row 6 专业行 (unmatched): same.
    assert _row_end(rows[5]) == _expected_row_end(results[1])


def test_hierarchical_missing_result_leaves_major_row_blank(
    minimal_hierarchical_dagluben, tmp_path
):
    """A专业行 with no result entry (defensive) leaves the 7 row-end cells blank."""
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        # row 6 deliberately omitted
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)
    assert _row_end(rows[5]) == [None] * 2 + [""] * 5


def test_hierarchical_zhuanke_row_carries_专科_stage(
    minimal_hierarchical_dagluben_with_zhuanke, tmp_path
):
    """分层版 专科 专业行: 匹配方式=专科（超范围）, 备注 empty (spec §3)."""
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=True, J=10.0, T=1.0,
                    log="核心名匹配：核心专业名相同"),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(
        minimal_hierarchical_dagluben_with_zhuanke, results, out
    )
    rows = _read_sheet(out)
    # The 专科 row (last in this fixture) has no MatchResult → writer annotates
    # it with LOG_ZHUANKE_OUT_OF_SCOPE. split_log turns that into the 5 cols.
    zhuanke_row = rows[-1]
    # 专科（超范围） in 匹配方式; 备注 empty; J/T blank (专科 excluded from matching).
    assert zhuanke_row[write_outputs.COL_STAGE - 1] == "专科（超范围）"
    assert _norm(zhuanke_row[write_outputs.COL_NOTE - 1]) == ""
    assert zhuanke_row[write_outputs.COL_J - 1] is None
    assert zhuanke_row[write_outputs.COL_T - 1] is None


# --- hierarchical output: 5 structured-column values ----------------------

def test_hierarchical_structured_5_columns_match_split_log(
    minimal_hierarchical_dagluben, tmp_path
):
    """For every major row with a MatchResult, columns 15-19 equal
    ``list(split_log(log).values())``."""
    log_strict_sy = f"{LOG_STRICT}；（仅一年数据，无标准差）"
    log_coarse = "核心名匹配：核心专业名相同（理工类）；选科要求跨年不同，已忽略"
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=log_strict_sy),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log=log_coarse),
    ]
    out = tmp_path / "hier.xlsx"
    write_outputs.write_hierarchical(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)

    for res, row in zip(results, rows[4:6]):
        expected = list(split_log(res["log"]).values())
        got = [_norm(v) for v in row[14:19]]  # 0-based 14..18 = cols 15..19
        assert got == expected, (res["log"], got, expected)


# --- flat output: structure (19 columns) ----------------------------------

def test_flat_header_row_has_exactly_19_columns(
    minimal_hierarchical_dagluben, tmp_path
):
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=False, J=None, T=None, log="未命中"),
    ]
    out = tmp_path / "flat.xlsx"
    write_outputs.write_flat(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)
    assert len(rows[0]) == 19
    assert rows[0][12:] == EXPECTED_HEADER_TAIL


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
    # Every row 19 cells wide.
    for i, r in enumerate(rows):
        assert len(r) == 19, f"row {i} width {len(r)}"

    header = rows[0]
    assert header[12:] == EXPECTED_HEADER_TAIL

    # First major row: original F (名称) + 7 row-end cells.
    assert rows[1][5] == "计算机科学与技术"
    assert _row_end(rows[1]) == _expected_row_end(results[0])
    # Second major row (unmatched).
    assert rows[2][5] == "英语"
    assert _row_end(rows[2]) == _expected_row_end(results[1])


def test_flat_structured_5_columns_match_split_log(
    minimal_hierarchical_dagluben, tmp_path
):
    """Flat version: columns 15-19 == list(split_log(log).values()) for every
    major row with a result."""
    log_strict_sy = f"{LOG_STRICT}；（仅一年数据，无标准差）"
    log_coarse = "核心名匹配：核心专业名相同（理工类）；选科要求跨年不同，已忽略"
    log_new = "新增专业：估算=同校同选科(19)均值=225.25"
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=log_strict_sy),
        MatchResult(src_row_idx=6, matched=True, J=70.0, T=2.0, log=log_coarse),
        MatchResult(src_row_idx=6, matched=True, J=225.25, T=10.0, log=log_new),
    ]
    out = tmp_path / "flat.xlsx"
    write_outputs.write_flat(minimal_hierarchical_dagluben, results, out)
    rows = _read_sheet(out)

    # rows[1] and rows[2] both map to src_row_idx 5/6 — the writer uses the
    # FIRST result per idx. So row 1 = log_strict_sy, row 2 = log_coarse.
    assert [_norm(v) for v in rows[1][14:19]] == list(split_log(log_strict_sy).values())
    assert [_norm(v) for v in rows[2][14:19]] == list(split_log(log_coarse).values())


# --- flat output: 专科 exclusion (unchanged behaviour) --------------------

def test_flat_still_excludes_zhuanke_rows(
    minimal_hierarchical_dagluben_with_zhuanke, tmp_path
):
    """Flat version continues to drop 专科 专业行 (spec §3, unchanged)."""
    results = [
        MatchResult(src_row_idx=5, matched=True, J=60.0, T=5.0, log=LOG_STRICT),
        MatchResult(src_row_idx=6, matched=True, J=70.0, T=2.0,
                    log="核心名匹配：核心专业名相同"),
    ]
    out = tmp_path / "flat.xlsx"
    write_outputs.write_flat(
        minimal_hierarchical_dagluben_with_zhuanke, results, out
    )
    rows = _read_sheet(out)
    # Only 2 major rows (本科); 专科 row excluded.
    assert len(rows) == 3  # header + 2
    for r in rows[1:]:
        # No 专科 stage leaks into flat.
        assert r[write_outputs.COL_STAGE - 1] != "专科（超范围）"
