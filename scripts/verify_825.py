"""825-弃用前重叠验证 (spec §6 Stage 0, §9 日志: 独有/待人工核验).

The近三年 `提前批` batch (825 rows) carries no extra information over the
supplement table once提前批 is sourced from the latter — but we prove it before
discarding. This module:

    1. Extracts (schoolcode, nfk(majorname)) pairs from both sides.
    2. Reports the近三年 提前批 keys that are NOT in the supplement本科 A+B pool.
    3. Writes those unique keys to ``intermediate/s2_j3_early_only.csv`` for
       human review — never silently dropped.

Per Plan v2 this is a **契约测试** (not a hard FAIL): the contract is
``reported_count == len(csv 独有行)``; the count itself is surfaced, not
asserted to be zero, because some unique rows are expected (定向培养军士生
专科 rows that近三年 still labels 提前批) and go to human review rather than
blocking the pipeline.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from scripts.normalize import nfk

__all__ = [
    "nfk",
    "OverlapReport",
    "extract_j3_early_pairs",
    "extract_tq_benke_pairs",
    "report_overlap",
    "write_unique_csv",
]

# Column anchors (0-based). Re-declared locally rather than pulling the full
# constants grab-bag; the 近三年 / 补充表 layouts differ and these indices are
# intrinsic to this verification's contract.
_J3_BATCH, _J3_SCHOOLCODE, _J3_MAJORNAME = 0, 1, 3
_TQ_BATCH, _TQ_SCHOOLCODE, _TQ_MAJORNAME = 0, 2, 5
_TQ_BENKE_BATCHES: frozenset[str] = frozenset({"本科提前批A类", "本科提前批B类"})


@dataclass(frozen=True)
class OverlapReport:
    """Outcome of the 825-vs-supplement overlap check.

    ``unique_keys`` preserves first-seen order over the近三年 提前批 input so
    the review CSV reads top-to-bottom as an analyst would expect in the
    source file.
    """

    reported_count: int
    unique_keys: list[tuple[str, str]] = field(default_factory=list)


def extract_j3_early_pairs(rows: Iterable[Sequence]) -> list[tuple[str, str]]:
    """Return ``[(schoolcode, nfk(majorname)), ...]`` for近三年 提前批 rows.

    Header and other batches are skipped. Duplicates are preserved so callers
    can inspect the raw multiplicity if needed; :func:`report_overlap`
    de-duplicates when counting uniques.
    """
    out: list[tuple[str, str]] = []
    for row in rows:
        if not row:
            continue
        batch = row[_J3_BATCH] if len(row) > _J3_BATCH else None
        if batch in (None, "batch", "批次"):
            continue
        if batch != "提前批":
            continue
        code = str(row[_J3_SCHOOLCODE]) if len(row) > _J3_SCHOOLCODE and row[_J3_SCHOOLCODE] is not None else ""
        major = row[_J3_MAJORNAME] if len(row) > _J3_MAJORNAME else None
        out.append((code, nfk(major)))
    return out


def extract_tq_benke_pairs(rows: Iterable[Sequence]) -> list[tuple[str, str]]:
    """Return ``[(院校代码, nfk(专业名称)), ...]`` for supplement本科 A+B rows.

    专科提前批 is excluded — those rows are dropped from the unified history
    (spec §3) and must not pad the overlap pool.
    """
    out: list[tuple[str, str]] = []
    for row in rows:
        if not row:
            continue
        batch = row[_TQ_BATCH] if len(row) > _TQ_BATCH else None
        if batch not in _TQ_BENKE_BATCHES:
            continue
        code = str(row[_TQ_SCHOOLCODE]) if len(row) > _TQ_SCHOOLCODE and row[_TQ_SCHOOLCODE] is not None else ""
        major = row[_TQ_MAJORNAME] if len(row) > _TQ_MAJORNAME else None
        out.append((code, nfk(major)))
    return out


def report_overlap(
    j3_pairs: Iterable[tuple[str, str]],
    tq_pairs: Iterable[tuple[str, str]],
) -> OverlapReport:
    """Compute the近三年 提前批 keys absent from the supplement本科 pool.

    Returns an :class:`OverlapReport` whose ``reported_count`` is the
    de-duplicated unique count and ``unique_keys`` lists them in first-seen
    order over ``j3_pairs``.
    """
    tq_set = set(tq_pairs)
    seen: set[tuple[str, str]] = set()
    unique_keys: list[tuple[str, str]] = []
    for key in j3_pairs:
        if key in tq_set or key in seen:
            continue
        seen.add(key)
        unique_keys.append(key)
    return OverlapReport(reported_count=len(unique_keys), unique_keys=unique_keys)


def write_unique_csv(report: OverlapReport, path: str | Path) -> int:
    """Write ``report.unique_keys`` to ``path`` for human review.

    CSV columns: ``schoolcode, majorname``. Returns the number of rows
    written (== ``report.reported_count``), so callers can assert the
    contract: the count reported equals the count surfaced.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["schoolcode", "majorname"])
        for code, major in report.unique_keys:
            writer.writerow([code, major])
    return len(report.unique_keys)
