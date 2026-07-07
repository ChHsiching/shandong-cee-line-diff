"""Slice 6 Task 6.1 — boundary edges: deleted / flight / special.

Per Plan v2 CRITICAL order: Task 6.2 (rename detection) runs **before** this
module's ``deleted_majors`` so that renamed schools' historical majors are
excluded from the被删 table — otherwise a renamed school's pre-rename majors
(the old school name) would satisfy「近三年有 + 2026 缺」and be misclassified
as deleted.

Spec §6 Stage 3 boundary semantics:
  - **被删旧专业**: 近三年有 + 该校(基础校名)在2026大绿本存在 + 2026缺 + 该校
    非改名校 (renamed_dgl_schools 排除). Log: ``近三年有、2026 大绿本无``.
  - **飞行技术(军队) 2 行** (batch=FLIGHT_BATCH): 归入提前批池参与匹配;
    不成则入特殊表. Log: ``飞行技术(军队)，提前批池匹配不成``.
  - **特殊/无法处理**: 剩余无法匹配的大绿本专业. Log: ``无法匹配：<原因>``.

Note on被删 2026-缺判定: :func:`deleted_majors` operates on the history pool
plus a ``dgl_present`` set (which schools exist in 2026). The「2026 缺该专业」
reduction is the caller's responsibility (it has the大绿本 专业集合); this
function returns the history rows whose school is present but is NOT renamed,
so the caller can subtract the大绿本 专业集合 to find true被删. See
``run_rename_smoke.py`` for the full reduction.
"""

from __future__ import annotations

from typing import Sequence, TypedDict

from scripts.constants import (
    LOG_DELETED,
    LOG_FLIGHT_UNMATCHED,
    LOG_VERIFY_DEMOTE_PREFIX,
)
from scripts.models import DaglubenRow, HistoryRow

__all__ = [
    "DeletedMajor",
    "EdgeRow",
    "deleted_majors",
    "flight_and_special",
]


# TypedDicts (total=False) keep the row payloads JSON/CSV-serialisable while
# giving downstream writers a stable schema. They reuse HistoryRow/DaglubenRow
# field names where fields overlap. Defined locally (not in models.py) because
# they are edge-table-specific and only Slice 6 writers consume them.
class DeletedMajor(TypedDict, total=False):
    """A近三年 history major deemed被删 in 2026.

    Carries the original history line-diff (J/T) so the被删旧专业 table can
    show what the major used to admit at, alongside the log.
    """

    school: str
    school_cat: str
    major: str
    J: float | None
    T: float | None
    log: str


class EdgeRow(TypedDict, total=False):
    """A大绿本 row routed to the特殊情况 table (flight-unmatched / unmatchable)."""

    src_row_idx: int
    school: str
    school_cat: str
    major: str
    core: str
    subject: str
    batch: str
    log: str


# ---------------------------------------------------------------------------
# deleted_majors
# ---------------------------------------------------------------------------


def deleted_majors(
    history: Sequence[HistoryRow],
    dgl_schools_present: set[str],
    renamed_dgl_schools: set[str],
) -> list[DeletedMajor]:
    """History majors whose school is present in 2026 but is NOT a renamed one.

    Parameters
    ----------
    history
        The unified近三年 history pool (regular + early batches).
    dgl_schools_present
        Base school names that appear in the 2026 大绿本. Rows whose school is
        absent from this set are整校缺席 and belong in the停招消失校表, not the
        被删表.
    renamed_dgl_schools
        大绿本 school names the rename step (Task 6.2) confirmed as renamed.
        Their historical majors (under the OLD school name) are NOT被删 — they
        are the same school's pre-rename catalogue and are flagged separately
        in the main output. Excluding them here is the v2 CRITICAL-order fix.

    Returns
    -------
    list[DeletedMajor]
        History rows whose school is present in 2026 and not renamed, each
        carrying ``J``/``T``/``school``/``major`` and log
        ``近三年有、2026 大绿本无``. Input order preserved.
    """
    # The renamed_dgl_schools are the NEW (大绿本) school names. Historical
    # rows for the same school carry the OLD name (which is NOT in
    # dgl_schools_present because the old name disappeared), so they are
    # already excluded by the dgl_schools_present membership test. We keep
    # the renamed_dgl_schools parameter for defensive double-exclusion: if a
    # caller passes the merged (old+new) present-set, renamed schools' rows
    # are still filtered out.
    present = dgl_schools_present - renamed_dgl_schools

    out: list[DeletedMajor] = []
    for h in history:
        school = h.get("school", "")
        if school not in present:
            continue
        out.append(
            DeletedMajor(
                school=school,
                school_cat=h.get("school_cat", ""),
                major=h.get("major", ""),
                J=h.get("J"),
                T=h.get("T"),
                log=LOG_DELETED,
            )
        )
    return out


# ---------------------------------------------------------------------------
# flight_and_special
# ---------------------------------------------------------------------------


def flight_and_special(
    flight_unmatched: Sequence[DaglubenRow],
    other_unmatched: Sequence[DaglubenRow],
    demoted_map: dict[int, str] | None = None,
) -> list[EdgeRow]:
    """Route flight(军队) and remaining-unmatched大绿本 rows to the特殊表.

    Parameters
    ----------
    flight_unmatched
        飞行技术(军队) 大绿本 rows (``batch == FLIGHT_BATCH``) that did not match
        in the提前批 pool. Per spec §6 Stage 3 they go to the特殊表 with log
        ``飞行技术(军队)，提前批池匹配不成``.
    other_unmatched
        Remaining大绿本 rows that survived Stage 1/1.5/2 + new-major + rename
        classification without a home — unclassifiable edge cases. Log:
        ``无法匹配：<原因>``.
    demoted_map
        Plan v2 阻断2: ``{src_row_idx: reason}`` for rows the V5-0 second-pass
        verification judged存疑. Such rows carry log ``复核存疑：<原因>``
        (bypassing the generic ``无法匹配`` fallback so the special table
        explains *why* the main-table match was rejected).

    Returns
    -------
    list[EdgeRow]
        Flight rows first (in input order), then other-unmatched rows. Each
        EdgeRow preserves the originating DaglubenRow's identifying fields
        (src_row_idx / school / major / core / subject / batch) for human
        review.
    """
    demoted_map = demoted_map or {}
    out: list[EdgeRow] = []
    for d in flight_unmatched:
        idx = d.get("src_row_idx", 0)
        if idx in demoted_map:
            log = f"{LOG_VERIFY_DEMOTE_PREFIX}：{demoted_map[idx]}"
        else:
            log = LOG_FLIGHT_UNMATCHED
        out.append(
            EdgeRow(
                src_row_idx=idx,
                school=d.get("school", ""),
                school_cat=d.get("school_cat", ""),
                major=d.get("major", ""),
                core=d.get("core", ""),
                subject=d.get("subject", ""),
                batch=d.get("batch", ""),
                log=log,
            )
        )
    for d in other_unmatched:
        idx = d.get("src_row_idx", 0)
        if idx in demoted_map:
            log = f"{LOG_VERIFY_DEMOTE_PREFIX}：{demoted_map[idx]}"
        else:
            log = f"没找到能匹配的往年专业：{d.get('core', '') or d.get('major', '')}"
        out.append(
            EdgeRow(
                src_row_idx=idx,
                school=d.get("school", ""),
                school_cat=d.get("school_cat", ""),
                major=d.get("major", ""),
                core=d.get("core", ""),
                subject=d.get("subject", ""),
                batch=d.get("batch", ""),
                log=log,
            )
        )
    return out
