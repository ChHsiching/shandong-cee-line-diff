"""Source-file immutability contract (Plan v2 / spec §3 铁律: 源文件只读).

Three sources under data/ must be byte-identical to the baseline hashes
captured at Task 1.1 (recorded in tests/baseline_hashes.py). This contract
guards every pipeline run: if any source drifts, the suite fails immediately
rather than silently producing corrupt outputs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import io_source
from tests.baseline_hashes import BASELINE_HASHES


@pytest.fixture(scope="module")
def repo_root_path() -> Path:
    return Path(__file__).resolve().parent.parent


def test_each_source_hash_matches_baseline(repo_root_path: Path):
    """All three source files must match the recorded baseline sha256."""
    missing = []
    drifted = []
    for rel, expected in BASELINE_HASHES.items():
        p = repo_root_path / rel
        if not p.exists():
            missing.append(rel)
            continue
        actual = io_source.sha256(p)
        if actual != expected:
            drifted.append((rel, expected, actual))
    assert not missing, f"missing source files: {missing}"
    assert not drifted, (
        "source files drifted from baseline (sources are read-only):\n"
        + "\n".join(f"  {r}: expected {e}, got {a}" for r, e, a in drifted)
    )


def test_assert_unchanged_passes_for_each_baseline_source(repo_root_path: Path):
    """The runtime guard io_source.assert_unchanged must be happy with each
    source against its baseline hash."""
    for rel, expected in BASELINE_HASHES.items():
        # Silent on match.
        assert io_source.assert_unchanged(repo_root_path / rel, expected) is None


def test_assert_unchanged_raises_if_source_drifts(repo_root_path: Path, tmp_path: Path):
    """If a source is somehow altered, the guard must raise RuntimeError."""
    import shutil

    src = repo_root_path / next(iter(BASELINE_HASHES))
    fake = tmp_path / "tampered.xlsx"
    shutil.copy(src, fake)
    # Tamper: append bytes.
    with fake.open("ab") as fh:
        fh.write(b"\x00\x00\x00\x00")
    baseline = BASELINE_HASHES[next(iter(BASELINE_HASHES))]
    with pytest.raises(RuntimeError):
        io_source.assert_unchanged(fake, baseline)
