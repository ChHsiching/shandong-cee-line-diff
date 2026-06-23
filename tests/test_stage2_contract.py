"""Stage 2 contract tests.

The agent dispatch itself is a harness-side step (no Agent tool from Python).
But the *results* the harness writes (``batch_NN_result.jsonl``) must obey
hard contracts enforced by :func:`scripts.stage2_apply.apply_results`:

  1. ``match`` is either ``null`` or a string present in that dagluben row's
     candidate set (same school, core-name pre-filtered). Out-of-candidate
     matches are rejected — the agent hallucinated.
  2. Each dagluben ``src_row_idx`` appears at most once across all jsonl
     inputs. Duplicates are rejected.
  3. ``reason`` is a non-empty string (<=30 chars per prompt.md; emptiness is
     a hard reject, length is a soft warning surfaced via the returned
     MatchResult log).
  4. ``src_row_idx`` must correspond to a dagluben row actually handed to the
     agent — an unknown idx is rejected.

Rejected inputs raise :class:`Stage2ContractError` carrying the offending
line so the harness run surfaces the problem instead of silently corrupting
the main table.

Golden-pair regression (``@pytest.mark.manual``): the agent is expected to
recover >=80% of pre-confirmed correct pairs. Those pairs are the harness
side's business and run after agent dispatch, so they are marked manual and
do not block CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.models import DaglubenRow, HistoryRow
from scripts.stage2_apply import Stage2ContractError, apply_results


def _dl(idx: int, school: str, major: str, core: str) -> DaglubenRow:
    return DaglubenRow(
        src_row_idx=idx,
        school=school,
        school_cat="",
        major=major,
        stripped=major,
        core=core,
        subject="物理和化学",
        batch="4.常规批",
    )


def _hist(school: str, major: str, core: str, j: float) -> HistoryRow:
    return HistoryRow(
        school=school,
        school_cat="",
        major=major,
        stripped=major,
        core=core,
        subject="物理",
        J=j,
        T=1.0,
        source_table="常规批一段线",
    )


def _line(idx: int, match: str | None, reason: str, j: float | None = 1.0) -> str:
    return json.dumps(
        {
            "src_row_idx": idx,
            "school": "甲大学",
            "major": "计算机类(图灵)",
            "match": match,
            "J": j,
            "T": 0.5,
            "reason": reason,
        },
        ensure_ascii=False,
    )


def _write(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "batch_01_result.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _fixtures() -> tuple[list[DaglubenRow], list[HistoryRow]]:
    dagluben = [_dl(1, "甲大学", "计算机类(图灵)", "计算机类")]
    history = [
        _hist("甲大学", "计算机类", "计算机类", 80.0),
        _hist("甲大学", "计算机类(网络)", "计算机类", 78.0),
    ]
    return dagluben, history


# --- contract: match must be null or in candidate set -----------------------


def test_reject_match_outside_candidate_set(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    # "量子力学" is not in 甲大学's computer candidates -> hallucination.
    jsonl = _write(tmp_path, [_line(1, "量子力学", "看似合理但其实越界")])
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([jsonl], dagluben, history)
    assert "候选" in str(exc.value) or "candidate" in str(exc.value).lower()


def test_accept_match_in_candidate_set(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(tmp_path, [_line(1, "计算机类(网络)", "括号方向对齐", 78.0)])
    results = apply_results([jsonl], dagluben, history)
    assert results[0]["matched"] is True
    assert results[0]["J"] == 78.0


def test_accept_null_match(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(tmp_path, [_line(1, None, "无对应", None)])
    results = apply_results([jsonl], dagluben, history)
    assert results[0]["matched"] is False


# --- contract: at most one result per dagluben src_row_idx ------------------


def test_reject_duplicate_src_row_idx_across_files(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    j1 = tmp_path / "batch_01_result.jsonl"
    j2 = tmp_path / "batch_02_result.jsonl"
    j1.write_text(_line(1, "计算机类", "第一次") + "\n", encoding="utf-8")
    j2.write_text(_line(1, "计算机类(网络)", "第二次") + "\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([j1, j2], dagluben, history)
    assert "重复" in str(exc.value) or "duplicate" in str(exc.value).lower()


def test_reject_duplicate_within_same_file(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(
        tmp_path,
        [_line(1, "计算机类", "第一次"), _line(1, "计算机类", "第二次")],
    )
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


# --- contract: reason non-empty --------------------------------------------


def test_reject_empty_reason(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(tmp_path, [_line(1, "计算机类", "")])
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([jsonl], dagluben, history)
    assert "reason" in str(exc.value).lower() or "理由" in str(exc.value)


# --- contract: src_row_idx must be a known dagluben row ---------------------


def test_reject_unknown_src_row_idx(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(tmp_path, [_line(999, "计算机类", "未知行")])
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


# --- contract: malformed json line is surfaced ------------------------------


def test_reject_malformed_json_line(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


# --- contract: missing required keys ----------------------------------------


@pytest.mark.parametrize("missing", ["match", "J", "reason", "src_row_idx"])
def test_reject_missing_required_key(tmp_path: Path, missing: str) -> None:
    dagluben, history = _fixtures()
    record: dict[str, object] = {
        "src_row_idx": 1,
        "school": "甲大学",
        "major": "计算机类(图灵)",
        "match": "计算机类",
        "J": 80.0,
        "T": 0.5,
        "reason": "核心名同",
    }
    record.pop(missing)
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


# --- golden-pair regression (manual; runs only when golden pairs exist) ------

GOLDEN_PATH = Path(__file__).parent / "golden" / "semantic_pairs.json"


@pytest.mark.manual
def test_golden_pair_hit_rate() -> None:
    """After agent dispatch, the harness should recover >=80% of pre-confirmed
    correct pairs. Skipped until the golden fixture + a result jsonl exist.

    This is a manual gate: the main session runs it after producing
    ``semantic-match/batch_*_result.jsonl`` and compares against
    ``tests/golden/semantic_pairs.json``.
    """
    pytest.skip(
        "golden regression runs in the main session after agent dispatch; "
        "see semantic-match/RUN.md"
    )
