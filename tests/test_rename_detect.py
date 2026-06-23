"""TDD tests for Slice 6 Task 6.2 — school rename detection (pure layer).

Per Plan v2 CRITICAL order + Slice 4 architecture: the agent semantic pairing
**cannot be invoked from a Python script** (Agent is a harness tool), so this
slice ships only the testable pure-function layer:

  - :func:`scripts.rename_detect.prep_rename_candidates` — compute大绿本独有校
    × 历史独有校, pre-screen each with difflib top-k candidates (a **proposal**
    only; final pairing is the agent's semantic judgement, spec §6 Stage 3).
  - :func:`scripts.rename_detect.write_rename_prompt` — write the candidate
    set + the agent task prompt (forbid pure string judgement).
  - :func:`scripts.rename_detect.apply_rename` — read agent result jsonl,
    enforce contract (confidence∈[0,1], fields non-empty, new∈独有校), build
    the改名表 and return the set of confirmed-renamed大绿本 school names.

Small-sample RED cases only; the real-data rename candidate count is a smoke
output (scripts/run_rename_smoke.py) and does NOT participate in the RED
contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.models import DaglubenRow, HistoryRow
from scripts.rename_detect import (
    RenameContractError,
    apply_rename,
    prep_rename_candidates,
    write_rename_prompt,
)


# ---------------------------------------------------------------------------
# prep_rename_candidates
# ---------------------------------------------------------------------------


def test_prep_rename_candidates_pairs_dagluben_only_with_history_only() -> None:
    # 大绿本独有校 (不在历史里) vs 历史独有校 (不在大绿本里)；相交校被排除。
    dgl_schools = ["新大学甲", "新大学乙", "共有大学"]
    hist_schools = ["旧大学甲", "旧大学乙", "共有大学"]

    candidates = prep_rename_candidates(dgl_schools, hist_schools, topk=3)

    # 仅大绿本独有校 × 历史独有校进入候选集；共有大学被排除。
    new_schools = {c["new_school"] for c in candidates}
    assert new_schools == {"新大学甲", "新大学乙"}
    # 每个独有校的候选旧校名集合 = 全部历史独有校。
    by_new = {c["new_school"]: c for c in candidates}
    assert set(by_new["新大学甲"]["candidate_old_schools"]) == {"旧大学甲", "旧大学乙"}


def test_prep_rename_candidates_respects_topk_and_similarity_order() -> None:
    # 字符串相似度（difflib.SequenceMatcher）仅作预筛提案：取 topk。
    dgl_schools = ["山东理工学院"]
    hist_schools = ["山东工程技师学院", "山东理工职业学院", "北京大学", "复旦大学"]

    candidates = prep_rename_candidates(dgl_schools, hist_schools, topk=2)
    assert len(candidates) == 1
    old_list = candidates[0]["candidate_old_schools"]
    assert len(old_list) == 2
    # 相似度高的两个「山东理工…/山东工程…」应排在完全不相关的「北京/复旦」前。
    assert "山东理工职业学院" in old_list
    # 完全不相关的远校不应进入 topk=2。
    assert "北京大学" not in old_list
    assert "复旦大学" not in old_list


def test_prep_rename_candidates_empty_when_no_unique_schools() -> None:
    # 两边完全重叠 → 无独有校 → 空候选集。
    assert prep_rename_candidates(["甲", "乙"], ["甲", "乙"]) == []
    assert prep_rename_candidates([], ["旧"]) == []
    assert prep_rename_candidates(["新"], []) == []


def test_prep_rename_candidates_similarity_is_only_a_proposal() -> None:
    # 契约：相似度只是预筛排序，最终配对由 agent；输出保留 topk 候选而非单选。
    dgl_schools = ["甲学院"]
    hist_schools = ["甲大学", "甲理工学院", "甲职业学院"]
    candidates = prep_rename_candidates(dgl_schools, hist_schools, topk=3)
    # 即使甲学院 vs 甲大学 相似度最高，也必须返回全部 topk 候选供 agent 判断。
    assert len(candidates[0]["candidate_old_schools"]) == 3


# ---------------------------------------------------------------------------
# write_rename_prompt
# ---------------------------------------------------------------------------


def test_write_rename_prompt_writes_prompt_md_and_candidates_json(
    tmp_path: Path,
) -> None:
    candidates = prep_rename_candidates(
        ["新大学甲", "新大学乙"], ["旧大学甲", "旧大学乙"], topk=2
    )
    paths = write_rename_prompt(candidates, tmp_path)

    # 必须同时生成 rename_prompt.md (agent 任务) 和 candidates jsonl。
    prompt_md = tmp_path / "rename_prompt.md"
    candidates_jsonl = tmp_path / "rename_candidates.jsonl"
    assert prompt_md in paths
    assert candidates_jsonl in paths
    assert prompt_md.exists()
    assert candidates_jsonl.exists()

    # prompt 必须明确禁纯字符串相似度判断（spec §6）。
    text = prompt_md.read_text(encoding="utf-8")
    assert "语义" in text
    assert "相似度" in text  # 须声明相似度不可靠
    # 输出 schema 含 confidence / is_rename 字段。
    assert "confidence" in text
    assert "is_rename" in text

    # candidates jsonl: 每行一个独有校 + 候选旧校名列表。
    lines = [
        json.loads(line)
        for line in candidates_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 2
    assert {line["new_school"] for line in lines} == {"新大学甲", "新大学乙"}


# ---------------------------------------------------------------------------
# apply_rename
# ---------------------------------------------------------------------------


def _make_jsonl(tmp_path: Path, name: str, rows: list[dict]) -> Path:
    p = tmp_path / name
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
        encoding="utf-8",
    )
    return p


def test_apply_rename_builds_rename_table_and_returns_confirmed_set(
    tmp_path: Path,
) -> None:
    # Agent 确认两条改名对（is_rename=True）；new∈大绿本独有校。
    jsonl = _make_jsonl(
        tmp_path,
        "rename_result.jsonl",
        [
            {
                "new_school": "新大学甲",
                "old_school": "旧大学甲",
                "confidence": 0.92,
                "is_rename": True,
            },
            {
                "new_school": "新大学乙",
                "old_school": "旧大学乙",
                "confidence": 0.85,
                "is_rename": True,
            },
        ],
    )
    dgl_rows = [
        DaglubenRow(school="新大学甲", major="计算机", src_row_idx=1),
        DaglubenRow(school="新大学甲", major="英语", src_row_idx=2),
        DaglubenRow(school="新大学乙", major="物理", src_row_idx=3),
        DaglubenRow(school="共有大学", major="数学", src_row_idx=4),
    ]
    hist_rows = [
        HistoryRow(school="旧大学甲", major="计算机"),
        HistoryRow(school="旧大学乙", major="物理"),
        HistoryRow(school="共有大学", major="数学"),
    ]

    rename_table, confirmed = apply_rename([jsonl], dgl_rows, hist_rows)

    assert len(rename_table) == 2
    by_new = {r["new_school"]: r for r in rename_table}
    assert by_new["新大学甲"]["old_school"] == "旧大学甲"
    assert by_new["新大学甲"]["confidence"] == 0.92
    # 该校 2026 本科专业数 = 2（计算机 + 英语）。
    assert by_new["新大学甲"]["major_count_2026"] == 2
    # 返回的 confirmed 集合 = 确认改名的大绿本校名。
    assert confirmed == {"新大学甲", "新大学乙"}


def test_apply_rename_skips_non_rename_and_keeps_them_out_of_confirmed(
    tmp_path: Path,
) -> None:
    # Agent 判定某条不构成改名 (is_rename=False) → 不进改名表，也不进 confirmed。
    jsonl = _make_jsonl(
        tmp_path,
        "rename_result.jsonl",
        [
            {
                "new_school": "新大学甲",
                "old_school": "旧大学甲",
                "confidence": 0.9,
                "is_rename": True,
            },
            {
                "new_school": "新大学乙",
                "old_school": "旧大学丙",
                "confidence": 0.2,
                "is_rename": False,
            },
        ],
    )
    dgl_rows = [DaglubenRow(school="新大学甲", major="计算机", src_row_idx=1)]
    hist_rows = [HistoryRow(school="旧大学甲", major="计算机")]

    rename_table, confirmed = apply_rename([jsonl], dgl_rows, hist_rows)

    assert [r["new_school"] for r in rename_table] == ["新大学甲"]
    assert confirmed == {"新大学甲"}


def test_apply_rename_rejects_confidence_out_of_range(
    tmp_path: Path,
) -> None:
    # 契约：confidence ∈ [0,1]。
    jsonl = _make_jsonl(
        tmp_path,
        "rename_result.jsonl",
        [
            {
                "new_school": "新大学甲",
                "old_school": "旧大学甲",
                "confidence": 1.5,
                "is_rename": True,
            },
        ],
    )
    with pytest.raises(RenameContractError):
        apply_rename([jsonl], [DaglubenRow(school="新大学甲", src_row_idx=1)],
                     [HistoryRow(school="旧大学甲")])


def test_apply_rename_rejects_missing_required_fields(
    tmp_path: Path,
) -> None:
    jsonl = _make_jsonl(
        tmp_path,
        "rename_result.jsonl",
        [
            {"new_school": "新大学甲", "old_school": "", "confidence": 0.9,
             "is_rename": True},
        ],
    )
    with pytest.raises(RenameContractError):
        apply_rename([jsonl], [DaglubenRow(school="新大学甲", src_row_idx=1)],
                     [HistoryRow(school="旧大学甲")])


def test_apply_rename_rejects_new_school_not_in_dagluben_unique(
    tmp_path: Path,
) -> None:
    # 契约：new_school 必须是大绿本独有校（即出现在大绿本但不在历史）。
    jsonl = _make_jsonl(
        tmp_path,
        "rename_result.jsonl",
        [
            {
                "new_school": "共有大学",  # 也出现在历史 → 非独有校
                "old_school": "旧大学甲",
                "confidence": 0.9,
                "is_rename": True,
            },
        ],
    )
    dgl_rows = [DaglubenRow(school="共有大学", major="数学", src_row_idx=1)]
    hist_rows = [HistoryRow(school="共有大学", major="数学"),
                 HistoryRow(school="旧大学甲", major="x")]
    with pytest.raises(RenameContractError):
        apply_rename([jsonl], dgl_rows, hist_rows)


def test_apply_rename_remarks_default_empty_and_manual_reviewed_false(
    tmp_path: Path,
) -> None:
    jsonl = _make_jsonl(
        tmp_path,
        "rename_result.jsonl",
        [
            {
                "new_school": "新大学甲",
                "old_school": "旧大学甲",
                "confidence": 0.9,
                "is_rename": True,
            },
        ],
    )
    dgl_rows = [DaglubenRow(school="新大学甲", major="计算机", src_row_idx=1)]
    hist_rows = [HistoryRow(school="旧大学甲", major="计算机")]

    rename_table, _ = apply_rename([jsonl], dgl_rows, hist_rows)
    row = rename_table[0]
    assert row.get("remark", "") == ""
    assert row.get("manual_reviewed") is False


def test_apply_rename_empty_input_returns_empty(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    rename_table, confirmed = apply_rename([empty], [], [])
    assert rename_table == []
    assert confirmed == set()
