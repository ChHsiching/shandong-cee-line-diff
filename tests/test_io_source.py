"""Tests for scripts.io_source — read-only source loader + sha256 guard."""

from __future__ import annotations


import pytest

from scripts import io_source


# --- sha256 ---------------------------------------------------------------

def test_sha256_is_stable(tmp_xlsx):
    path = tmp_xlsx([["a", "b"], [1, 2]])
    h1 = io_source.sha256(path)
    h2 = io_source.sha256(path)
    assert h1 == h2
    # 64-char hex digest
    assert len(h1) == 64
    int(h1, 16)  # parses as hex


def test_sha256_changes_when_bytes_change(tmp_xlsx):
    path = tmp_xlsx([["a"], [1]])
    before = io_source.sha256(path)
    path2 = tmp_xlsx([["a"], [2]])
    after = io_source.sha256(path2)
    assert before != after


# --- assert_unchanged -----------------------------------------------------

def test_assert_unchanged_silent_when_match(tmp_xlsx):
    path = tmp_xlsx([["x"], [1]])
    h = io_source.sha256(path)
    # returns None / does not raise
    assert io_source.assert_unchanged(path, h) is None


def test_assert_unchanged_raises_on_drift(tmp_xlsx):
    path1 = tmp_xlsx([["x"], [1]])
    path2 = tmp_xlsx([["x"], [2]])  # different bytes -> different hash
    baseline = io_source.sha256(path1)
    with pytest.raises(RuntimeError):
        io_source.assert_unchanged(path2, baseline)


# --- load_source ----------------------------------------------------------

def test_load_source_returns_read_only_workbook(tmp_xlsx):

    path = tmp_xlsx([["col1", "col2"], ["a", "b"], ["c", "d"]])
    wb = io_source.load_source(path)
    try:
        assert wb.read_only is True
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        assert rows[0] == ["col1", "col2"]
        assert rows[1] == ["a", "b"]
    finally:
        wb.close()


def test_load_source_accepts_explicit_read_only(tmp_xlsx):
    path = tmp_xlsx([["h"], [1]])
    wb = io_source.load_source(path, read_only=True)
    try:
        assert wb.read_only is True
    finally:
        wb.close()


# --- Python 3.14 smoke: real source via read_only, no DeprecationWarning ----

def test_real_source_loads_without_deprecation_warning(repo_root):
    """Plan v2 binding: openpyxl read_only on the largest source under
    Python 3.14 must not emit DeprecationWarning (the smoke gate for
    Task 1.2). Promoted to error so any regression fails the suite."""
    import warnings

    biggest = repo_root / "data" / "近三年学校批次专业线差统计.xlsx"
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        wb = io_source.load_source(biggest)
        try:
            assert wb.read_only is True
            assert "统计结果" in wb.sheetnames
        finally:
            wb.close()
