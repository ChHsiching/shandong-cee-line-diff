"""Slice 6 Task 6.3 — rename web-search remark merge (pure layer).

Per Plan v2 binding + spec §6 Stage 3 最后一步 + Slice 4 architecture:
WebSearch **cannot be invoked from a Python script** (harness tool), so this
module ships only the testable pure functions. The harness runs the per-school
WebSearch loop against the改名表 (see ``research/RUN_RENAME.md``) and feeds
each ``research/<school>.md`` summary through :func:`merge_remark`.

Idempotency (Plan v2 binding): the改名表 备注 column carries a
``manual_reviewed`` boolean. :func:`merge_remark` **must not** overwrite the
备注 of a row whose ``manual_reviewed`` is True — a human has already curated
that note and re-running the web-search step should preserve it.
"""

from __future__ import annotations

from scripts.models import RenameRow

__all__ = ["format_query", "merge_remark"]


def format_query(school_new: str, school_old: str) -> str:
    """Build the WebSearch query for one renamed school.

    Includes both names and an explicit rename/转设/前身 intent so the harness
    WebSearch surfaces官方公告 / 教育部更名批复 / 同源证据. The exact phrasing
    is intentionally simple — harness WebSearch is best-effort and the human
    reads the raw ``research/<school>.md`` before merging.
    """
    return f"{school_new} {school_old} 更名 转设 前身 同源 高校"


def merge_remark(research_md: str, row: RenameRow) -> RenameRow:
    """Merge a research/<school>.md summary into a RenameRow's 备注.

    Contract (Plan v2 idempotency binding):
      - If ``row["manual_reviewed"]`` is True, the备注 is returned **unchanged**
        (a human has curated it; web-search re-runs never overwrite human
        edits). ``manual_reviewed`` stays True.
      - Otherwise the research summary is folded into备注 (non-destructively —
        an existing non-empty备注 is preserved when the research summary is
        empty, so a failed/empty WebSearch never wipes prior content).
        ``manual_reviewed`` stays False (web-search is not human review).

    Returns a **new** RenameRow — input is never mutated (coding-style.md
    immutability). The merged备注 is the stripped research text so downstream
    writers can render it as a single cell.
    """
    if row.get("manual_reviewed") is True:
        return RenameRow(**dict(row))  # shallow copy, unchanged

    summary = (research_md or "").strip()
    existing = (row.get("remark") or "").strip()

    if summary == "":
        new_remark = existing
    elif existing == "":
        new_remark = summary
    else:
        new_remark = f"{existing}\n{summary}"

    merged = dict(row)
    merged["remark"] = new_remark
    # manual_reviewed stays False — web-search is not human confirmation.
    merged["manual_reviewed"] = bool(row.get("manual_reviewed", False))
    return RenameRow(**merged)
