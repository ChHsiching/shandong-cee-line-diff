"""Read-only loader + SHA256 immutability guard for the three source xlsx.

The source files under ``data/`` are the single source of truth and must never
be modified. Every stage opens them with ``open_only=True``; callers wrap
reads in :func:`assert_unchanged` before/after to enforce byte-level stability.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import openpyxl
from openpyxl.workbook.workbook import Workbook

__all__ = ["load_source", "sha256", "assert_unchanged"]

# Block size chosen to be friendly to CPython's read-ahead buffer without
# slurping a 10MB file into memory at once.
_CHUNK = 1 << 20  # 1 MiB


def sha256(path: str | Path) -> str:
    """Return the sha256 hexdigest of the file at ``path``."""
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def assert_unchanged(path: str | Path, before_hash: str) -> None:
    """Raise :class:`RuntimeError` if the file's sha256 differs from baseline.

    Called before and after pipeline stages that touch a source workbook so
    any accidental mutation surfaces immediately rather than corrupting the
    output. Silent (returns ``None``) when the hash matches.
    """
    current = sha256(path)
    if current != before_hash:
        raise RuntimeError(
            f"source file changed during pipeline: {path}\n"
            f"  before: {before_hash}\n"
            f"  after : {current}\n"
            "Source files are read-only; aborting to protect data integrity."
        )


def load_source(path: str | Path, *, read_only: bool = True) -> Workbook:
    """Open a source workbook in read-only mode by default.

    ``data_only=True`` returns the last cached computed values for formula
    cells, which is what we want for the line-diff statistics already stored
    in 近三年. The caller is responsible for closing the workbook.
    """
    return openpyxl.load_workbook(Path(path), read_only=read_only, data_only=True)
