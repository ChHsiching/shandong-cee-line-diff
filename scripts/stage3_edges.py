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
so the caller can subtract the大绿本 专业集合 to find true被删.
"""

from __future__ import annotations

from typing import Sequence, TypedDict

from scripts.constants import (
    LOG_DELETED,
    LOG_FLIGHT_UNMATCHED,
    LOG_VERIFY_DEMOTE_PREFIX,
)
from scripts.models import DaglubenRow, EstimateResult, HistoryRow

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
    # 估算（仅「对不上」的 other 行填；飞行/无历史的不填）：同校同选科均值。
    # 用户口径（2026-07-08）：同核心多对一/类别对不上 = 无有效对应 → 按新专业
    # 估算同校同选科均值 + 备注，不留在表里空着。
    est_value: float | None  # 统计线差估算
    est_t: float | None  # 线差标准差估算
    est_level: int  # 0=同校同选科 1=同校全专业 2=无法估算
    est_n: int  # 用了几条往年数据


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


def _unmatched_log(d: DaglubenRow, history: Sequence[HistoryRow]) -> str:
    """#17: 写具体的无法匹配原因，不笼统。同校同核心名有候选时列出，否则只给 core。"""
    school = d.get("school", "")
    core = d.get("core", "") or d.get("major", "")
    cands = [
        h.get("major", "")
        for h in history
        if h.get("school", "") == school and h.get("core", "") == d.get("core", "")
    ]
    if cands:
        brief = "/".join(cands[:3]) + ("…" if len(cands) > 3 else "")
        return (
            f"没找到能匹配的往年专业：同校同核心名有 {len(cands)} 个"
            f"（{brief}），今年的方向和这些都对不上"
        )
    return f"没找到能匹配的往年专业：{core}"


def flight_and_special(
    flight_unmatched: Sequence[DaglubenRow],
    other_unmatched: Sequence[DaglubenRow],
    demoted_map: dict[int, str] | None = None,
    history: Sequence[HistoryRow] | None = None,
    estimates: dict[int, EstimateResult] | None = None,
) -> list[EdgeRow]:
    """Route flight(军队) and remaining-unmatched大绿本 rows to the特殊表.

    Parameters
    ----------
    flight_unmatched
        飞行技术(军队) 大绿本 rows (``batch == FLIGHT_BATCH``) that did not match
        in the提前批 pool. Per spec §6 Stage 3 they go to the特殊表 with log
        ``飞行技术(军队)，提前批池匹配不成``.
    other_unmatched
        Remaining大绿本 rows that survived Stage 1/2 + new-major + rename
        classification without a home — unclassifiable edge cases. Log:
        ``没找到能匹配的往年专业：<具体原因>`` (#17: 同校同核心名候选摘要).
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
            log = _unmatched_log(d, history or [])
        edge = EdgeRow(
            src_row_idx=idx,
            school=d.get("school", ""),
            school_cat=d.get("school_cat", ""),
            major=d.get("major", ""),
            core=d.get("core", ""),
            subject=d.get("subject", ""),
            batch=d.get("batch", ""),
            log=log,
        )
        # 对不上的行（同核心多对一/类别冲突）→ 按同校同选科均值估算（用户口径
        # 2026-07-08：不留在表里空着）。飞行/无历史的不估（estimates 不含它们）。
        est = (estimates or {}).get(idx)
        if est is not None:
            edge["est_value"] = est.get("value")
            edge["est_t"] = est.get("T")
            edge["est_level"] = est.get("level")
            edge["est_n"] = est.get("n")
        out.append(edge)
    return out
