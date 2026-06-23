"""Stage 2 — apply agent semantic-match results back into the main table.

Reads ``batch_NN_result.jsonl`` files (written by the harness after agent
dispatch — see ``semantic-match/RUN.md``) and back-fills ``match`` / ``J`` /
``T`` / ``reason`` into :class:`MatchResult` rows.

Contract enforcement (hard rejects — never silently corrupt the main table):

  - ``match`` is ``null`` or a string present in that dagluben row's
    candidate set (same school, core-name pre-filtered). Out-of-candidate
    matches raise :class:`Stage2ContractError` (agent hallucination).
  - Each ``src_row_idx`` appears at most once across all inputs. Duplicates
    raise.
  - ``reason`` is a non-empty string.
  - ``src_row_idx`` corresponds to a dagluben row actually handed to the
    agent (present in ``dagluben``).
  - Each line is valid JSON with the required keys.

A rejected line carries its source file + 1-based line number in the
exception message so the harness run can pinpoint the offender.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Sequence

from scripts.constants import LOG_SEMANTIC_NULL_PREFIX, LOG_SEMANTIC_PREFIX, LOG_SUBJECT_DRIFT
from scripts.models import DaglubenRow, HistoryRow, MatchResult
from scripts.stage1_strict import normalise_cat
from scripts.stage2_agent import _core_compatible  # reuse the pre-filter

__all__ = [
    "Stage2ContractError",
    "apply_results",
    "REQUIRED_KEYS",
]

REQUIRED_KEYS: tuple[str, ...] = (
    "src_row_idx",
    "school",
    "major",
    "match",
    "J",
    "T",
    "reason",
)


class Stage2ContractError(ValueError):
    """Raised when a result jsonl line violates the Stage 2 contract."""


def _candidate_set(
    dagluben: DaglubenRow, history: Sequence[HistoryRow]
) -> set[str]:
    """The set of近三年 major strings the agent was allowed to pick from for
    this dagluben row. Mirrors :func:`scripts.stage2_agent._is_candidate` but
    returns the major names so we can membership-test the agent's answer."""
    dl_school = dagluben.get("school", "")
    dl_cat = normalise_cat(dagluben.get("school_cat", ""))
    dl_core = dagluben.get("core", "")
    out: set[str] = set()
    for h in history:
        if (h.get("school", "") != dl_school):
            continue
        if normalise_cat(h.get("school_cat", "")) != dl_cat:
            continue
        if _core_compatible(dl_core, h.get("core", "")):
            out.add(h.get("major", ""))
    return out


def _subject_drift_note(dagluben: DaglubenRow, matched: HistoryRow | None) -> str:
    if matched is None:
        return ""
    a = (dagluben.get("subject", "") or "").strip()
    b = (matched.get("subject", "") or "").strip()
    if not a or not b or a == b:
        return ""
    return f"；{LOG_SUBJECT_DRIFT}"


def _find_matched(
    match_major: str, dagluben: DaglubenRow, history: Sequence[HistoryRow]
) -> HistoryRow | None:
    """Locate the history row whose major == match_major among the
    dagluben row's candidate pool. Returns None if match is null or no
    matching history row exists (the latter should not happen because the
    contract check already guaranteed membership)."""
    dl_school = dagluben.get("school", "")
    dl_cat = normalise_cat(dagluben.get("school_cat", ""))
    dl_core = dagluben.get("core", "")
    for h in history:
        if h.get("school", "") != dl_school:
            continue
        if normalise_cat(h.get("school_cat", "")) != dl_cat:
            continue
        if h.get("major", "") == match_major and _core_compatible(dl_core, h.get("core", "")):
            return h
    return None


def _parse_line(raw: str, path: Path, lineno: int) -> dict[str, object]:
    raw = raw.strip()
    if not raw:
        raise Stage2ContractError(f"{path.name}:{lineno}: 空行")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: JSON 解析失败 — {exc.msg}"
        ) from exc
    if not isinstance(obj, dict):
        raise Stage2ContractError(
            f"{path.name}:{lineno}: 顶层不是 JSON 对象"
        )
    missing = [k for k in REQUIRED_KEYS if k not in obj]
    if missing:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: 缺少必需字段 {missing}"
        )
    return obj


def _validate_and_build(
    obj: dict[str, object],
    path: Path,
    lineno: int,
    dagluben_by_idx: dict[int, DaglubenRow],
    history: Sequence[HistoryRow],
    seen_idx: set[int],
) -> MatchResult:
    idx_raw = obj["src_row_idx"]
    if not isinstance(idx_raw, int) or isinstance(idx_raw, bool):
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx 不是整数 ({idx_raw!r})"
        )
    idx: int = idx_raw
    if idx not in dagluben_by_idx:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} 不在派发给 agent 的大绿本行中"
        )
    if idx in seen_idx:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} 重复出现(每专业至多 1 结果)"
        )
    seen_idx.add(idx)

    match_raw = obj["match"]
    reason_raw = obj["reason"]
    j_raw = obj["J"]
    t_raw = obj["T"]

    if not isinstance(reason_raw, str) or reason_raw.strip() == "":
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} reason 为空或非字符串"
        )
    reason: str = reason_raw.strip()
    if len(reason) > 30:
        # Soft: trim rather than reject so a verbose agent doesn't abort the
        # whole batch; the full reason is preserved in the prompt file.
        reason = reason[:30]

    dagluben = dagluben_by_idx[idx]

    if match_raw is None:
        log = f"{LOG_SEMANTIC_NULL_PREFIX}：{reason_raw.strip()[:30]}"
        return MatchResult(
            src_row_idx=idx,
            school=dagluben.get("school", ""),
            school_cat=dagluben.get("school_cat", ""),
            major=dagluben.get("major", ""),
            matched=False,
            J=None,
            T=None,
            log=log,
        )

    if not isinstance(match_raw, str):
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} match 既非字符串也非 null"
        )
    match_major: str = match_raw

    allowed = _candidate_set(dagluben, history)
    if match_major not in allowed:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} match={match_major!r} "
            f"不在候选集内(候选数={len(allowed)}) — agent 越界/幻觉"
        )

    matched_hist = _find_matched(match_major, dagluben, history)
    # Membership in `allowed` guarantees _find_matched succeeds; guard anyway.
    if matched_hist is None:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} match={match_major!r} "
            f"通过候选集但无法定位历史行(数据不一致)"
        )

    # J/T must echo the matched candidate's values (agent must not fabricate).
    # 舍入到 2 位再比较：精度统一后，历史候选已舍入（line_diff/estimate round 2），
    # 而 agent 结果可能是旧未舍入值；按 2 位对齐避免误报不一致。
    expected_j = matched_hist.get("J")
    expected_t = matched_hist.get("T")
    j_cmp = round(j_raw, 2) if isinstance(j_raw, float) else j_raw
    t_cmp = round(t_raw, 2) if isinstance(t_raw, float) else t_raw
    if j_cmp != expected_j:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} J={j_raw!r} 与候选 "
            f"{match_major!r} 的 J={expected_j!r} 不一致"
        )
    if t_cmp != expected_t:
        raise Stage2ContractError(
            f"{path.name}:{lineno}: src_row_idx={idx} T={t_raw!r} 与候选 "
            f"{match_major!r} 的 T={expected_t!r} 不一致"
        )

    log = f"{LOG_SEMANTIC_PREFIX}：{reason}{_subject_drift_note(dagluben, matched_hist)}"
    return MatchResult(
        src_row_idx=idx,
        school=dagluben.get("school", ""),
        school_cat=dagluben.get("school_cat", ""),
        major=dagluben.get("major", ""),
        matched=True,
        J=expected_j,
        T=expected_t,
        log=log,
    )


def apply_results(
    result_jsonl_paths: Iterable[Path],
    dagluben: Sequence[DaglubenRow],
    history: Sequence[HistoryRow],
) -> list[MatchResult]:
    """Read agent result jsonl files and back-fill MatchResult rows.

    Order of returned rows follows first-appearance order across the input
    files (so a stable input order yields a stable output). Raises
    :class:`Stage2ContractError` on the first contract violation.
    """
    dagluben_by_idx: dict[int, DaglubenRow] = {
        d.get("src_row_idx", 0): d for d in dagluben
    }
    seen_idx: set[int] = set()
    results: list[MatchResult] = []

    for path in result_jsonl_paths:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), start=1):
            if raw.strip() == "":
                continue
            obj = _parse_line(raw, path, lineno)
            results.append(
                _validate_and_build(
                    obj, path, lineno, dagluben_by_idx, history, seen_idx
                )
            )

    return results
