"""Pure-function normalisation utilities (spec §5.1, §5.2, §5.3).

Functions:
    nfk(s)                       -> str                   # NFKC + strip whitespace
    split_school(s)              -> (base, category)      # split 招生类别 off校名
    strip_ignore_brackets(name)  -> str                   # drop 忽略类 brackets, keep gender
    core_of(name)                -> str                   # all brackets removed
    diff_brackets(name)          -> [(kind, value), ...]  # classify each bracket

Conventions:
    - All functions are idempotent and side-effect free.
    - Bracket extraction treats ``(...)`` and full-width ``（...）`` uniformly
      because :func:`nfk` is applied first.
    - Gender (男/女) is the explicit exception to the ignore rule (spec §5.3).
"""

from __future__ import annotations

import re
import unicodedata

from scripts.constants import (
    IGNORE_BRACKET_KEYWORDS,
    SCHOOL_CATEGORY_KEYWORDS,
)

__all__ = [
    "nfk",
    "split_school",
    "strip_ignore_brackets",
    "core_of",
    "diff_brackets",
]

# A bracket group is (...) — after nfk, full-width parens are already half-width.
_BRACKET_RE = re.compile(r"\(([^()]*)\)")
# Gender marker is recognised as a standalone 男 or 女 token inside a bracket.
_GENDER_RE = re.compile(
    r"^[男女]$|^[男女][,，、]|[,，、][男女]$|[,，、][男女][,，、]|招[男女]生"
)


def nfk(s: str) -> str:
    """NFKC-normalise and strip all whitespace."""
    if s is None:
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s)))


def _is_category_bracket(content: str) -> bool:
    """True if the bracket content encodes a招生类别 (cooperation/special-track)."""
    return any(kw in content for kw in SCHOOL_CATEGORY_KEYWORDS)


def _is_gender_bracket(content: str) -> bool:
    """True if the bracket's defining content is a gender marker (男/女).

    Gender is recognised even when the bracket also lists 忽略类 requirements
    (spec §5.3: gender is the explicit exception to the ignore rule).
    """
    return bool(_GENDER_RE.search(content)) and ("男" in content or "女" in content)


def _is_ignore_bracket(content: str) -> bool:
    """True if the bracket content is a 忽略类 objective requirement.

    A pure-gender bracket is NOT ignored. A bracket that mixes gender with
    ignore keywords is still an ignore-bracket for the purpose of stripping,
    but :func:`strip_ignore_brackets` preserves the gender token.
    """
    if _is_gender_bracket(content) and not any(
        kw in content for kw in IGNORE_BRACKET_KEYWORDS
    ):
        return False
    return any(kw in content for kw in IGNORE_BRACKET_KEYWORDS)


def split_school(s: str) -> tuple[str, str]:
    """Split a校名 into ``(base, category)``.

    If a trailing bracket encodes a招生类别 (中外合作/专项/走读/边防/预科/…),
    that bracket's content becomes ``category`` and is removed from the base
    name. A校名 with no such bracket returns ``(name, "")``. An empty trailing
    bracket ``()`` is treated as no category and stripped.

    >>> split_school("三亚学院(中外合作办学)")
    ('三亚学院', '中外合作办学')
    >>> split_school("北京大学")
    ('北京大学', '')
    """
    name = nfk(s)
    # Only the *trailing* category bracket is split off — some校名 legitimately
    # contain other括号 (e.g. direction) that belong to the school name.
    m = re.search(r"\(([^()]*?)\)$", name)
    if not m:
        return name, ""
    content = m.group(1)
    if content == "":
        # An empty trailing bracket carries no category; drop it from the base.
        return name[: m.start()], ""
    if _is_category_bracket(content):
        return name[: m.start()], content
    return name, ""


def strip_ignore_brackets(name: str) -> str:
    """Remove 忽略类 brackets, but preserve gender content within them.

    A bracket that is purely a gender marker survives unchanged. A bracket
    mixing gender with ignore keywords is reduced to just its gender token
    (e.g. ``(男,通用标准合格)`` -> ``(男)``). All other brackets pass through.
    """
    cleaned = nfk(name)

    def _reduce(match: re.Match[str]) -> str:
        content = match.group(1)
        if not _is_ignore_bracket(content):
            return match.group(0)
        # Bracket has ignore content. Preserve gender + 「面向…就业」方向
        # （公安/师范类同性别下分就业方向，不能一起剥掉塌缩 — Bug #4 残留）。
        if _GENDER_RE.search(content):
            gender = "男" if "男" in content else "女"
            m_face = re.search(r"面向[^,，;；()]+就业", content)
            if m_face:
                return f"({gender},{m_face.group(0)})"
            return f"({gender})"
        return ""

    return _BRACKET_RE.sub(_reduce, cleaned)


def core_of(name: str) -> str:
    """Strip every括号, leaving only the基础专业名 (core name). 循环处理嵌套括号（如「1+3(一年国内加三年芬兰)」）。"""
    cleaned = nfk(name)
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = _BRACKET_RE.sub("", cleaned)
    return cleaned


def diff_brackets(name: str) -> list[tuple[str, str]]:
    """Classify each bracket of ``name`` into (kind, value) pairs.

    kind ∈ {"性别", "合作", "其他"}. Gender takes precedence over other
    classifications (spec §5.3 exception). Brackets are returned in source
    order; an empty list when the name has no brackets.

    >>> diff_brackets("英语")
    []
    """
    cleaned = nfk(name)
    out: list[tuple[str, str]] = []
    for m in _BRACKET_RE.finditer(cleaned):
        content = m.group(1)
        if _is_gender_bracket(content):
            out.append(("性别", "男" if "男" in content else "女"))
        elif "合作" in content:
            out.append(("合作", content))
        else:
            out.append(("其他", content))
    return out
