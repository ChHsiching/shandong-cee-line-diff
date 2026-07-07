"""Stage 3 — 新增专业 graded-fallback estimation (spec §6 Stage 3 新增专业).

A 大绿本专业 that no history row pairs with (真·新增 — see
:func:`scripts.write_edge_tables.identify_new_majors`) is estimated by a
three-level degradation, each level transparently logged for human review:

    退化0: 同校 + 选科集合包含 的历史专业 `统计线差` 均值
           log: 新增专业：估算=同校同选科(<n>)均值=<值>
    退化1: 同校无同选科 → 同校全部有统计线差者的均值
           log: 新增专业：退化=同校全专业均值(无同选科)(<n>)=<值>
    退化2: 整校无历史 → value=None
           log: 新校/无历史，无法估算

选科集合包含 (grilling Q3: 37.5% of 近三年 rows are multi-valued across
years, joined by ` | `):
    近三年 subject `物理 | 物理和化学` splits on ` | ` into year variants;
    any variant (itself split on 「和」 into subject atoms) ⊇ 新专业选科
    (split on 「和」) ⇒ compatible.

Pure functions only — no I/O.
"""

from __future__ import annotations

import statistics

from scripts.models import DaglubenRow, EstimateResult, HistoryRow

__all__ = ["select_kit_compatible", "estimate"]


# 选科原子分隔符：大绿本/近三年 单一年份内多科目用「和」连接 (物理和化学)。
_SUBJECT_ATOM_SEP = "和"
# 近三年跨年份多值分隔符 (grilling Q3: 37.5% 多值，按 ` | ` 拼接)。
_YEAR_VARIANT_SEP = " | "


def _subject_atoms(subject: str) -> frozenset[str]:
    """Split a single year-variant subject string into its atom set.

    ``"物理和化学"`` -> ``frozenset({"物理", "化学"})``.
    Empty input -> empty set (空集 ⊆ 任意集合).
    """
    cleaned = (subject or "").strip()
    if not cleaned:
        return frozenset()
    parts = [p for p in cleaned.split(_SUBJECT_ATOM_SEP) if p]
    return frozenset(parts)


def select_kit_compatible(new_subject: str, history_subject: str) -> bool:
    """True iff ``history_subject`` (one近三年 row) covers ``new_subject``.

    近三年 rows span three years; when the选科 policy drifted across years
    the cell is the variants joined by ``" | "`` (e.g. ``物理 | 物理和化学``).
    Each variant is a single year's requirement. The row is *compatible* with
    a new major's requirement iff **some** year-variant's atom set is a
    superset of the new major's atom set — i.e. the school has, in some year,
    required at least everything the new major requires.

    The new major's requirement is taken from the大绿本 cell (single-valued),
    split on 「和」 into atoms.
    """
    new_atoms = _subject_atoms(new_subject)
    # Empty new requirement (不限) matches any history variant.
    if not new_atoms:
        return True

    history_raw = (history_subject or "").strip()
    if not history_raw:
        # 历史行无选科信息 — 无法证明兼容；按 spec 保守视为不兼容，
        # 让 level0 失败退化到 level1，口径更稳。
        return False

    variants = [v.strip() for v in history_raw.split(_YEAR_VARIANT_SEP)]
    for variant in variants:
        if new_atoms <= _subject_atoms(variant):
            return True
    return False


def _level0_value(
    new_major: DaglubenRow, school_history: list[HistoryRow]
) -> tuple[float | None, int]:
    """Mean of J over same-school, kit-compatible history rows that have a J.

    Returns ``(mean, n)`` where n is the count of contributing rows. If no
    compatible row carries a J, returns ``(None, 0)`` and the caller falls
    back to level 1.
    """
    new_subject = new_major.get("subject", "")
    js = [
        h["J"]
        for h in school_history
        if h.get("J") is not None
        and select_kit_compatible(new_subject, h.get("subject", ""))
    ]
    if not js:
        return None, 0
    return statistics.fmean(js), len(js)


def _level0_T(new_major: DaglubenRow, school_history: list[HistoryRow]) -> float | None:
    """Mean of T over same-school, kit-compatible history rows that have a T.

    Rows whose T is None are excluded (V5-1). Returns None if no compatible
    row carries a T.
    """
    new_subject = new_major.get("subject", "")
    ts = [
        h["T"]
        for h in school_history
        if h.get("T") is not None
        and select_kit_compatible(new_subject, h.get("subject", ""))
    ]
    if not ts:
        return None
    return statistics.fmean(ts)


def _level1_value(school_history: list[HistoryRow]) -> tuple[float | None, int]:
    """Mean of J over all same-school history rows that have a J."""
    js = [h["J"] for h in school_history if h.get("J") is not None]
    if not js:
        return None, 0
    return statistics.fmean(js), len(js)


def _level1_T(school_history: list[HistoryRow]) -> float | None:
    """Mean of T over all same-school history rows that have a T (V5-1)."""
    ts = [h["T"] for h in school_history if h.get("T") is not None]
    if not ts:
        return None
    return statistics.fmean(ts)


def _fmt_value(v: float) -> str:
    """Format a float for logs without a trailing .0 when it is integral."""
    s = format(v, ".4f").rstrip("0").rstrip(".")
    return s if s else "0"


def estimate(
    new_major_row: DaglubenRow, school_history: list[HistoryRow]
) -> EstimateResult:
    """Estimate a新增专业's statistical line-diff via graded fallback.

    Parameters
    ----------
    new_major_row
        The unmatched大绿本专业 row. Only ``school`` and ``subject`` are read.
    school_history
        History rows whose ``school`` equals the new major's school. Callers
        are expected to pre-filter by school; defensively, this function
        re-filters so a stray out-of-school row cannot pollute the mean.

    Returns
    -------
    EstimateResult
        ``{value, T, level, log, n}`` per Plan v2 binding + V5-1. ``level`` is
        0/1/2. J (``value``) and T are each the mean over their degradation
        level's rows (T excludes rows whose T is None), rounded to 2 decimals
        (V5-6). At level 2 both are None.
    """
    school = new_major_row.get("school", "")
    same_school = [h for h in school_history if h.get("school") == school]

    # 退化2: 整校无历史.
    if not same_school:
        return EstimateResult(
            value=None,
            T=None,
            level=2,
            n=0,
            log="新校/无历史，无法估算",
        )

    # 退化0: 同校 + 选科集合包含.
    value0, n0 = _level0_value(new_major_row, same_school)
    if value0 is not None:
        value0 = round(value0, 2)  # 舍入 2 位，匹配近三年源精度。
        t0 = _level0_T(new_major_row, same_school)
        t0 = round(t0, 2) if t0 is not None else None  # V5-6: T 也 round 2。
        log = f"新增专业：估算=同校同选科({n0})均值={_fmt_value(value0)}"
        return EstimateResult(value=value0, T=t0, level=0, n=n0, log=log)

    # 退化1: 同校无同选科 (或兼容行全无 J) → 同校全专业均值.
    value1, n1 = _level1_value(same_school)
    if value1 is not None:
        value1 = round(value1, 2)  # 舍入 2 位，匹配近三年源精度。
        t1 = _level1_T(same_school)
        t1 = round(t1, 2) if t1 is not None else None  # V5-6: T 也 round 2。
        log = f"新增专业：退化=同校全专业均值(无同选科)({n1})={_fmt_value(value1)}"
        return EstimateResult(value=value1, T=t1, level=1, n=n1, log=log)

    # 同校历史行存在但全部 J=None → 仍无法估算，记 level2 口径.
    return EstimateResult(
        value=None,
        T=None,
        level=2,
        n=0,
        log="新校/无历史，无法估算",
    )
