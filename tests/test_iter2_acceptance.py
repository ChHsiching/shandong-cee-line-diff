"""iteration-2 Slice D Task D2 — end-to-end acceptance (issue #13).

Manual acceptance test: reruns the full pipeline over the **real** three
source xlsx + the V5-3 audit hard gate, and asserts exit 0.

Marked ``@pytest.mark.manual`` so it does NOT run in default CI:
  - the three source bytes are invariant (their correctness is guarded by
    ``tests/test_immutability.py``), and rerunning the full pipeline over the
    real ~12MB sources is slow;
  - the judgmental-coverage check depends on the real
    ``verify_*_result.jsonl`` produced by the harness second-pass agent step,
    which is not deterministic in a fresh checkout.

Run explicitly when performing the iteration-2 acceptance:

    .venv/bin/python -m pytest tests/test_iter2_acceptance.py -m manual
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def test_iter2_acceptance_pipeline_plus_audit_exit_zero() -> None:
    """The full pipeline + V5-3 audit over the real sources must exit 0.

    This is the iteration-2 completion gate (issue #13). Wraps the manual
    acceptance runner ``scripts.run_iter2_acceptance`` so the harness / human
    has a single pytest entry point.
    """
    root = _repo_root()
    venv_python = root / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable

    result = subprocess.run(
        [python, "-m", "scripts.run_iter2_acceptance", "--log-level", "WARNING"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "iteration-2 acceptance FAILED (exit != 0):\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    # Confirm the audit hard gate was the source of the green verdict.
    assert "OK (exit 0)" in result.stdout
    assert "FAIL" not in result.stdout
