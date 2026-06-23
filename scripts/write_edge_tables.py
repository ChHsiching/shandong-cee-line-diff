"""Edge/boundary table writers (新增/被删/特殊/改名/新增校/停招校).

Per Plan v2 binding, these are separated from write_outputs.py so that
Slices 5/6 (which populate them) do not modify the Slice-1-stable
write_outputs module. This file is intentionally a stub in Slice 1; the
functions raise NotImplementedError until their owning slices implement them.

Tables to produce (spec §7):
    - 新增专业.xlsx        (Slice 5)
    - 被删旧专业.xlsx      (Slice 6)
    - 学校改名表.xlsx      (Slice 6)
    - 新增校表.xlsx        (Slice 6)
    - 停招消失校表.xlsx    (Slice 6)
    - 特殊情况.xlsx        (Slice 6)
"""

from __future__ import annotations

__all__ = [
    "write_new_major_table",
    "write_deleted_major_table",
    "write_rename_table",
    "write_new_school_table",
    "write_gone_school_table",
    "write_special_table",
]


def write_new_major_table(*args, **kwargs):
    raise NotImplementedError("Slice 5 (Stage 3 新增估算) implements this.")


def write_deleted_major_table(*args, **kwargs):
    raise NotImplementedError("Slice 6 (被删/飞行/特殊) implements this.")


def write_rename_table(*args, **kwargs):
    raise NotImplementedError("Slice 6 (学校改名) implements this.")


def write_new_school_table(*args, **kwargs):
    raise NotImplementedError("Slice 6 implements this.")


def write_gone_school_table(*args, **kwargs):
    raise NotImplementedError("Slice 6 implements this.")


def write_special_table(*args, **kwargs):
    raise NotImplementedError("Slice 6 implements this.")
