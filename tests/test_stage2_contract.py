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


def _line(
    idx: int,
    match: str | None,
    reason: str,
    j: float | None = 1.0,
    t: float | None = 1.0,
) -> str:
    """Build one result line. Default J/T echo the candidate's history values
    (T=1.0 from _hist); tests that want a null match pass match=None and the
    caller is expected to set j=None,t=None."""
    return json.dumps(
        {
            "src_row_idx": idx,
            "school": "甲大学",
            "major": "计算机类(图灵)",
            "match": match,
            "J": j,
            "T": t,
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
    jsonl = _write(tmp_path, [_line(1, "计算机类(网络)", "括号方向对齐", 78.0, 1.0)])
    results = apply_results([jsonl], dagluben, history)
    assert results[0]["matched"] is True
    assert results[0]["J"] == 78.0
    assert results[0]["T"] == 1.0


def test_accept_null_match(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(tmp_path, [_line(1, None, "无对应", None, None)])
    results = apply_results([jsonl], dagluben, history)
    assert results[0]["matched"] is False


# --- contract: at most one result per dagluben src_row_idx ------------------


def test_reject_duplicate_src_row_idx_across_files(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    j1 = tmp_path / "batch_01_result.jsonl"
    j2 = tmp_path / "batch_02_result.jsonl"
    # Both lines echo the real candidate J/T so we reach the dedupe gate
    # rather than tripping the J/T echo contract first.
    j1.write_text(_line(1, "计算机类", "第一次", 80.0, 1.0) + "\n", encoding="utf-8")
    j2.write_text(_line(1, "计算机类(网络)", "第二次", 78.0, 1.0) + "\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([j1, j2], dagluben, history)
    assert "重复" in str(exc.value) or "duplicate" in str(exc.value).lower()


def test_reject_duplicate_within_same_file(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(
        tmp_path,
        [
            _line(1, "计算机类", "第一次", 80.0, 1.0),
            _line(1, "计算机类", "第二次", 80.0, 1.0),
        ],
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
        "T": 1.0,
        "reason": "核心名同",
    }
    record.pop(missing)
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


# --- extra contract paths ---------------------------------------------------


def test_reject_non_integer_src_row_idx(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    record = {
        "src_row_idx": "1",
        "school": "甲大学",
        "major": "计算机类(图灵)",
        "match": "计算机类",
        "J": 80.0,
        "T": 1.0,
        "reason": "核心名同",
    }
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([jsonl], dagluben, history)
    assert "src_row_idx" in str(exc.value)


def test_reject_match_wrong_type(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    record = {
        "src_row_idx": 1,
        "school": "甲大学",
        "major": "计算机类(图灵)",
        "match": 123,
        "J": 80.0,
        "T": 1.0,
        "reason": "核心名同",
    }
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


def test_reject_j_mismatch_with_candidate(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    # match is a real candidate but J is fabricated -> reject.
    jsonl = _write(tmp_path, [_line(1, "计算机类", "核心名同", 999.0, 1.0)])
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([jsonl], dagluben, history)
    assert "J" in str(exc.value)


def test_reject_t_mismatch_with_candidate(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = _write(tmp_path, [_line(1, "计算机类", "核心名同", 80.0, 999.0)])
    with pytest.raises(Stage2ContractError) as exc:
        apply_results([jsonl], dagluben, history)
    assert "T" in str(exc.value)


def test_reason_over_30_chars_is_trimmed_not_rejected(tmp_path: Path) -> None:
    # Use a dagluben whose选科 matches the history选科 so no drift suffix is
    # appended — isolates the reason-trim check.
    dagluben = [_dl(1, "甲大学", "计算机类(图灵)", "计算机类")]
    dagluben[0]["subject"] = "物理"  # matches history _hist subject
    history = list(_fixtures()[1])
    long_reason = "核心名完全一致且方向括号完美对齐无任何歧义可放心匹配成功" * 2  # >30 chars
    assert len(long_reason) > 30
    jsonl = _write(tmp_path, [_line(1, "计算机类", long_reason, 80.0, 1.0)])
    results = apply_results([jsonl], dagluben, history)
    assert results[0]["matched"] is True
    # log = 语义匹配：<trimmed reason>. No选科 drift here (subjects match).
    assert results[0]["log"].startswith("语义匹配：")
    assert "选科政策漂移" not in results[0]["log"]
    reason_portion = results[0]["log"][len("语义匹配："):]
    assert len(reason_portion) <= 30
    assert len(reason_portion) < len(long_reason)  # was actually trimmed


def test_blank_lines_in_jsonl_are_skipped(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text(
        "\n"
        + _line(1, "计算机类", "核心名同", 80.0, 1.0)
        + "\n\n"
        + "   \n",
        encoding="utf-8",
    )
    results = apply_results([jsonl], dagluben, history)
    assert len(results) == 1


def test_reject_non_object_top_level(tmp_path: Path) -> None:
    dagluben, history = _fixtures()
    jsonl = tmp_path / "batch_01_result.jsonl"
    jsonl.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(Stage2ContractError):
        apply_results([jsonl], dagluben, history)


def test_subject_drift_appended_to_log(tmp_path: Path) -> None:
    """When the matched history选科 differs from the dagluben选科, the log
    picks up the「选科政策漂移，已忽略」suffix (spec §9 选科漂移)."""
    dagluben = [_dl(1, "甲大学", "计算机类(图灵)", "计算机类")]
    # override subject to force drift
    dagluben[0]["subject"] = "物理和化学"
    history = [_hist("甲大学", "计算机类", "计算机类", 80.0)]
    history[0]["subject"] = "物理"
    jsonl = _write(tmp_path, [_line(1, "计算机类", "核心名同", 80.0, 1.0)])
    results = apply_results([jsonl], dagluben, history)
    assert "选科政策漂移" in results[0]["log"]


# --- end-to-end orchestration on stub jsonl (pre -> write -> apply) ---------


def test_end_to_end_pre_write_apply(tmp_path: Path) -> None:
    """Full orchestration happy path on a stub: build_batches -> write_prompts
    -> (harness would dispatch agent) -> stub a result jsonl echoing the
    candidate J/T -> apply_results. Demonstrates the orchestration layer
    runs end-to-end on stub jsonl without invoking any agent."""
    from scripts.stage2_agent import build_batches, write_prompts

    unmatched = [
        _dl(1, "甲大学", "计算机类(图灵)", "计算机类"),
        _dl(2, "甲大学", "数学类(拔尖)", "数学类"),
    ]
    history = [
        _hist("甲大学", "计算机类", "计算机类", 80.0),
        _hist("甲大学", "数学类", "数学类", 90.0),
    ]

    batches = build_batches(unmatched, history, batch_size=20)
    prompt_paths = write_prompts(batches, tmp_path)
    assert len(prompt_paths) == 1

    # Simulate the agent answering: idx=1 matched, idx=2 no correspondence.
    result = tmp_path / "batch_01_result.jsonl"
    result.write_text(
        _line(1, "计算机类", "核心名同方向对齐", 80.0, 1.0)
        + "\n"
        + _line(2, None, "无对应", None, None)
        + "\n",
        encoding="utf-8",
    )
    out = apply_results([result], unmatched, history)
    assert len(out) == 2
    assert out[0]["matched"] is True and out[0]["J"] == 80.0
    assert out[1]["matched"] is False and out[1]["J"] is None
    assert all("语义匹配" in r["log"] for r in out)


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
