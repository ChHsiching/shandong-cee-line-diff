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
    LOG_COARSE_CANDIDATE,
    LOG_SUBJECT_NOTE,
)
from scripts.models import DaglubenRow, HistoryRow, MatchResult
from scripts.normalize import diff_brackets
from scripts.stage1_strict import normalise_cat, single_year_note

__all__ = [
    "build_core_idx",
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


def _accept(
    dagluben: DaglubenRow, candidate: HistoryRow, base_log: str
) -> MatchResult:
    """Build an accepted MatchResult, appending the选科 drift note and the
    single-year-T note if applicable."""
    log = base_log
    if _subject_differs(
        dagluben.get("subject", ""), candidate.get("subject", "")
    ):
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

    for d in unmatched:
        key = _dagluben_core_key(d)
        candidates = core_idx.get(key)
        if not candidates:
            still.append(d)
            continue

        if len(candidates) == 1:
            accepted.append(_accept(d, candidates[0], LOG_COARSE_CANDIDATE))
            continue

        # Multi-candidate: keep only those whose differentiated brackets are
        # all substrings of the大绿本 major全名.
        dl_major = d.get("major", "")
        compatible = [
            c for c in candidates if _brackets_subset_of(c.get("major", ""), dl_major)
        ]
        if len(compatible) == 1:
            accepted.append(_accept(d, compatible[0], _disambig_log(compatible[0])))
        else:
            # Zero compatible or >=2 compatible -> ambiguous -> Stage 2.
            still.append(d)

    return accepted, still
