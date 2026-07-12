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
    "特别强调**一对多**: 一个往年候选可以被**多个**今年专业各自选中（往年同核心只"
    " 1 条、今年拆成多个变体时常见）——「这个候选已被同 batch 别的 item 配过」**不"
    "是**配 null 的理由；每个 item 独立按对应关系判, 别管别的 item 选了什么。"
    "身份由数据定、不靠标签: 往年这学校这核心有**几条记录就是几个单独招生的"
    "专业**（各有独立分数线）——你看到的候选都是往年单独招过的不同专业, 任务是"
    "按今年专业实际描述 1:1 精配到语义真正对应的那 1 条; 挑不出真正对应的配 null。"
    "括号里这些都是区分不同专业的标志(往年分了多条线招, 就别合并到 plain): "
    "培养标签班(拔尖/卓越/创新/英才/基地/未来/试验班/订单班等「XX 班」)、出国"
    "模式(中澳/中俄/1+3)、师范、性别(男/女)、学制(5年制≠5+3一体化≠8年制)、"
    "独立划线校区、真正不同的方向(如投资学(量化投资)≠投资学)。"
    "只有**纯描述噪音**不算身份(它是同一个专业的说明文字、不是单独招生标记): "
    "标点/词序/体检/色盲/学费/语种/章程引用/子专业清单长描述。"
    "注: 招生类别(普通/地方专项/高校专项/综合评价)和中外合作程序已按同类别预筛"
    "——你看到的候选都是**同招生类别**的, 不同类别的不"
    "会到你手里(它们走 past=1 一对多兜底或「未能匹配」估算)，故不用再判类别。"
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


def build_batches(
    unmatched: Iterable[DaglubenRow],
    history: Iterable[HistoryRow],
    batch_size: int = 20,
) -> list[Batch]:
    """Group unmatched dagluben rows by school, attach **same-招生类别**
    candidates (core-name pre-filtered), and slice into batches of ``batch_size``.

    招生类别是硬身份：只挂同类别候选；同类别无候选的 item 不进 batch，留给下游
    「未能匹配」估算（past=1 跨类由 Stage 1.5 step3 一对多兜底，到不了这里）。

    The candidate list is computed per item from the ``(school, cat)`` bucket:
    every dagluben item gets the same-school **same-cat** history rows whose
    core name is core-compatible (基础专业名 pre-filter).

    Output preserves input dagluben order. ``batch_size`` <= 0 is treated as
    a single batch.
    """
    unmatched_list = list(unmatched)
    history_list = list(history)
    if not unmatched_list:
        return []

    if batch_size <= 0:
        batch_size = len(unmatched_list)

    # Bucket history by (school, cat) only. 招生类别是硬身份：同类别无候选时不再
    # 跨类回退（1.6.x 曾回退→高校专项被配到普通批；1.7.0 去掉）——该 item 不进
    # agent batch，留给下游「未能匹配」+ 同校同选科均值估算。past=1 跨类（往年同校
    # 该核心只 1 条、不同身份）由 Stage 1.5 step3 一对多兜底处理，到不了这里；到
    # 这里的都是「同类别 2+ 候选」交 agent 判。
    by_school_cat: dict[tuple[str, str], list[HistoryRow]] = {}
    for h in history_list:
        by_school_cat.setdefault(
            (h.get("school", ""), normalise_cat(h.get("school_cat", ""))), []
        ).append(h)

    items: list[BatchItem] = []
    for d in unmatched_list:
        dl_core = d.get("core", "")
        candidates = [
            h
            for h in by_school_cat.get(
                (d.get("school", ""), normalise_cat(d.get("school_cat", ""))), []
            )
            if _core_compatible(dl_core, h.get("core", ""))
        ]
        # 同类别无候选 → 不跨类回退 → 不进 batch，下游走「未能匹配」估算。
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
