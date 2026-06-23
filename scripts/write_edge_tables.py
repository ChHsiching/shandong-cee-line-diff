"""Edge/boundary table writers (新增/被删/特殊/改名/新增校/停招校).

Per Plan v2 binding, these are separated from write_outputs.py so that
Slices 5/6 (which populate them) do not modify the Slice-1-stable
write_outputs module.

Slice 5 implements the新增 (new-major) surface:
    - identify_new_majors(unmatched, history) -> list[DaglubenRow]
    - mark_newmajor_in_main(dagluben_rows, estimates) -> list[dict]
    - write_new_major_table(new_majors_with_estimate, out_path) -> None

Tables to produce (spec §7):
    - 新增专业.xlsx        (Slice 5)  <- implemented here
    - 被删旧专业.xlsx      (Slice 6)
    - 学校改名表.xlsx      (Slice 6)
    - 新增校表.xlsx        (Slice 6)
    - 停招消失校表.xlsx    (Slice 6)
    - 特殊情况.xlsx        (Slice 6)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from scripts.models import DaglubenRow, EstimateResult, HistoryRow

__all__ = [
    "identify_new_majors",
    "mark_newmajor_in_main",
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


def mark_newmajor_in_main(
    dagluben_rows: list[DaglubenRow],
    estimates: dict[int, EstimateResult],
) -> list[dict[str, Any]]:
    """Attach new-major estimate to main-output rows.

    Each大绿本 row becomes a main-output record carrying the original fields
    plus, when an estimate exists for its ``src_row_idx``:
        - ``J`` = estimate value (may be None for level 2)
        - ``log`` = estimate log (transparent口径)
        - ``is_new_major`` = True

    Rows without an estimate pass through with ``is_new_major`` absent so
    downstream writers can distinguish them.
    """
    out: list[dict[str, Any]] = []
    for d in dagluben_rows:
        idx = d.get("src_row_idx", 0)
        est = estimates.get(idx)
        record: dict[str, Any] = dict(d)
        if est is not None:
            record["J"] = est.get("value")
            record["log"] = est.get("log", "")
            record["is_new_major"] = True
        out.append(record)
    return out


# 新增专业.xlsx columns. 统计线差估算 may be None (level 2); 退化级别 0/1/2.
_NEW_MAJOR_HEADER: tuple[str, ...] = (
    "学校", "专业", "选科", "统计线差估算", "退化级别", "样本量", "日志",
)

# Map record dict keys (from write_new_major_table input) to header labels.
_NEW_MAJOR_KEY_TO_HEADER = {
    "school": "学校",
    "major": "专业",
    "subject": "选科",
    "value": "统计线差估算",
    "level": "退化级别",
    "n": "样本量",
    "log": "日志",
}


def write_new_major_table(
    new_majors_with_estimate: list[dict[str, Any]], out_path: str | Path
) -> None:
    """Write ``新增专业.xlsx`` with estimate value, level, sample size, log.

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
            record.get("level"),
            record.get("n"),
            record.get("log", ""),
        ])
    wb.save(out_p)
    wb.close()


# ---------------------------------------------------------------------------
# Slice 6 stubs — not implemented in this slice
# ---------------------------------------------------------------------------


def write_deleted_major_table(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError("Slice 6 (被删/飞行/特殊) implements this.")


def write_rename_table(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError("Slice 6 (学校改名) implements this.")


def write_new_school_table(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError("Slice 6 implements this.")


def write_gone_school_table(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError("Slice 6 implements this.")


def write_special_table(*args, **kwargs):  # pragma: no cover
    raise NotImplementedError("Slice 6 implements this.")
