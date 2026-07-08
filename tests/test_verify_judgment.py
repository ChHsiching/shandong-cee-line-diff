"""Slice B — judgmental-match second-pass verification contract tests.

Per spec V5-0 / plan Slice B (v2 binding). All judgmental matches (coarse
核心名唯一/消歧 + agent 语义 matched) must pass a **second agent review** that
returns either「确定」(keep in main table) or「存疑」(demote to special). The
agent dispatch is a harness-side step (Agent tool); this module tests the
**pure-function layer** that the harness drives:

  - :func:`build_verify_batches` — attach dagluben row + matched candidate +
    judgment requirement to each judgmental match; slice into batches.
  - :func:`write_verify_prompts` — write ``verify_batch_NN.json`` per batch.
  - :func:`apply_verify` — read ``verify_*_result.jsonl`` and route each row
    to ``confirmed`` (verdict=确定, MatchResult) or ``demoted`` (verdict=存疑,
    EdgeRow); hard-reject verdict outside {确定, 存疑} / empty reason / unknown
    / duplicate src_row_idx.

Contract routing test (CI): given a verdict jsonl with one确定 and one存疑,
apply_verify returns the first in ``confirmed`` and the second in ``demoted``.

Golden regression (``@pytest.mark.manual``): after agent dispatch, ≥95% of the
pre-confirmed pairs judge 确定, and the 投资学(量化投资)↔投资学 counter-example
judges 存疑.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.models import DaglubenRow, HistoryRow, MatchResult
from scripts.verify_judgment import (
    VerifyContractError,
    apply_verify,
    build_verify_batches,
    write_verify_prompts,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _dl(
    idx: int, school: str, major: str, core: str, batch: str = "4.常规批"
) -> DaglubenRow:
    return DaglubenRow(
        src_row_idx=idx,
        school=school,
        school_cat="",
        major=major,
        stripped=major,
        core=core,
        subject="物理和化学",
        batch=batch,
    )


def _hist(
    school: str, major: str, core: str, j: float = 80.0, t: float | None = 1.0
) -> HistoryRow:
    return HistoryRow(
        school=school,
        school_cat="",
        major=major,
        stripped=major,
        core=core,
        subject="物理",
        J=j,
        T=t,
        source_table="常规批一段线",
    )


def _match(
    idx: int, school: str, major: str, log: str = "核心名匹配：核心专业名相同"
) -> MatchResult:
    return MatchResult(
        src_row_idx=idx,
        school=school,
        school_cat="",
        major=major,
        matched=True,
        J=80.0,
        T=1.0,
        log=log,
    )


def _write_jsonl(path: Path, objs: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in objs) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# build_verify_batches
# ---------------------------------------------------------------------------


def test_build_verify_batches_attaches_dagluben_candidate_and_requirement() -> None:
    """Each judgmental match carries its dagluben row, the matched history
    candidate, and the judgment requirement in one VerifyBatchItem."""
    judgment_matches = [
        _match(1, "甲大学", "投资学(量化投资)", log="核心名匹配：核心专业名相同"),
        _match(2, "甲大学", "会计学", log="agent 语义匹配：方向对齐"),
        _match(3, "乙大学", "数学类", log="核心名匹配：核心专业名相同（方向）"),
    ]
    dagluben = [
        _dl(1, "甲大学", "投资学(量化投资)", "投资学"),
        _dl(2, "甲大学", "会计学", "会计学"),
        _dl(3, "乙大学", "数学类", "数学类"),
    ]
    history = [
        _hist("甲大学", "投资学", "投资学", 60.0),
        _hist("甲大学", "会计学", "会计学", 70.0),
        _hist("乙大学", "数学类", "数学类", 90.0),
    ]

    batches = build_verify_batches(judgment_matches, dagluben, history, batch_size=20)

    assert len(batches) == 1
    items = batches[0].items
    assert len(items) == 3
    # idx 1: dagluben 投资学(量化投资), candidate 投资学
    assert items[0].dagluben["src_row_idx"] == 1
    assert items[0].matched_candidate["major"] == "投资学"
    assert "判定要求" in items[0].requirement or items[0].requirement  # non-empty
    # idx 2: dagluben 会计学, candidate 会计学
    assert items[1].matched_candidate["major"] == "会计学"


def test_build_verify_batches_splits_into_batches_of_2() -> None:
    """3 judgmental matches / batch_size=2 → 2 batches (2 + 1)."""
    judgment_matches = [
        _match(i, "甲大学", f"专业{i}", log="核心名匹配：核心专业名相同")
        for i in (1, 2, 3)
    ]
    dagluben = [_dl(i, "甲大学", f"专业{i}", f"专业{i}") for i in (1, 2, 3)]
    history = [_hist("甲大学", f"专业{i}", f"专业{i}") for i in (1, 2, 3)]

    batches = build_verify_batches(judgment_matches, dagluben, history, batch_size=2)
    assert len(batches) == 2
    assert len(batches[0].items) == 2
    assert len(batches[1].items) == 1
    assert batches[0].index == 1
    assert batches[1].index == 2


def test_build_verify_batches_empty_input_returns_empty() -> None:
    assert build_verify_batches([], [], []) == []


def test_build_verify_batches_skips_non_judgmental_strict_matches() -> None:
    """Strict-exact matches are构造确定 — they must NOT enter verification.
    Only matches whose log starts with 粗筛 or agent 语义匹配 (matched) qualify."""
    judgment_matches = [
        _match(1, "甲大学", "计算机", log="严格匹配：归一化专业名+招生类别一致"),
        _match(2, "甲大学", "投资学(量化投资)", log="核心名匹配：核心专业名相同"),
    ]
    dagluben = [
        _dl(1, "甲大学", "计算机", "计算机"),
        _dl(2, "甲大学", "投资学(量化投资)", "投资学"),
    ]
    history = [_hist("甲大学", "计算机", "计算机"), _hist("甲大学", "投资学", "投资学")]

    batches = build_verify_batches(judgment_matches, dagluben, history, batch_size=20)
    assert len(batches) == 1
    idxs = [it.dagluben["src_row_idx"] for it in batches[0].items]
    assert idxs == [2]  # strict idx 1 excluded


def test_build_verify_batches_matched_major_pins_candidate_when_jt_collide() -> None:
    """#3: 两个同校同核心名候选 J/T 恰好相同时，MatchResult.matched_major 精确
    锁定 agent 选中的那条，避开 J/T 巧合错定位（量子计划↔未来工程师项目制
    bug 的根因）。matched_major 缺失时退化到旧 J/T 路径。"""
    history = [
        _hist("X大学", "数学(量子)", "数学", j=70.0, t=3.0),
        _hist("X大学", "数学(未来工程师)", "数学", j=70.0, t=3.0),
    ]
    match = MatchResult(
        src_row_idx=5,
        school="X大学",
        school_cat="",
        major="数学(量子先锋)",
        matched=True,
        matched_major="数学(量子)",
        J=70.0,
        T=3.0,
        log="agent 语义匹配：方向对齐",
    )
    dagluben = [_dl(5, "X大学", "数学(量子先锋)", "数学")]

    batches = build_verify_batches([match], dagluben, history, batch_size=20)
    assert len(batches) == 1
    cand = batches[0].items[0].matched_candidate
    # matched_major 锁定「数学(量子)」，而非 J/T 巧合命中的第一条。
    assert cand["major"] == "数学(量子)"


# ---------------------------------------------------------------------------
# write_verify_prompts
# ---------------------------------------------------------------------------


def test_write_verify_prompts_writes_one_file_per_batch(tmp_path: Path) -> None:
    judgment_matches = [
        _match(i, "甲大学", f"专业{i}", "核心名匹配：核心专业名相同") for i in (1, 2, 3)
    ]
    dagluben = [_dl(i, "甲大学", f"专业{i}", f"专业{i}") for i in (1, 2, 3)]
    history = [_hist("甲大学", f"专业{i}", f"专业{i}") for i in (1, 2, 3)]

    batches = build_verify_batches(judgment_matches, dagluben, history, batch_size=2)
    paths = write_verify_prompts(batches, tmp_path)
    assert len(paths) == 2
    assert paths[0].name == "verify_batch_01.json"
    assert paths[1].name == "verify_batch_02.json"
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["batch"] == 1
    assert len(payload["items"]) == 2
    assert "output_schema" in payload


# ---------------------------------------------------------------------------
# apply_verify — contract enforcement
# ---------------------------------------------------------------------------


def _basic_setup() -> tuple[list[MatchResult], list[DaglubenRow]]:
    matches = [
        _match(1, "甲大学", "投资学(量化投资)", "核心名匹配：核心专业名相同"),
        _match(2, "甲大学", "会计学", "agent 语义匹配：方向对齐"),
    ]
    dagluben = [
        _dl(1, "甲大学", "投资学(量化投资)", "投资学"),
        _dl(2, "甲大学", "会计学", "会计学"),
    ]
    return matches, dagluben


def test_apply_verify_routes_confirmed_to_confirmed_and_uncertain_to_demoted(
    tmp_path: Path,
) -> None:
    """CI contract: 确定 → confirmed (MatchResult), 存疑 → demoted (EdgeRow)."""
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "verify_batch_01_result.jsonl",
        [
            {
                "src_row_idx": 1,
                "verdict": "存疑",
                "reason": "方向不同：量化投资≠投资学",
            },
            {"src_row_idx": 2, "verdict": "确定", "reason": "同名同方向"},
        ],
    )
    result = apply_verify([jsonl], dagluben, matches)
    confirmed_idxs = {r["src_row_idx"] for r in result["confirmed"]}
    demoted_idxs = {r["src_row_idx"] for r in result["demoted"]}
    assert 2 in confirmed_idxs
    assert 1 in demoted_idxs
    # demoted EdgeRow carries dagluben core/subject/batch
    demoted = result["demoted"][0]
    assert demoted["core"] == "投资学"
    assert demoted["batch"] == "4.常规批"
    assert "二次复核认为可能有误" in demoted["log"]
    # verdict_by_idx
    assert result["verdict_by_idx"] == {1: "存疑", 2: "确定"}


def test_apply_verify_confirmed_keeps_original_matchresult(tmp_path: Path) -> None:
    """确定 keeps the original MatchResult (J/T/log intact)."""
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "r.jsonl",
        [
            {"src_row_idx": 2, "verdict": "确定", "reason": "ok"},
        ],
    )
    result = apply_verify([jsonl], dagluben, matches)
    assert len(result["confirmed"]) == 1
    assert result["confirmed"][0]["J"] == 80.0
    assert result["confirmed"][0]["matched"] is True


def test_apply_verify_rejects_verdict_outside_allowed(tmp_path: Path) -> None:
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "r.jsonl",
        [
            {"src_row_idx": 1, "verdict": "可能", "reason": "x"},
        ],
    )
    with pytest.raises(VerifyContractError):
        apply_verify([jsonl], dagluben, matches)


def test_apply_verify_rejects_missing_required_key(tmp_path: Path) -> None:
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "r.jsonl",
        [
            {"src_row_idx": 1, "verdict": "确定"},  # missing reason
        ],
    )
    with pytest.raises(VerifyContractError):
        apply_verify([jsonl], dagluben, matches)


def test_apply_verify_rejects_empty_reason(tmp_path: Path) -> None:
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "r.jsonl",
        [
            {"src_row_idx": 1, "verdict": "存疑", "reason": "   "},
        ],
    )
    with pytest.raises(VerifyContractError):
        apply_verify([jsonl], dagluben, matches)


def test_apply_verify_rejects_duplicate_src_row_idx(tmp_path: Path) -> None:
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "r.jsonl",
        [
            {"src_row_idx": 1, "verdict": "确定", "reason": "a"},
            {"src_row_idx": 1, "verdict": "存疑", "reason": "b"},
        ],
    )
    with pytest.raises(VerifyContractError):
        apply_verify([jsonl], dagluben, matches)


def test_apply_verify_rejects_src_row_idx_not_in_judgment_matches(
    tmp_path: Path,
) -> None:
    matches, dagluben = _basic_setup()
    jsonl = _write_jsonl(
        tmp_path / "r.jsonl",
        [
            {"src_row_idx": 999, "verdict": "确定", "reason": "x"},
        ],
    )
    with pytest.raises(VerifyContractError):
        apply_verify([jsonl], dagluben, matches)


def test_apply_verify_rejects_bad_json_line(tmp_path: Path) -> None:
    matches, dagluben = _basic_setup()
    jsonl = tmp_path / "r.jsonl"
    jsonl.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(VerifyContractError):
        apply_verify([jsonl], dagluben, matches)


# ---------------------------------------------------------------------------
# requirement text — rule content (single source of truth, drift guard)
# ---------------------------------------------------------------------------
# verify 判定规则只在 _requirement_text（按往年同核心数动态生成），OUTPUT_SCHEMA
# 只指回这里——避免两处复述 drift。曾因此把培养模式标签丢掉，verify 把
# 数学(拔尖)↔数学 判了存疑（handoff 2026-07-08）。规则与 SKILL §3 一致：
#   past=1 (一对多) → 今年任何校内变体(培养模式/合作/方向/性别)都是同一专业→确定
#   past>1         → 培养模式标签差异→确定；中外合作/师范/类别/真方向→存疑

def test_requirement_past_one_absorbs_all_variants() -> None:
    """past=1：培养模式标签 + 中外合作/方向/性别 都判确定（一对多）。drift guard。"""
    from scripts.verify_judgment import _requirement_text

    req = _requirement_text(
        _dl(1, "甲大学", "数学(拔尖)", "数学"),
        _hist("甲大学", "数学", "数学"),
        past_same_core=1,
    )
    assert any(l in req for l in ("培养模式", "拔尖", "卓越", "创新", "试验班"))
    assert "中外合作" in req  # past=1 连合作都吸收
    assert "确定" in req


def test_requirement_past_many_training_mode_ok_but_category_doubt() -> None:
    """past>1：培养模式标签→确定；但中外合作/师范/类别→存疑。"""
    from scripts.verify_judgment import _requirement_text

    req = _requirement_text(
        _dl(1, "甲大学", "数学(拔尖)", "数学"),
        _hist("甲大学", "数学", "数学"),
        past_same_core=3,
    )
    assert any(l in req for l in ("培养模式", "拔尖", "卓越", "创新", "试验班"))
    assert "中外合作" in req
    assert "存疑" in req


def test_requirement_covers_dalei_vs_specific_exception() -> None:
    """Def-3（fresh-test 2026-07-09）：verify requirement 必须覆盖「大类↔具体」
    例外——不然 cores 不同(工商管理 vs 工商管理类)时落到「真方向不同→存疑」，
    把有效的 X↔X类 一对多匹配误降级（~30-50 条）。drift guard。"""
    from scripts.verify_judgment import _requirement_text

    for past_n in (1, 3):
        req = _requirement_text(
            _dl(1, "甲大学", "工商管理", "工商管理"),
            _hist("甲大学", "工商管理类", "工商管理类"),
            past_same_core=past_n,
        )
        assert any(
            tok in req for tok in ("大类↔具体", "X类", "工商管理类")
        ), f"past={past_n} requirement 缺大类↔具体例外"
        assert "确定" in req


def test_build_verify_batches_routes_by_past_same_core_count() -> None:
    """build_verify_batches 按往年同核心数选 regime：1 个→一对多确定, 多个→细比。"""
    judgment = [_match(1, "甲大学", "数学(拔尖)", log="agent 语义匹配：方向对齐")]
    dagluben = [_dl(1, "甲大学", "数学(拔尖)", "数学")]
    # 往年同核心 3 个 → past>1 regime（中外合作应判存疑，不是被吸收）
    history = [_hist("甲大学", f"数学({x})", "数学") for x in ("普通", "拔尖", "中外合作")]
    batches = build_verify_batches(judgment, dagluben, history, batch_size=20)
    req = batches[0].items[0].requirement
    assert "中外合作" in req and "存疑" in req

    # 对比：往年同核心只 1 个 → past=1 regime（中外合作被吸收→确定）
    history_one = [_hist("甲大学", "数学", "数学")]
    batches_one = build_verify_batches(judgment, dagluben, history_one, batch_size=20)
    req_one = batches_one[0].items[0].requirement
    assert "确定" in req_one


def test_output_schema_description_defers_to_requirement() -> None:
    """OUTPUT_SCHEMA 不再复述规则（单一真理源），只指回每条 item 的 requirement。"""
    from scripts.verify_judgment import OUTPUT_SCHEMA

    desc = OUTPUT_SCHEMA["description"]
    assert "requirement" in desc.lower()


# ---------------------------------------------------------------------------
# golden regression (manual — after agent dispatch)
# ---------------------------------------------------------------------------

GOLDEN_PATH = Path(__file__).parent / "golden" / "verify_pairs.json"


@pytest.mark.manual
def test_verify_golden_certainty_threshold() -> None:
    """After verification dispatch, ≥95% of pre-confirmed correct pairs must
    judge「确定」, and the 投资学(量化投资)↔投资学 counter-example must judge
    「存疑». Runs in the main session after producing verify_*_result.jsonl;
    see semantic-match/RUN_VERIFY.md.
    """
    pytest.skip(
        "golden regression runs in the main session after agent dispatch; "
        "see semantic-match/RUN_VERIFY.md"
    )
