"""Stage 0 — build the unified history table and the大绿本本科专业表.

Slice 1 scope: regular-batch one-segment (常规批一段线) only. Early-batch
(提前批) is added in Slice 2; the broader unified history table is assembled
there.

Two pure builders:
    build_history_regular(rows)  -> list[HistoryRow]
    build_dagluben_regular(rows) -> list[DaglubenRow]

Both accept workbook rows as produced by ``openpyxl.iter_rows(values_only=True)``
(header row included). Source files are read-only — these functions never touch
the original workbooks; callers pass already-parsed rows.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from scripts.constants import (
    J3_BASE_MAJOR,
    J3_BATCH,
    J3_BATCH_REGULAR,
    J3_BRACKET,
    J3_DIFF_2023,
    J3_DIFF_2024,
    J3_DIFF_2025,
    J3_MAJORNAME,
    J3_REMARKS,
    J3_SCHOOLCODE,
    J3_SCHOOLNAME,
    J3_STAT_LINE_DIFF,
    J3_STDDEV,
    J3_SUBJECT,
    ZHUANKE_KEYWORD,
)
from scripts.models import DaglubenRow, HistoryRow
from scripts.normalize import core_of, nfk, split_school, strip_ignore_brackets

__all__ = [
    "build_history_regular",
    "build_dagluben_regular",
    "write_history_csv",
    "write_dagluben_csv",
]


# Cells beyond the workbook width come back as None; guard against short rows.
def _cell(row: Sequence, idx: int):
    if idx < 0 or idx >= len(row):
        return None
    return row[idx]


def _is_header(row: Sequence) -> bool:
    """Detect the header row by its first cell spelling 'batch' (ascii) —
    the only non-data row our builders must skip."""
    first = _cell(row, J3_BATCH)
    return first == "batch" or first == "批次"


def _looks_zhuanke(*values) -> bool:
    return any(v is not None and ZHUANKE_KEYWORD in str(v) for v in values)


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_history_regular(rows: Iterable[Sequence]) -> list[HistoryRow]:
    """Filter近三年 rows down to常规批一段线本科 and normalise fields.

    Excludes常规批二段线 and any row whose remarks/bracket carries the专科
    keyword (近三年 seg1 is本科 by口径, but defensive — vocational pollution
    must never leak into the本科 matching pool).
    """
    out: list[HistoryRow] = []
    for row in rows:
        if _is_header(row):
            continue
        batch = _cell(row, J3_BATCH)
        if batch != J3_BATCH_REGULAR:
            continue
        # Drop rows that carry the专科 keyword in remarks or bracket content.
        if _looks_zhuanke(_cell(row, J3_REMARKS), _cell(row, J3_BRACKET)):
            continue

        school_raw = _cell(row, J3_SCHOOLNAME) or ""
        school, school_cat = split_school(school_raw)
        major_raw = _cell(row, J3_MAJORNAME) or ""
        major = nfk(major_raw)
        stripped = strip_ignore_brackets(major_raw)
        core = nfk(core_of(major_raw))
        subject = nfk(_cell(row, J3_SUBJECT) or "")
        j = _to_float(_cell(row, J3_STAT_LINE_DIFF))
        t = _to_float(_cell(row, J3_STDDEV))

        out.append(
            HistoryRow(
                school=school,
                school_cat=school_cat,
                major=major,
                stripped=stripped,
                core=core,
                subject=subject,
                J=j,
                T=t,
                source_table=J3_BATCH_REGULAR,
            )
        )
    return out


def build_dagluben_regular(rows: Iterable[Sequence]) -> list[DaglubenRow]:
    """Extract大绿本 regular-batch (4.常规批) 本科专业 rows.

    专业行 = 代号(E, idx4) and 名称(F, idx5) both non-empty. 批次头/小标题/
    学校行 (lacking both) are skipped. Subtitles carrying the专科 keyword are
    excluded (spec §3: 专科全排除).
    """
    out: list[DaglubenRow] = []
    # Header is row 1 (1-based); first data row is row 2.
    for row_idx, row in enumerate(rows, start=1):
        if _is_header(row):
            continue
        batch = _cell(row, 0)
        if batch != "4.常规批":
            continue
        subtitle = _cell(row, 1) or ""
        if _looks_zhuanke(subtitle):
            continue
        code = _cell(row, 4)
        name = _cell(row, 5)
        # 专业行 requires both 代号 and 名称.
        if code in (None, "") or name in (None, ""):
            continue

        school = nfk(_cell(row, 3) or "")
        school_cat = nfk(subtitle) if subtitle != "" else ""
        major = nfk(name)
        stripped = strip_ignore_brackets(name)
        core = nfk(core_of(name))
        subject = nfk(_cell(row, 6) or "")

        out.append(
            DaglubenRow(
                school=school,
                school_cat=school_cat,
                major=major,
                stripped=stripped,
                core=core,
                subject=subject,
                batch=str(batch),
                src_row_idx=row_idx,
            )
        )
    return out


# --- intermediate CSV writers ---------------------------------------------

_HISTORY_FIELDS: tuple[str, ...] = (
    "school", "school_cat", "major", "stripped", "core",
    "subject", "J", "T", "source_table",
)
_DAGLUBEN_FIELDS: tuple[str, ...] = (
    "school", "school_cat", "major", "stripped", "core",
    "subject", "batch", "src_row_idx",
)


def write_history_csv(rows: list[HistoryRow], path: str | Path) -> None:
    """Persist a history table to CSV (intermediate/ artefact)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_HISTORY_FIELDS))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _HISTORY_FIELDS})


def write_dagluben_csv(rows: list[DaglubenRow], path: str | Path) -> None:
    """Persist the大绿本本科专业 table to CSV (intermediate/ artefact)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_DAGLUBEN_FIELDS))
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _DAGLUBEN_FIELDS})
