"""Stage 2 — agent semantic-match **orchestration layer** (pure functions).

Spec §6 Stage 2: for Stage 1.5 misses, dispatch parallel agents that read each
大绿本专业 + its same-school candidate set and return the unique semantic
correspondence. **The agent itself cannot be invoked from a Python script**
(Agent is a harness tool), so this module ships only the testable pure layer:

  - :func:`build_batches` — group unmatched dagluben rows by school, attach
    same-school history candidates pre-filtered by core name (基础专业名),
    slice into batches.
  - :func:`write_prompts` — write ``batch_NN_prompt.json`` per batch, each
    item carrying full dagluben info + candidate list + output schema.

The actual agent dispatch + result collection is a harness-side step; see
``semantic-match/RUN.md``. Results land in ``batch_NN_result.jsonl`` and are
back-filled by :mod:`scripts.stage2_apply`.

Candidate pre-filter (spec §6 Stage 2 「按基础专业名预筛」): a history row is
a candidate for a dagluben row iff they share ``(school, normalised cat)``
*and* the history core name matches the dagluben core name OR one is a
substring of the other. The substring relaxation absorbs「经济学类 vs 经济学」
style core-name drift the prototype flagged as归一化 pseudo-misses, so the
agent sees the right pool without us hard-coding identity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from scripts.models import DaglubenRow, HistoryRow
from scripts.stage1_strict import normalise_cat

__all__ = [
    "Batch",
    "BatchItem",
    "build_batches",
    "write_prompts",
    "OUTPUT_SCHEMA",
]

# JSON schema description embedded into every prompt file so the dispatched
# agent has the contract inline. Kept as a plain dict (not a jsonschema) so
# no extra dependency is introduced; the contract is enforced on apply by
# scripts.stage2_apply.
OUTPUT_SCHEMA: dict[str, object] = {
    "description": (
        "每条 item 输出一行 JSON,写入 batch_NN_result.jsonl。字段:"
        " src_row_idx(与输入相同), school, major(与输入大绿本 major 相同),"
        " match(候选 major 字符串逐字相等 或 null), J(float|null),"
        " T(float|null), reason(≤30字 非空)。每 src_row_idx 至多一行。"
    ),
    "required_keys": [
        "src_row_idx",
        "school",
        "major",
        "match",
        "J",
        "T",
        "reason",
    ],
}


@dataclass(frozen=True)
class BatchItem:
    """One dagluben专业 packaged for agent dispatch with its candidate pool."""

    dagluben: DaglubenRow
    candidates: list[HistoryRow] = field(default_factory=list)


@dataclass(frozen=True)
class Batch:
    """A slice of dagluben items dispatched as one agent call.

    ``index`` is 1-based to align with the ``batch_NN_prompt.json`` filename.
    """

    index: int
    items: list[BatchItem]


def _same_school_cat(dl: DaglubenRow, h: HistoryRow) -> bool:
    return dl.get("school", "") == h.get("school", "") and normalise_cat(
        dl.get("school_cat", "")
    ) == normalise_cat(h.get("school_cat", ""))


def _core_compatible(dl_core: str, h_core: str) -> bool:
    """Core-name pre-filter: exact, or one is a substring of the other.

    Substring relaxation absorbs the「经济学类 vs 经济学」「数学类 vs 数学」
    style drift that the prototype identified as归一化 pseudo-misses — the
    agent still gets to make the final call, but the candidate pool is not
    gutted by a too-strict equality.
    """
    if not dl_core or not h_core:
        return False
    if dl_core == h_core:
        return True
    return dl_core in h_core or h_core in dl_core


def _is_candidate(dl: DaglubenRow, h: HistoryRow) -> bool:
    return _same_school_cat(dl, h) and _core_compatible(
        dl.get("core", ""), h.get("core", "")
    )


def build_batches(
    unmatched: Iterable[DaglubenRow],
    history: Iterable[HistoryRow],
    batch_size: int = 20,
) -> list[Batch]:
    """Group unmatched dagluben rows by school, attach same-school candidates
    (core-name pre-filtered), and slice into batches of ``batch_size``.

    The candidate list is computed per **school group** (not per item): every
    dagluben item in the same school group shares the same candidate pool,
    because the pre-filter is keyed on ``(school, cat, core-compatibility)``
    and a school's candidates are independent of which dagluben row we ask
    about. Computing once per group keeps the prompt size bounded.

    Output preserves input dagluben order. ``batch_size`` <= 0 is treated as
    a single batch.
    """
    unmatched_list = list(unmatched)
    history_list = list(history)
    if not unmatched_list:
        return []

    if batch_size <= 0:
        batch_size = len(unmatched_list)

    # Bucket history once by (school, normalised cat) so candidate lookup is
    # O(candidates) not O(all-history) per dagluben row.
    hist_by_school: dict[tuple[str, str], list[HistoryRow]] = {}
    for h in history_list:
        key = (h.get("school", ""), normalise_cat(h.get("school_cat", "")))
        hist_by_school.setdefault(key, []).append(h)

    items: list[BatchItem] = []
    for d in unmatched_list:
        key = (d.get("school", ""), normalise_cat(d.get("school_cat", "")))
        pool = hist_by_school.get(key, [])
        candidates = [
            h for h in pool if _core_compatible(d.get("core", ""), h.get("core", ""))
        ]
        items.append(BatchItem(dagluben=d, candidates=candidates))

    batches: list[Batch] = []
    for i in range(0, len(items), batch_size):
        batches.append(Batch(index=len(batches) + 1, items=items[i : i + batch_size]))
    return batches


def _candidate_payload(h: HistoryRow) -> dict[str, object]:
    return {
        "major": h.get("major", ""),
        "core": h.get("core", ""),
        "J": h.get("J"),
        "T": h.get("T"),
    }


def _item_payload(item: BatchItem) -> dict[str, object]:
    d = item.dagluben
    return {
        "src_row_idx": d.get("src_row_idx", 0),
        "school": d.get("school", ""),
        "school_cat": d.get("school_cat", ""),
        "major": d.get("major", ""),
        "core": d.get("core", ""),
        "subject": d.get("subject", ""),
        "batch": d.get("batch", ""),
        "candidates": [_candidate_payload(h) for h in item.candidates],
    }


def write_prompts(batches: Sequence[Batch], out_dir: Path) -> list[Path]:
    """Write one ``batch_NN_prompt.json`` per batch into ``out_dir``.

    Each file is a dict with ``batch`` (1-based index), ``items`` (full
    dagluben info + candidates), and ``output_schema`` (the inline contract
    the agent must obey). Returns the paths in batch order.
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
        path = out_dir / f"batch_{b.index:02d}_prompt.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths.append(path)
    return paths
