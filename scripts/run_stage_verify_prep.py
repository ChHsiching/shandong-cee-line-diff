"""Slice B orchestration (coverage-exempt) — extract judgmental matches into
verification batches.

Per Plan v2 Slice B: drives the deterministic pipeline chain to recover the
current ``main_results``, filters the judgmental matches (coarse 核心名唯一/
消歧 + agent 语义 matched, per V5-0), and writes ``semantic-match/
verify_batch_NN.json`` (20/batch) for harness-side agent dispatch.

This mirrors :mod:`scripts.run_stage2_prep`: pure orchestration, no pipeline
feature — hence coverage-exempt (see ``.coveragerc``). Expected full-scale
count ~5500 (coarse ~4775 + agent semantic ~763) → ~275 batches.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from scripts.models import HistoryRow
from scripts.run_pipeline import run
from scripts.verify_judgment import build_verify_batches, write_verify_prompts

logger = logging.getLogger(__name__)

BATCH_SIZE = 20


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_stage_verify_prep",
        description="Extract judgmental matches into verify batches (V5-0).",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"),
        help="Directory holding the three source xlsx (default: data)",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("output"),
        help="Directory for final xlsx outputs (default: output)",
    )
    parser.add_argument(
        "--semantic-dir", type=Path, default=Path("semantic-match"),
        help="Directory for agent prompts/results (default: semantic-match)",
    )
    parser.add_argument(
        "--no-agent-results", action="store_true",
        help="Do not apply batch_*_result.jsonl when extracting judgmental "
             "matches (use the strict+coarse-only口径).",
    )
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
    )

    main_results = report["main_results"]
    dagluben_rows = report["dagluben_rows"]
    # History lives in the intermediate CSV; re-run build_unified_history from
    # the same source to avoid coupling to CSV layout. For prompt generation we
    # only need candidate identification — pass dagluben as the row source.
    # build_verify_batches needs history to locate matched candidates; we read
    # it from the intermediate unified-history CSV that run() already wrote.
    import csv

    hist_csv = Path("intermediate") / "s2_unified_history.csv"
    history: list[HistoryRow] = []
    if hist_csv.exists():
        with hist_csv.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                history.append(_coerce_history(row))

    # Filter judgmental matches (V5-0): coarse + agent-semantic matched rows.
    judgmental = [r for r in main_results if _is_judgmental(r)]

    batches = build_verify_batches(judgmental, dagluben_rows, history, batch_size=BATCH_SIZE)
    # Clear stale verify_batch_*.json so a re-run does not leave orphans.
    for stale in sorted(args.semantic_dir.glob("verify_batch_*.json")):
        stale.unlink()
    paths = write_verify_prompts(batches, args.semantic_dir)

    # Report by prior-stage来源.
    coarse_n = sum(1 for r in judgmental if r.get("log", "").startswith("粗筛"))
    semantic_n = sum(1 for r in judgmental if r.get("log", "").startswith("语义匹配"))
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
    dependency in this exempt orchestration script)."""
    if not match.get("matched"):
        return False
    log = match.get("log", "")
    return log.startswith("粗筛") or log.startswith("语义匹配")


def _coerce_history(row: dict) -> HistoryRow:
    """Coerce a CSV dict row into a typed HistoryRow (J/T → float|None)."""
    def _num(v: str) -> float | None:
        if v is None or v.strip() == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None

    return HistoryRow(
        school=row.get("school", ""),
        school_cat=row.get("school_cat", ""),
        major=row.get("major", ""),
        stripped=row.get("stripped", ""),
        core=row.get("core", ""),
        subject=row.get("subject", ""),
        J=_num(row.get("J", "")),
        T=_num(row.get("T", "")),
        source_table=row.get("source_table", ""),
    )


if __name__ == "__main__":
    raise SystemExit(main())
