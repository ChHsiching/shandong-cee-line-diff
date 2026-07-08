"""Tests for scripts.stage0_merge — Stage 0 pure builders.

Per Plan v2: small synthetic workbooks are the RED判据; real-workbook row
counts (28269 / 23887) are smoke-level only and live in the separate
TestStage0Smoke class (not part of pure-function RED).
"""

from __future__ import annotations

import csv
from pathlib import Path


from scripts import stage0_merge


# --- build_history_regular (pure function, RED) ----------------------------


def _j3_rows(rows: list[tuple]) -> list[tuple]:
    """Pad short tuples to full 20-col width so list[tuple] is workbook-shaped."""
    width = 20
    return [tuple(list(r) + [None] * (width - len(r))) for r in rows]


def test_build_history_regular_keeps_regular_and_early_drops_seg2():
    rows = _j3_rows(
        [
            # header
            (
                "batch",
                "code",
                "school",
                "major",
                "subject",
                "remarks",
                "base",
                "isb",
                "bracket",
                "J",
                "k",
                "l",
                "m",
            ),
            # regular seg1 — kept
            (
                "常规批一段线",
                "D1",
                "北京大学",
                "数学",
                "物理",
                "",
                "数学",
                "否",
                "",
                60.0,
                60,
                60,
                60,
            ),
            # seg2 — dropped
            (
                "常规批二段线",
                "D2",
                "X大学",
                "护理",
                "不限",
                "",
                "护理",
                "否",
                "",
                10.0,
                10,
                10,
                10,
            ),
            # 提前批 — kept（J3 提前批带现成线差，直接用；只有 TQ 补充表才现场算）
            (
                "提前批",
                "D3",
                "Y大学",
                "小语种",
                "历史",
                "",
                "小语种",
                "否",
                "",
                50.0,
                50,
                50,
                50,
            ),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    assert len(out) == 2  # 常规批一段线 + 提前批（二段线 dropped）
    by_school = {r["school"]: r for r in out}
    assert "北京大学" in by_school  # 常规批一段线
    assert "Y大学" in by_school  # 提前批
    assert by_school["北京大学"]["source_table"] == "常规批一段线"
    assert by_school["Y大学"]["source_table"] == "提前批"
    assert by_school["Y大学"]["J"] == 50.0  # 现成线差，直接用


def test_build_history_regular_splits_category_from_school_name():
    rows = _j3_rows(
        [
            (
                "常规批一段线",
                "D9",
                "三亚学院(中外合作办学)",
                "俄语",
                "不限",
                "3",
                "俄语",
                "否",
                "",
                30.0,
                None,
                None,
                30,
            ),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    assert out[0]["school"] == "三亚学院"
    assert out[0]["school_cat"] == "中外合作办学"
    assert out[0]["stripped"] == "俄语"


def test_build_history_regular_strips_ignore_brackets_in_major():
    rows = _j3_rows(
        [
            (
                "常规批一段线",
                "D1",
                "Z大学",
                "临床医学(色盲考生不予录取)",
                "化学",
                "",
                "临床医学",
                "是",
                "色盲考生不予录取",
                40.0,
                40,
                40,
                40,
            ),
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
            (
                "常规批一段线",
                "D1",
                "A大学",
                "数学",
                "物理",
                "",
                "数学",
                "否",
                "",
                60.0,
                60,
                60,
                60,
            ),
            (
                "常规批一段线",
                "D2",
                "B职业学院",
                "护理(专科)",
                "不限",
                "专科",
                "护理",
                "否",
                "专科",
                10.0,
                10,
                10,
                10,
            ),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    # 专科 row excluded
    assert len(out) == 1
    assert out[0]["school"] == "A大学"


def test_build_history_regular_excludes_junshizhuanke_early_rows():
    """Def-2（fresh-test 2026-07-09 真实数据）：提前批「定向培养军士生」专科行
    （威海职业/滨州职业等专科校，bracket=「定向培养军士生,与xx联合培养」、
    remarks 空、线差为负）曾漏进本科池——_looks_zhuanke 只查「专科」漏掉了它。
    污染改名候选（专科校成历史独有校）+ 潜在线差错配。必须排除。"""
    rows = _j3_rows(
        [
            (
                "提前批", "D1", "威海职业学院", "现代通信技术", "物理", "",
                "现代通信技术", "是", "定向培养军士生，与武警部队联合培养",
                -2.0, -2, -2, -2,
            ),
            (
                "提前批", "D2", "A大学", "数学", "物理", "",
                "数学", "否", "", 80.0, 80, 80, 80,
            ),
        ]
    )
    out = stage0_merge.build_history_regular(rows)
    # 军士生专科行排除，本科行保留
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
            [
                "批次",
                "小标题",
                "学校代码",
                "学校名",
                "代号",
                "名称",
                "选科",
                "学制",
                "计划数",
                "备注",
                "年收费",
                "整行校准",
            ]
        ),
        # 批次头 (no 代号/名称) -> skipped
        _dl_row(["4.常规批", "", "", "", "", "", "", "", "", "", "", ""]),
        # 小标题 (no 代号/名称) -> skipped
        _dl_row(["4.常规批", "普通计划", "", "", "", "", "", "", "", "", "", ""]),
        # 学校行 (no 代号/名称) -> skipped
        _dl_row(["4.常规批", "普通计划", "A001", "示例大学", "", "", "", "", "100"]),
        # 专业行 1 -> kept
        _dl_row(
            [
                "4.常规批",
                "普通计划",
                "A001",
                "示例大学",
                "01",
                "计算机科学与技术",
                "物理和化学",
                "4",
                "2",
            ]
        ),
        # 专业行 2 -> kept
        _dl_row(
            ["4.常规批", "普通计划", "A001", "示例大学", "02", "英语", "不限", "4", "1"]
        ),
        # 提前批 major row -> dropped (not regular batch)
        _dl_row(
            [
                "1.提前批A类",
                "军事类",
                "P002",
                "国防科大",
                "10",
                "数学",
                "物理和化学",
                "4",
                "1",
            ]
        ),
        # 专科 subtitle major row -> dropped
        _dl_row(
            [
                "4.常规批",
                "定向培养军士生(专科)",
                "C001",
                "D职业学院",
                "03",
                "护理",
                "不限",
                "3",
                "50",
            ]
        ),
    ]
    out = stage0_merge.build_dagluben_regular(rows)
    assert len(out) == 2
    schools = [r["school"] for r in out]
    assert schools == ["示例大学", "示例大学"]
    cats = [r["school_cat"] for r in out]
    assert cats == ["普通计划", "普通计划"]
    assert out[0]["major"] == "计算机科学与技术"
    assert out[0]["batch"] == "4.常规批"
    assert (
        out[0]["src_row_idx"] == 5
    )  # 1-based: header=1, 头=2, 小标题=3, 学校=4, 专业1=5
    assert out[1]["src_row_idx"] == 6  # 专业2 = row 6


def test_build_dagluben_regular_normalises_school_and_major():
    rows = [
        _dl_row(["批次", "小标题", "学校代码", "学校名", "代号", "名称"]),
        _dl_row(
            [
                "4.常规批",
                "中外合作办学",
                "A002",
                "三亚学院",
                "01",
                "英语（师范）",
                "不限",
                "4",
                "1",
            ]
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
            (
                "常规批一段线",
                "D1",
                "北京大学",
                "数学",
                "物理",
                "",
                "数学",
                "否",
                "",
                60.0,
                60,
                60,
                60,
            ),
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


# --- build_history_early (提前批 supplement, pure function RED) -------------


def _tq_row(row: list) -> list:
    """Pad a提前批-supplement-shaped row to full 19-col width
    (idx0..idx18 covers batch..23年录取低分; deeper columns irrelevant)."""
    width = 19
    return list(row) + [None] * (width - len(row))


def test_build_history_early_keeps_only_benke_a_b_and_drops_zhuanke():
    rows = [
        # header
        _tq_row(
            [
                "批次名称",
                "招生类别",
                "院校代码",
                "院校名称",
                "专业代码",
                "专业名称",
                "选科",
                "25人",
                "25高",
                "25均",
                "25低",
                "24人",
                "24高",
                "24均",
                "24低",
                "23人",
                "23高",
                "23均",
                "23低",
            ]
        ),
        # 本科 A — kept
        _tq_row(
            [
                "本科提前批A类",
                "军事类",
                "P002",
                "国防科技大学",
                "36",
                "软件工程",
                "物理和化学",
                1,
                670,
                670,
                670,
                2,
                668,
                665,
                662,
                1,
                660,
                658,
                655,
            ]
        ),
        # 本科 B — kept (merged into same pool)
        _tq_row(
            [
                "本科提前批B类",
                "公安政法类",
                "P010",
                "中国人民公安大学",
                "01",
                "治安学",
                "历史",
                2,
                600,
                590,
                580,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        ),
        # 专科提前批 — dropped
        _tq_row(
            [
                "专科提前批",
                "其他类",
                "Z001",
                "某职业学院",
                "01",
                "护理",
                "不限",
                1,
                300,
                290,
                280,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        ),
    ]
    out = stage0_merge.build_history_early(rows)
    assert len(out) == 2
    assert {r["school"] for r in out} == {"国防科技大学", "中国人民公安大学"}


def test_build_history_early_unifies_batch_to_early_label():
    rows = [
        _tq_row(
            [
                "批次名称",
                "招生类别",
                "院校代码",
                "院校名称",
                "专业代码",
                "专业名称",
                "选科",
                "25人",
                "25高",
                "25均",
                "25低",
                "24人",
                "24高",
                "24均",
                "24低",
                "23人",
                "23高",
                "23均",
                "23低",
            ]
        ),
        _tq_row(
            [
                "本科提前批A类",
                "军事类",
                "P002",
                "国防科技大学",
                "36",
                "软件工程",
                "物理和化学",
                1,
                670,
                670,
                670,
                2,
                668,
                665,
                662,
                1,
                660,
                658,
                655,
            ]
        ),
        _tq_row(
            [
                "本科提前批B类",
                "公安政法类",
                "P010",
                "中国人民公安大学",
                "01",
                "治安学",
                "历史",
                2,
                600,
                590,
                580,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        ),
    ]
    out = stage0_merge.build_history_early(rows)
    # Both A and B are folded to the unified constants.TQ_BATCH_EARLY label.
    assert {r["source_table"] for r in out} == {"提前批"}


def test_build_history_early_computes_J_T_from_low_scores_minus_one_line():
    """3-year low scores {524,568,500} → diffs {83,124,57} → mean=88.0,
    pstdev over 3 samples."""
    rows = [
        _tq_row(
            [
                "批次名称",
                "招生类别",
                "院校代码",
                "院校名称",
                "专业代码",
                "专业名称",
                "选科",
                "25人",
                "25高",
                "25均",
                "25低",
                "24人",
                "24高",
                "24均",
                "24低",
                "23人",
                "23高",
                "23均",
                "23低",
            ]
        ),
        _tq_row(
            [
                "本科提前批A类",
                "军事类",
                "P002",
                "X大学",
                "01",
                "数学",
                "物理和化学",
                None,
                None,
                None,
                524,  # 2025 low
                None,
                None,
                None,
                568,  # 2024 low
                None,
                None,
                None,
                500,  # 2023 low
            ]
        ),
    ]
    out = stage0_merge.build_history_early(rows)
    row = out[0]
    assert row["J"] == 88.0  # mean(83,124,57)
    assert row["T"] is not None  # pstdev of 3 samples
    import statistics

    assert row["T"] == round(statistics.pstdev([83, 124, 57]), 2)  # ≈ 27.58


def test_build_history_early_single_year_J_no_T():
    rows = [
        _tq_row(
            [
                "批次名称",
                "招生类别",
                "院校代码",
                "院校名称",
                "专业代码",
                "专业名称",
                "选科",
                "25人",
                "25高",
                "25均",
                "25低",
                "24人",
                "24高",
                "24均",
                "24低",
                "23人",
                "23高",
                "23均",
                "23低",
            ]
        ),
        _tq_row(
            [
                "本科提前批B类",
                "公安政法类",
                "P010",
                "Y大学",
                "02",
                "治安学",
                "历史",
                None,
                None,
                None,
                500,  # only 2025: 500-441 = 59
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        ),
    ]
    out = stage0_merge.build_history_early(rows)
    assert out[0]["J"] == 59.0
    assert out[0]["T"] is None


def test_build_history_early_no_low_scores_yields_none_J_T():
    rows = [
        _tq_row(
            [
                "批次名称",
                "招生类别",
                "院校代码",
                "院校名称",
                "专业代码",
                "专业名称",
                "选科",
                "25人",
                "25高",
                "25均",
                "25低",
                "24人",
                "24高",
                "24均",
                "24低",
                "23人",
                "23高",
                "23均",
                "23低",
            ]
        ),
        _tq_row(
            [
                "本科提前批A类",
                "军事类",
                "P099",
                "Z大学",
                "03",
                "英语",
                "历史",
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        ),
    ]
    out = stage0_merge.build_history_early(rows)
    assert out[0]["J"] is None
    assert out[0]["T"] is None


def test_build_history_early_normalises_major_and_strips_ignore_brackets():
    rows = [
        _tq_row(
            [
                "批次名称",
                "招生类别",
                "院校代码",
                "院校名称",
                "专业代码",
                "专业名称",
                "选科",
                "25人",
                "25高",
                "25均",
                "25低",
                "24人",
                "24高",
                "24均",
                "24低",
                "23人",
                "23高",
                "23均",
                "23低",
            ]
        ),
        _tq_row(
            [
                "本科提前批A类",
                "军事类",
                "P002",
                "国防科技大学",
                "36",
                "软件工程（男，通用标准合格，特殊类型招生控制线，英语）",
                "物理和化学",
                None,
                None,
                None,
                500,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ]
        ),
    ]
    out = stage0_merge.build_history_early(rows)
    row = out[0]
    # gender token preserved inside brackets, ignore keywords stripped
    assert row["stripped"] == "软件工程(男)"
    assert row["core"] == "软件工程"
    assert row["school_cat"] == "军事类"  # category from col B (招生类别)


# --- Real-workbook smoke (NOT RED; Plan v2 separates smoke from RED) -------


class TestStage0Smoke:
    """Smoke层: real source row counts. Marked so pure-function failures
    aren't masked by these — they're here to lock the documented cardinalities
    (常规批一段线 28269, 大绿本常规批专业 23887) per spec §2."""

    def test_smoke_history_regular_row_count(self, repo_root: Path):
        from scripts import io_source

        wb = io_source.load_source(
            repo_root / "data" / "近三年学校批次专业线差统计.xlsx"
        )
        try:
            ws = wb["统计结果"]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        built = stage0_merge.build_history_regular(rows)
        assert len(built) == 29048  # 常规批一段 28269 + J3 提前批 779（已排除 45 条定向培养军士生专科行，Def-2）

    def test_smoke_dagluben_regular_major_row_count(self, repo_root: Path):
        from scripts import io_source

        wb = io_source.load_source(
            repo_root / "data" / "山东省2026年大绿本招生计划.xlsx"
        )
        try:
            ws = wb[wb.sheetnames[0]]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        built = stage0_merge.build_dagluben_regular(rows)
        assert len(built) == 23887

    def test_smoke_history_early_row_count(self, repo_root: Path):
        """补充表 本科A+B = 1707 (1161 + 546); 专科提前批 193 dropped."""
        from scripts import io_source

        wb = io_source.load_source(repo_root / "data" / "山东省高考提前批录取数据.xlsx")
        try:
            ws = wb[wb.sheetnames[0]]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()
        built = stage0_merge.build_history_early(rows)
        assert len(built) == 1707

    def test_smoke_unified_history_row_count(self, repo_root: Path):
        """统一历史表 = J3(常规批一段 28269 + 提前批 824 = 29093) + TQ 提前批 1707 = 30800."""
        from scripts import io_source

        wb_j3 = io_source.load_source(
            repo_root / "data" / "近三年学校批次专业线差统计.xlsx"
        )
        try:
            rows_j3 = list(wb_j3["统计结果"].iter_rows(values_only=True))
        finally:
            wb_j3.close()
        wb_tq = io_source.load_source(
            repo_root / "data" / "山东省高考提前批录取数据.xlsx"
        )
        try:
            rows_tq = list(wb_tq[wb_tq.sheetnames[0]].iter_rows(values_only=True))
        finally:
            wb_tq.close()
        unified = stage0_merge.build_unified_history(rows_j3, rows_tq)
        assert 30800 - 50 <= len(unified) <= 30800 + 50
