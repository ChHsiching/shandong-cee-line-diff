"""Output writers for the admission-data pipeline.

Two products (spec §7):
    - Hierarchical (大绿本_附线差_分层版.xlsx): a full copy of the大绿本
      workbook with three columns appended at the row end
      (近三年统计线差 / 近三年线差标准差 / 匹配日志). Every original row is
      preserved verbatim; non-major rows leave the three new cells blank.
      Original columns are never overwritten.
    - Flat (大绿本_附线差_扁平版.xlsx): only专业行, each with all original
      fields plus the three appended columns.

``write_edge_tables.py`` handles the boundary tables (Slice 5/6) so this
module's file domain is stable across slices (Plan v2 binding).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import openpyxl
from openpyxl.utils import get_column_letter

from scripts.models import MatchResult

__all__ = [
    "write_hierarchical",
    "write_flat",
    "COL_J",
    "COL_T",
    "COL_LOG",
    "HEADER_J",
    "HEADER_T",
    "HEADER_LOG",
]

# Append-position header labels.
HEADER_J = "近三年统计线差"
HEADER_T = "近三年线差标准差"
HEADER_LOG = "匹配日志"

# 1-based column indices for the appended trio, given the大绿本 has 12 cols.
COL_J = 13
COL_T = 14
COL_LOG = 15

# 大绿本 column where 代号(E) and 名称(F) live (1-based); both non-empty on
# 专业行.
COL_CODE = 5
COL_NAME = 6


def _is_major_row(row_cells) -> bool:
    code = row_cells[COL_CODE - 1] if len(row_cells) >= COL_CODE else None
    name = row_cells[COL_NAME - 1] if len(row_cells) >= COL_NAME else None
    return code not in (None, "") and name not in (None, "")


def _index_by_src_row(results: Iterable[MatchResult]) -> dict[int, MatchResult]:
    out: dict[int, MatchResult] = {}
    for r in results:
        idx = r.get("src_row_idx", 0)
        if idx and idx not in out:
            out[idx] = r
    return out


def _open_template(path: str | Path) -> openpyxl.Workbook:
    """Open the source workbook for copying. write_outputs must not mutate the
    source, so we load it without read_only (we need to append cells) and save
    to a *different* path."""
    return openpyxl.load_workbook(Path(path), data_only=True)


def write_hierarchical(
    src_path: str | Path,
    results: Iterable[MatchResult],
    out_path: str | Path,
) -> None:
    """Copy the大绿本 workbook verbatim and append J/T/log on matched major rows.

    - Every original row (header / 批次头 / 小标题 / 学校行 / 专业行) preserved.
    - Original columns (1-12) never overwritten.
    - The three new columns are added at positions 13/14/15; only专业行 that
      have a :class:`MatchResult` carry values, all others stay blank.
    """
    wb = _open_template(src_path)
    try:
        ws = wb.active
        # Header row for the new columns.
        ws.cell(row=1, column=COL_J, value=HEADER_J)
        ws.cell(row=1, column=COL_T, value=HEADER_T)
        ws.cell(row=1, column=COL_LOG, value=HEADER_LOG)

        results_by_idx = _index_by_src_row(results)

        # Iterate over rows; row index in openpyxl is 1-based and matches
        # src_row_idx (header is row 1).
        for row_idx in range(2, ws.max_row + 1):
            res = results_by_idx.get(row_idx)
            if res is None:
                continue
            # Defensive: only fill if this is actually a major row.
            code = ws.cell(row=row_idx, column=COL_CODE).value
            name = ws.cell(row=row_idx, column=COL_NAME).value
            if code in (None, "") or name in (None, ""):
                continue
            ws.cell(row=row_idx, column=COL_J, value=res.get("J"))
            ws.cell(row=row_idx, column=COL_T, value=res.get("T"))
            ws.cell(row=row_idx, column=COL_LOG, value=res.get("log"))

        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        wb.save(out_p)
    finally:
        wb.close()


def write_flat(
    src_path: str | Path,
    results: Iterable[MatchResult],
    out_path: str | Path,
) -> None:
    """Write a flat table containing only专业行 + the three appended columns.

    Columns 1-12 carry the original大绿本 fields; 13/14/15 carry J/T/log.
    Non-major rows (批次头/小标题/学校行) are omitted entirely.
    """
    src_wb = _open_template(src_path)
    out_wb = openpyxl.Workbook()
    try:
        src_ws = src_wb.active
        out_ws = out_wb.active
        out_ws.title = src_ws.title

        results_by_idx = _index_by_src_row(results)

        # Header row: original 12 columns + J/T/log.
        out_row = 1
        for col_idx in range(1, 13):
            out_ws.cell(row=out_row, column=col_idx,
                        value=src_ws.cell(row=1, column=col_idx).value)
        out_ws.cell(row=out_row, column=COL_J, value=HEADER_J)
        out_ws.cell(row=out_row, column=COL_T, value=HEADER_T)
        out_ws.cell(row=out_row, column=COL_LOG, value=HEADER_LOG)
        out_row += 1

        for src_row_idx in range(2, src_ws.max_row + 1):
            # Read original row cells.
            cells = [
                src_ws.cell(row=src_row_idx, column=c).value
                for c in range(1, 13)
            ]
            if not _is_major_row(cells):
                continue
            for col_idx, val in enumerate(cells, start=1):
                out_ws.cell(row=out_row, column=col_idx, value=val)
            res = results_by_idx.get(src_row_idx)
            if res is not None:
                out_ws.cell(row=out_row, column=COL_J, value=res.get("J"))
                out_ws.cell(row=out_row, column=COL_T, value=res.get("T"))
                out_ws.cell(row=out_row, column=COL_LOG, value=res.get("log"))
            else:
                out_ws.cell(row=out_row, column=COL_J, value=None)
                out_ws.cell(row=out_row, column=COL_T, value=None)
                out_ws.cell(row=out_row, column=COL_LOG, value=None)
            out_row += 1

        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_wb.save(out_p)
    finally:
        src_wb.close()
        out_wb.close()
