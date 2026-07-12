"""Stage 0 — build the unified history table and the大绿本本科专业表.

Slice 1: regular-batch one-segment (常规批一段线) builder + 大绿本 regular-batch
builder. Slice 2: early-batch supplement (提前批) builder + unified history
assembly (常规批一段 + 提前批).

Pure builders:
    build_history_regular(rows)  -> list[HistoryRow]   (常规批一段线, J/T 已算好)
    build_history_early(rows)    -> list[HistoryRow]   (本科提前批 A+B, 现场算 J/T)
    build_unified_history(j3, tq) -> list[HistoryRow]  (前两者拼接)
    build_dagluben_regular(rows) -> list[DaglubenRow]

All accept workbook rows as produced by ``openpyxl.iter_rows(values_only=True)``
(header row included). Source files are read-only — these functions never touch
the original workbooks; callers pass already-parsed rows.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from scripts.constants import (
    BATCH_EARLY_A,
    BATCH_EARLY_B,
    FLIGHT_BATCH,
    J3_BATCH,
    J3_BATCH_EARLY,
    J3_BATCH_REGULAR,
    J3_BRACKET,
    J3_MAJORNAME,
    J3_REMARKS,
    J3_SCHOOLNAME,
    J3_STAT_LINE_DIFF,
    J3_STDDEV,
    J3_SUBJECT,
    ONE_LINE,
    TQ_BATCH_EARLY,
    TQ_BATCH_EARLY_A,
    TQ_BATCH_EARLY_B,
    TQ_LOW_2023,
    TQ_LOW_2024,
    TQ_LOW_2025,
    ZHUANKE_KEYWORDS,
)
from scripts.line_diff import compute as compute_line_diff
from scripts.models import DaglubenRow, HistoryRow
from scripts.normalize import (
    core_of,
    infer_cat_from_major,
    nfk,
    split_school,
    strip_ignore_brackets,
)

__all__ = [
    "build_history_regular",
    "build_history_early",
    "build_unified_history",
    "build_dagluben_regular",
    "build_dagluben_early",
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
    """True if any value carries a专科 marker keyword (专科 / 军士生 / 定向培养军士).

    军士生 = 高职专科层（定向培养军士），bracket 常写「定向培养军士生,与xx联合
    培养」不含「专科」字样——只查「专科」会漏（Def-2 实测 46 条泄漏）。
    """
    return any(
        v is not None and any(kw in str(v) for kw in ZHUANKE_KEYWORDS)
        for v in values
    )


def _to_float(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_history_regular(rows: Iterable[Sequence]) -> list[HistoryRow]:
    """Filter近三年 rows: 常规批一段线 + 提前批（J3 已统计的，用现成 J/T）.

    J3 提前批（825 行）带现成线差/标准差，直接用——TQ 补充表里 J3 没统计到的
    提前批才由 build_history_early 现场算。Excludes常规批二段线 + 专科行
    （defensive——专科绝不能漏进本科匹配池）。
    """
    out: list[HistoryRow] = []
    for row in rows:
        if _is_header(row):
            continue
        batch = _cell(row, J3_BATCH)
        if batch not in (J3_BATCH_REGULAR, J3_BATCH_EARLY):
            continue
        # Drop rows that carry a专科 marker (专科 / 军士生 / 定向培养军士) in
        # remarks / bracket / major. 军士生标记常在 bracket + major，不在 remarks
        # （Def-2：定向培养军士生专科行曾漏进本科池）。
        if _looks_zhuanke(
            _cell(row, J3_REMARKS), _cell(row, J3_BRACKET), _cell(row, J3_MAJORNAME)
        ):
            continue

        school_raw = _cell(row, J3_SCHOOLNAME) or ""
        school, school_cat = split_school(school_raw)
        major_raw = _cell(row, J3_MAJORNAME) or ""
        major = nfk(major_raw)
        # 往年把身份写在专业名里（公费师范生/地方专项/综合评价/中外合作…）、校名
        # 里没有 → split_school 给空。从专业名补全 school_cat，让同身份匹配成立
        # （否则公费生会因 school_cat 空而配不上、被错丢去估算）。
        if not school_cat:
            school_cat = infer_cat_from_major(major)
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
                source_table=batch,
            )
        )
    return out


# --- 提前批 supplement columns (constants re-anchored here for readability) -
TQ_BATCH = 0  # 批次名称
TQ_CATEGORY = 1  # 招生类别 (B 列) — the differentiated admission track
TQ_SCHOOLNAME = 3  # 院校名称 (D 列)
TQ_MAJORNAME = 5  # 专业名称 (F 列)
TQ_SUBJECT = 6  # 选科 (G 列)


def build_history_early(
    rows: Iterable[Sequence],
    one_line: dict[int, int] | None = None,
    batches: frozenset[str] | None = None,
    low_cols: dict[int, int] | None = None,
) -> list[HistoryRow]:
    """Build the提前批 history pool from the supplement table.

    Keeps本科提前批 A类 + B类 (spec §3: AB 无差别, 合并), drops专科提前批
    (193 rows). J/T are computed on the fly from per-year 录取低分
    (2025→idx10, 2024→idx14, 2023→idx18) minus the one-line cutoff
    via :func:`line_diff.compute`.

    ``one_line`` 覆盖 constants.ONE_LINE（参数化，不写死年份/分数）。

    The招生类别 comes from column B (supplement-table semantics), which differs
    from 近三年 where it is split off the校名 bracket; the supplement table
    never embeds category in 院校名称 (verified: 0/1707 rows). Both feeds funnel
    into the same ``school_cat`` field so the strict matcher can key on it
    uniformly.
    """
    cutoff = one_line or ONE_LINE
    early_batches = batches or frozenset({TQ_BATCH_EARLY_A, TQ_BATCH_EARLY_B})
    cols = low_cols or {2025: TQ_LOW_2025, 2024: TQ_LOW_2024, 2023: TQ_LOW_2023}
    out: list[HistoryRow] = []
    for row in rows:
        if _is_header(row):
            continue
        batch = _cell(row, TQ_BATCH)
        if batch not in early_batches:
            continue  # 专科提前批 and anything else dropped

        school_raw = _cell(row, TQ_SCHOOLNAME) or ""
        school, _embedded_cat = split_school(school_raw)
        # Category comes from the招生类别 column, not the校名 bracket.
        cat_raw = nfk(_cell(row, TQ_CATEGORY) or "")
        major_raw = _cell(row, TQ_MAJORNAME) or ""
        major = nfk(major_raw)
        stripped = strip_ignore_brackets(major_raw)
        core = nfk(core_of(major_raw))
        subject = nfk(_cell(row, TQ_SUBJECT) or "")

        lows = {y: _to_float(_cell(row, c)) for y, c in cols.items()}
        j, t = compute_line_diff(lows, cutoff)

        out.append(
            HistoryRow(
                school=school,
                school_cat=cat_raw,
                major=major,
                stripped=stripped,
                core=core,
                subject=subject,
                J=j,
                T=t,
                source_table=TQ_BATCH_EARLY,
            )
        )
    return out


def build_unified_history(
    j3_rows: Iterable[Sequence],
    tq_rows: Iterable[Sequence],
    one_line: dict[int, int] | None = None,
    batches: frozenset[str] | None = None,
    low_cols: dict[int, int] | None = None,
) -> list[HistoryRow]:
    """Concatenate常规批一段 + 提前批 into the unified history pool (spec §4.1).

    Order is regular-first then early so any future deduplication (not needed
    in Slice 2 — the two feeds have disjoint source batches) keeps the
    larger, pre-computed regular pool as the canonical side.
    """
    regular = build_history_regular(j3_rows)
    early = build_history_early(
        tq_rows, one_line=one_line, batches=batches, low_cols=low_cols
    )
    return [*regular, *early]


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


def build_dagluben_early(
    rows: Iterable[Sequence],
    batches: frozenset[str] | None = None,
) -> list[DaglubenRow]:
    """Extract大绿本 提前批 A类 + B类 本科专业 rows into one merged pool.

    Spec §3 / §4.2: AB 类无差别, merged into a single matching pool whose
    ``batch`` is the unified label ``提前批`` (constants.TQ_BATCH_EARLY) so it
    keys against the提前批 history pool built by :func:`build_history_early`.

    专业行 = 代号(E, idx4) and 名称(F, idx5) both non-empty. Subtitles carrying
    the专科 keyword are excluded. ``batches`` 参数化（默认提前批 A/B + 飞行；
    大绿本批次命名变化时覆盖，不用改代码）。
    """
    early_batches = batches or frozenset({BATCH_EARLY_A, BATCH_EARLY_B, FLIGHT_BATCH})
    out: list[DaglubenRow] = []
    for row_idx, row in enumerate(rows, start=1):
        if _is_header(row):
            continue
        batch = _cell(row, 0)
        if batch not in early_batches:
            continue
        subtitle = _cell(row, 1) or ""
        if _looks_zhuanke(subtitle):
            continue
        code = _cell(row, 4)
        name = _cell(row, 5)
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
                batch=TQ_BATCH_EARLY,
                src_row_idx=row_idx,
            )
        )
    return out


# --- intermediate CSV writers ---------------------------------------------

_HISTORY_FIELDS: tuple[str, ...] = (
    "school",
    "school_cat",
    "major",
    "stripped",
    "core",
    "subject",
    "J",
    "T",
    "source_table",
)
_DAGLUBEN_FIELDS: tuple[str, ...] = (
    "school",
    "school_cat",
    "major",
    "stripped",
    "core",
    "subject",
    "batch",
    "src_row_idx",
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
