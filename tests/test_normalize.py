"""Tests for scripts.normalize — pure-function normalisation utilities."""

from __future__ import annotations

from scripts import normalize


# --- nfk -------------------------------------------------------------------

def test_nfk_normalises_fullwidth_and_whitespace():
    # full-width comma -> half-width, full-width parens -> half-width,
    # all whitespace removed.
    assert normalize.nfk("英语（师范），　学前教育") == "英语(师范),学前教育"
    assert normalize.nfk("  a　b\r\n c") == "abc"


def test_nfk_idempotent():
    s = "数学与应用数学（男，通用标准合格）"
    once = normalize.nfk(s)
    twice = normalize.nfk(once)
    assert once == twice


# --- split_school ----------------------------------------------------------

def test_split_school_empirical_examples_from_spec():
    assert normalize.split_school("三亚学院(中外合作办学)") == (
        "三亚学院", "中外合作办学",
    )
    assert normalize.split_school("山东中医药大学(地方专项计划)") == (
        "山东中医药大学", "地方专项计划",
    )
    assert normalize.split_school("山东建筑大学(走读)") == (
        "山东建筑大学", "走读",
    )
    assert normalize.split_school("桂林电子科技大学(边防军人子女预科班)") == (
        "桂林电子科技大学", "边防军人子女预科班",
    )


def test_split_school_no_category_returns_school_and_empty():
    assert normalize.split_school("北京大学") == ("北京大学", "")
    assert normalize.split_school("北京大学()") == ("北京大学", "")


def test_split_school_handles_fullwidth_and_whitespace():
    assert normalize.split_school("三亚学院（中外合作办学）") == (
        "三亚学院", "中外合作办学",
    )


# --- strip_ignore_brackets ------------------------------------------------

def test_strip_ignore_brackets_removes_ignore_brackets():
    assert normalize.strip_ignore_brackets("临床医学(色盲考生不予录取)") == "临床医学"
    assert (
        normalize.strip_ignore_brackets("数学与应用数学(男,通用标准合格)")
        == "数学与应用数学(男)"
    )
    assert (
        normalize.strip_ignore_brackets("护理学(女生身高不低于160cm)")
        == "护理学"
    )


def test_strip_ignore_brackets_keeps_non_ignore_brackets():
    assert (
        normalize.strip_ignore_brackets("经济学类(经济学、国民经济管理)")
        == "经济学类(经济学、国民经济管理)"
    )


def test_strip_ignore_brackets_no_brackets_passthrough():
    assert normalize.strip_ignore_brackets("计算机科学与技术") == "计算机科学与技术"


# --- core_of ---------------------------------------------------------------

def test_core_of_strips_all_brackets():
    assert normalize.core_of("经济学类(经济学、国民经济管理)") == "经济学类"
    assert normalize.core_of("理科试验班类(严济慈物理学拔尖人才班)(含物理学)") == "理科试验班类"
    assert normalize.core_of("数学与应用数学(男,通用标准合格)") == "数学与应用数学"


def test_core_of_no_brackets_passthrough():
    assert normalize.core_of("英语") == "英语"


# --- diff_brackets ---------------------------------------------------------

def test_diff_brackets_classifies_each_bracket():
    result = normalize.diff_brackets(
        "理科试验班类(严济慈物理学拔尖人才班)(含物理学)"
    )
    # expected: gender="" , cooperation="" , other includes 严济慈…
    kinds = {kind for kind, _val in result}
    assert "其他" in kinds
    others = [val for kind, val in result if kind == "其他"]
    assert any("严济慈" in v for v in others)


def test_diff_brackets_tags_gender():
    result = normalize.diff_brackets("数学与应用数学(男,通用标准合格)")
    genders = [val for kind, val in result if kind == "性别"]
    assert genders == ["男"]


def test_diff_brackets_tags_cooperation():
    result = normalize.diff_brackets("计算机类(中外合作办学)")
    kinds = {kind for kind, _val in result}
    assert "合作" in kinds


def test_diff_brackets_no_brackets_returns_empty_list():
    assert normalize.diff_brackets("英语") == []
