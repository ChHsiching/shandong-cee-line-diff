"""Edge/boundary table writers (新增/被删/特殊/改名/新增校/停招校).

Per Plan v2 binding, these are separated from write_outputs.py so that
Slices 5/6 (which populate them) do not modify the Slice-1-stable
write_outputs module.

Slice 5 implements the新增 (new-major) surface:
    - identify_new_majors(unmatched, history) -> list[DaglubenRow]
    - write_new_major_table(new_majors_with_estimate, out_path) -> None

Slice 6 (this file, lower half) implements the remaining edge tables (spec §7):
    - 被删旧专业.xlsx        (Task 6.1)
    - 学校改名表.xlsx        (Task 6.2)
    - 新增校表.xlsx          (Task 6.2 — 未配对的大绿本独有校)
    - 停招消失校表.xlsx      (Task 6.2 — 未配对的历史独有校)
    - 特殊情况.xlsx          (Task 6.1 — 飞行不成/剩余无法匹配)

iteration-2 Slice D (issue #13) removed two dead functions:
``mark_newmajor_in_main`` and ``mark_rename_in_main`` were never called by
run_pipeline (the main-table J/T/log are filled directly in
``_build_main_results``); keeping them around invited stale-API confusion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import openpyxl

from scripts.models import DaglubenRow, HistoryRow, RenameRow

__all__ = [
    "identify_new_majors",
    "write_new_major_table",
    "write_deleted_major_table",
    "write_rename_table",
    "write_new_school_table",
    "write_gone_school_table",
    "write_special_table",
]


# ---------------------------------------------------------------------------
# Slice 5 — 新增专业 surface
# ---------------------------------------------------------------------------


def identify_new_majors(
    unmatched: list[DaglubenRow], history: list[HistoryRow]
) -> list[DaglubenRow]:
    """Keep unmatched大绿本 rows whose school has **no** same-core candidate.

    A真·新增 (spec §6 Stage 3 新增专业) is a大绿本专业 that has no history
    counterpart at its school *by core name*. Rows whose school does carry a
    history row with the same core name are NOT new — they are归一化伪影 /
    改名 / 无候选 and are handled by other Slice 6 edges. This function is
    deliberately conservative: only the absence of any same-school core match
    qualifies.

    School-scoped: a core name appearing at a *different* school does not
    disqualify a row.

    Parameters
    ----------
    unmatched
        大绿本 rows that survived Stage 1/1.5/2 without a match.
    history
        The unified近三年 history pool (any source table).

    Returns
    -------
    list[DaglubenRow]
        Subset of ``unmatched`` deemed truly new, in input order.
    """
    # Index history cores by school for O(1) lookup.
    school_cores: dict[str, set[str]] = {}
    for h in history:
        school = h.get("school", "")
        if not school:
            continue
        school_cores.setdefault(school, set()).add(h.get("core", ""))

    out: list[DaglubenRow] = []
    for d in unmatched:
        school = d.get("school", "")
        cores = school_cores.get(school, set())
        if d.get("core", "") in cores:
            continue  # 同校已有同 core 名 → 不是真新增
        out.append(d)
    return out


# 新增专业.xlsx columns. 统计线差估算 / 线差标准差估算 may be None
# (level 2 / no compatible T); 退化级别 0/1/2.
_NEW_MAJOR_HEADER: tuple[str, ...] = (
    "学校", "专业", "选科",
    "统计线差估算", "线差标准差估算",
    "退化级别", "样本量", "日志",
)

# Map record dict keys (from write_new_major_table input) to header labels.
_NEW_MAJOR_KEY_TO_HEADER = {
    "school": "学校",
    "major": "专业",
    "subject": "选科",
    "value": "统计线差估算",
    "T": "线差标准差估算",
    "level": "退化级别",
    "n": "样本量",
    "log": "日志",
}


def write_new_major_table(
    new_majors_with_estimate: list[dict[str, Any]], out_path: str | Path
) -> None:
    """Write ``新增专业.xlsx`` with estimate value, T, level, sample size, log.

    Columns: 学校 / 专业 / 选科 / 统计线差估算 / 线差标准差估算 / 退化级别 /
    样本量 / 日志. The 统计线差估算 and 线差标准差估算 columns come directly
    from the EstimateResult (V5-1 — T is estimated alongside J; either may be
    None at level 2 or when no compatible row carries a T).

    Idempotent: overwrites any existing file at ``out_path``. An empty input
    still produces a header-only workbook so downstream tooling can rely on
    the schema.
    """
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "新增专业"
    ws.append(list(_NEW_MAJOR_HEADER))
    for record in new_majors_with_estimate:
        ws.append([
            record.get("school", ""),
            record.get("major", ""),
            record.get("subject", ""),
            record.get("value"),
            record.get("T"),
            record.get("level"),
            record.get("n"),
            record.get("log", ""),
        ])
    wb.save(out_p)
    wb.close()


# ---------------------------------------------------------------------------
# Slice 6 — boundary edge tables + rename main-output marker
# ---------------------------------------------------------------------------
#
# All writers are idempotent (overwrite any existing file) and produce a
# header-only workbook for empty input so downstream tooling can rely on the
# schema. Column headers are Chinese per spec §7 (output artefacts are for
# human review).


def _write_simple_table(
    header: Sequence[str],
    rows: Sequence[dict[str, Any]],
    out_path: str | Path,
    sheet_title: str,
) -> None:
    """Shared writer: append header + rows to a fresh workbook."""
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title
    ws.append(list(header))
    for record in rows:
        ws.append([record.get(h, "") for h in header])
    wb.save(out_p)
    wb.close()


# --- 被删旧专业 -------------------------------------------------------------

_DELETED_HEADER: tuple[str, ...] = (
    "学校", "招生类别", "专业", "近三年统计线差", "近三年线差标准差", "日志",
)


def write_deleted_major_table(
    deleted: Sequence[dict[str, Any]], out_path: str | Path
) -> None:
    """Write ``被删旧专业.xlsx`` — history majors absent from 2026 at schools
    that still exist in 2026 (and are NOT renamed). Each row carries the
    original近三年 J/T and log ``近三年有、2026 大绿本无`` (spec §9).

    DeletedMajor fields (school/school_cat/major/J/T/log) are remapped to the
    header columns — ``_write_simple_table`` looks cells up by header name."""
    rows = [
        {
            "学校": r.get("school", ""),
            "招生类别": r.get("school_cat", ""),
            "专业": r.get("major", ""),
            "近三年统计线差": r.get("J"),
            "近三年线差标准差": r.get("T"),
            "日志": r.get("log", ""),
        }
        for r in deleted
    ]
    _write_simple_table(_DELETED_HEADER, rows, out_path, "被删旧专业")


# --- 学校改名表 -------------------------------------------------------------

_RENAME_HEADER: tuple[str, ...] = (
    "2026新校名", "候选旧校名", "置信度", "2026本科专业数", "备注", "人工已核验",
)


def write_rename_table(
    rename_rows: Sequence[RenameRow], out_path: str | Path
) -> None:
    """Write ``学校改名表.xlsx`` (spec §7). The ``备注`` column holds the
    web-search summary (Task 6.3) and ``manual_reviewed`` is surfaced as a
    boolean column ``人工已核验`` so humans can see which备注 are curated.

    RenameRow fields (new_school/old_school/confidence/major_count_2026/remark/
    manual_reviewed) are remapped to the header column names —
    ``_write_simple_table`` looks cells up by header name, so passing RenameRow
    directly left every cell empty (field name ≠ header name)."""
    rows = [
        {
            "2026新校名": r.get("new_school", ""),
            "候选旧校名": r.get("old_school") or "",
            "置信度": r.get("confidence", ""),
            "2026本科专业数": r.get("major_count_2026", 0),
            "备注": r.get("remark") or "",
            "人工已核验": bool(r.get("manual_reviewed", False)),
        }
        for r in rename_rows
    ]
    _write_simple_table(_RENAME_HEADER, rows, out_path, "学校改名表")


# --- 新增校表 (未配对的大绿本独有校) ----------------------------------------

_NEW_SCHOOL_HEADER: tuple[str, ...] = ("2026新校名", "2026本科专业数", "日志")


def write_new_school_table(
    new_schools: Sequence[dict[str, Any]], out_path: str | Path
) -> None:
    """Write ``新增校表.xlsx`` — 大绿本独有校 the agent did NOT pair with any
    history school (真新增校 / 无历史). Each record: ``{"new_school": str,
    "major_count_2026": int}``; the log is fixed."""
    rows = [
        {
            "2026新校名": r.get("new_school", r.get("school", "")),
            "2026本科专业数": r.get("major_count_2026", r.get("count", 0)),
            "日志": "2026 新增校，近三年无招生",
        }
        for r in new_schools
    ]
    _write_simple_table(_NEW_SCHOOL_HEADER, rows, out_path, "新增校")


# --- 停招消失校表 (未配对的历史独有校) --------------------------------------

_GONE_SCHOOL_HEADER: tuple[str, ...] = ("历史旧校名", "日志")


def write_gone_school_table(
    gone_schools: Sequence[dict[str, Any]], out_path: str | Path
) -> None:
    """Write ``停招消失校表.xlsx`` — 历史独有校 the agent did NOT pair (整校
    缺席 2026, 含独立学院转设消失). Each record: ``{"old_school": str}``."""
    rows = [
        {
            "历史旧校名": r.get("old_school", r.get("school", "")),
            "日志": "学校未在 2026 招生",
        }
        for r in gone_schools
    ]
    _write_simple_table(_GONE_SCHOOL_HEADER, rows, out_path, "停招消失校")


# --- 特殊情况 (飞行不成 / 剩余无法匹配) ------------------------------------

_SPECIAL_HEADER: tuple[str, ...] = (
    "src_row_idx", "学校", "招生类别", "专业", "核心名", "选科", "批次", "日志",
)


def write_special_table(
    special_rows: Sequence[dict[str, Any]], out_path: str | Path
) -> None:
    """Write ``特殊情况.xlsx`` — 飞行技术(军队) 提前批池匹配不成 + 其余无法
    归类的大绿本行. Each EdgeRow preserves the originating DaglubenRow fields
    (src_row_idx / school / major / core / subject / batch) + log (spec §9).

    EdgeRow fields are remapped to the header columns — ``_write_simple_table``
    looks cells up by header name."""
    rows = [
        {
            "src_row_idx": r.get("src_row_idx", 0),
            "学校": r.get("school", ""),
            "招生类别": r.get("school_cat", ""),
            "专业": r.get("major", ""),
            "核心名": r.get("core", ""),
            "选科": r.get("subject", ""),
            "批次": r.get("batch", ""),
            "日志": r.get("log", ""),
        }
        for r in special_rows
    ]
    _write_simple_table(_SPECIAL_HEADER, rows, out_path, "特殊情况")
