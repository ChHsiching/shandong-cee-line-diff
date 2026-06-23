"""Slice C — data-quality audit hard gate (spec V5-3, Plan v2 Slice C 修订).

The audit module (:mod:`scripts.audit_output`) reads the **real produced xlsx**
plus the verification jsonl and runs five checks; only ``ok=True`` exits 0.
These tests build tiny synthetic output fixtures (good + defective) and drive
each check RED→GREEN, plus the ``main()`` exit-code contract.

Check mapping (Plan v2 Slice C 修订):
  0  复核覆盖完备性 (judgmental coverage): every judgmental-match row in the
     hierarchical output (logs in JUDGMENT_LOG_PREFIXES — coarse / semantic)
     must appear in ``verify_*_result.jsonl`` with verdict=确定. Missing jsonl
     → fail with「复核未派发」.
  1  每本科专业行匹配日志非空 (0 缺失).
  2  每张产出表 0 个全空数据行.
  3  字段映射回归: each produced table non-empty (header assertion already locked
     in test_output_quality; audit re-asserts the produced tables are non-empty
     so a writer regression that blanks a table fails the gate).
  4  随机 ≥30 匹配行 J/T 与近三年原值逐行比对 (精度区分): matched rows compared
     to source history values; 新增估算 rows compared to round(估算, 2).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

from scripts.audit_output import AuditReport, audit, main

# --- fixtures ---------------------------------------------------------------

HEADER = [
    "批次", "小标题", "学校代码", "学校名", "代号", "名称",
    "选考科目要求", "学制", "计划数", "学校备注", "年收费", "整行校准",
    "近三年统计线差", "近三年线差标准差", "匹配日志",
]


def _write_hier(path: Path, rows: list[list]) -> None:
    """Write a hierarchical-style workbook (header + major rows)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(HEADER))
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    wb.close()


def _write_edge(path: Path, header: list[str], rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    wb.save(path)
    wb.close()


def _good_output_dir(tmp_path: Path) -> Path:
    """A clean output dir that passes every check.

    Layout:
      - hierarchical: 1 strict + 1 coarse(judgmental, confirmed) + 1 new-major
        estimate row. The coarse row's src_row_idx (3) appears in the verify
        jsonl with verdict=确定.
      - flat: same three rows.
      - new major table with the estimate row.
      - empty-ish but non-empty special/deleted tables.
    """
    out = tmp_path / "output"
    out.mkdir()
    hier_rows = [
        # strict matched (src_row_idx=2)
        ["4.常规批", "普通计划", "A01", "示例大学", "01", "计算机",
         "物理", "4", "2", "", "", "01计算机", 60.0, 5.0,
         "严格匹配：归一化专业名+招生类别一致"],
        # coarse judgmental matched (src_row_idx=3) — confirmed
        ["4.常规批", "普通计划", "A01", "示例大学", "02", "数学",
         "物理", "4", "1", "", "", "02数学", 70.0, None,
         "粗筛匹配：核心名唯一"],
        # new major estimate (src_row_idx=4) — J/T from estimate, rounded
        ["4.常规批", "普通计划", "A01", "示例大学", "03", "新专业",
         "物理", "4", "1", "", "", "03新专业", 80.0, 4.0,
         "新增专业：估算=同校同选科(2)均值=80.0"],
    ]
    _write_hier(out / "大绿本_附线差_分层版.xlsx", hier_rows)
    _write_hier(out / "大绿本_附线差_扁平版.xlsx", hier_rows)
    _write_edge(
        out / "新增专业.xlsx",
        ["学校", "专业", "选科", "统计线差估算", "线差标准差估算",
         "退化级别", "样本量", "日志"],
        [["示例大学", "新专业", "物理", 80.0, 4.0, 0, 2,
          "新增专业：估算=同校同选科(2)均值=80.0"]],
    )
    _write_edge(
        out / "特殊情况.xlsx",
        ["src_row_idx", "学校", "招生类别", "专业", "核心名", "选科", "批次", "日志"],
        [[5, "他大学", "", "其他", "其他", "物理", "4.常规批", "无法匹配：剩余未归类"]],
    )
    _write_edge(
        out / "被删旧专业.xlsx",
        ["学校", "招生类别", "专业", "近三年统计线差", "近三年线差标准差", "日志"],
        [["他大学", "", "旧专业", 40.0, 3.0, "近三年有、2026 大绿本无"]],
    )
    _write_edge(
        out / "学校改名表.xlsx",
        ["2026新校名", "候选旧校名", "置信度", "2026本科专业数", "备注", "人工已核验"],
        [["新校", "旧校", 0.9, 5, "前身旧校", False]],
    )
    _write_edge(
        out / "新增校表.xlsx",
        ["2026新校名", "2026本科专业数", "日志"],
        [["全新校", 3, "2026 新增校，近三年无招生"]],
    )
    _write_edge(
        out / "停招消失校表.xlsx",
        ["历史旧校名", "日志"],
        [["消失校", "学校未在 2026 招生"]],
    )
    return out


def _good_intermediate_dir(tmp_path: Path) -> Path:
    """Stage1 / stage1.5 / stage2 stage files carrying the single-year note +
    judgmental log anchors (not asserted by audit directly but passed through)."""
    inter = tmp_path / "intermediate"
    inter.mkdir()
    return inter


def _good_semantic_dir(tmp_path: Path, confirmed_idx: list[int]) -> Path:
    """A semantic-match dir with one verify_*_result.jsonl covering confirmed idx."""
    sem = tmp_path / "semantic-match"
    sem.mkdir()
    res = sem / "verify_batch_01_result.jsonl"
    lines = [
        json.dumps({"src_row_idx": i, "verdict": "确定", "reason": "核心名一致"})
        for i in confirmed_idx
    ]
    res.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sem


def _good_data_dir(tmp_path: Path) -> Path:
    """A data dir carrying a tiny 近三年 history used by check 4 (J/T compare).

    History row school=示例大学, core=计算机, J=60.0, T=5.0 matches the strict
    hierarchical row; core=数学, J=70.0, T=None matches the coarse row.
    """
    data = tmp_path / "data"
    data.mkdir()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "统计结果"
    # Minimal近三年-style header + 2 rows.
    ws.append(["批次", "校码", "校名", "专业名", "选科", "备注",
               "基础专业", "是否括号", "括号", "统计线差",
               "2023", "2024", "2025", "", "", "", "年数",
               "", "", "线差标准差"])
    ws.append(["常规批一段线", "A01", "示例大学", "计算机", "物理", "",
               "计算机", "否", "", 60.0, 60.0, 60.0, 60.0,
               "", "", "", 3, "", "", 5.0])
    ws.append(["常规批一段线", "A01", "示例大学", "数学", "物理", "",
               "数学", "否", "", 70.0, 70.0, 70.0, 70.0,
               "", "", "", 3, "", "", None])
    wb.save(data / "近三年学校批次专业线差统计.xlsx")
    wb.close()
    # placeholder sources so history rebuild won't crash if invoked; the audit
    # reads history via the provided path but only J/T compare uses it.
    return data


# --- check 0: judgmental coverage ------------------------------------------


def test_audit_passes_on_good_output(tmp_path: Path) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert isinstance(report, AuditReport)
    assert report.ok is True, report.checks


def test_check0_fails_when_judgmental_row_not_in_verify(tmp_path: Path) -> None:
    """A judgmental-match row (粗筛/语义 log) whose src_row_idx is absent from
    verify_*_result.jsonl → check 0 fails → ok=False."""
    out = _good_output_dir(tmp_path)
    # verify jsonl confirms only idx=99 (NOT the coarse row idx=3).
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[99])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert report.ok is False
    c0 = next(c for c in report.checks if c["name"].startswith("judgmental_coverage"))
    assert c0["passed"] is False
    assert "3" in c0["detail"]


def test_check0_fails_when_verify_jsonl_missing(tmp_path: Path) -> None:
    """No verify_*_result.jsonl present at all → fail with「复核未派发」."""
    out = _good_output_dir(tmp_path)
    sem = tmp_path / "semantic-match"
    sem.mkdir()  # exists but no verify results
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert report.ok is False
    c0 = next(c for c in report.checks if c["name"].startswith("judgmental_coverage"))
    assert c0["passed"] is False
    assert "复核未派发" in c0["detail"]


# --- check 1: every 本科 major row has non-empty 匹配日志 ------------------


def test_check1_fails_on_blank_log(tmp_path: Path) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    # Corrupt the flat output: blank the log on one major row.
    wb = openpyxl.load_workbook(out / "大绿本_附线差_扁平版.xlsx")
    ws = wb.active
    ws.cell(row=2, column=15).value = None
    wb.save(out / "大绿本_附线差_扁平版.xlsx")
    wb.close()

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert report.ok is False
    c1 = next(c for c in report.checks if c["name"].startswith("nonempty_log"))
    assert c1["passed"] is False


# --- check 2: no fully-empty data rows in any produced table ---------------


def test_check2_fails_on_empty_row(tmp_path: Path) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    # Append a fully-blank data row to 特殊情况.xlsx.
    wb = openpyxl.load_workbook(out / "特殊情况.xlsx")
    ws = wb.active
    ws.append([None, None, None, None, None, None, None, None])
    wb.save(out / "特殊情况.xlsx")
    wb.close()

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert report.ok is False
    c2 = next(c for c in report.checks if c["name"].startswith("no_empty_rows"))
    assert c2["passed"] is False


# --- check 3: produced tables non-empty (field-mapping regression guard) ---


def test_check3_fails_when_table_has_no_data_rows(tmp_path: Path) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    # Overwrite 新增专业.xlsx with header only (no data rows).
    _write_edge(
        out / "新增专业.xlsx",
        ["学校", "专业", "选科", "统计线差估算", "线差标准差估算",
         "退化级别", "样本量", "日志"],
        [],
    )

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert report.ok is False
    c3 = next(c for c in report.checks if c["name"].startswith("tables_nonempty"))
    assert c3["passed"] is False


# --- check 4: J/T consistency with source history (precision-aware) --------


def test_check4_fails_on_jt_mismatch(tmp_path: Path) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    # Supply history directly (avoids rebuilding from a fixture data dir); the
    # strict row is school=示例大学, major=计算机, J=60.0 in history.
    history = [
        {"school": "示例大学", "major": "计算机", "J": 60.0, "T": 5.0},
        {"school": "示例大学", "major": "数学", "J": 70.0, "T": None},
    ]
    # Corrupt the strict row's J to a value that disagrees with history (60.0).
    wb = openpyxl.load_workbook(out / "大绿本_附线差_分层版.xlsx")
    ws = wb.active
    ws.cell(row=2, column=13).value = 999.0
    wb.save(out / "大绿本_附线差_分层版.xlsx")
    wb.close()

    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=history, semantic_dir=sem,
    )
    assert report.ok is False
    c4 = next(c for c in report.checks if c["name"].startswith("jt_consistency"))
    assert c4["passed"] is False


def test_check4_estimate_row_uses_round_tolerance(tmp_path: Path) -> None:
    """V5-6 precision split: 新增估算 rows are compared against the value in
    新增专业.xlsx (the estimate table is ground truth), not source history.
    The good fixture's estimate row (J=80.0) matches the estimate table → pass."""
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    history = [
        {"school": "示例大学", "major": "计算机", "J": 60.0, "T": 5.0},
        {"school": "示例大学", "major": "数学", "J": 70.0, "T": None},
    ]
    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=history, semantic_dir=sem,
    )
    c4 = next(c for c in report.checks if c["name"].startswith("jt_consistency"))
    assert c4["passed"] is True, c4


# --- AuditReport structure + sample artefact -------------------------------


def test_audit_report_structure(tmp_path: Path) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    report = audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    assert hasattr(report, "ok")
    assert hasattr(report, "checks")
    assert isinstance(report.checks, list)
    assert len(report.checks) >= 5
    for c in report.checks:
        assert {"name", "passed", "detail"} <= set(c.keys())


def test_audit_writes_sample_xlsx(tmp_path: Path) -> None:
    """A manual-sample xlsx (audit_sample.xlsx) is produced for human review —
    it does NOT influence ok/exit code."""
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    audit(
        out, data_dir=data, intermediate_dir=inter,
        history=None, semantic_dir=sem,
    )
    sample = out / "audit_sample.xlsx"
    assert sample.exists()
    wb = openpyxl.load_workbook(sample, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    # header + at least one sampled row
    assert len(rows) >= 2


# --- main() exit code contract ---------------------------------------------


def test_main_exits_zero_on_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["audit_output",
         "--output-dir", str(out),
         "--data-dir", str(data),
         "--intermediate-dir", str(inter),
         "--semantic-dir", str(sem)],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_main_exits_nonzero_on_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = _good_output_dir(tmp_path)
    # No verify jsonl → check 0 fails.
    sem = tmp_path / "semantic-match"
    sem.mkdir()
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["audit_output",
         "--output-dir", str(out),
         "--data-dir", str(data),
         "--intermediate-dir", str(inter),
         "--semantic-dir", str(sem)],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code != 0


def test_main_cli_subprocess_zero(tmp_path: Path) -> None:
    """End-to-end CLI: `python -m scripts.audit_output` exits 0 on good output."""
    out = _good_output_dir(tmp_path)
    sem = _good_semantic_dir(tmp_path, confirmed_idx=[3])
    data = _good_data_dir(tmp_path)
    inter = _good_intermediate_dir(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.audit_output",
         "--output-dir", str(out),
         "--data-dir", str(data),
         "--intermediate-dir", str(inter),
         "--semantic-dir", str(sem)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
