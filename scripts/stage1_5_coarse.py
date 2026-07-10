"""Stage 1.5 — core-name coarse match with bracket-subset disambiguation.

Spec §6 Stage 1.5 (prototype-validated, 74.4% cumulative auto coverage):

For Stage 1 misses, bucket the unified history by
``(基础校名, 招生类别, 核心名)`` and look up each unmatched大绿本 row:

  - **No candidate**         -> still unmatched (真新增 / 改名 / 归一化伪影).
  - **Exactly one candidate** -> auto-accept. Per prototype evidence: 大绿本
    2026 names are far more detailed than近三年 (子专业清单 / 校区 / 培养描述 /
    国际交流长文), so core-name alignment alone is sufficient. **Signature
    equality is explicitly banned** (全等仅 0%).
  - **Multiple candidates**   -> disambiguate by「近三年候选差异化括号 ⊂
    大绿本全名」: every diff_bracket (性别 / 合作 / 其他) of the candidate must
    appear as a substring of the大绿本 major全名. Exactly one compatible
    candidate -> accept (log ``粗筛匹配：括号子集消歧（<简述>）``); zero or
    more than one compatible -> still unmatched (Stage 2 territory).

选科 (subject) is non-differentiated (spec §5.4): it never enters the key,
and a mismatch logs ``选科要求跨年不同，不影响匹配`` so a reviewer can see the drift.

招生类别 (spec §5.2 element 6) IS differentiated: 普通 vs 中外合作 etc. are
different admission tracks with different cutoffs and so live in different
buckets. The default「普通计划」/「」folding is reused from :mod:`stage1_strict`
so the coarse key is consistent with the strict key.
"""

from __future__ import annotations

from typing import Iterable

from scripts.constants import (
    LOG_COARSE_CANDIDATE,
    LOG_SUBJECT_NOTE,
)
from scripts.models import DaglubenRow, HistoryRow, MatchResult
from scripts.normalize import diff_brackets
from scripts.stage1_strict import normalise_cat, single_year_note
from scripts.stage2_agent import _core_compatible

__all__ = [
    "build_core_idx",
    "build_core_school_idx",
    "match_coarse",
    "LOG_MISS",
]

LOG_MISS = "未命中"


CoreKey = tuple[str, str, str]
CoreIndex = dict[CoreKey, list[HistoryRow]]


def build_core_idx(history: Iterable[HistoryRow]) -> CoreIndex:
    """Bucket history rows by ``(school, normalise_cat(school_cat), core)``.

    The default「普通计划」/「」folding is applied so a dagluben row whose
    招生类别 is ``普通计划`` lands in the same bucket as a history row with an
    empty category (both encode the普通 default track).
    """
    idx: CoreIndex = {}
    for h in history:
        key: CoreKey = (
            h.get("school", ""),
            normalise_cat(h.get("school_cat", "")),
            h.get("core", ""),
        )
        idx.setdefault(key, []).append(h)
    return idx


def build_core_school_idx(history: Iterable[HistoryRow]) -> dict[str, list[HistoryRow]]:
    """Bucket history rows by ``school`` only (ignoring 招生类别 + core).

    Used by :func:`match_coarse` as a **跨类别回退**：当同校同类别同核心一个候选
    都没有时（今年普通、往年只招过中外合作 school-level），退到同校、用
    :func:`scripts.stage2_agent._core_compatible` 找核心兼容的——让「名头变了的
    往年专业」也能被 past=1 配上（用户口径 2026-07-09：往年只有一个，无论什么
    方向/名头，今年直接用它的分）。
    """
    idx: dict[str, list[HistoryRow]] = {}
    for h in history:
        idx.setdefault(h.get("school", ""), []).append(h)
    return idx


def _dagluben_core_key(row: DaglubenRow) -> CoreKey:
    return (
        row.get("school", ""),
        normalise_cat(row.get("school_cat", "")),
        row.get("core", ""),
    )


def _brackets_subset_of(candidate_major: str, dl_major: str) -> bool:
    """True iff every diff_bracket of ``candidate_major`` appears as a
    substring of ``dl_major``.

    A candidate with no differentiated brackets trivially satisfies the subset
    requirement (vacuous truth) — this is intentional: a bare「数学」candidate
    is compatible with any「数学(…)」dagluben row. The disambiguation rule's
    job is to reject candidates whose brackets are NOT in the大绿本全名, not
    to require any particular bracket be present.
    """
    for _kind, value in diff_brackets(candidate_major):
        if value not in dl_major:
            return False
    return True


def _disambig_log(candidate: HistoryRow) -> str:
    """Build the「括号子集消歧」log suffix with a short bracket summary."""
    diffs = diff_brackets(candidate.get("major", ""))
    if not diffs:
        brief = "无差异化括号"
    else:
        # Use the first bracket's value (truncated) as the human hint.
        first_val = diffs[0][1]
        brief = first_val[:10] + ("…" if len(first_val) > 10 else "")
    return f"{LOG_COARSE_CANDIDATE}（{brief}）"


def _subject_differs(dl_subject: str, hist_subject: str) -> bool:
    """Compare选科 strings for drift. Empty either side is treated as
    'no drift' (we only log when both are present and disagree)."""
    a = (dl_subject or "").strip()
    b = (hist_subject or "").strip()
    if not a or not b:
        return False
    return a != b


def _accept(dagluben: DaglubenRow, candidate: HistoryRow, base_log: str) -> MatchResult:
    """Build an accepted MatchResult, appending the选科 drift note and the
    single-year-T note if applicable."""
    log = base_log
    if _subject_differs(dagluben.get("subject", ""), candidate.get("subject", "")):
        log = f"{log}；{LOG_SUBJECT_NOTE}"
    note = single_year_note(candidate)
    if note:
        log = f"{log}；{note}"
    return MatchResult(
        src_row_idx=dagluben.get("src_row_idx", 0),
        school=dagluben.get("school", ""),
        school_cat=dagluben.get("school_cat", ""),
        major=dagluben.get("major", ""),
        matched=True,
        J=candidate.get("J"),
        T=candidate.get("T"),
        log=log,
    )


def match_coarse(
    unmatched: Iterable[DaglubenRow],
    core_idx: CoreIndex,
    core_school_idx: dict[str, list[HistoryRow]] | None = None,
) -> tuple[list[MatchResult], list[DaglubenRow]]:
    """Run the Stage 1.5 coarse matcher over Stage 1's unmatched rows.

    Returns ``(auto_accepted, still_unmatched)``:
      - ``auto_accepted`` — :class:`MatchResult` rows that Stage 1.5 resolved
        (unique core candidate, or a single bracket-subset-compatible
        candidate out of many).
      - ``still_unmatched`` — the original :class:`DaglubenRow` rows that
        Stage 1.5 could not resolve (no candidate, or ambiguous after
        bracket-subset disambiguation). These are the input to Stage 2.

    Input order is preserved in both output lists.
    """
    accepted: list[MatchResult] = []
    still: list[DaglubenRow] = []
    school_idx = core_school_idx or {}

    for d in unmatched:
        dl_core = d.get("core", "")
        dl_cat_raw = d.get("school_cat", "") or ""
        dl_cat_norm = normalise_cat(dl_cat_raw)

        # 1) 同校同类别、核心精确一致（past=1 exact）→ 直接配。
        same_cat = core_idx.get(_dagluben_core_key(d), [])
        if len(same_cat) == 1:
            accepted.append(_accept(d, same_cat[0], LOG_COARSE_CANDIDATE))
            continue

        # 2) 同类别、核心大类↔具体（X↔X类）：exact 没配上、但同类别下 _core_compatible
        #    只 1 条 → 也是 past=1，直接配。fresh-test run10：3 条 X↔X类（生物科学↔
        #    生物科学类、工商管理↔工商管理类）同类别只 1 条、但跨类别还有别的，旧版
        #    any_cat>1 把它们漏进了 Stage2（带 1 候选进 agent）。同类别 past=1 就该
        #    程序配，不该麻烦 agent（也让「batch 里只 2+ 候选」的文档自洽）。
        same_cat_compat = [
            h
            for h in school_idx.get(d.get("school", ""), [])
            if normalise_cat(h.get("school_cat", "")) == dl_cat_norm
            and _core_compatible(dl_core, h.get("core", ""))
        ]
        if len(same_cat_compat) == 1:
            note = (
                "（注：今年该专业与往年记录的核心名属大类↔具体关系"
                "（如「化学」对「化学类」），招生类别相同；"
                "同校该类别往年只有这一条记录，按规则沿用它的线差）"
            )
            accepted.append(_accept(d, same_cat_compat[0], LOG_COARSE_CANDIDATE + note))
            continue

        # 3) 跨类别回退：同类别无候选，退到同校任意类别、_core_compatible 只 1 条——
        #    让「今年普通、往年只招过中外合作(校名级)」这种也能 past=1 配上（用户口径：
        #    往年只有一个、无论什么名头/方向，今年直接用它的分）。
        any_cat = [
            h
            for h in school_idx.get(d.get("school", ""), [])
            if _core_compatible(dl_core, h.get("core", ""))
        ]
        if len(any_cat) == 1:
            # 走到这说明同类别 0 候选（步骤 2 没配上），这 1 条必是跨类别的。
            mh = any_cat[0]
            note = (
                "（注：今年与往年的招生类别不同，例如今年普通批、往年只招过中外合作；"
                "同校该专业往年只有这一条记录，按规则仍把它的线差作为参考填入）"
            )
            if "综合评价" in (d.get("major", "") or "") or "综合评价" in dl_cat_raw:
                note += (
                    "；今年是综合评价招生=高考分+大学校测+学业考复合录取，"
                    "往年该校只有普通批=纯高考分录取，两类分数线差口径不同，"
                    "此处填的是普通批的线差、仅作参考，不等于综合评价的真实门槛"
                )
            accepted.append(_accept(d, mh, LOG_COARSE_CANDIDATE + note))
            continue

        # 0 或 2+ → Stage 2 agent（旧 multi-candidate bracket-subset 消歧已停用）
        still.append(d)

    return accepted, still
