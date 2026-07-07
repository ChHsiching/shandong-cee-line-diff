"""show_table CLI 基础契约测试（#18e）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import openpyxl

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_xlsx(path: Path, rows: list[list]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
    wb.close()


def test_show_table_prints_header_and_rows(tmp_path: Path) -> None:
    xlsx = tmp_path / "t.xlsx"
    _write_xlsx(
        xlsx,
        [["学校", "专业"], ["甲大学", "计算机科学与技术"], ["乙大学", "数学类"]],
    )
    result = subprocess.run(
        [sys.executable, "-m", "scripts.show_table", str(xlsx)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "学校" in result.stdout
    assert "甲大学" in result.stdout
    assert "计算机科学与技术" in result.stdout


def test_show_table_head_limits_row_count(tmp_path: Path) -> None:
    xlsx = tmp_path / "t.xlsx"
    rows = [["i", "v"], *[[str(i), f"val{i}"] for i in range(50)]]
    _write_xlsx(xlsx, rows)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.show_table", str(xlsx), "--head", "5"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = [ln for ln in result.stdout.splitlines() if ln]
    assert len(lines) == 5  # head=5


def test_show_table_grep_filters_rows(tmp_path: Path) -> None:
    xlsx = tmp_path / "t.xlsx"
    _write_xlsx(
        xlsx,
        [
            ["学校", "专业"],
            ["甲大学", "计算机"],
            ["乙大学", "数学"],
            ["丙大学", "计算机(人工智能)"],
        ],
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.show_table",
            str(xlsx),
            "--grep",
            "计算机",
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    lines = [ln for ln in result.stdout.splitlines() if ln]
    # 含「计算机」的行：表头 + 甲大学 + 丙大学（3 行）；乙大学不含。
    assert any("甲大学" in ln for ln in lines)
    assert any("丙大学" in ln for ln in lines)
    assert all("乙大学" not in ln for ln in lines)
