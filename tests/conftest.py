"""Shared pytest fixtures and path configuration.

Conventions:
- All paths resolved from the repo root (this file lives in tests/).
- Source workbooks are opened read-only via openpyxl.
- Small synthetic xlsx fixtures are built in tmp_path to keep pure-function
  tests fast and independent of the real 12MB source files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Repo root = parent of this tests/ directory.
REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config: pytest.Config) -> None:
    """Ensure the repo root is importable so `import scripts.<mod>` works.

    pytest derives `rootdir` from the location of pytest.ini (the repo root),
    so we only need the sys.path anchor here.
    """
    import sys

    root_str = str(REPO_ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Absolute path to the repository root."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def data_dir(repo_root: Path) -> Path:
    """Absolute path to the read-only source data/ directory."""
    return repo_root / "data"


@pytest.fixture
def tmp_xlsx(tmp_path: Path):
    """Factory: write rows (list of list) to a fresh xlsx and return its path.

    Each call produces a uniquely-named file under tmp_path so multiple
    fixtures in one test never clobber each other.

    Usage:
        path = tmp_xlsx([["a", "b"], [1, 2]])
    """

    import openpyxl
    import itertools

    counter = itertools.count()

    def _build(rows: list[list], sheet_name: str = "Sheet1") -> Path:
        n = next(counter)
        path = tmp_path / f"fixture_{n}.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name
        for row in rows:
            ws.append(list(row))
        wb.save(path)
        wb.close()
        return path

    return _build


@pytest.fixture
def minimal_hierarchical_dagluben(tmp_path: Path):
    """A tiny dagluben-shaped workbook exercising every layered row type.

    Row taxonomy (mirrors the real 大绿本):
      1. header
      2. 批次头        (batch only)
      3. 小标题        (batch + subtitle/招生类别)
      4. 学校行        (batch + subtitle + schoolcode/schoolname, no 代号/名称)
      5..n 专业行      (代号 + 名称 both non-empty)

    Columns (0-based): 批次 小标题 学校代码 学校名 代号 名称 选科 学制 计划数
                       学校备注 年收费 整行校准
    Returns the saved path.
    """
    import openpyxl

    path = tmp_path / "mini_dagluben.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(
        [
            "批次", "小标题", "学校代码", "学校名", "代号", "名称",
            "选考科目要求", "学制", "计划数", "学校备注", "年收费", "整行校准",
        ]
    )
    # 批次头
    ws.append(["4.常规批", "", "", "", "", "", "", "", "", "", "", "4.常规批"])
    # 小标题（招生类别）
    ws.append(["4.常规批", "普通计划", "", "", "", "", "", "", "", "", "", "普通计划"])
    # 学校行
    ws.append(
        ["4.常规批", "普通计划", "A001", "示例大学", "", "", "", "", "100",
         "本地公办", "", "A001示例大学本地公办100"]
    )
    # 专业行 1
    ws.append(
        ["4.常规批", "普通计划", "A001", "示例大学", "01", "计算机科学与技术",
         "物理和化学", "4", "2", "", "", "01计算机科学与技术..."]
    )
    # 专业行 2
    ws.append(
        ["4.常规批", "普通计划", "A001", "示例大学", "02", "英语",
         "不限", "4", "1", "", "", "02英语..."]
    )
    wb.save(path)
    wb.close()
    return path


@pytest.fixture
def minimal_history_rows():
    """Parsed近三年-style rows as plain dicts (post-build_history_regular shape)."""
    return [
        {
            "school": "示例大学", "school_cat": "", "major": "计算机科学与技术",
            "stripped": "计算机科学与技术", "core": "计算机科学与技术",
            "subject": "物理和化学", "J": 60.0, "T": 5.0,
        },
        {
            "school": "示例大学", "school_cat": "", "major": "数学",
            "stripped": "数学", "core": "数学",
            "subject": "物理", "J": 70.0, "T": None,
        },
    ]
