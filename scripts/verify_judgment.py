"""Slice B — judgmental-match second-pass verification (V5-0) — pure functions.

Per spec V5-0 / Plan v2 binding (Slice B修订). Every judgmental match
(agent 语义 matched) must pass a **second agent review** that
returns「确定」(confirmed — keep in main table) or「存疑」(uncertain — demote to
special). The agent itself cannot be invoked from Python (Agent is a harness
tool), so this module ships only the testable pure layer:

  - :func:`build_verify_batches` — package each judgmental match with its
    大绿本专业 (dagluben), the matched近三年 candidate, and the judgment
    requirement; slice into batches.
  - :func:`write_verify_prompts` — write ``verify_batch_NN.json`` per batch.
  - :func:`apply_verify` — read ``verify_*_result.jsonl``, route each row to
    ``confirmed`` (verdict=确定, original MatchResult) or ``demoted`` (verdict=
    存疑, EdgeRow); hard-reject contract violations.

The harness-side dispatch (read verify_batch_NN.json → Agent(general-purpose)
with verify_prompt.md → verify_batch_NN_result.jsonl) is documented in
``semantic-match/RUN_VERIFY.md``; it is not invoked here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from scripts.constants import (
    LOG_SEMANTIC_PREFIX,
    LOG_COARSE_CANDIDATE,
    LOG_VERIFY_DEMOTE_PREFIX,
)
from scripts.models import DaglubenRow, HistoryRow, MatchResult, VerifyApplyResult
from scripts.stage3_edges import EdgeRow

__all__ = [
    "VerifyBatch",
    "VerifyBatchItem",
    "VerifyContractError",
    "OUTPUT_SCHEMA",
    "REQUIRED_KEYS",
    "JUDGMENT_LOG_PREFIXES",
    "is_judgmental",
    "build_verify_batches",
    "write_verify_prompts",
    "apply_verify",
    "filter_demoted",
    "DEMOTE_LOG_PREFIX",
]

# Logs marking a match as 判断型 (needs second-pass verification, V5-0).
# Strict-exact (LOG_STRICT) is构造确定 and excluded.
JUDGMENT_LOG_PREFIXES: tuple[str, ...] = (
    LOG_COARSE_CANDIDATE,  # 核心名匹配（#5 后 pipeline 不产生；保留兼容旧 jsonl/测试）
    LOG_SEMANTIC_PREFIX,  # agent 语义匹配 (matched)
)

# Demote log prefix injected into special-table EdgeRows for存疑 verdicts.
DEMOTE_LOG_PREFIX = LOG_VERIFY_DEMOTE_PREFIX


def filter_demoted(
    results: Sequence[MatchResult],
    classified_idx: set[int],
    verdict_by_idx: dict[int, str],
    reasons_by_idx: dict[int, str],
) -> tuple[list[MatchResult], set[int], dict[int, str]]:
    """Strip存疑 verdicts from a MatchResult list + the classified set.

    Called by ``run_pipeline`` on ``coarse_results`` and ``semantic_results``
    (and their ``classified_idx`` contributions) BEFORE ``_build_main_results``
    so demoted rows fall naturally into ``remaining_unmatched → special``.

    Returns ``(filtered_results, filtered_classified, demoted_map)`` where
    ``demoted_map`` is ``{src_row_idx: reason}`` for every存疑 idx the caller
    passes onward to :func:`scripts.stage3_edges.flight_and_special` via its
    ``demoted_map`` parameter.

    ``reasons_by_idx`` may be sparse (reasons only for存疑 rows); missing
    reasons default to the demote prefix alone.
    """
    demoted_map: dict[int, str] = {}
    out_results: list[MatchResult] = []
    for r in results:
        idx = r.get("src_row_idx", 0)
        if verdict_by_idx.get(idx) == "存疑":
            demoted_map[idx] = reasons_by_idx.get(idx, "")
        else:
            out_results.append(r)
    out_classified = {
        idx for idx in classified_idx if verdict_by_idx.get(idx) != "存疑"
    }
    return out_results, out_classified, demoted_map


# Inline output contract shipped in every prompt file.
OUTPUT_SCHEMA: dict[str, object] = {
    "description": (
        "每条 item 输出一行 JSON, 写入 verify_batch_NN_result.jsonl。字段:"
        " src_row_idx(与输入相同), verdict(只允许「确定」或「存疑」),"
        " reason(非空, ≤30字, 说明判定依据)。每 src_row_idx 至多一行。"
        " 判定原则: 该配对是否确定正确? 六要素(核心名/性别/合作/校区/方向/"
        "招生类别)是否真对齐? 方向不同(如投资学(量化投资)≠投资学)→存疑。"
        "重要规则: 这所学校往年只有 1 个同核心专业名时, 今年的专业不管改方向/"
        "改名/换措辞(标点/词序/加减括号内容)都是同一个专业, 判确定——只有往年"
        "有多个同核心名时才需细比方向。不确定就判存疑, 宁可保守。"
    ),
    "required_keys": ["src_row_idx", "verdict", "reason"],
    "allowed_verdicts": ["确定", "存疑"],
}

REQUIRED_KEYS: tuple[str, ...] = ("src_row_idx", "verdict", "reason")
_ALLOWED_VERDICTS: frozenset[str] = frozenset({"确定", "存疑"})


class VerifyContractError(ValueError):
    """Raised when a verify result jsonl line violates the V5-0 contract."""


@dataclass(frozen=True)
class VerifyBatchItem:
    """One judgmental match packaged for verification dispatch.

    Carries the dagluben row (大绿本专业 with方向/括号), the matched近三年
    candidate (what the prior stage picked), and the ``requirement`` text the
    agent must apply to judge 确定/存疑.
    """

    dagluben: DaglubenRow
    matched_candidate: HistoryRow
    match: MatchResult
    requirement: str


@dataclass(frozen=True)
class VerifyBatch:
    """A slice of verify items dispatched as one agent call.

    ``index`` is 1-based, aligned with the ``verify_batch_NN.json`` filename.
    """

    index: int
    items: list[VerifyBatchItem] = field(default_factory=list)


def is_judgmental(match: MatchResult) -> bool:
    """True iff a MatchResult is 判断型 and thus needs V5-0 verification.

    Strict-exact matches (LOG_STRICT) are构造确定 and excluded; everything
    else that *matched* via coarse / semantic stages qualifies. Unmatched
    rows do not need verification.
    """
    if not match.get("matched"):
        return False
    log = match.get("log", "")
    return any(log.startswith(p) for p in JUDGMENT_LOG_PREFIXES)


def _requirement_text(dagluben: DaglubenRow, cand: HistoryRow) -> str:
    """The judgment requirement shown to the agent for one item."""
    return (
        "判定该配对是否确定正确。六要素(核心名/性别/合作/校区/方向/招生类别)"
        "是否真对齐? 大绿本专业带方向括号时须与候选方向一致"
        "(如投资学(量化投资)≠投资学)。重要规则: 这所学校往年只有 1 个同核心"
        "专业名时, 今年的专业不管改方向/改名/换措辞(标点/词序/加减括号内容)都"
        "是同一个专业, 判确定——只有往年有多个同核心名时才需细比方向。"
        "不确定→存疑, 宁可保守。"
    )


def build_verify_batches(
    judgment_matches: Iterable[MatchResult],
    dagluben: Iterable[DaglubenRow],
    history: Iterable[HistoryRow],
    batch_size: int = 20,
) -> list[VerifyBatch]:
    """Package judgmental matches into verify batches.

    Filters ``judgment_matches`` to the judgmental ones (V5-0), attaches each
    its dagluben row + matched近三年 candidate (located by src_row_idx → the
    matched history row's major via the dagluben pool), and slices into batches
    of ``batch_size``. ``batch_size <= 0`` produces a single batch.

    The matched candidate is the history row whose major equals the matched
    J/T carried on the MatchResult under the same school; for coarse matches
    the candidate is identified by same school + core + J/T echo. If no
    candidate can be located (data inconsistency) the match is still packaged
    with whatever dagluben row carries its src_row_idx and an empty candidate,
    so verification proceeds and the agent can flag存疑.
    """
    dgl_by_idx: dict[int, DaglubenRow] = {d.get("src_row_idx", 0): d for d in dagluben}
    hist_list = list(history)

    items: list[VerifyBatchItem] = []
    for m in judgment_matches:
        if not is_judgmental(m):
            continue
        idx = m.get("src_row_idx", 0)
        d = dgl_by_idx.get(idx)
        if d is None:
            # No dagluben row for this idx — cannot build a verify item.
            continue
        cand = _locate_candidate(d, m, hist_list)
        items.append(
            VerifyBatchItem(
                dagluben=d,
                matched_candidate=cand,
                match=m,
                requirement=_requirement_text(d, cand),
            )
        )

    if not items:
        return []
    if batch_size <= 0:
        batch_size = len(items)

    batches: list[VerifyBatch] = []
    for i in range(0, len(items), batch_size):
        batches.append(
            VerifyBatch(index=len(batches) + 1, items=items[i : i + batch_size])
        )
    return batches


def _locate_candidate(
    dagluben: DaglubenRow, match: MatchResult, history: Sequence[HistoryRow]
) -> HistoryRow:
    """Find the近三年 row the prior stage matched this dagluben row to.

    优先用 ``MatchResult.matched_major``（agent 语义匹配记录的候选 major 原文）
    在同校精确锁定——避开 J/T 舍入或巧合相同导致的定位错误（多个不同方向的
    候选 J/T 恰好相同会让 J/T 匹配找错行，曾导致量子计划被错定位成未来工程师
    项目制）。matched_major 是 agent 选中的候选字面值，同校内唯一。

    matched_major 缺失（未经 Stage 2 的旧 MatchResult）才退化到 J/T echo +
    同校同核心名 + closest-J 容差。Returns an empty HistoryRow if none matches
    (agent will see empty + can judge存疑).
    """
    dl_school = dagluben.get("school", "")

    # 优先：matched_major 精确匹配（#3 修复，避开 J/T 巧合错配）。
    matched_major = match.get("matched_major", "")
    if matched_major:
        for h in history:
            if h.get("school", "") == dl_school and h.get("major", "") == matched_major:
                return h

    # 退化 1：J/T echo + 同校同核心名（matched_major 缺失时的旧路径）。
    dl_core = dagluben.get("core", "")
    j = match.get("J")
    t = match.get("T")
    for h in history:
        if h.get("school", "") != dl_school:
            continue
        if h.get("core", "") != dl_core:
            continue
        if h.get("J") == j and h.get("T") == t:
            return h
    # 退化 2：唯一同校同核心名候选（J/T 可能因舍入漂移）。
    same_core = [
        h
        for h in history
        if h.get("school", "") == dl_school and h.get("core", "") == dl_core
    ]
    if len(same_core) == 1:
        return same_core[0]
    # 退化 3：多个 same-core 候选时，按 J 最接近 echo 的(容差 0.5)。
    if same_core and j is not None:
        closest = min(same_core, key=lambda h: abs((h.get("J") or 0) - (j or 0)))
        if abs((closest.get("J") or 0) - (j or 0)) <= 0.5:
            return closest
    return HistoryRow()


def _item_payload(item: VerifyBatchItem) -> dict[str, object]:
    d = item.dagluben
    c = item.matched_candidate
    return {
        "src_row_idx": d.get("src_row_idx", 0),
        "school": d.get("school", ""),
        "school_cat": d.get("school_cat", ""),
        "dagluben_major": d.get("major", ""),
        "dagluben_core": d.get("core", ""),
        "subject": d.get("subject", ""),
        "batch": d.get("batch", ""),
        "matched_candidate": {
            "major": c.get("major", ""),
            "core": c.get("core", ""),
            "J": c.get("J"),
            "T": c.get("T"),
        },
        "prior_log": item.match.get("log", ""),
        "requirement": item.requirement,
    }


def write_verify_prompts(batches: Sequence[VerifyBatch], out_dir: Path) -> list[Path]:
    """Write one ``verify_batch_NN.json`` per batch into ``out_dir``.

    Each file is a dict with ``batch`` (1-based index), ``items`` (full
    dagluben + matched candidate + requirement), and ``output_schema`` (the
    inline contract the agent must obey). Returns paths in batch order.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for b in batches:
        payload = {
            "batch": b.index,
            "items": [_item_payload(it) for it in b.items],
            "output_schema": OUTPUT_SCHEMA,
        }
        path = out_dir / f"verify_batch_{b.index:02d}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# apply_verify
# ---------------------------------------------------------------------------


def _parse_line(raw: str, path: Path, lineno: int) -> dict[str, object]:
    raw = raw.strip()
    if not raw:
        raise VerifyContractError(f"{path.name}:{lineno}: 空行")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VerifyContractError(
            f"{path.name}:{lineno}: JSON 解析失败 — {exc.msg}"
        ) from exc
    if not isinstance(obj, dict):
        raise VerifyContractError(f"{path.name}:{lineno}: 顶层不是 JSON 对象")
    missing = [k for k in REQUIRED_KEYS if k not in obj]
    if missing:
        raise VerifyContractError(f"{path.name}:{lineno}: 缺少必需字段 {missing}")
    return obj


def _to_edge_row(dagluben: DaglubenRow, reason: str) -> EdgeRow:
    return EdgeRow(
        src_row_idx=dagluben.get("src_row_idx", 0),
        school=dagluben.get("school", ""),
        school_cat=dagluben.get("school_cat", ""),
        major=dagluben.get("major", ""),
        core=dagluben.get("core", ""),
        subject=dagluben.get("subject", ""),
        batch=dagluben.get("batch", ""),
        log=f"{DEMOTE_LOG_PREFIX}：{reason}",
    )


def apply_verify(
    result_jsonl_paths: Iterable[Path],
    dagluben: Sequence[DaglubenRow],
    matches: Sequence[MatchResult],
) -> VerifyApplyResult:
    """Read verify result jsonl files and route verdicts.

    Parameters
    ----------
    result_jsonl_paths
        ``verify_*_result.jsonl`` files written by the harness after agent
        dispatch.
    dagluben
        The大绿本 rows (needed to build EdgeRows for demoted matches).
    matches
        The judgmental MatchResult list that was sent to verification. Used to
        (a) validate src_row_idx ∈ judgmental set, and (b) recover the original
        MatchResult for confirmed rows.

    Returns
    -------
    VerifyApplyResult
        ``confirmed``: MatchResults with verdict=确定 (original row, J/T/log
        intact). ``demoted``: EdgeRows with verdict=存疑 (dagluben fields +
        ``复核存疑：<reason>`` log, J/T omitted). ``verdict_by_idx``: every seen
        src_row_idx → verdict.

    Contract (hard-reject via :class:`VerifyContractError`):
      - verdict ∈ {确定, 存疑}
      - reason non-empty
      - src_row_idx unique across all inputs
      - src_row_idx ∈ judgmental matches set
    """
    dgl_by_idx: dict[int, DaglubenRow] = {d.get("src_row_idx", 0): d for d in dagluben}
    match_by_idx: dict[int, MatchResult] = {m.get("src_row_idx", 0): m for m in matches}

    confirmed: list[MatchResult] = []
    demoted: list[EdgeRow] = []
    verdict_by_idx: dict[int, str] = {}
    seen_idx: set[int] = set()

    for path in result_jsonl_paths:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), start=1):
            if raw.strip() == "":
                continue
            obj = _parse_line(raw, path, lineno)

            idx_raw = obj["src_row_idx"]
            if not isinstance(idx_raw, int) or isinstance(idx_raw, bool):
                raise VerifyContractError(
                    f"{path.name}:{lineno}: src_row_idx 不是整数 ({idx_raw!r})"
                )
            idx: int = idx_raw
            if idx not in match_by_idx:
                raise VerifyContractError(
                    f"{path.name}:{lineno}: src_row_idx={idx} 不在判断型匹配集中"
                )
            if idx in seen_idx:
                raise VerifyContractError(
                    f"{path.name}:{lineno}: src_row_idx={idx} 重复出现"
                    "(每专业至多 1 个复核结果)"
                )
            seen_idx.add(idx)

            verdict_raw = obj["verdict"]
            if not isinstance(verdict_raw, str) or verdict_raw not in _ALLOWED_VERDICTS:
                raise VerifyContractError(
                    f"{path.name}:{lineno}: src_row_idx={idx} verdict={verdict_raw!r}"
                    f" 不在允许集 {sorted(_ALLOWED_VERDICTS)}"
                )
            verdict: str = verdict_raw

            reason_raw = obj["reason"]
            if not isinstance(reason_raw, str) or reason_raw.strip() == "":
                raise VerifyContractError(
                    f"{path.name}:{lineno}: src_row_idx={idx} reason 为空或非字符串"
                )
            reason: str = reason_raw.strip()[:30]

            verdict_by_idx[idx] = verdict
            if verdict == "确定":
                confirmed.append(match_by_idx[idx])
            else:  # 存疑
                demoted.append(_to_edge_row(dgl_by_idx[idx], reason))

    return VerifyApplyResult(
        confirmed=confirmed,
        demoted=demoted,
        verdict_by_idx=verdict_by_idx,
    )
