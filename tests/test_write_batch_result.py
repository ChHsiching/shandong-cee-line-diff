"""TDD for write_batch_result helper — eliminates agent hand-written JSON.

痛点（fresh-test handoff 2026-07-08）：agent 手写 ``batch_NN_result.jsonl`` 易出
JSON 转义错（专业名含英文双引号，如「法学类(...)(含"法学+英语"...)」）+ 弯引号
逐字复制坑 + J/T 编造坑。本 helper 让 agent 只提供「每条选了第几个候选 / null +
一句理由」，由 helper 读 prompt 反填 match/J/T/school/major 并 ``json.dumps`` 出
合法 jsonl——agent 端零手写 JSON。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.write_batch_result import (
    DecisionsError,
    build_results,
    build_verify_results,
    parse_decisions_tsv,
    parse_verify_decisions_tsv,
    write_results_jsonl,
)


def _prompt() -> dict:
    return {
        "batch": 1,
        "items": [
            {
                "src_row_idx": 1,
                "school": "甲大学",
                "school_cat": "",
                "major": "计算机类(图灵)",
                "core": "计算机类",
                "subject": "物理和化学",
                "batch": "4.常规批",
                "candidates": [
                    {"major": "计算机类", "core": "计算机类", "J": 80.0, "T": 1.0},
                    {"major": '计算机类(含"AI"方向)', "core": "计算机类", "J": 78.0, "T": 0.9},
                ],
            },
            {
                "src_row_idx": 2,
                "school": "乙大学",
                "school_cat": "",
                "major": "新专业",
                "core": "新专业",
                "subject": "物理",
                "batch": "4.常规批",
                "candidates": [],
            },
        ],
        "output_schema": {"description": "...", "required_keys": []},
        "matching_rule": "...",
    }


def test_build_results_fills_match_jt_from_prompt_candidates() -> None:
    """agent 只给 cand index + reason；helper 反填 match(候选 major 逐字) + J/T。"""
    decisions = {
        1: {"cand": 1, "reason": "方向对齐"},  # 选第 2 个候选（含英文双引号的 major）
        2: {"cand": None, "reason": "无候选"},
    }
    results = build_results(_prompt(), decisions)
    assert results[0] == {
        "src_row_idx": 1,
        "school": "甲大学",
        "major": "计算机类(图灵)",
        "match": '计算机类(含"AI"方向)',  # 逐字来自 prompt，agent 没抄字符串
        "J": 78.0,
        "T": 0.9,
        "reason": "方向对齐",
    }
    assert results[1]["match"] is None
    assert results[1]["J"] is None and results[1]["T"] is None
    assert results[1]["reason"] == "无候选"


def test_build_results_rejects_out_of_range_candidate() -> None:
    """cand index 越界 → 立即抛错（在写 jsonl 前截住，不在 apply 时才炸）。"""
    with pytest.raises(DecisionsError):
        build_results(_prompt(), {1: {"cand": 5, "reason": "x"}})


def test_build_results_rejects_missing_decision() -> None:
    """每条 item 都要有 decision（防 agent 漏判）。"""
    with pytest.raises(DecisionsError):
        build_results(_prompt(), {1: {"cand": 0, "reason": "x"}})  # 漏了 item 2


def test_parse_decisions_tsv_handles_null_and_reason() -> None:
    """TSV: src_row_idx<TAB>cand(或 -) <TAB>reason。cand=-/空 → null。"""
    tsv = "1\t0\t核心名同\n2\t-\t无候选\n3\t\tx\n"
    dec = parse_decisions_tsv(tsv)
    assert dec == {
        1: {"cand": 0, "reason": "核心名同"},
        2: {"cand": None, "reason": "无候选"},
        3: {"cand": None, "reason": "x"},
    }


def test_write_results_jsonl_produces_valid_json_passing_stage2_contract(
    tmp_path: Path,
) -> None:
    """写出的 jsonl 每行合法 JSON + match 逐字等于候选 major + J/T echo 一致。
    含英文双引号的 major 也能正确转义（核心痛点）。"""
    decisions = {1: {"cand": 1, "reason": "ok"}, 2: {"cand": None, "reason": "无"}}
    results = build_results(_prompt(), decisions)
    out = tmp_path / "batch_01_result.jsonl"
    write_results_jsonl(results, out)

    lines = out.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    obj = json.loads(lines[0])  # 含双引号的 major 也能 json.loads 成功
    assert obj["match"] == '计算机类(含"AI"方向)'
    assert obj["J"] == 78.0  # echo 候选 J，没编造


def test_build_verify_results_formats_verdict_reason() -> None:
    """verify: agent 给 verdict + reason，helper 输出 {src_row_idx,verdict,reason}。"""
    items = [{"src_row_idx": 1}, {"src_row_idx": 2}]
    decisions = {1: {"verdict": "确定", "reason": "同名"}, 2: {"verdict": "存疑", "reason": "方向不同"}}
    results = build_verify_results(items, decisions)
    assert results[0] == {"src_row_idx": 1, "verdict": "确定", "reason": "同名"}
    assert results[1]["verdict"] == "存疑"


def test_build_verify_results_rejects_bad_verdict() -> None:
    with pytest.raises(DecisionsError):
        build_verify_results([{"src_row_idx": 1}], {1: {"verdict": "可能", "reason": "x"}})


def test_parse_verify_decisions_tsv() -> None:
    tsv = "1\t确定\t同名\n2\t存疑\t方向不同\n"
    dec = parse_verify_decisions_tsv(tsv)
    assert dec == {
        1: {"verdict": "确定", "reason": "同名"},
        2: {"verdict": "存疑", "reason": "方向不同"},
    }
