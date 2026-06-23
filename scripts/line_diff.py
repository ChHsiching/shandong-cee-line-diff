"""提前批 line-diff computation (spec §2.3, §4.1).

The supplement table (山东省高考提前批录取数据.xlsx) carries only raw 录取低分
per year, not pre-computed line diffs. This module turns those low scores into
the same (统计线差 J, 线差标准差 T) shape the 近三年 table uses for常规批.

口径 (locked by spec §2.3 说明 + user grilling):
    year_line_diff = 录取低分 − 当年一段线   (一段线 ∈ constants.ONE_LINE)
    统计线差 (J)   = mean(有数据年份的线差)  (单年用该年)
    线差标准差 (T) = population stdev over the same years
                    (单年 / 全无 → None; 单年 pstdev 形式上为 0 但口径上置空)

Signature renamed per Plan v2 to ``compute(low_scores_by_year, provincial_lines)``
so the two dicts cannot be transposed without the maths going obviously wrong.
``low_scores_by_year`` may carry ``None`` for years where the school has no
enrolled low score; those years are skipped. ``provincial_lines`` is the
authoritative cutoff table (constants.ONE_LINE) and is expected to be dense.
"""

from __future__ import annotations

import statistics
from typing import Mapping

__all__ = ["compute"]


def _to_float(v) -> float | None:
    """Coerce a workbook cell to float, treating blank/None/empty as missing."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compute(
    low_scores_by_year: Mapping[int, float | int | None],
    provincial_lines: Mapping[int, float | int],
) -> tuple[float | None, float | None]:
    """Return ``(统计线差, 线差标准差)`` from per-year low scores.

    A year contributes only when both its low score and the matching one-line
    cutoff resolve to a number. When fewer than two years contribute, the
    standard deviation is ``None`` per the spec single-year 口径. When zero
    years contribute, both values are ``None``.
    """
    diffs: list[float] = []
    for year, low in low_scores_by_year.items():
        cutoff = provincial_lines.get(year)
        low_f = _to_float(low)
        cutoff_f = _to_float(cutoff)
        if low_f is None or cutoff_f is None:
            continue
        diffs.append(low_f - cutoff_f)

    if not diffs:
        return None, None
    stat = statistics.mean(diffs)
    std: float | None = statistics.pstdev(diffs) if len(diffs) >= 2 else None
    # 舍入到 2 位，匹配近三年源表精度（源 T 为 2 位，如 12.73）；避免长浮点。
    return round(stat, 2), (round(std, 2) if std is not None else None)
