"""Tests for scripts.structured_log — split_log 5-column parser (iter3).

split_log takes the legacy single「匹配日志」string produced by iteration-2
and parses it into 5 structured columns (匹配阶段 / 单年数据 / 选科漂移 /
复核结果 / 原因备注) without losing information.

Real log-prefix universe (sampled from output/大绿本_附线差_扁平版.xlsx on
2026-06-24, see plan v2 修订 binding): 严格匹配 / 粗筛匹配 / 新增专业 /
特殊情况 / 语义匹配 (all with「：」); plus prefix-without-colon markers
新校/无历史 / 疑似改名校(见改名表). 专科（不在本次整理范围）appears only
in the hierarchical output; 复核存疑 appears only in edge tables — both must
still be parseable defensively.
"""

from __future__ import annotations

from scripts.constants import (
    LOG_COARSE_DISAMBIG_PREFIX,
    LOG_COARSE_UNIQUE,
    LOG_SEMANTIC_PREFIX,
    LOG_SPECIAL_UNMATCHED,
    LOG_STRICT,
    LOG_SUBJECT_DRIFT,
    LOG_ZHUANKE_OUT_OF_SCOPE,
)
from scripts.structured_log import split_log


# --- happy path: every log type --------------------------------------------


def test_strict_with_single_year_marker() -> None:
    out = split_log(
        f"{LOG_STRICT}；（单年数据，无标准差）"
    )
    assert out["匹配阶段"] == "严格匹配"
    assert out["单年数据"] == "是"
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""  # 严格 is构造确定 — not a judgmental verify
    assert out["原因备注"] == "归一化专业名+招生类别一致"


def test_strict_without_single_year() -> None:
    """Reverse sample: strict match WITHOUT the single-year marker leaves
    单年数据 empty."""
    out = split_log(LOG_STRICT)
    assert out["匹配阶段"] == "严格匹配"
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""
    assert out["原因备注"] == "归一化专业名+招生类别一致"


def test_coarse_unique_core_name() -> None:
    out = split_log(LOG_COARSE_UNIQUE)
    assert out["匹配阶段"] == "粗筛匹配"
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == "确定"  # judgmental — verified
    assert out["原因备注"] == "核心名唯一"


def test_coarse_disambig_with_drift() -> None:
    log = (
        f"{LOG_COARSE_DISAMBIG_PREFIX}（不限选考科目类专业）；"
        f"{LOG_SUBJECT_DRIFT}"
    )
    out = split_log(log)
    assert out["匹配阶段"] == "粗筛匹配"
    assert out["单年数据"] == ""
    assert out["选科漂移"] == "是"
    assert out["复核结果"] == "确定"
    assert out["原因备注"] == "括号子集消歧（不限选考科目类专业）"


def test_coarse_without_drift_leaves_drift_blank() -> None:
    """Reverse sample: coarse match WITHOUT drift marker leaves 选科漂移 empty."""
    out = split_log(f"{LOG_COARSE_DISAMBIG_PREFIX}（理工类）")
    assert out["匹配阶段"] == "粗筛匹配"
    assert out["选科漂移"] == ""
    assert out["复核结果"] == "确定"
    assert out["原因备注"] == "括号子集消歧（理工类）"


def test_semantic_match() -> None:
    out = split_log(f"{LOG_SEMANTIC_PREFIX}：核心名法学对齐")
    assert out["匹配阶段"] == "语义匹配"
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == "确定"
    assert out["原因备注"] == "核心名法学对齐"


def test_new_major_estimate() -> None:
    log = "新增专业：估算=同校同选科(19)均值=225.25"
    out = split_log(log)
    assert out["匹配阶段"] == "新增专业"
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""
    assert out["原因备注"] == "估算=同校同选科(19)均值=225.25"


def test_special_case_unmatched() -> None:
    out = split_log(LOG_SPECIAL_UNMATCHED)
    assert out["匹配阶段"] == "特殊情况"
    assert out["复核结果"] == ""
    assert out["原因备注"] == "未匹配，见特殊情况表"


def test_zhuanke_out_of_scope_hierarchical() -> None:
    """Hierarchical-only row: 专科 marker. 阶段=专科（超范围）, 备注 empty."""
    out = split_log(LOG_ZHUANKE_OUT_OF_SCOPE)
    assert out["匹配阶段"] == "专科（超范围）"
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""
    assert out["原因备注"] == ""


def test_new_school_no_history() -> None:
    """No「：」prefix — keyword-driven match (新校/无历史)."""
    out = split_log("新校/无历史，无法估算")
    assert out["匹配阶段"] == "新校无历史"
    assert out["复核结果"] == ""
    assert out["原因备注"] == "无法估算"


def test_rename_pending_school() -> None:
    """No「：」prefix — keyword-driven match (疑似改名校)."""
    out = split_log("疑似改名校(见改名表)，待人工核验")
    assert out["匹配阶段"] == "疑似改名校"
    assert out["复核结果"] == ""
    assert out["原因备注"] == "见改名表，待人工核验"


def test_review_doubt_demoted_row() -> None:
    """复核存疑 only lives in edge tables (not main), but split_log must
    still handle it defensively: 阶段=复核存疑, 备注=the reason."""
    out = split_log("复核存疑：方向不同:化学英才≠化学与生命资源")
    assert out["匹配阶段"] == "复核存疑"
    assert out["复核结果"] == ""
    assert out["原因备注"] == "方向不同:化学英才≠化学与生命资源"


# --- edge cases (plan v2 修订 binding) -------------------------------------


def test_empty_string_returns_empty_stage_original_note() -> None:
    """Empty input: 阶段="", 备注="" (no original text to preserve)."""
    out = split_log("")
    assert out["匹配阶段"] == ""
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""
    assert out["原因备注"] == ""


def test_unknown_prefix_keeps_original_in_note() -> None:
    """Unknown prefix: 阶段="", 备注=原文 (no information loss, no exception)."""
    log = "未来阶段：尚无规则"
    out = split_log(log)
    assert out["匹配阶段"] == ""
    assert out["单年数据"] == ""
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""
    assert out["原因备注"] == "未来阶段：尚无规则"


def test_keys_are_exactly_five_in_fixed_order() -> None:
    """Interface lock: 5 keys, exact names, fixed order."""
    out = split_log(LOG_STRICT)
    assert list(out.keys()) == [
        "匹配阶段", "单年数据", "选科漂移", "复核结果", "原因备注",
    ]


def test_values_helper_returns_5_strings_in_order() -> None:
    """``values()`` returns exactly 5 strings in the column order used by
    write_outputs (J/T + 5 structured)."""
    out = split_log(f"{LOG_STRICT}；（单年数据，无标准差）")
    vals = list(out.values())
    assert vals == ["严格匹配", "是", "", "", "归一化专业名+招生类别一致"]


def test_real_sample_strict_with_single_year_from_output() -> None:
    """Real row pulled from output/大绿本_附线差_扁平版.xlsx — guards against
    prefix-string drift in constants.py (the actual LOG_STRICT text)."""
    log = "严格匹配：归一化专业名+招生类别一致；（单年数据，无标准差）"
    out = split_log(log)
    assert out["匹配阶段"] == "严格匹配"
    assert out["单年数据"] == "是"
    assert out["选科漂移"] == ""
    assert out["复核结果"] == ""
    assert out["原因备注"] == "归一化专业名+招生类别一致"


def test_real_sample_new_major_estimate_from_output() -> None:
    log = "新增专业：估算=同校同选科(2)均值=171.92"
    out = split_log(log)
    assert out["匹配阶段"] == "新增专业"
    assert out["原因备注"] == "估算=同校同选科(2)均值=171.92"
