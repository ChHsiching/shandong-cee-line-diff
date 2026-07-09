"""Slice B orchestration (coverage-exempt) — extract judgmental matches into
verification batches.

Drives the deterministic pipeline chain to recover the current
``main_results``, filters the judgmental matches (agent 语义 matched, per
V5-0), and writes ``semantic-match/verify_batch_NN.json`` (20/batch) for
harness-side agent dispatch. Pure orchestration, no pipeline feature — hence
coverage-exempt (see ``.coveragerc``).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scripts.constants import LOG_COARSE_CANDIDATE, LOG_SEMANTIC_PREFIX
from scripts.run_pipeline import add_source_files_args, parse_source_files_args, run
from scripts.verify_judgment import build_verify_batches, write_verify_prompts

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_stage_verify_prep",
        description="Extract judgmental matches into verify batches (V5-0).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory holding the three source xlsx (default: data)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output"),
        help="Directory for final xlsx outputs (default: output)",
    )
    parser.add_argument(
        "--semantic-dir",
        type=Path,
        default=Path("semantic-match"),
        help="Directory for agent prompts/results (default: semantic-match)",
    )
    parser.add_argument(
        "--no-agent-results",
        action="store_true",
        help="Do not apply batch_*_result.jsonl when extracting judgmental "
        "matches (use the strict+coarse-only口径).",
    )
    # 与 run_pipeline 同一组数据源参数（BUG-2: 此前一个都不转发，导致 verify
    # prep 用默认一段线/文件名，与最终产出不一致）。
    add_source_files_args(parser)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Run the deterministic chain to recover main_results. Apply existing
    # Stage2 agent results (if any) so semantic matches are included in the
    # judgmental set. Verify result jsonl, if present, would demote rows — we
    # deliberately do NOT apply it here so the prep reflects pre-verify state.
    report = run(
        args.data_dir,
        args.out_dir,
        with_agent_results=not args.no_agent_results,
        semantic_dir=args.semantic_dir,
        **parse_source_files_args(args),
    )

    main_results = report["main_results"]
    dagluben_rows = report["dagluben_rows"]
    # build_verify_batches needs history to locate matched candidates; run()
    # returns it directly (Bug #2 fix — was reading a CSV that nobody writes).
    history = report.get("history", [])

    # Filter judgmental matches (V5-0): coarse + agent-semantic matched rows.
    judgmental = [r for r in main_results if _is_judgmental(r)]

    batches = build_verify_batches(
        judgmental, dagluben_rows, history, batch_size=BATCH_SIZE
    )
    # Clear stale verify_batch_*.json so a re-run does not leave orphans.
    for stale in sorted(args.semantic_dir.glob("verify_batch_*.json")):
        stale.unlink()
    paths = write_verify_prompts(batches, args.semantic_dir)

    # Report by prior-stage来源.
    coarse_n = sum(
        1 for r in judgmental if r.get("log", "").startswith(LOG_COARSE_CANDIDATE)
    )
    semantic_n = sum(
        1 for r in judgmental if r.get("log", "").startswith(LOG_SEMANTIC_PREFIX)
    )
    print("=== 判断型二次复核 prep 完成 ===")
    print(f"判断型匹配总数: {len(judgmental)}")
    print(f"  粗筛(核心名唯一/消歧): {coarse_n}")
    print(f"  语义匹配(agent):      {semantic_n}")
    print(f"切批 (20/批): {len(paths)} 批 → semantic-match/verify_batch_NN.json")
    print("下一步: 按 semantic-match/RUN_VERIFY.md 派发复核 agent。")
    return 0


def _is_judgmental(match: dict) -> bool:
    """Inline V5-0 judgmental filter (mirrors verify_judgment.is_judgmental
    but operates on the dict-shaped main_results row to avoid a cross-module
    dependency in this exempt orchestration script).

    只算 agent 语义匹配（LOG_SEMANTIC_PREFIX）。Stage 1.5 past=1 粗筛匹配
    （LOG_COARSE_CANDIDATE）是构造确定（往年同核心只 1 个→直接配），豁免复核。"""
    if not match.get("matched"):
        return False
    log = match.get("log", "")
    return log.startswith(LOG_SEMANTIC_PREFIX)


if __name__ == "__main__":
    raise SystemExit(main())
