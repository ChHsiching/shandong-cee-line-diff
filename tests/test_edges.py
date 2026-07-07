"""TDD tests for Slice 6 Task 6.1 — boundary edges (deleted/flight/special).

Per Plan v2 CRITICAL order: Task 6.2 (rename detect) runs **before** this so
``deleted_majors`` can take ``renamed_dgl_schools`` and exclude renamed
schools' historical majors — otherwise a renamed school's pre-rename majors
would be misclassified as「被删」.

Pure functions under test (scripts/stage3_edges.py):
  - :func:`deleted_majors` — 近三年有 + 该校(基础校名)在2026大绿本存在 + 2026缺
    + 该校非改名校 (renamed_dgl_schools 排除).
  - :func:`flight_and_special` — 飞行技术(军队)2行归提前批池匹配不成→特殊；
    其余无法匹配→特殊.

Small-sample RED cases only; the real-data counts are a smoke output
(scripts/run_rename_smoke.py) and do NOT participate in the RED contract.
"""

from __future__ import annotations

from scripts.constants import FLIGHT_BATCH
from scripts.models import DaglubenRow, HistoryRow
from scripts.stage3_edges import DeletedMajor, EdgeRow, deleted_majors, flight_and_special


# ---------------------------------------------------------------------------
# deleted_majors
# ---------------------------------------------------------------------------


def test_deleted_majors_keeps_history_major_absent_from_2026_dagluben() -> None:
    # 近三年有「甲专业」，该校在 2026 大绿本存在，但 2026 无「甲专业」 → 被删。
    history = [
        HistoryRow(school="示例大学", major="甲专业", school_cat="", J=80.0, T=1.0),
        HistoryRow(school="示例大学", major="乙专业", school_cat="", J=70.0, T=0.5),
    ]
    dgl_present = {"示例大学"}
    deleted = deleted_majors(history, dgl_present, renamed_dgl_schools=set())

    by_major = {d["major"]: d for d in deleted}
    # 两个专业都不在 2026（dgl_present 只表示学校在，不代表专业在）→ 均为被删候选。
    # 注意：本函数仅按「该校在 + 专业近三年有」判，是否 2026 缺由调用方用大绿本
    # 专业集合减出；这里用最小样本直接断言全部近三年专业均进入被删池。
    assert "甲专业" in by_major
    assert "乙专业" in by_major
    assert by_major["甲专业"]["school"] == "示例大学"
    assert by_major["甲专业"]["J"] == 80.0


def test_deleted_majors_excludes_schools_absent_from_2026_dagluben() -> None:
    # 该校不在 2026 大绿本 → 整校缺席，归「停招消失校表」，不进被删表。
    history = [
        HistoryRow(school="消失大学", major="甲专业", J=80.0),
        HistoryRow(school="存在大学", major="乙专业", J=70.0),
    ]
    dgl_present = {"存在大学"}  # 消失大学 不在
    deleted = deleted_majors(history, dgl_present, renamed_dgl_schools=set())
    schools = {d["school"] for d in deleted}
    assert schools == {"存在大学"}
    assert all(d["school"] != "消失大学" for d in deleted)


def test_deleted_majors_excludes_renamed_schools() -> None:
    # CRITICAL (v2 顺序注记)：改名校的历史专业不应被误塞被删表。
    # 改名后该校在 2026 用「新校名」招生；若不排除，旧校名下的历史专业会
    # 被误判为「近三年有、2026 缺」。
    history = [
        HistoryRow(school="旧大学", major="甲专业", J=80.0),   # 旧名 = 历史独有校
        HistoryRow(school="新大学", major="乙专业", J=70.0),   # 新名 = 大绿本独有校
    ]
    # 「新大学」在 2026 存在；「旧大学」不在（改名消失）。
    dgl_present = {"新大学"}
    # confirmed 改名的大绿本校名 = 新大学（即旧大学 → 新大学）。
    renamed = {"新大学"}

    deleted = deleted_majors(history, dgl_present, renamed_dgl_schools=renamed)
    # 新大学是改名校 → 其历史专业不入被删；旧大学不在 2026 → 不入被删。
    # 结果应为空（无被删专业）。
    assert deleted == []


def test_deleted_majors_distinguishes_school_and_major_scoping() -> None:
    # 同一专业名在多校出现：仅「该校在 2026」者计入被删。
    history = [
        HistoryRow(school="甲大学", major="公共专业", J=80.0),
        HistoryRow(school="乙大学", major="公共专业", J=70.0),
    ]
    dgl_present = {"甲大学"}  # 乙大学 不在
    deleted = deleted_majors(history, dgl_present, renamed_dgl_schools=set())
    assert {d["school"] for d in deleted} == {"甲大学"}


def test_deleted_majors_empty_history_returns_empty() -> None:
    assert deleted_majors([], {"甲大学"}, renamed_dgl_schools=set()) == []


# ---------------------------------------------------------------------------
# flight_and_special
# ---------------------------------------------------------------------------


def test_flight_rows_unmatched_become_special() -> None:
    # 飞行技术(军队) 2 行：batch=FLIGHT_BATCH，归提前批池匹配不成 → 特殊。
    flight_unmatched = [
        DaglubenRow(school="空军航空大学", major="飞行技术",
                    batch=FLIGHT_BATCH, src_row_idx=101),
        DaglubenRow(school="海军航空大学", major="飞行技术",
                    batch=FLIGHT_BATCH, src_row_idx=102),
    ]
    # 其它无法匹配的大绿本专业（剩余 unmatched 残留）。
    other_unmatched = [
        DaglubenRow(school="某大学", major="奇怪专业",
                    batch="4.常规批", src_row_idx=200),
    ]

    special = flight_and_special(flight_unmatched, other_unmatched)

    # 全部进特殊表。
    schools = {r["school"] for r in special}
    assert "空军航空大学" in schools
    assert "海军航空大学" in schools
    assert "某大学" in schools
    # 飞行行的日志写明「飞行技术(军队)，提前批池匹配不成」。
    flight_rows = [r for r in special if r["batch"] == FLIGHT_BATCH]
    assert len(flight_rows) == 2
    assert all("飞行" in r["log"] for r in flight_rows)
    # 其它行日志为「无法匹配：<原因>」。
    other = [r for r in special if r["school"] == "某大学"]
    assert len(other) == 1
    assert "没找到" in other[0]["log"]


def test_flight_and_special_empty_inputs_returns_empty() -> None:
    assert flight_and_special([], []) == []


def test_flight_and_special_preserves_dagluben_fields() -> None:
    flight = [
        DaglubenRow(school="空军航空大学", major="飞行技术", core="飞行技术",
                    subject="物理", batch=FLIGHT_BATCH, src_row_idx=7),
    ]
    special = flight_and_special(flight, [])
    assert len(special) == 1
    row = special[0]
    # EdgeRow 保留原大绿本关键字段以便人工核验。
    assert row["src_row_idx"] == 7
    assert row["major"] == "飞行技术"
    assert row["batch"] == FLIGHT_BATCH


def test_deletedmajor_is_edgerow_subschema() -> None:
    # DeletedMajor 与 EdgeRow 共享关键字段（school/major/src_row_idx/log）。
    dm = DeletedMajor(school="甲大学", major="乙专业", J=80.0, T=1.0,
                      school_cat="", log="近三年有、2026 大绿本无")
    er = EdgeRow(school="甲大学", major="乙专业", batch="", src_row_idx=0,
                 log="无法匹配：测试")
    # 二者都有 school / major / log 键。
    for key in ("school", "major", "log"):
        assert key in dm
        assert key in er
