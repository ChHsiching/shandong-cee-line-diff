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
``REFERENCE「管线串联命令」第 4 步``. Results land in ``batch_NN_result.jsonl`` and are
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
    "MATCHING_RULE",
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

# 匹配规则（单一真理源 = SKILL §3「基数规则」；与 verify_judgment 的 requirement
# 保持一致）。每个 batch prompt 内联一份，让被派发的 subagent 不必再翻 SKILL.md
# —— 曾因 prompt 里没规则，subagent 各自重读 SKILL 还把培养模式标签判错。
MATCHING_RULE: str = (
    "判断今年每个专业和往年哪个候选是同一个专业。基数: 一对一、一对多允许, "
    "多对一不行。"
    "(前提)程序已处理两类 item、不会到你手里: 往年同核心只 1 个的(Stage 1.5 直接"
    "配)、同校真没有同核心的(0 候选→直接走估算)。你看到的 item 都是「2 个及以上"
    "候选」, 任务是按实际描述挑往年 1 个最对应的(一对一; 不能把往年多个并到今年"
    " 1 个上)。挑不出真正对应的就配 null(→走估算)。"
    "永远不算身份(对得上就配): 培养模式标签(拔尖/卓越/创新/英才/基地/未来/试验"
    "班/订单班等「XX 班」)、出国模式(中澳/中俄/1+3 等)、描述性噪音(标点/词序/"
    "体检/学费/语种/子专业清单长描述)。"
    "一对一时算不同专业(挑不到对应→null): 中外合作、师范、性别(男/女)、招生类别"
    "(普通/地方专项/高校专项/综合评价)、学制(5年制≠5+3一体化≠8年制, 各自独立分数线)、"
    "真正不同的方向(如投资学(量化投资)≠投资学)。"
    "大类↔具体(X↔X类，经济学↔经济学类、护理学↔护理类): 算同核心, 配(大类线差作参考);"
    "工科试验班类这种混杂宽大类除外(挑不出→null)。"
    "省属公费师范生/医学生/农科生 的「面向X市就业」是身份——不同市就是不同专业"
    "(各市单独划线、线差口径不同): 必须配「面向同一个市」的候选; 候选里没有面向相同"
    "市的→配 null(走估算), 绝不能配到别的市(那会把别市的线差错填进来)。"
    "**照搬这条规则, 不要自己改写或加判据**。学制/方向/校区都按基数规则: 往年按某"
    "维度(学制/方向/独立划线校区如中山 广州·珠海·深圳)分开记录、各自独立分数线的"
    "→配同档、跨档配=null(→走新增估算); 往年只 1 条的已由 Stage 1.5 程序吸收、不"
    "会到你手里——你看到的都是多条, 按档精确配。同一记录上的校区只是描述、不影响。"
    "有疑问配 null, 别瞎配。"
    "结果用 scripts.write_batch_result 写、不要手写 JSON。"
)


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
    """Core-name pre-filter: exact, or **X ↔ X类**（大类↔具体）.

    旧版用「互为子串」→ 化学配到化学工程与工艺（不同专业，§5.3 bug）。
    现在只允许精确 + X↔X类（经济学↔经济学类、数学↔数学类）——大类招生↔具体
    专业是 OPP-1 一对多形式。化学↔化学工程与工艺 这种纯子串不再算兼容。
    """
    if not dl_core or not h_core:
        return False
    if dl_core == h_core:
        return True
    return dl_core + "类" == h_core or h_core + "类" == dl_core


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

    # Bucket history by (school, cat) AND by school-only (for 跨类别回退).
    by_school_cat: dict[tuple[str, str], list[HistoryRow]] = {}
    by_school: dict[str, list[HistoryRow]] = {}
    for h in history_list:
        by_school_cat.setdefault(
            (h.get("school", ""), normalise_cat(h.get("school_cat", ""))), []
        ).append(h)
        by_school.setdefault(h.get("school", ""), []).append(h)

    items: list[BatchItem] = []
    for d in unmatched_list:
        dl_core = d.get("core", "")
        # 同类别同核心；为空则跨类别回退（同校任意类别）——与 Stage 1.5 一致，
        # 让多候选跨类别 item（如今年普通、往年有中外合作+师范）也能被 agent 判。
        same_cat = [
            h
            for h in by_school_cat.get(
                (d.get("school", ""), normalise_cat(d.get("school_cat", ""))), []
            )
            if _core_compatible(dl_core, h.get("core", ""))
        ]
        if same_cat:
            candidates = same_cat
        else:
            candidates = [
                h
                for h in by_school.get(d.get("school", ""), [])
                if _core_compatible(dl_core, h.get("core", ""))
            ]
        # 0 候选（同校真没有同核心）→ 不进 agent batch，直接走估算（identify_new_majors）。
        if not candidates:
            continue
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
    dagluben info + candidates), ``output_schema`` (the inline contract the
    agent must obey), and ``matching_rule`` (the基数规则, inline so each
    dispatched subagent has it without re-reading SKILL.md). Returns paths
    in batch order.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for b in batches:
        payload = {
            "batch": b.index,
            "items": [_item_payload(it) for it in b.items],
            "output_schema": OUTPUT_SCHEMA,
            "matching_rule": MATCHING_RULE,
        }
        path = out_dir / f"batch_{b.index:02d}_prompt.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        paths.append(path)
    return paths
