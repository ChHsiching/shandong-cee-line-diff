"""TDD tests for Stage 2 agent semantic-match **orchestration layer**.

Per Plan v2 binding + Slice 4 (issue #5): the agent itself cannot be invoked
from a Python script (Agent is a harness tool), so this slice only ships the
testable pure-function layer:

  - :func:`scripts.stage2_agent.build_batches` — group unmatched dagluben rows
    by school, attach same-school history candidates (pre-filtered by 基础
    专业名 / core name), and slice into batches.
  - :func:`scripts.stage2_agent.write_prompts` — write one ``batch_NN_prompt.json``
    per batch, each item carrying the dagluben专业全信息 + candidate list +
    the required JSON output schema.
  - :func:`scripts.stage2_apply.apply_results` — read ``batch_NN_result.jsonl``
    (produced by the harness after agent dispatch) and back-fill ``match`` /
    ``J`` / ``T`` / ``reason`` into :class:`MatchResult`.

Contract tests (match ∈ candidate set, at most one match per major, reason
non-empty, out-of-range / duplicate rejected) live in
``test_stage2_contract.py``. These tests focus on the pure-function behaviour
with small synthetic fixtures.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.models import DaglubenRow, HistoryRow
from scripts.stage2_agent import build_batches, write_prompts
from scripts.stage2_apply import apply_results


# ---------------------------------------------------------------------------
# build_batches
# ---------------------------------------------------------------------------


def _dl(school: str, major: str, core: str, idx: int, cat: str = "") -> DaglubenRow:
    return DaglubenRow(
        src_row_idx=idx,
        school=school,
        school_cat=cat,
        major=major,
        stripped=major,
        core=core,
        subject="物理和化学",
        batch="4.常规批",
    )


def _hist(school: str, major: str, core: str, j: float, cat: str = "") -> HistoryRow:
    return HistoryRow(
        school=school,
        school_cat=cat,
        major=major,
        stripped=major,
        core=core,
        subject="物理",
        J=j,
        T=1.0,
        source_table="常规批一段线",
    )


def test_build_batches_groups_by_school_and_attaches_candidates() -> None:
    """3 unmatched rows across 2 schools split into batches of 2.

    Asserts:
      - rows are batched in input order with batch_size respected,
      - each item carries the same-school candidates whose core name is
        compatible (基础专业名 pre-filter) with THAT dagluben row's core,
      - candidates from *other* schools are NOT attached,
      - unrelated cores within the same school are NOT attached.
    """
    unmatched = [
        _dl("甲大学", "计算机类(图灵)", "计算机类", 1),
        _dl("甲大学", "数学类(拔尖)", "数学类", 2),
        _dl("乙大学", "物理学(严济慈)", "物理学", 3),
    ]
    history = [
        _hist("甲大学", "计算机类", "计算机类", 80.0),
        _hist("甲大学", "计算机类(网络)", "计算机类", 78.0),
        _hist("甲大学", "数学类", "数学类", 90.0),
        _hist("甲大学", "化学", "化学", 70.0),  # unrelated core, must NOT attach
        _hist("乙大学", "物理学", "物理学", 60.0),
        _hist("丙大学", "物理学", "物理学", 99.0),  # other school, must NOT attach
    ]

    batches = build_batches(unmatched, history, batch_size=2)

    # batch_size=2 over 3 rows -> 2 batches (sizes 2 and 1).
    assert len(batches) == 2
    assert [len(b.items) for b in batches] == [2, 1]
    assert sum(len(b.items) for b in batches) == 3

    all_items = [it for b in batches for it in b.items]
    by_idx = {it.dagluben["src_row_idx"]: it for it in all_items}

    # 计算机类 dagluben (idx=1): same-school computer candidates only.
    cs_item = by_idx[1]
    assert {c["major"] for c in cs_item.candidates} == {"计算机类", "计算机类(网络)"}
    assert "化学" not in {c["major"] for c in cs_item.candidates}
    assert "物理学" not in {c["major"] for c in cs_item.candidates}

    # 数学类 dagluben (idx=2): same-school math candidate only (computer
    # candidates have a different core and are correctly excluded).
    math_item = by_idx[2]
    assert {c["major"] for c in math_item.candidates} == {"数学类"}

    # 乙大学 physics dagluben (idx=3): its physics candidate only — 丙大学
    # is a different school and must NOT leak in.
    phys_item = by_idx[3]
    assert {c["major"] for c in phys_item.candidates} == {"物理学"}


def test_build_batches_empty_unmatched_returns_empty() -> None:
    assert (
        build_batches([], [_hist("甲大学", "数学", "数学", 1.0)], batch_size=20) == []
    )


def test_build_batches_no_candidates_still_emits_item() -> None:
    """A dagluben专业 whose school has NO history still becomes an item with an
    empty candidate list — the agent may legitimately answer ``match=null``."""
    unmatched = [_dl("新校", "新专业", "新专业", 1)]
    batches = build_batches(unmatched, [], batch_size=20)
    assert len(batches) == 1
    assert len(batches[0].items) == 1
    assert batches[0].items[0].candidates == []


# ---------------------------------------------------------------------------
# write_prompts
# ---------------------------------------------------------------------------


def test_write_prompts_emits_one_json_per_batch_with_required_fields(
    tmp_path: Path,
) -> None:
    unmatched = [
        _dl("甲大学", "计算机类(图灵)", "计算机类", 1),
        _dl("乙大学", "物理学", "物理学", 2),
    ]
    history = [
        _hist("甲大学", "计算机类", "计算机类", 80.0),
        _hist("乙大学", "物理学", "物理学", 60.0),
    ]
    batches = build_batches(unmatched, history, batch_size=1)

    paths = write_prompts(batches, tmp_path)

    assert len(paths) == 2
    for i, p in enumerate(paths, start=1):
        assert p.name == f"batch_{i:02d}_prompt.json"
        payload = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        # required top-level keys
        assert "batch" in payload
        assert "items" in payload
        assert "output_schema" in payload
        # each item carries full dagluben info + candidates + schema ref
        item = payload["items"][0]
        for key in (
            "school",
            "school_cat",
            "major",
            "core",
            "subject",
            "src_row_idx",
            "candidates",
        ):
            assert key in item
        # candidate rows expose J/T/major so the agent can return them verbatim
        cand = item["candidates"][0]
        for key in ("major", "J", "T"):
            assert key in cand


def test_write_prompts_preserves_item_order_and_indices(tmp_path: Path) -> None:
    unmatched = [
        _dl("甲大学", "数学", "数学", 10),
        _dl("甲大学", "物理", "物理", 20),
        _dl("甲大学", "化学", "化学", 30),
    ]
    batches = build_batches(unmatched, [], batch_size=2)
    paths = write_prompts(batches, tmp_path)
    b1 = json.loads(paths[0].read_text(encoding="utf-8"))
    b2 = json.loads(paths[1].read_text(encoding="utf-8"))
    assert [it["src_row_idx"] for it in b1["items"]] == [10, 20]
    assert [it["src_row_idx"] for it in b2["items"]] == [30]


def test_write_prompts_embeds_cardinality_matching_rule(tmp_path: Path) -> None:
    """每个 batch prompt 内联基数规则（单一真理源 = SKILL §3），让 subagent
    不必再翻 SKILL.md。drift guard：培养模式标签 + 一对多/多对一 + 中外合作
    必须都在——曾因缺这条规则，subagent 各自重读 SKILL 还把培养模式判错。"""
    batches = build_batches(
        [_dl("甲大学", "数学(拔尖)", "数学", 1)],
        [_hist("甲大学", "数学", "数学", 80.0)],
        batch_size=20,
    )
    paths = write_prompts(batches, tmp_path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert "matching_rule" in payload
    rule = payload["matching_rule"]
    assert any(tok in rule for tok in ("培养模式", "拔尖"))
    assert "一对多" in rule
    assert any(tok in rule for tok in ("多对一", "多对1"))
    assert "中外合作" in rule


# ---------------------------------------------------------------------------
# apply_results
# ---------------------------------------------------------------------------


def _result_line(
    idx: int,
    match: str | None,
    j: float | None,
    reason: str,
    t: float | None = 1.0,
) -> str:
    return json.dumps(
        {
            "src_row_idx": idx,
            "school": "甲大学",
            "major": "计算机类(图灵)",
            "match": match,
            "J": j,
            "T": t,
            "reason": reason,
        },
        ensure_ascii=False,
    )


def test_apply_results_backfills_matched_and_null(tmp_path: Path) -> None:
    dagluben = [
        _dl("甲大学", "计算机类(图灵)", "计算机类", 1),
        _dl("甲大学", "数学类(拔尖)", "数学类", 2),
    ]
    history = [
        _hist("甲大学", "计算机类", "计算机类", 80.0),
        _hist("甲大学", "数学类", "数学类", 90.0),
    ]

    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text(
        _result_line(1, "计算机类", 80.0, "核心名同、方向括号对齐")
        + "\n"
        + _result_line(2, None, None, "无对应历史专业", None)
        + "\n",
        encoding="utf-8",
    )

    results = apply_results([jsonl], dagluben, history)

    assert len(results) == 2
    matched = next(r for r in results if r["src_row_idx"] == 1)
    assert matched["matched"] is True
    assert matched["J"] == 80.0
    assert matched["T"] == 1.0
    assert "agent 语义匹配" in matched["log"]
    assert "核心名同、方向括号对齐" in matched["log"]

    null_r = next(r for r in results if r["src_row_idx"] == 2)
    assert null_r["matched"] is False
    assert null_r["J"] is None
    assert "无对应历史专业" in null_r["log"]


def test_apply_results_merges_multiple_jsonl(tmp_path: Path) -> None:
    dagluben = [
        _dl("甲大学", "数学", "数学", 1),
        _dl("乙大学", "物理", "物理", 2),
    ]
    history = [
        _hist("甲大学", "数学", "数学", 90.0),
        _hist("乙大学", "物理", "物理", 60.0),
    ]
    j1 = tmp_path / "batch_01_result.jsonl"
    j2 = tmp_path / "batch_02_result.jsonl"
    # Both echo their candidate's T (1.0 from _hist) so the J/T echo contract
    # passes and the merge itself is what's under test.
    j1.write_text(
        _result_line(1, "数学", 90.0, "唯一同校候选") + "\n", encoding="utf-8"
    )
    j2.write_text(
        json.dumps(
            {
                "src_row_idx": 2,
                "school": "乙大学",
                "major": "物理",
                "match": "物理",
                "J": 60.0,
                "T": 1.0,
                "reason": "核心名一致",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    results = apply_results([j1, j2], dagluben, history)
    assert {r["src_row_idx"] for r in results} == {1, 2}
    assert all(r["matched"] for r in results)
