"""Structured 5-column log parser.

Splits a single log string into 5 columns so users can filter the output
table by how each major was matched, whether only one year of data was
available, whether subject requirements changed across years, whether the
match passed second-pass verification, and a free-text reason.

Public API: :func:`split_log` (returns :class:`scripts.models.StructuredLog`).
"""

from __future__ import annotations

from scripts.constants import LOG_VERIFY_DEMOTE_PREFIX
from scripts.models import StructuredLog

__all__ = ["split_log", "JUDGMENTAL_STAGES"]

# Marker tokens embedded inside the log body.
_SINGLE_YEAR_MARKER = "（仅一年数据"
_DRIFT_MARKER = "选科要求跨年不同"
_FLAG_YES = "是"
_VERIFY_OK = "确定"
_COLON = "："

# Stages whose matches are judgment-type (need second-pass verify).
# 只有「agent 语义匹配」需要二次复核——「核心名匹配」是 Stage 1.5 past=1 程序
# 直接配（构造确定，像严格匹配一样不靠 agent 判断），豁免复核（fresh-test
# 2026-07-09 §8：保留它会让 audit judgmental_coverage 误判为缺复核而 FAIL）。
# 公开（audit_output 复用——#18d 单点化 stage 名，避免两处定义漂移）.
JUDGMENTAL_STAGES: frozenset[str] = frozenset({"agent 语义匹配"})

# Prefixed stages: log text before the first「：」 → stage label.
_PREFIXED_STAGES: tuple[tuple[str, str], ...] = (
    ("严格匹配", "严格匹配"),
    ("核心名匹配", "核心名匹配"),
    ("agent 语义匹配", "agent 语义匹配"),
    ("新增专业", "新增专业"),
    ("未能匹配", "未能匹配"),
    (LOG_VERIFY_DEMOTE_PREFIX, LOG_VERIFY_DEMOTE_PREFIX),  # 二次复核认为可能有误
    ("专科", "专科"),
)

# Stage names exposed to users. ``专科`` becomes ``专科（超范围）``.
_STAGE_DISPLAY = {
    "专科": "专科（超范围）",
}


def split_log(log: str) -> StructuredLog:
    """Parse a single-cell match log into 5 structured columns.

    Conservative: unrecognised input leaves 匹配方式 empty and preserves
    the original text in 原因说明. Empty input yields five empty strings.
    """
    text = (log or "").strip()

    single_year = _FLAG_YES if _SINGLE_YEAR_MARKER in text else ""
    drift = _FLAG_YES if _DRIFT_MARKER in text else ""

    stage, note = _stage_and_note(text)
    verify = _VERIFY_OK if stage in JUDGMENTAL_STAGES else ""
    return StructuredLog(
        匹配方式=stage,
        仅一年数据=single_year,
        选科要求跨年变化=drift,
        二次复核=verify,
        原因说明=note,
    )


def _stage_and_note(text: str) -> tuple[str, str]:
    """Return (stage, note) for a stripped log body."""
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

    # 3. Unknown — preserve verbatim.
    return "", text


def _match_prefixed(text: str) -> tuple[str, str]:
    """Return (stage, note) for a colon-prefixed log, else ("", "")."""
    for raw_label, stage in _PREFIXED_STAGES:
        prefix = raw_label + _COLON
        if text.startswith(prefix):
            note = _strip_markers(text[len(prefix) :])
            display = _STAGE_DISPLAY.get(stage, stage)
            if stage == "专科":
                note = ""
            return display, note
    return "", ""


def _match_keyword(text: str) -> tuple[str, str]:
    """Return (stage, note) for a colon-less keyword log, else ("", "")."""
    if text.startswith("这所学校可能改了名字"):
        return "可能改名的学校", text
    if text.startswith("这所学校今年没有在山东招生"):
        return "停招消失", text
    if text.startswith("往年有这个专业"):
        return "往年今年停招", text
    if text.startswith("新校") or text.startswith("整校近三年无数据"):
        return "新校无历史", text
    return "", ""


def _strip_markers(note: str) -> str:
    """Remove the single-year / drift flag markers + surrounding separators."""
    out = note
    # Drop the single-year parenthetical.
    sy_idx = out.find(_SINGLE_YEAR_MARKER)
    if sy_idx != -1:
        close = out.find("）", sy_idx)
        if close != -1:
            out = out[:sy_idx] + out[close + 1 :]
        else:
            out = out[:sy_idx]
    # Drop the drift marker and its trailing tail.
    dr_idx = out.find(_DRIFT_MARKER)
    if dr_idx != -1:
        tail_idx = out.find("不影响匹配", dr_idx)
        end = tail_idx + len("不影响匹配") if tail_idx != -1 else dr_idx
        out = out[:dr_idx] + out[end:]
    return out.strip("；，、 ").rstrip("；，").lstrip("；，")
