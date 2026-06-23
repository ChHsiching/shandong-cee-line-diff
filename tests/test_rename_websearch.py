"""TDD tests for Slice 6 Task 6.3 — rename web-search remark merge (pure layer).

Per Plan v2 binding + Slice 4 architecture: WebSearch **cannot be invoked from
a Python script** (harness tool), so this slice ships only the testable pure
functions plus the harness-side RUN doc:

  - :func:`scripts.rename_websearch.format_query` — build the WebSearch query
    string for one renamed school.
  - :func:`scripts.rename_websearch.merge_remark` — merge a research/<school>.md
    summary into a RenameRow's ``remark``. **Idempotent (v2)**: rows whose
    ``manual_reviewed`` is True are NOT overwritten (human edits win).

Contract tests:
  - confidence range / field presence / 改名校 excluded from deleted — covered
    in test_rename_detect.py / test_edges.py.
  - 这里聚焦网查格式化与幂等合并契约.
"""

from __future__ import annotations

from scripts.models import RenameRow
from scripts.rename_websearch import format_query, merge_remark


# ---------------------------------------------------------------------------
# format_query
# ---------------------------------------------------------------------------


def test_format_query_includes_both_names() -> None:
    q = format_query(school_new="山东航空学院", school_old="滨州学院")
    # 查询须含新校名与候选旧校名，便于网查确认是否同源/更名。
    assert "山东航空学院" in q
    assert "滨州学院" in q


def test_format_query_mentions_rename_intent() -> None:
    q = format_query(school_new="甲大学", school_old="乙学院")
    # 提示网查关注「更名/转设」语义（spec §6 最后一步）。
    assert any(kw in q for kw in ("更名", "转设", "改名", "前身"))


# ---------------------------------------------------------------------------
# merge_remark — idempotency
# ---------------------------------------------------------------------------


def test_merge_remark_fills_empty_remark_when_not_manually_reviewed() -> None:
    row = RenameRow(
        new_school="山东航空学院",
        old_school="滨州学院",
        confidence=0.9,
        is_rename=True,
        major_count_2026=10,
        remark="",
        manual_reviewed=False,
    )
    research_md = "## 网查摘要\n滨州学院于 2023 年更名为山东航空学院。"
    merged = merge_remark(research_md, row)
    assert "滨州学院" in merged["remark"]
    assert "2023" in merged["remark"]
    # 合并后仍标记未人工审核（网查写入不等于人工确认）。
    assert merged["manual_reviewed"] is False


def test_merge_remark_does_not_overwrite_manually_reviewed() -> None:
    # v2 幂等契约：manual_reviewed=True 的备注已被人工编辑，网查重跑不覆盖。
    row = RenameRow(
        new_school="甲大学",
        old_school="乙学院",
        confidence=0.9,
        is_rename=True,
        major_count_2026=5,
        remark="人工已确认：2022年更名，同源。",
        manual_reviewed=True,
    )
    research_md = "## 网查摘要\n（网查旧结论，应被忽略）"
    merged = merge_remark(research_md, row)
    assert merged["remark"] == "人工已确认：2022年更名，同源。"
    assert merged["manual_reviewed"] is True


def test_merge_remark_returns_new_row_does_not_mutate_input() -> None:
    # 不可变契约 (coding-style.md): 返回新对象, 不原地改输入.
    row = RenameRow(
        new_school="甲大学",
        old_school="乙学院",
        confidence=0.9,
        is_rename=True,
        major_count_2026=5,
        remark="",
        manual_reviewed=False,
    )
    merged = merge_remark("网查结果", row)
    assert merged is not row
    assert row["remark"] == ""  # 原行未被改


def test_merge_remark_empty_research_keeps_existing_remark() -> None:
    # 网查无结果（空 md）→ 不清空已有备注。
    row = RenameRow(
        new_school="甲大学",
        old_school="乙学院",
        confidence=0.9,
        is_rename=True,
        major_count_2026=5,
        remark="已有人工备注",
        manual_reviewed=False,
    )
    merged = merge_remark("", row)
    assert merged["remark"] == "已有人工备注"
