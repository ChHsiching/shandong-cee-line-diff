"""Tests for scripts.stage0_merge — Stage 0 pure builders.

Per Plan v2: small synthetic workbooks are the RED判据; real-workbook row
counts (28269 / 23887) are smoke-level only and live in the separate
TestStage0Smoke class (not part of pure-function RED).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import stage0_merge


# --- build_history_regular (pure function, RED) ----------------------------

def _j3_rows(rows: list[tuple]) -> list[tuple]:
    """Pad short tuples to full 20-col width so list[tuple] is workbook-shaped."""
    width = 20
    return [tuple(list(r) + [None] * (width - len(r))) for r in rows]


def test_build_history_regular_filters_one_batch_only():
    rows = _j3_rows(
        [
            # header
            ("batch", "code", "school", "major", "subject", "remarks",
             "base", "isb", "bracket", "J", "k", "l", "m"),
            # regular seg1 — kept
            ("常规批一段线", "D1", "北京大学", "数学", "物理", "",
             "数学", "否", "", 60.0, 60, 60, 60),
            # seg2 — dropped
            ("常规批二段线", "D2", "X大学", "护理", "不限", "",
             "护理", "否", "", 10.0, 10, 10, 10),
            # 提前批 — dropped (not in this builder's scope)
            ("提前批", "D3", "Y大学", "小语种", "历史", "",
             "小语种", "否", "", 50.0, 50, 50, 50),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    assert len(out) == 1
    row = out[0]
    assert row["school"] == "北京大学"
    assert row["school_cat"] == ""
    assert row["major"] == "数学"
    assert row["stripped"] == "数学"
    assert row["core"] == "数学"
    assert row["J"] == 60.0
    assert row["T"] is None  # column T (idx 19) was None
    assert row["source_table"] == "常规批一段线"


def test_build_history_regular_splits_category_from_school_name():
    rows = _j3_rows(
        [
            ("常规批一段线", "D9", "三亚学院(中外合作办学)", "俄语", "不限", "3",
             "俄语", "否", "", 30.0, None, None, 30),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    assert out[0]["school"] == "三亚学院"
    assert out[0]["school_cat"] == "中外合作办学"
    assert out[0]["stripped"] == "俄语"


def test_build_history_regular_strips_ignore_brackets_in_major():
    rows = _j3_rows(
        [
            ("常规批一段线", "D1", "Z大学", "临床医学(色盲考生不予录取)", "化学", "",
             "临床医学", "是", "色盲考生不予录取", 40.0, 40, 40, 40),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    assert out[0]["stripped"] == "临床医学"
    assert out[0]["core"] == "临床医学"


def test_build_history_regular_excludes_zhuanke_subtitle_via_remarks():
    """seg1 is本科-only; 近三年 still lists 专科 — remarks/subtitle carrying
    the专科 keyword is excluded even within常规批一段线."""
    rows = _j3_rows(
        [
            ("常规批一段线", "D1", "A大学", "数学", "物理", "",
             "数学", "否", "", 60.0, 60, 60, 60),
            ("常规批一段线", "D2", "B职业学院", "护理(专科)", "不限", "专科",
             "护理", "否", "专科", 10.0, 10, 10, 10),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    # 专科 row excluded
    assert len(out) == 1
    assert out[0]["school"] == "A大学"


# --- build_dagluben_regular (pure function, RED) ---------------------------

def _dl_row(row: list) -> list:
    """Pad to 12 cols (dagluben width)."""
    width = 12
    return list(row) + [None] * (width - len(row))


def test_build_dagluben_regular_keeps_only_major_rows_of_regular_batch():
    rows = [
        _dl_row(
            ["批次", "小标题", "学校代码", "学校名", "代号", "名称",
             "选科", "学制", "计划数", "备注", "年收费", "整行校准"]
        ),
        # 批次头 (no 代号/名称) -> skipped
        _dl_row(["4.常规批", "", "", "", "", "", "", "", "", "", "", ""]),
        # 小标题 (no 代号/名称) -> skipped
        _dl_row(["4.常规批", "普通计划", "", "", "", "", "", "", "", "", "", ""]),
        # 学校行 (no 代号/名称) -> skipped
        _dl_row(["4.常规批", "普通计划", "A001", "示例大学", "", "", "", "", "100"]),
        # 专业行 1 -> kept
        _dl_row(["4.常规批", "普通计划", "A001", "示例大学", "01", "计算机科学与技术",
                 "物理和化学", "4", "2"]),
        # 专业行 2 -> kept
        _dl_row(["4.常规批", "普通计划", "A001", "示例大学", "02", "英语",
                 "不限", "4", "1"]),
        # 提前批 major row -> dropped (not regular batch)
        _dl_row(["1.提前批A类", "军事类", "P002", "国防科大", "10", "数学",
                 "物理和化学", "4", "1"]),
        # 专科 subtitle major row -> dropped
        _dl_row(["4.常规批", "定向培养军士生(专科)", "C001", "D职业学院",
                 "03", "护理", "不限", "3", "50"]),
    ]
    out = stage0_merge.build_dagluben_regular(rows)
    assert len(out) == 2
    schools = [r["school"] for r in out]
    assert schools == ["示例大学", "示例大学"]
    cats = [r["school_cat"] for r in out]
    assert cats == ["普通计划", "普通计划"]
    assert out[0]["major"] == "计算机科学与技术"
    assert out[0]["batch"] == "4.常规批"
    assert out[0]["src_row_idx"] == 5  # 1-based: header=1, 头=2, 小标题=3, 学校=4, 专业1=5
    assert out[1]["src_row_idx"] == 6  # 专业2 = row 6


def test_build_dagluben_regular_normalises_school_and_major():
    rows = [
        _dl_row(
            ["批次", "小标题", "学校代码", "学校名", "代号", "名称"]
        ),
        _dl_row(
            ["4.常规批", "中外合作办学", "A002", "三亚学院", "01",
             "英语（师范）", "不限", "4", "1"]
        ),
    ]
    out = stage0_merge.build_dagluben_regular(rows)
    # school stays as-is (大绿本 does not append category to校名);
    # major normalised (full-width -> half-width).
    assert out[0]["school"] == "三亚学院"
    assert out[0]["school_cat"] == "中外合作办学"
    assert out[0]["major"] == "英语(师范)"
    assert out[0]["stripped"] == "英语(师范)"
    assert out[0]["core"] == "英语"


# --- write intermediate CSV (round-trip) -----------------------------------

def test_write_history_regular_csv_writes_expected_columns(tmp_path):
    rows = _j3_rows(
        [
            ("常规批一段线", "D1", "北京大学", "数学", "物理", "",
             "数学", "否", "", 60.0, 60, 60, 60),
        ]
    )
    built = stage0_merge.build_history_regular(rows)
    out_path = tmp_path / "hist.csv"
    stage0_merge.write_history_csv(built, out_path)
    with out_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        records = list(reader)
    assert len(records) == 1
    assert records[0]["school"] == "北京大学"
    assert records[0]["major"] == "数学"
    assert records[0]["J"] == "60.0"


# --- Real-workbook smoke (NOT RED; Plan v2 separates smoke from RED) -------

class TestStage0Smoke:
    """Smoke层: real source row counts. Marked so pure-function failures
    aren't masked by these — they're here to lock the documented cardinalities
    (常规批一段线 28269, 大绿本常规批专业 23887) per spec §2."""

    def test_smoke_history_regular_row_count(self, repo_root: Path):
        from scripts import io_source

        wb = io_source.load_source(repo_root / "data" / "近三年学校批次专业线差统计.xlsx")
        try:
            ws = wb["统计结果"]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        built = stage0_merge.build_history_regular(rows)
        assert len(built) == 28269

    def test_smoke_dagluben_regular_major_row_count(self, repo_root: Path):
        from scripts import io_source

        wb = io_source.load_source(repo_root / "data" / "山东省2026年大绿本招生计划.xlsx")
        try:
            ws = wb[wb.sheetnames[0]]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        built = stage0_merge.build_dagluben_regular(rows)
        assert len(built) == 23887
