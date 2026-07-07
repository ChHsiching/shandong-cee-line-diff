"""Slice 7 — end-to-end pipeline runner.

Threads the **deterministic** stages of the admission-data pipeline (spec §6,
Plan v2 Slice 7 / issue #8):

    Stage 0  build_unified_history + build_dagluben (常规批 + 提前批, 专科 excluded)
       ↓
    Stage 1  match_strict                       (严格 3-tuple)
       ↓
    Stage 2  (agent — harness-side)
       - if semantic-match/batch_*_result.jsonl exist → apply_results
       - else → emit batch_NN_prompt.json + log「Stage2 待 harness 派发」
       ↓
    Stage 3  identify_new_majors + estimate + write_new_major_table
       ↓
    Stage 3  edges:
       - rename: if semantic-match/rename_result.jsonl exists → apply_rename
                 else → empty renamed set + log「改名 待 harness 派发」
       - deleted_majors (uses the confirmed renamed set to exclude)
       - flight_and_special (FLIGHT_BATCH unmatched + remaining unmatched)
       ↓
    write_outputs  (hierarchical + flat — same MatchResult source)
    write_edge_tables (被删/新增校/停招消失校/特殊/改名)

The agent (Stage 2 semantic, Stage 3 rename pairing) and WebSearch (rename
remarks) are **harness-side steps** — Python cannot invoke the Agent/WebSearch
tools. This module therefore treats them as optional: when their result jsonls
are absent, the run still succeeds end-to-end and emits the prompts + candidates
the harness needs to dispatch them.

Pure function: :func:`run` returns a structured report dict and writes all
artefacts under ``out_dir`` / ``semantic_dir`` / ``intermediate_dir``. The three
source files are guarded by :func:`io_source.assert_unchanged` before and after.
"""

from __future__ import annotations

import argparse
import collections
import logging
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from scripts import io_source
from scripts.constants import FLIGHT_BATCH, J3_SHEET
from scripts.models import DaglubenRow, EstimateResult, HistoryRow, MatchResult
from scripts.rename_detect import (
    apply_rename,
    prep_rename_candidates,
    write_rename_prompt,
)
from scripts.stage0_merge import (
    build_dagluben_early,
    build_dagluben_regular,
    build_unified_history,
)
from scripts.stage1_strict import match_strict
from scripts.stage2_agent import build_batches, write_prompts
from scripts.stage2_apply import apply_results
from scripts.stage3_edges import deleted_majors, flight_and_special
from scripts.stage3_newmajor import estimate
from scripts.write_edge_tables import (
    identify_new_majors,
    write_deleted_major_table,
    write_gone_school_table,
    write_new_major_table,
    write_new_school_table,
    write_rename_table,
    write_special_table,
)
from scripts.write_outputs import write_flat, write_hierarchical

__all__ = ["run", "main", "SOURCE_FILES", "PipelineReport"]

logger = logging.getLogger(__name__)

# Repository layout — the three source filenames are fixed (spec §2 / CLAUDE.md).
SOURCE_FILES: dict[str, str] = {
    "j3": "近三年学校批次专业线差统计.xlsx",
    "tq": "山东省高考提前批录取数据.xlsx",
    "dl": "山东省2026年大绿本招生计划.xlsx",
}

# Typed alias for the structured report returned by :func:`run`. Kept as a
# plain dict (not TypedDict) because the report is a test/debug surface, not a
# stable inter-module contract.
PipelineReport = dict[str, Any]


def _load_rows(path: Path, sheet_name: str | None = None):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet_name] if sheet_name else wb.active
    try:
        return list(ws.iter_rows(values_only=True))
    finally:
        wb.close()


def _guard_sources(data_dir: Path) -> dict[str, str]:
    """Hash every source before the run; return the baseline map."""
    hashes: dict[str, str] = {}
    for key, name in SOURCE_FILES.items():
        p = data_dir / name
        h = io_source.sha256(p)
        hashes[name] = h
        io_source.assert_unchanged(p, h)
    return hashes


def _apply_stage2(
    post_coarse_unmatched: list[DaglubenRow],
    history: list[HistoryRow],
    semantic_dir: Path,
    with_agent_results: bool,
) -> tuple[list[MatchResult], list[DaglubenRow], bool]:
    """Stage 2 — apply agent jsonl if present, else emit prompts + log.

    Returns ``(semantic_results, still_unmatched, applied)``:
      - ``semantic_results``: MatchResult rows produced by the agent (empty if
        no jsonl was applied).
      - ``still_unmatched``: dagluben rows the agent did NOT resolve (input to
        Stage 3 new-major / edges). When no jsonl is applied this equals the
        full ``post_coarse_unmatched`` list.
      - ``applied``: True iff at least one result line was read and applied.
    """
    semantic_dir.mkdir(parents=True, exist_ok=True)

    if not post_coarse_unmatched:
        # Nothing for the agent to do; still emit no prompts, no apply.
        logger.info("Stage2: Stage 1.5 后无剩余未匹配行，无需 agent 派发")
        return [], [], False

    result_paths = sorted(semantic_dir.glob("batch_*_result.jsonl"))
    if with_agent_results and result_paths:
        applied_results = apply_results(result_paths, post_coarse_unmatched, history)
        resolved_idx = {r["src_row_idx"] for r in applied_results if r.get("matched")}
        still = [
            d
            for d in post_coarse_unmatched
            if d["src_row_idx"] not in resolved_idx
            and not any(
                r["src_row_idx"] == d["src_row_idx"] and r.get("matched")
                for r in applied_results
            )
        ]
        logger.info(
            "Stage2: 已应用 %d 条 agent 结果（%d 条命中，%d 条仍未匹配）",
            len(applied_results),
            len(resolved_idx),
            len(still),
        )
        return applied_results, still, True

    # No results to apply → emit batch prompts for harness dispatch.
    batches = build_batches(post_coarse_unmatched, history, batch_size=20)
    write_prompts(batches, semantic_dir)
    logger.info(
        "Stage2: 未发现 batch_*_result.jsonl，已写出 %d 个批次 prompt；"
        "Stage2 待 harness 派发（见 semantic-match/RUN.md）",
        len(batches),
    )
    return [], list(post_coarse_unmatched), False


def _apply_rename(
    dagluben: list[DaglubenRow],
    history: list[HistoryRow],
    semantic_dir: Path,
    with_agent_results: bool,
) -> tuple[list, set[str], bool]:
    """Rename agent step — apply rename_result.jsonl if present.

    Returns ``(rename_rows, renamed_dgl_schools, applied)``. When no jsonl is
    present, emits rename candidates + prompt and returns an empty renamed set
    (so被删 uses the upper bound — true被删 ⊆ the reported count after the
    agent excludes改名校).
    """
    semantic_dir.mkdir(parents=True, exist_ok=True)
    dgl_schools = sorted({d["school"] for d in dagluben if d.get("school")})
    hist_schools = sorted({h["school"] for h in history if h.get("school")})

    candidates = prep_rename_candidates(dgl_schools, hist_schools, topk=0)
    write_rename_prompt(candidates, semantic_dir)

    rename_path = semantic_dir / "rename_result.jsonl"
    if with_agent_results and rename_path.exists():
        rename_rows, confirmed = apply_rename([rename_path], dagluben, history)
        logger.info("改名: 已应用 rename_result.jsonl（%d 所改名校）", len(confirmed))
        return rename_rows, confirmed, True

    logger.info(
        "改名: 未发现 rename_result.jsonl（候选 %d 所）；改名 待 harness 派发"
        "（见 research/RUN_RENAME.md）",
        len(candidates),
    )
    return [], set(), False


def _research_summary(text: str, school: str) -> str:
    """Concise remark from a research/<school>.md note (Task 6.3 websearch).

    Prefer the richest conclusion line (判定 段: 前身/更名/原名/...), skipping
    query-statement and source-URL lines that also contain those keywords."""
    skip = ("查询语句", "来源URL", "来源", "查询")
    concl = ("前身", "更名", "原名", "转设", "合并", "升格", "揭牌", "教育部", "由")
    cands = []
    for line in text.splitlines():
        s = line.strip().lstrip("-").lstrip("#").strip()
        if not s or any(k in s[:8] for k in skip):
            continue
        if any(k in s for k in concl):
            cands.append(s)
    if cands:
        return max(cands, key=len)[:100]
    for line in text.splitlines():
        s = line.strip().lstrip("-").lstrip("#").strip()
        if s and not any(k in s[:8] for k in skip):
            return s[:100]
    return f"（见 research/{school}.md）"


def _enrich_rename_rows(
    rename_rows: list,
    dagluben: list,
    research_dir: str = "research",
) -> None:
    """Populate ``major_count_2026`` + websearch ``remark`` on rename rows
    (spec §6 Task 6.3) before the学校改名表 is written. apply_rename returns
    RenameRows without these fields."""
    cnt = collections.Counter(d.get("school", "") for d in dagluben if d.get("school"))
    rdir = Path(research_dir)
    for r in rename_rows:
        ns = r.get("new_school", "")
        r["major_count_2026"] = cnt.get(ns, 0)
        md = rdir / f"{ns}.md"
        if md.exists():
            r["remark"] = _research_summary(md.read_text(encoding="utf-8"), ns)
        else:
            r.setdefault("remark", f"（见 research/{ns}.md）")


def _build_main_results(
    dagluben: list[DaglubenRow],
    strict_results: list[MatchResult],
    coarse_results: list[MatchResult],
    semantic_results: list[MatchResult],
    new_major_estimates: dict[int, EstimateResult],
    renamed_dgl_schools: set[str],
    *,
    classified_idx: set[int] | None = None,
) -> list[MatchResult]:
    """Assemble the final per-row MatchResult list, one entry per大绿本 row.

    Resolution order (first matched wins per src_row_idx): strict → coarse →
    semantic. Unmatched results never claim a slot. Rows that survived all
    matchers pick up the new-major estimate (if any) or the rename-pending
    marker (if their school is a confirmed rename).

    ``classified_idx`` (Plan v2 阻断2) optionally overrides the classified
    set — the V5-0 demote step shrinks it (drops存疑 idx) BEFORE this build so
    demoted rows fall naturally into the unmatched / special bucket. When
    ``None`` it is derived from the matched results as usual.
    """
    by_idx: dict[int, MatchResult] = {}

    # When the V5-0 demote step passes an explicit classified set, only
    # classified idx may claim a matched slot (存疑 idx were stripped upstream
    # and must fall through to the unmatched bucket).
    allowed = classified_idx

    for r in strict_results:
        if r.get("matched") and (allowed is None or r["src_row_idx"] in allowed):
            by_idx.setdefault(r["src_row_idx"], r)
    for r in coarse_results:
        if r.get("matched") and (allowed is None or r["src_row_idx"] in allowed):
            by_idx.setdefault(r["src_row_idx"], r)
    for r in semantic_results:
        if r.get("matched") and (allowed is None or r["src_row_idx"] in allowed):
            by_idx.setdefault(r["src_row_idx"], r)

    # Remaining rows: new-major estimate or rename-pending marker.
    for d in dagluben:
        idx = d["src_row_idx"]
        if idx in by_idx:
            continue
        school = d.get("school", "")
        if school in renamed_dgl_schools:
            from scripts.constants import LOG_RENAME_PENDING

            by_idx[idx] = MatchResult(
                src_row_idx=idx,
                school=school,
                school_cat=d.get("school_cat", ""),
                major=d.get("major", ""),
                matched=False,
                J=None,
                T=None,
                log=LOG_RENAME_PENDING,
            )
            continue
        est = new_major_estimates.get(idx)
        if est is not None:
            by_idx[idx] = MatchResult(
                src_row_idx=idx,
                school=school,
                school_cat=d.get("school_cat", ""),
                major=d.get("major", ""),
                matched=False,
                J=est.get("value"),
                T=est.get("T"),
                log=est.get("log", ""),
            )
        else:
            # 特殊: 未匹配本科。spec 要求每行都有日志，兜底发特殊情况日志
            # （详情见 output/特殊情况.xlsx）。
            from scripts.constants import LOG_SPECIAL_UNMATCHED

            by_idx[idx] = MatchResult(
                src_row_idx=idx,
                school=school,
                school_cat=d.get("school_cat", ""),
                major=d.get("major", ""),
                matched=False,
                J=None,
                T=None,
                log=LOG_SPECIAL_UNMATCHED,
            )

    # Emit in dagluben order for stable downstream output. Every 本科 row now
    # carries a MatchResult (matched / 新增 / 改名 / 特殊), so no row is left
    # without a 匹配日志.
    return [by_idx[d["src_row_idx"]] for d in dagluben]


def run(
    data_dir: str | Path,
    out_dir: str | Path,
    *,
    with_agent_results: bool = False,
    semantic_dir: str | Path | None = None,
    intermediate_dir: str | Path | None = None,
) -> PipelineReport:
    """Run the deterministic admission-data pipeline end-to-end.

    Parameters
    ----------
    data_dir
        Directory holding the three source xlsx (see :data:`SOURCE_FILES`).
    out_dir
        Directory where the final xlsx outputs are written.
    with_agent_results
        When True, apply any ``semantic-match/batch_*_result.jsonl`` and
        ``semantic-match/rename_result.jsonl`` produced by the harness agent
        step. When False (default), the run emits prompts + candidates and
        logs that the agent step is pending.
    semantic_dir
        Where to read/write agent prompts/results. Defaults to ``<repo>/semantic-match``.
    intermediate_dir
        Where to write intermediate CSVs. Defaults to ``<repo>/intermediate``.

    Returns
    -------
    PipelineReport
        Structured dict with source hashes, dagluben row indices, main
        MatchResult list, edge buckets, new-major rows, coverage stats, and
        flags (stage2_applied / renamed_dgl_schools). See the field assignments
        below for the full shape.
    """
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    if semantic_dir is None:
        semantic_dir = data_dir.parent / "semantic-match"
    else:
        semantic_dir = Path(semantic_dir)
    if intermediate_dir is None:
        intermediate_dir = data_dir.parent / "intermediate"
    else:
        intermediate_dir = Path(intermediate_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    # --- Source immutability guard (before) ---------------------------------
    source_hashes = _guard_sources(data_dir)

    # --- Stage 0 ------------------------------------------------------------
    j3_rows = _load_rows(data_dir / SOURCE_FILES["j3"], J3_SHEET)
    tq_rows = _load_rows(data_dir / SOURCE_FILES["tq"])
    dl_rows = _load_rows(data_dir / SOURCE_FILES["dl"])

    history = build_unified_history(j3_rows, tq_rows)
    dagluben = [
        *build_dagluben_regular(dl_rows),
        *build_dagluben_early(dl_rows),
    ]
    dgl_indices = [d["src_row_idx"] for d in dagluben]
    logger.info(
        "Stage0: 统一历史 %d 行；大绿本本科专业 %d 行",
        len(history),
        len(dagluben),
    )

    # --- Stage 1 (strict) ---------------------------------------------------
    strict_results = match_strict(dagluben, history)
    strict_unmatched_dgl = [
        d for d, r in zip(dagluben, strict_results, strict=True) if not r.get("matched")
    ]
    logger.info(
        "Stage1: 严格匹配 %d/%d (%.1f%%)",
        sum(1 for r in strict_results if r.get("matched")),
        len(strict_results),
        100.0
        * sum(1 for r in strict_results if r.get("matched"))
        / max(1, len(strict_results)),
    )

    # --- Stage 1.5 已并入 Stage 2 ------------------------------------------
    # 程序模糊匹配（核心名粗筛自动接受）已停用：全部 strict 未匹配交由 Stage 2
    # agent 逐条语义判断。skill 规格＝只有「程序严格匹配 + agent 语义匹配」，
    # 不让程序做模糊决定（避免「临床医学5+3」式低级误判）。coarse_results 恒空，
    # 保留为占位以维持下游 _build_main_results 签名稳定（#18 清理时再删）。
    coarse_results: list[MatchResult] = []
    post_coarse_unmatched = strict_unmatched_dgl
    logger.info(
        "Stage1.5: 程序模糊匹配已停用，%d 条 strict 未匹配全部进 Stage2 agent",
        len(post_coarse_unmatched),
    )

    # --- Stage 2 (agent) ----------------------------------------------------
    semantic_results, post_stage2_unmatched, stage2_applied = _apply_stage2(
        post_coarse_unmatched,
        history,
        semantic_dir,
        with_agent_results,
    )

    # --- Stage 3 (new-major estimation) ------------------------------------
    new_majors = identify_new_majors(post_stage2_unmatched, history)
    by_school: dict[str, list[HistoryRow]] = collections.defaultdict(list)
    for h in history:
        by_school[h["school"]].append(h)

    new_major_estimates: dict[int, EstimateResult] = {}
    new_major_rows: list[dict[str, Any]] = []
    for d in new_majors:
        est = estimate(d, by_school.get(d["school"], []))
        new_major_estimates[d["src_row_idx"]] = est
        new_major_rows.append(
            {
                "src_row_idx": d["src_row_idx"],
                "school": d.get("school", ""),
                "major": d.get("major", ""),
                "subject": d.get("subject", ""),
                "value": est.get("value"),
                "T": est.get("T"),
                "level": est.get("level"),
                "n": est.get("n"),
                "log": est.get("log", ""),
            }
        )
    write_new_major_table(new_major_rows, out_dir / "新增专业.xlsx")
    logger.info("Stage3 新增专业: %d", len(new_majors))

    # --- Stage 3 (rename) --------------------------------------------------
    rename_rows, renamed_dgl_schools, rename_applied = _apply_rename(
        dagluben,
        history,
        semantic_dir,
        with_agent_results,
    )
    _enrich_rename_rows(rename_rows, dagluben)
    write_rename_table(rename_rows, out_dir / "学校改名表.xlsx")

    # --- Stage 3 (edges: deleted / flight / special) -----------------------
    dgl_present = {d["school"] for d in dagluben if d.get("school")}
    dgl_school_major = {(d.get("school", ""), d.get("major", "")) for d in dagluben}
    deleted_pool = deleted_majors(history, dgl_present, renamed_dgl_schools)
    true_deleted = [
        dm
        for dm in deleted_pool
        if (dm.get("school", ""), dm.get("major", "")) not in dgl_school_major
    ]
    write_deleted_major_table(true_deleted, out_dir / "被删旧专业.xlsx")

    # New-school / gone-school tables: 大绿本独有校 / 历史独有校 minus rename.
    major_count: dict[str, int] = collections.Counter(
        d.get("school", "") for d in dagluben if d.get("school")
    )
    hist_school_set = {h["school"] for h in history if h.get("school")}
    dgl_unique = [
        s for s in sorted(dgl_present - hist_school_set) if s not in renamed_dgl_schools
    ]
    # 改名旧校名从停招消失校表移出（它们是改名的旧名，不是真停招）。
    rename_old_schools = {
        r.get("old_school", "") for r in rename_rows if r.get("old_school")
    }
    hist_unique = [
        s for s in sorted(hist_school_set - dgl_present) if s not in rename_old_schools
    ]
    write_new_school_table(
        [{"new_school": s, "major_count_2026": major_count[s]} for s in dgl_unique],
        out_dir / "新增校表.xlsx",
    )
    write_gone_school_table(
        [{"old_school": s} for s in hist_unique],
        out_dir / "停招消失校表.xlsx",
    )

    # --- V5-0 second-pass verification apply (Plan v2 阻断2) ----------------
    # If verify_*_result.jsonl exists, apply verdicts BEFORE _build_main_results:
    # filter 存疑 idx out of coarse/semantic results + classified_idx so they
    # fall naturally into remaining_unmatched → special, carrying a
    # 「复核存疑：<原因>」 log (bypassing the generic fallback).
    verify_result_paths = sorted(semantic_dir.glob("verify_*_result.jsonl"))
    verdict_by_idx: dict[int, str] = {}
    demoted_map: dict[int, str] = {}
    coarse_for_main = coarse_results
    semantic_for_main = semantic_results
    classified_for_main: set[int] | None = None
    verify_applied = False
    if with_agent_results and verify_result_paths:
        from scripts.verify_judgment import apply_verify, filter_demoted

        judgmental = list(
            semantic_results
        )  # coarse 已停用，判断型匹配只剩 agent 语义匹配
        verify_out = apply_verify(verify_result_paths, dagluben, judgmental)
        verdict_by_idx = verify_out["verdict_by_idx"]
        # reasons map: pull the reason from the demoted EdgeRows (built by apply_verify).
        reasons = {
            e["src_row_idx"]: e["log"].split("：", 1)[1]
            if "：" in e.get("log", "")
            else ""
            for e in verify_out["demoted"]
        }
        # coarse 已停用（coarse_results 恒空）→ 无需 filter；coarse_for_main 保持空。
        coarse_for_main: list[MatchResult] = []
        semantic_for_main, _, _ = filter_demoted(
            semantic_results,
            set(),
            verdict_by_idx,
            reasons,
        )
        # Build the classified set from the filtered results (so存疑 idx drop).
        classified_for_main = (
            {r["src_row_idx"] for r in strict_results if r.get("matched")}
            | {r["src_row_idx"] for r in semantic_for_main if r.get("matched")}
            | {d["src_row_idx"] for d in new_majors}
            | {d["src_row_idx"] for d in dagluben if d["school"] in renamed_dgl_schools}
        )
        demoted_map = {
            idx: reasons.get(idx, "")
            for idx, v in verdict_by_idx.items()
            if v == "存疑"
        }
        verify_applied = True
        logger.info(
            "复核: 已应用 %d 条复核结果（%d 确定，%d 存疑→特殊）",
            len(verdict_by_idx),
            sum(1 for v in verdict_by_idx.values() if v == "确定"),
            len(demoted_map),
        )
    else:
        if verify_result_paths:
            logger.info(
                "复核: 检测到 verify_*_result.jsonl 但未启用 --with-agent-results，跳过 apply"
            )
        else:
            logger.info(
                "复核: 未发现 verify_*_result.jsonl，判断型复核 待 harness 派发"
                "（见 semantic-match/RUN_VERIFY.md）"
            )

    # Flight + remaining-unmatched → special.
    classified_idx = (
        classified_for_main
        if classified_for_main is not None
        else (
            {r["src_row_idx"] for r in strict_results if r.get("matched")}
            | {r["src_row_idx"] for r in semantic_results if r.get("matched")}
            | {d["src_row_idx"] for d in new_majors}
            | {d["src_row_idx"] for d in dagluben if d["school"] in renamed_dgl_schools}
        )
    )
    remaining_unmatched = [
        d for d in dagluben if d["src_row_idx"] not in classified_idx
    ]
    flight = [d for d in remaining_unmatched if d.get("batch") == FLIGHT_BATCH]
    other = [d for d in remaining_unmatched if d.get("batch") != FLIGHT_BATCH]
    special_rows = flight_and_special(flight, other, demoted_map=demoted_map)
    write_special_table(special_rows, out_dir / "特殊情况.xlsx")

    # --- Outputs (hierarchical + flat, same MatchResult source) ------------
    main_results = _build_main_results(
        dagluben,
        strict_results,
        coarse_for_main,
        semantic_for_main,
        new_major_estimates,
        renamed_dgl_schools,
        classified_idx=classified_for_main,
    )
    dl_path = data_dir / SOURCE_FILES["dl"]
    write_hierarchical(
        dl_path,
        main_results,
        out_dir / "大绿本_附线差_分层版.xlsx",
    )
    write_flat(
        dl_path,
        main_results,
        out_dir / "大绿本_附线差_扁平版.xlsx",
    )

    # --- Source immutability guard (after) ---------------------------------
    for name, h in source_hashes.items():
        io_source.assert_unchanged(data_dir / name, h)

    # --- Coverage report ---------------------------------------------------
    matched_n = sum(1 for r in main_results if r.get("matched"))
    coverage = {
        "total_dagluben": len(dagluben),
        "matched": matched_n,
        "new_major": len(new_majors),
        "special": len(special_rows),
        "deleted": len(true_deleted),
        "new_school": len(dgl_unique),
        "gone_school": len(hist_unique),
        "rename": len(renamed_dgl_schools),
    }

    logger.info(
        "覆盖率: 匹配 %d / 新增 %d / 特殊 %d / 被删 %d / 改名 %d （总 %d）",
        coverage["matched"],
        coverage["new_major"],
        coverage["special"],
        coverage["deleted"],
        coverage["rename"],
        coverage["total_dagluben"],
    )

    return {
        "source_hashes": source_hashes,
        "dagluben_indices": dgl_indices,
        "dagluben_rows": dagluben,
        "main_results": main_results,
        "new_major_rows": new_major_rows,
        "post_coarse_unmatched_indices": [
            d["src_row_idx"] for d in post_coarse_unmatched
        ],
        "edge": {
            "deleted": true_deleted,
            "special": special_rows,
            "new_school": dgl_unique,
            "gone_school": hist_unique,
            "rename": rename_rows,
        },
        "coverage": coverage,
        "stage2_applied": stage2_applied,
        "rename_applied": rename_applied,
        "verify_applied": verify_applied,
        "verdict_by_idx": verdict_by_idx,
        "demoted_map": demoted_map,
        "renamed_dgl_schools": renamed_dgl_schools,
    }


def main() -> None:
    """CLI entry: run the deterministic chain over the real data dir."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.run_pipeline",
        description="Run the deterministic admission-data pipeline end-to-end.",
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
        "--intermediate-dir",
        type=Path,
        default=Path("intermediate"),
        help="Directory for intermediate CSVs (default: intermediate)",
    )
    parser.add_argument(
        "--with-agent-results",
        action="store_true",
        help="Apply any batch_*_result.jsonl / rename_result.jsonl present in "
        "semantic-dir. Without this flag, prompts are emitted and the "
        "agent step is logged as pending harness dispatch.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report = run(
        args.data_dir,
        args.out_dir,
        with_agent_results=args.with_agent_results,
        semantic_dir=args.semantic_dir,
        intermediate_dir=args.intermediate_dir,
    )

    cov = report["coverage"]
    semantic_suffix = "+语义" if report["stage2_applied"] else ""
    print("=== 管线确定性链完成 ===")
    print(f"大绿本本科专业总数: {cov['total_dagluben']}")
    print(f"  严格匹配{semantic_suffix}: {cov['matched']}")
    print(f"  新增专业(估算):     {cov['new_major']}")
    print(f"  特殊情况:           {cov['special']}")
    print(f"  被删旧专业:         {cov['deleted']}")
    print(f"  新增校:             {cov['new_school']}")
    print(f"  停招消失校:         {cov['gone_school']}")
    print(f"  改名校:             {cov['rename']}")
    if not report["stage2_applied"]:
        print()
        print("注: 未应用 Stage2 agent 结果（语义匹配待 harness 派发，")
        print("    见 semantic-match/RUN.md）。匹配置为严格匹配口径。")
    if not report["rename_applied"]:
        print("注: 未应用改名 agent 结果（改名配对待 harness 派发，")
        print("    见 research/RUN_RENAME.md）。被删/新增校为上界。")


if __name__ == "__main__":
    main()
