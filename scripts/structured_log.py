"""Structured 5-column log parser (iteration-3, spec §2.1).

The legacy pipeline (iteration-2) produced a single「匹配日志」string per
main-table row packing multiple kinds of information (match stage, single-year
note, subject-policy drift, verify outcome, free-text reason). iteration-3
splits that string into 5 structured columns so users can filter directly by
stage / single-year / drift / verify.

This module is a **pure** parser — it does not alter matching logic, does not
touch the source strings, and loses no information: every byte of the original
log is recoverable from the 5 columns (prefix → 匹配阶段; flag markers → 单年
数据 / 选科漂移; remaining text → 原因备注; verify outcome derived from stage).

Real log-prefix universe (sampled 2026-06-24 from
``output/大绿本_附线差_扁平版.xlsx`` + the hierarchical variant):

    带前缀（含「：」）   严格匹配 / 粗筛匹配 / 新增专业 / 特殊情况 / 语义匹配
                       （分层版另含「专科」；边界表另含「复核存疑」）
    无「：」关键字      新校/无历史…  /  疑似改名校(见改名表)…

Public API: :func:`split_log` (returns :class:`scripts.models.StructuredLog`).
"""

from __future__ import annotations

from scripts.constants import LOG_VERIFY_DEMOTE_PREFIX
from scripts.models import StructuredLog

__all__ = ["split_log"]

# Marker tokens embedded inside the log body (kept short so a future wording
# tweak does not silently drop the flag).
_SINGLE_YEAR_MARKER = "（单年数据"   # spec log: （单年数据，无标准差）
_DRIFT_MARKER = "选科政策漂移"       # spec log: 选科政策漂移，已忽略
_FLAG_YES = "是"
_VERIFY_OK = "确定"
_COLON = "："

# Stages whose matches are 判断型 (need second-pass verify); per spec §2.1 the
# 复核结果 column is「确定」only for these two after a confirmed verdict.
_JUDGMENTAL_STAGES: tuple[str, ...] = ("粗筛匹配", "语义匹配")

# Prefixed stages: log text before the first「：」 → stage label. Order matters
# only for documentation; the colon split is unambiguous in practice.
_PREFIXED_STAGES: tuple[tuple[str, str], ...] = (
    ("严格匹配", "严格匹配"),
    ("粗筛匹配", "粗筛匹配"),
    ("语义匹配", "语义匹配"),
    ("新增专业", "新增专业"),
    ("特殊情况", "特殊情况"),
    ("复核存疑", LOG_VERIFY_DEMOTE_PREFIX),   # 复核存疑 (edge tables)
    ("专科", "专科"),                          # 专科 (hierarchical only)
)

# Stage names exposed to users. ``专科`` becomes ``专科（超范围）`` per spec §3
# (the only re-named stage); all others pass through unchanged.
_STAGE_DISPLAY = {
    "专科": "专科（超范围）",
}


def split_log(log: str) -> StructuredLog:
    """Parse a legacy single-cell match log into 5 structured columns.

    The parser is conservative: any input it cannot recognise leaves
    ``匹配阶段`` empty and the original text in ``原因备注`` (no information
    loss, no exception). Empty input yields five empty strings.

    Examples
    --------
    >>> split_log("严格匹配：归一化专业名+招生类别一致；（单年数据，无标准差）")
    {'匹配阶段': '严格匹配', '单年数据': '是', '选科漂移': '',
     '复核结果': '', '原因备注': '归一化专业名+招生类别一致'}
    >>> split_log("粗筛匹配：核心名唯一")["复核结果"]
    '确定'
    """
    text = (log or "").strip()

    single_year = _FLAG_YES if _SINGLE_YEAR_MARKER in text else ""
    drift = _FLAG_YES if _DRIFT_MARKER in text else ""

    stage, note = _stage_and_note(text)
    verify = _VERIFY_OK if stage in _JUDGMENTAL_STAGES else ""
    return StructuredLog(
        匹配阶段=stage,
        单年数据=single_year,
        选科漂移=drift,
        复核结果=verify,
        原因备注=note,
    )


def _stage_and_note(text: str) -> tuple[str, str]:
    """Return (stage, note) for a stripped log body.

    ``note`` is the original text with the stage prefix and flag markers
    removed (separators around markers are trimmed). Unknown prefixes
    leave ``stage=""`` and preserve the full original text in ``note``.
    """
    if text == "":
        return "", ""

    # 1. Prefixed stages — log starts with「<label>：<reason>」.
    stage, note = _match_prefixed(text)
    if stage:
        return stage, note

    # 2. Colon-less keyword stages (whole-log keyword match).
    stage, note = _match_keyword(text)
    if stage:
        return stage, note

    # 3. Unknown — preserve the original verbatim (no information loss).
    return "", text


def _match_prefixed(text: str) -> tuple[str, str]:
    """Return (stage, note) for a colon-prefixed log, else ("", "").

    The note is the text after the first「：」with the flag markers and
    surrounding separators stripped. ``专科（超范围）`` rows carry no
    free-text reason → note="".
    """
    for raw_label, stage in _PREFIXED_STAGES:
        prefix = raw_label + _COLON
        if text.startswith(prefix):
            note = _strip_markers(text[len(prefix):])
            display = _STAGE_DISPLAY.get(stage, stage)
            # 专科 row: the trailing text is the fixed 超范围 label, not a
            # free-text reason — drop it.
            if stage == "专科":
                note = ""
            return display, note
    return "", ""


def _match_keyword(text: str) -> tuple[str, str]:
    """Return (stage, note) for a colon-less keyword log, else ("", "").

    These log forms have no「：」separator — the keyword sits at the head and
    the free-text reason trails after a punctuation mark (comma / bracket).

    Per Task-1 RED样例:
      疑似改名校(见改名表)，待人工核验  → 阶段=疑似改名校，备注=见改名表，待人工核验
      新校/无历史，无法估算            → 阶段=新校无历史，备注=无法估算
    """
    # 疑似改名校(见改名表)，待人工核验  — strip only the leading「疑似改名校」.
    if text.startswith("疑似改名校"):
        note = text[len("疑似改名校"):]
        return "疑似改名校", _strip_keyword_head(note)
    # 新校/无历史，无法估算  — strip only the leading「新校/无历史」.
    if text.startswith("新校/无历史"):
        note = text[len("新校/无历史"):]
        return "新校无历史", _strip_keyword_head(note)
    return "", ""


def _strip_keyword_head(note: str) -> str:
    """For colon-less logs: drop a single leading「(…)，」/「，」head, leaving
    the free-text reason. e.g. ``(见改名表)，待人工核验`` → ``见改名表，待人工核验``;
    ``，无法估算`` → ``无法估算``.
    """
    out = note
    # Leading parenthetical: (见改名表) → 见改名表 (drop the parens, keep text).
    if out.startswith("（"):
        close = out.find("）")
        if close != -1:
            inner = out[1:close]
            rest = out[close + 1:]
            out = inner + rest
    elif out.startswith("("):
        close = out.find(")")
        if close != -1:
            inner = out[1:close]
            rest = out[close + 1:]
            out = inner + rest
    # Strip exactly one leading separator (，/、).
    return out.lstrip("，、").strip()


def _strip_markers(note: str) -> str:
    """Remove the single-year / drift flag markers + surrounding separators
    from a free-text note.

    e.g. ``归一化专业名+招生类别一致；（单年数据，无标准差）`` →
         ``归一化专业名+招生类别一致``
    e.g. ``括号子集消歧（不限选考科目类专业）；选科政策漂移，已忽略`` →
         ``括号子集消歧（不限选考科目类专业）``
    """
    out = note
    # Drop the single-year parenthetical (greedy on this single marker).
    sy_idx = out.find(_SINGLE_YEAR_MARKER)
    if sy_idx != -1:
        close = out.find("）", sy_idx)
        if close != -1:
            out = out[:sy_idx] + out[close + 1:]
        else:
            out = out[:sy_idx]
    # Drop the drift marker and its trailing「，已忽略」tail.
    dr_idx = out.find(_DRIFT_MARKER)
    if dr_idx != -1:
        # Remove from the marker through「已忽略」(or end of string).
        tail_idx = out.find("已忽略", dr_idx)
        end = tail_idx + len("已忽略") if tail_idx != -1 else dr_idx
        out = out[:dr_idx] + out[end:]
    # Trim separators left behind at either end / in the middle.
    return out.strip("；，、 ").rstrip("；，").lstrip("；，")
