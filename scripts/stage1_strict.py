"""Stage 1 — strict matching (spec §6 Stage 1).

Strict key = ``(基础校名, 招生类别, 剥忽略类括号后的归一化全名)``.

招生类别 normalisation: the普通计划 track is the default. 大绿本 marks it
explicitly as ``普通计划`` while近三年 omits the suffix (empty). Both encode
the same普通 track, so they are folded to a single canonical value before
keying. Non-empty special tracks (中外合作办学 / 地方专项计划 / …) must match
exactly — they are different admission tracks with different cutoff lines
(spec §5.2 element 6).
"""

from __future__ import annotations

from typing import Iterable

from scripts.constants import LOG_STRICT
from scripts.models import DaglubenRow, HistoryRow, MatchResult

__all__ = ["match_strict", "normalise_cat", "single_year_note", "LOG_MISS"]

LOG_MISS = "未命中"

# 大绿本 subtitle for the default普通 track; folded to "" (= history default).
DEFAULT_CAT_DAGLUBEN = "普通计划"

# V5-1: 近三年 rows with only a single year of data have no defined standard
# deviation (T). Such matched rows leave T=None and the match log appends this
# note so a reviewer sees why T is blank. Shared by stage1_strict /
# stage1_5_coarse / stage2_apply (Plan v2 binding — three anchors, one helper).
LOG_SINGLE_YEAR_NOTE = "（单年数据，无标准差）"


def single_year_note(hist: HistoryRow) -> str:
    """Return the single-year-T annotation if ``hist`` has no T, else "".

    A matched近三年 row whose ``T`` is None was computed from a single year
    of data (standard deviation is undefined for n<2). Per V5-1 the match log
    must annotate this so the blank T is not mistaken for missing data.
    """
    return LOG_SINGLE_YEAR_NOTE if hist.get("T") is None else ""


def normalise_cat(cat: str) -> str:
    """Fold the default普通 track to "" on both sides of the match.

    Near-three-year rows carry an empty category for普通; 大绿本 writes the
    explicit ``普通计划`` subtitle. Anything else is a real differentiated
    admission track and passes through unchanged.
    """
    return "" if cat == DEFAULT_CAT_DAGLUBEN else cat


def _history_key(row: HistoryRow) -> tuple[str, str, str]:
    return (
        row.get("school", ""),
        normalise_cat(row.get("school_cat", "")),
        row.get("stripped", ""),
    )


def _dagluben_key(row: DaglubenRow) -> tuple[str, str, str]:
    return (
        row.get("school", ""),
        normalise_cat(row.get("school_cat", "")),
        row.get("stripped", ""),
    )


def match_strict(
    dagluben: Iterable[DaglubenRow],
    history: Iterable[HistoryRow],
) -> list[MatchResult]:
    """Match each大绿本 row against history by the strict 3-tuple key.

    Returns one :class:`MatchResult` per大绿本 row in input order. Matched
    rows carry the history J/T and :data:`LOG_STRICT`; unmatched rows carry
    ``J=None`` and :data:`LOG_MISS`.

    When multiple history rows share a key (a real duplicate), the first one
    wins — Stage 1 is strict-by-equality and does not attempt disambiguation
    (that is Stage 1.5 / Stage 2's job).
    """
    # Build the lookup, keeping the first history row per key (deterministic).
    index: dict[tuple[str, str, str], HistoryRow] = {}
    for h in history:
        key = _history_key(h)
        if key not in index:
            index[key] = h

    out: list[MatchResult] = []
    for d in dagluben:
        key = _dagluben_key(d)
        h = index.get(key)
        if h is not None:
            note = single_year_note(h)
            log = LOG_STRICT if not note else f"{LOG_STRICT}；{note}"
            out.append(
                MatchResult(
                    src_row_idx=d.get("src_row_idx", 0),
                    school=d.get("school", ""),
                    school_cat=d.get("school_cat", ""),
                    major=d.get("major", ""),
                    matched=True,
                    J=h.get("J"),
                    T=h.get("T"),
                    log=log,
                )
            )
        else:
            out.append(
                MatchResult(
                    src_row_idx=d.get("src_row_idx", 0),
                    school=d.get("school", ""),
                    school_cat=d.get("school_cat", ""),
                    major=d.get("major", ""),
                    matched=False,
                    J=None,
                    T=None,
                    log=LOG_MISS,
                )
            )
    return out
