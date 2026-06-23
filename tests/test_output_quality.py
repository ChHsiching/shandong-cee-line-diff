"""Regression: output data-quality gaps (Phase 2 acceptance feedback).

Two bugs surfaced when the user reviewed the actual output:
- 本科 majors matched by none of strict/coarse/semantic/new/rename (特殊) got
  NO MatchResult → blank 匹配日志 in the output (spec requires a log on every row).
- 扁平版 included 专科 专业行 (scope is 仅本科)."""
from __future__ import annotations

from pathlib import Path

import openpyxl

from scripts.constants import LOG_SPECIAL_UNMATCHED, LOG_ZHUANKE_OUT_OF_SCOPE
from scripts.models import DaglubenRow
from scripts.run_pipeline import _build_main_results
from scripts.write_outputs import write_flat


def test_build_main_results_emits_log_for_unmatched_special() -> None:
    """A 本科 row matched by none of strict/coarse/semantic/new/rename must still
    receive a MatchResult with a special-case log (was: dropped → blank 日志)."""
    dagluben = [
        DaglubenRow(src_row_idx=5, school="X大学", school_cat="普通计划",
                    major="未知专业", batch="4.常规批"),
    ]
    out = _build_main_results(dagluben, [], [], [], {}, set())
    assert len(out) == 1
    assert out[0]["src_row_idx"] == 5
    assert out[0]["matched"] is False
    assert out[0]["J"] is None and out[0]["T"] is None
    assert out[0]["log"]
    assert LOG_SPECIAL_UNMATCHED in out[0]["log"]


def test_build_main_results_new_major_carries_estimate_T() -> None:
    """V5-1 / Plan v2 阻断1: a 新增专业 row's T must come from the estimate,
    not a hardcoded None. The estimate's value (J) and T are both surfaced."""
    from scripts.models import EstimateResult

    dagluben = [
        DaglubenRow(src_row_idx=7, school="Y大学", school_cat="普通计划",
                    major="新专业Z", batch="4.常规批"),
    ]
    estimates = {
        7: EstimateResult(value=88.0, T=13.5, level=0, n=2, log="估算log"),
    }
    out = _build_main_results(dagluben, [], [], [], estimates, set())
    assert len(out) == 1
    assert out[0]["src_row_idx"] == 7
    assert out[0]["J"] == 88.0
    assert out[0]["T"] == 13.5  # from estimate, NOT hardcoded None
    assert out[0]["log"] == "估算log"


def test_write_flat_excludes_zhuanke_major_rows(tmp_path: Path) -> None:
    """扁平版 must omit 专科 专业行 (小标题含「专科」); scope is 仅本科."""
    src = tmp_path / "src.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["批次", "小标题", "学校代码", "学校名", "代号", "名称",
               "选科", "学制", "计划", "备注", "收费", "校准"])
    ws.append(["4.常规批", "普通计划", "D001", "本大学", "01", "计算机",
               "物理和化学", "4", "10", "", "", ""])
    ws.append(["2.提前批B类", "定向培养军士生(专科)", "D002", "专学院", "02",
               "电气技术", "物理", "3", "5", "", "", ""])
    wb.save(src)
    wb.close()

    out = tmp_path / "flat.xlsx"
    write_flat(src, [], out)

    ws2 = openpyxl.load_workbook(out, read_only=True).active
    rows = list(ws2.iter_rows(values_only=True))
    majors = [r for r in rows[1:] if r[4] not in (None, "")]
    assert len(majors) == 1, f"expected only the 本科 row, got {len(majors)}"
    assert majors[0][5] == "计算机"
    # 专科 row must not appear anywhere.
    assert all("专科" not in (r[1] or "") for r in rows)


def test_zhuanke_log_constants_exist() -> None:
    """Guard: the two new log constants are defined and non-empty."""
    assert LOG_SPECIAL_UNMATCHED
    assert LOG_ZHUANKE_OUT_OF_SCOPE


def test_build_dagluben_early_includes_flight_rows() -> None:
    """飞行技术(军队) 2 行 (batch 3) must enter the 提前批 pool (spec §6:
    归入提前批池匹配), not be excluded — otherwise they get no 匹配日志."""
    from scripts.constants import BATCH_EARLY_A, FLIGHT_BATCH
    from scripts.stage0_merge import build_dagluben_early

    rows = [
        ["批次", "小标题", "学校代码", "学校名", "代号", "名称",
         "选科", "学制", "计划", "备注", "收费", "校准"],
        [BATCH_EARLY_A, "军事类", "P001", "军大", "01", "指挥",
         "物理和化学", "4", "5", "", "", ""],
        [FLIGHT_BATCH, None, "P002", "飞大", "02", "飞行技术",
         "物理和化学", "4", "3", "", "", ""],
    ]
    out = build_dagluben_early(rows)
    majors = [r["major"] for r in out]
    assert "飞行技术" in majors, f"flight row must be in pool, got {majors}"


def _load_xlsx(path: Path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    return rows


def test_write_deleted_major_table_maps_fields_to_columns(tmp_path: Path) -> None:
    """Regression (same class as 改名表): DeletedMajor field names must map to
    被删旧专业 header columns — passing field-named rows directly left cells empty."""
    from scripts.write_edge_tables import write_deleted_major_table

    rows = [{"school": "X大学", "school_cat": "普通计划", "major": "旧专业",
             "J": 50.0, "T": 5.0, "log": "近三年有、2026 大绿本无"}]
    out = tmp_path / "被删.xlsx"
    write_deleted_major_table(rows, out)
    data = _load_xlsx(out)
    assert data[1][0] == "X大学"
    assert data[1][2] == "旧专业"
    assert data[1][3] == 50.0
    assert data[1][5] == "近三年有、2026 大绿本无"


def test_write_special_table_maps_fields_to_columns(tmp_path: Path) -> None:
    """Regression (same class): EdgeRow field names must map to 特殊情况 header."""
    from scripts.write_edge_tables import write_special_table

    rows = [{"src_row_idx": 7, "school": "飞大", "school_cat": "", "major": "飞行技术",
             "core": "飞行技术", "subject": "物理和化学", "batch": "提前批",
             "log": "飞行技术(军队)，提前批池匹配不成"}]
    out = tmp_path / "特.xlsx"
    write_special_table(rows, out)
    data = _load_xlsx(out)
    assert data[1][0] == 7
    assert data[1][1] == "飞大"
    assert data[1][3] == "飞行技术"
    assert data[1][7] == "飞行技术(军队)，提前批池匹配不成"
