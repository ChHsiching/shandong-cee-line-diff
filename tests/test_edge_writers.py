"""TDD tests for Slice 6 Task 6.1/6.2 — boundary table writers + rename marker.

Covers the five writers that replace the Slice 5 NotImplementedError stubs
in scripts/write_edge_tables.py plus mark_rename_in_main (改名校专业 J/T
留空+日志, spec §6 Stage 3 改名 / §9 改名 log).

Small-sample RED cases; the real-data counts are a smoke output
(scripts/run_rename_smoke.py).
"""

from __future__ import annotations

from pathlib import Path

import openpyxl

from scripts.constants import LOG_RENAME_PENDING
from scripts.models import DaglubenRow
from scripts.write_edge_tables import (
    mark_rename_in_main,
    write_deleted_major_table,
    write_gone_school_table,
    write_new_school_table,
    write_rename_table,
    write_special_table,
)


def _load(path: Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    try:
        return list(ws.iter_rows(values_only=True))
    finally:
        wb.close()


# ---------------------------------------------------------------------------
# write_deleted_major_table
# ---------------------------------------------------------------------------


def test_write_deleted_major_table(tmp_path: Path) -> None:
    rows = [
        {"学校": "甲大学", "招生类别": "", "专业": "旧专业",
         "近三年统计线差": 80.0, "近三年线差标准差": 1.0,
         "日志": "近三年有、2026 大绿本无"},
    ]
    out = tmp_path / "被删旧专业.xlsx"
    write_deleted_major_table(rows, out)
    data = _load(out)
    assert data[0][0] == "学校"
    assert "日志" in data[0]
    assert data[1][2] == "旧专业"
    assert data[1][5] == "近三年有、2026 大绿本无"


def test_write_deleted_major_table_empty(tmp_path: Path) -> None:
    out = tmp_path / "被删旧专业.xlsx"
    write_deleted_major_table([], out)
    data = _load(out)
    assert len(data) == 1  # header only


# ---------------------------------------------------------------------------
# write_rename_table
# ---------------------------------------------------------------------------


def test_write_rename_table_has_manual_reviewed_column(tmp_path: Path) -> None:
    rows = [
        {"new_school": "新大学", "old_school": "旧大学", "confidence": 0.9,
         "major_count_2026": 5, "remark": "", "manual_reviewed": False},
    ]
    out = tmp_path / "学校改名表.xlsx"
    write_rename_table(rows, out)
    data = _load(out)
    # v2 幂等契约: manual_reviewed 必须作为可见列。
    assert "人工已核验" in data[0]
    assert "备注" in data[0]
    assert data[1][0] == "新大学"
    assert data[1][3] == 5


def test_write_rename_table_empty(tmp_path: Path) -> None:
    out = tmp_path / "学校改名表.xlsx"
    write_rename_table([], out)
    assert len(_load(out)) == 1


def test_write_rename_table_maps_field_names_to_columns(tmp_path: Path) -> None:
    """Regression: real RenameRow fields (new_school/old_school/...) must map to
    header columns (2026新校名/候选旧校名/...). Previously write_rename_table
    passed RenameRow straight to _write_simple_table, whose record.get(header)
    lookup missed every field (header name ≠ field name) → empty cells."""
    rows = [
        {"new_school": "新大学", "old_school": "旧大学", "confidence": 0.9,
         "is_rename": True, "major_count_2026": 5,
         "remark": "网查：2026由旧大学更名", "manual_reviewed": False},
    ]
    out = tmp_path / "学校改名表.xlsx"
    write_rename_table(rows, out)
    data = _load(out)
    assert data[0] == ("2026新校名", "候选旧校名", "置信度",
                       "2026本科专业数", "备注", "人工已核验")
    assert data[1][0] == "新大学"          # 2026新校名 ← new_school
    assert data[1][1] == "旧大学"          # 候选旧校名 ← old_school
    assert data[1][2] == 0.9              # 置信度 ← confidence
    assert data[1][3] == 5                # 2026本科专业数 ← major_count_2026
    assert data[1][4] == "网查：2026由旧大学更名"  # 备注 ← remark
    assert data[1][5] is False            # 人工已核验 ← manual_reviewed


# ---------------------------------------------------------------------------
# write_new_school_table / write_gone_school_table
# ---------------------------------------------------------------------------


def test_write_new_school_table(tmp_path: Path) -> None:
    rows = [{"new_school": "全新大学", "major_count_2026": 3}]
    out = tmp_path / "新增校表.xlsx"
    write_new_school_table(rows, out)
    data = _load(out)
    assert data[0][0] == "2026新校名"
    assert data[1][0] == "全新大学"
    assert data[1][1] == 3


def test_write_gone_school_table(tmp_path: Path) -> None:
    rows = [{"old_school": "消失大学"}]
    out = tmp_path / "停招消失校表.xlsx"
    write_gone_school_table(rows, out)
    data = _load(out)
    assert data[0][0] == "历史旧校名"
    assert data[1][0] == "消失大学"
    assert "未在 2026 招生" in data[1][1]


# ---------------------------------------------------------------------------
# write_special_table
# ---------------------------------------------------------------------------


def test_write_special_table(tmp_path: Path) -> None:
    rows = [
        {"src_row_idx": 7, "学校": "空军航空大学", "招生类别": "",
         "专业": "飞行技术", "核心名": "飞行技术", "选科": "物理",
         "批次": "3.提前批—飞行技术(军队)",
         "日志": "飞行技术(军队)，提前批池匹配不成"},
    ]
    out = tmp_path / "特殊情况.xlsx"
    write_special_table(rows, out)
    data = _load(out)
    assert "飞行" in data[1][7]


# ---------------------------------------------------------------------------
# mark_rename_in_main
# ---------------------------------------------------------------------------


def test_mark_rename_in_main_empties_j_t_and_sets_log() -> None:
    dagluben = [
        DaglubenRow(school="新大学", major="计算机", J=70.0, T=1.0,
                    src_row_idx=1),
        DaglubenRow(school="共有大学", major="数学", J=80.0, T=2.0,
                    src_row_idx=2),
    ]
    renamed = {"新大学"}
    marked = mark_rename_in_main(dagluben, renamed)
    by_idx = {r["src_row_idx"]: r for r in marked}

    # 改名校专业: J/T 置空, 日志为「疑似改名校…」, 带 is_rename_pending 标记.
    assert by_idx[1]["J"] is None
    assert by_idx[1]["T"] is None
    assert by_idx[1]["log"] == LOG_RENAME_PENDING
    assert by_idx[1].get("is_rename_pending") is True

    # 非改名校专业: 保持原样, 无改名标记.
    assert by_idx[2]["J"] == 80.0
    assert by_idx[2].get("is_rename_pending") is not True


def test_mark_rename_in_main_empty_renamed_keeps_all() -> None:
    dagluben = [DaglubenRow(school="甲", major="x", J=70.0, src_row_idx=1)]
    marked = mark_rename_in_main(dagluben, set())
    assert marked[0].get("is_rename_pending") is not True
    assert marked[0]["J"] == 70.0
