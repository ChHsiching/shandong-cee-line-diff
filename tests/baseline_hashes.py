"""Baseline SHA256 hashes of the three source xlsx files.

Captured in Task 1.1 immediately after `git mv` to `data/`.
The immutability contract test (tests/test_immutability.py) asserts these
hashes never drift across pipeline runs.

Hashes are the sha256 of the file bytes at commit time (post git mv).
"""

from __future__ import annotations

# (relative-to-repo-root path, sha256 hexdigest)
BASELINE_HASHES: dict[str, str] = {
    "data/山东省2026年大绿本招生计划.xlsx": (
        "532937ddaf0d25c9519ae8c9440398f202a04e56107fc2d6ce38ed692abc9769"
    ),
    "data/近三年学校批次专业线差统计.xlsx": (
        "8b5763224a7d6aa103bc4dc180cf47b654101aa4b97d52905a6d4712e88c65e5"
    ),
    "data/山东省高考提前批录取数据.xlsx": (
        "64c43d5f6ddcacf2fac1c0bd762c0e266487c21ed4f09c8b4919a09e91f93b61"
    ),
}
