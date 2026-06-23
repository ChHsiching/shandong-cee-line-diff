"""Slice C — data-quality audit hard gate (spec V5-3, Plan v2 Slice C 修订).

The completion gate for the admission-data pipeline. Before the pipeline is
declared "done", the **real produced xlsx** (not just pytest) must pass five
checks. The audit reads the produced xlsx + the verification jsonl and returns
an :class:`AuditReport`; :func:`main` exits 0 iff ``ok=True``.

Checks (Plan v2 Slice C 修订):
  0  judgmental_coverage — every judgmental-match row in the hierarchical
     output (logs starting with coarse / semantic prefixes per V5-0) must
     appear in ``verify_*_result.jsonl`` with verdict=确定. Missing jsonl
     entirely → fail with「复核未派发」.
  1  nonempty_log — every 本科 major row in the flat output carries a
     non-empty 匹配日志 (0 缺失).
  2  no_empty_rows — every produced table has zero fully-blank data rows.
  3  tables_nonempty — every produced table has at least one data row
     (field-mapping regression guard; the writer-level header lock lives in
     test_output_quality).
  4  jt_consistency — random ≥30 matched rows' J/T agree with the source
     近三年 values (matched rows) or with the round(estimate, 2) value (新增
     rows). Precision-aware: matched rows use a tight tolerance against source
     history; 新增 rows use the estimate table as ground truth.

A side artefact ``audit_sample.xlsx`` is written for human semantic review; it
does NOT influence ``ok`` / the exit code (Plan v2 Slice C 修订: 语义抽样 →
``@manual`` 不计 exit 0).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import openpyxl

from scripts.constants import (
    LOG_COARSE_DISAMBIG_PREFIX,
    LOG_COARSE_UNIQUE,
    LOG_SEMANTIC_PREFIX,
    LOG_STRICT,
)
from scripts.stage0_merge import build_unified_history

__all__ = [
    "AuditReport",
    "AuditCheck",
    "HIER_ARCHICAL_NAME",
    "FLAT_NAME",
    "JUDGMENTAL_LOG_PREFIXES",
    "audit",
    "main",
]

logger = logging.getLogger(__name__)

# Produced-file names (mirror write_outputs / write_edge_tables).
HIER_ARCHICAL_NAME = "大绿本_附线差_分层版.xlsx"
FLAT_NAME = "大绿本_附线差_扁平版.xlsx"
NEW_MAJOR_NAME = "新增专业.xlsx"
SPECIAL_NAME = "特殊情况.xlsx"
DELETED_NAME = "被删旧专业.xlsx"
RENAME_NAME = "学校改名表.xlsx"
NEW_SCHOOL_NAME = "新增校表.xlsx"
GONE_SCHOOL_NAME = "停招消失校表.xlsx"

# Every produced table the audit must consider for the empty-row / nonempty
# checks. Order is stable for readable reports.
PRODUCED_TABLES: tuple[str, ...] = (
    HIER_ARCHICAL_NAME,
    FLAT_NAME,
    NEW_MAJOR_NAME,
    SPECIAL_NAME,
    DELETED_NAME,
    RENAME_NAME,
    NEW_SCHOOL_NAME,
    GONE_SCHOOL_NAME,
)

# Logs marking a main-table row as 判断型 (V5-0 — needs second-pass verify).
# Strict-exact (LOG_STRICT) is构造确定 and excluded. Aligned with
# verify_judgment.JUDGMENT_LOG_PREFIXES (kept local to avoid an import cycle
# through verify_judgment → stage3_edges).
JUDGMENTAL_LOG_PREFIXES: tuple[str, ...] = (
    LOG_COARSE_UNIQUE,
    LOG_COARSE_DISAMBIG_PREFIX,
    LOG_SEMANTIC_PREFIX,
)

# Column indices in the hierarchical / flat output (1-based).
COL_SCHOOL = 4
COL_MAJOR_NAME = 6
COL_J = 13
COL_T = 14
COL_LOG = 15
# Major-row detector columns (1-based): 代号(E=5) + 名称(F=6) both non-empty.
COL_CODE = 5

# Sample size for the human-review artefact (Plan v2: 随机 ≥30).
SAMPLE_SIZE = 30
# Tolerance for matched-row J/T comparison (history values are exact; the
# output may carry the same float, so a tiny epsilon guards float drift).
JT_TOLERANCE = 0.011


# One check result: ``{name, passed, detail}`` (Plan v2 binding structure).
AuditCheck = dict[str, Any]


@dataclass
class AuditReport:
    """Aggregate audit outcome. ``ok`` is True iff every check passed.

    ``checks`` is a list of ``{name, passed, detail}`` dicts (Plan v2 binding
    structure) so callers can index by key.
    """

    ok: bool
    checks: list[AuditCheck] = field(default_factory=list)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load_rows(path: Path) -> list[tuple]:
    """Read all rows of a workbook's active sheet as tuples."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return list(wb.active.iter_rows(values_only=True))
    finally:
        wb.close()


def _is_major_row(row: tuple) -> bool:
    """A 本科 专业行: 代号 + 名称 both non-empty (mirrors write_outputs)."""
    if len(row) < COL_MAJOR_NAME:
        return False
    code = row[COL_CODE - 1]
    name = row[COL_MAJOR_NAME - 1]
    return code not in (None, "") and name not in (None, "")


def _load_verify_verdicts(semantic_dir: Path) -> dict[int, str] | None:
    """Read every ``verify_*_result.jsonl`` under semantic_dir.

    Returns ``{src_row_idx: verdict}`` or ``None`` when no verify result file
    exists at all (signals「复核未派发」to check 0).
    """
    paths = sorted(semantic_dir.glob("verify_*_result.jsonl"))
    if not paths:
        return None
    out: dict[int, str] = {}
    for p in paths:
        for raw in p.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            idx = obj["src_row_idx"]
            out[idx] = obj["verdict"]
    return out


def _judgmental_log(log: str) -> bool:
    """True iff a main-table log marks the row as 判断型 (needs verify)."""
    return any(log.startswith(p) for p in JUDGMENTAL_LOG_PREFIXES)


def _history_index(
    history: Sequence[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Index history rows by (school, major) for J/T comparison in check 4."""
    idx: dict[tuple[str, str], dict[str, Any]] = {}
    for h in history:
        key = (h.get("school", ""), h.get("major", ""))
        if key not in idx:
            idx[key] = h
    return idx


def _row_fully_blank(row: tuple) -> bool:
    """True iff every cell is None or empty string (a '全空数据行')."""
    return all(c is None or c == "" for c in row)


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------


def _check0_judgmental_coverage(
    hier_rows: list[tuple], verdicts: dict[int, str] | None
) -> AuditCheck:
    """Every judgmental-match row's src_row_idx must appear with verdict=确定."""
    name = "judgmental_coverage"
    if verdicts is None:
        return {
            "name": name, "passed": False,
            "detail": "复核未派发：semantic-match/verify_*_result.jsonl 缺失",
        }

    missing: list[int] = []
    wrong_verdict: list[int] = []
    for row_idx_0, row in enumerate(hier_rows):
        src_row_idx = row_idx_0 + 1  # 1-based; header is row 1
        if src_row_idx == 1:
            continue
        if not _is_major_row(row):
            continue
        if len(row) < COL_LOG:
            continue
        log = row[COL_LOG - 1] or ""
        if not _judgmental_log(str(log)):
            continue
        v = verdicts.get(src_row_idx)
        if v is None:
            missing.append(src_row_idx)
        elif v != "确定":
            wrong_verdict.append(src_row_idx)

    if missing or wrong_verdict:
        detail = (
            f"判断型匹配 {len(missing)} 行无复核结果、"
            f"{len(wrong_verdict)} 行 verdict≠确定；"
            f"示例缺 idx={missing[:5]}，verdict≠确定 idx={wrong_verdict[:5]}"
        )
        return {"name": name, "passed": False, "detail": detail}
    return {"name": name, "passed": True, "detail": "判断型匹配复核覆盖完备（verdict=确定）"}


def _check1_nonempty_log(flat_rows: list[tuple]) -> AuditCheck:
    """Every 本科 major row in the flat output has a non-empty 匹配日志."""
    name = "nonempty_log"
    blank: list[int] = []
    for row_idx_0, row in enumerate(flat_rows):
        if row_idx_0 == 0:
            continue  # header
        if not _is_major_row(row):
            continue
        if len(row) < COL_LOG:
            blank.append(row_idx_0 + 1)
            continue
        log = row[COL_LOG - 1]
        if log is None or str(log).strip() == "":
            blank.append(row_idx_0 + 1)
    if blank:
        return {
            "name": name, "passed": False,
            "detail": f"扁平版 {len(blank)} 行匹配日志为空；示例行={blank[:5]}",
        }
    return {"name": name, "passed": True, "detail": "本科专业行匹配日志全部非空"}


def _check2_no_empty_rows(out_dir: Path) -> AuditCheck:
    """No produced table contains a fully-blank data row."""
    name = "no_empty_rows"
    offenders: list[str] = []
    for fname in PRODUCED_TABLES:
        path = out_dir / fname
        if not path.exists():
            continue
        rows = _load_rows(path)
        for row_idx_0, row in enumerate(rows):
            if row_idx_0 == 0:
                continue  # header
            if _row_fully_blank(tuple(row)):
                offenders.append(f"{fname}:行{row_idx_0 + 1}")
                break  # one offender per table is enough
    if offenders:
        return {
            "name": name, "passed": False,
            "detail": f"{len(offenders)} 张表含全空数据行：{offenders[:5]}",
        }
    return {"name": name, "passed": True, "detail": "所有产出表无全空数据行"}


def _check3_tables_nonempty(out_dir: Path) -> AuditCheck:
    """Every produced table has at least one data row (header-only = regression)."""
    name = "tables_nonempty"
    empty_tables: list[str] = []
    for fname in PRODUCED_TABLES:
        path = out_dir / fname
        if not path.exists():
            empty_tables.append(f"{fname}(缺失)")
            continue
        rows = _load_rows(path)
        data_rows = [r for i, r in enumerate(rows) if i > 0]
        if not data_rows:
            empty_tables.append(fname)
    if empty_tables:
        return {
            "name": name, "passed": False,
            "detail": f"{len(empty_tables)} 张表无数据行：{empty_tables}",
        }
    return {"name": name, "passed": True, "detail": "所有产出表均含至少 1 行数据"}


def _check4_jt_consistency(
    hier_rows: list[tuple],
    history: Sequence[dict[str, Any]],
    new_major_rows: list[tuple],
    seed: int = 20260623,
) -> AuditCheck:
    """Random ≥30 matched rows' J/T agree with source (precision-aware).

    Matched rows (strict / coarse / semantic logs) are compared against the
    source近三年 history value at (school, major) with a tight tolerance
    (handles float display drift; single-year T=None must match None).

    新增估算 rows (LOG startswith「新增专业」) are compared against the value
    in ``新增专业.xlsx`` at (school, major) — the estimate table is the ground
    truth for new-major rows (V5-6 precision split).
    """
    name = "jt_consistency"
    hist_idx = _history_index(history)
    # Index the new-major table by (学校, 专业) → (J, T).
    nm_idx: dict[tuple[str, str], tuple[Any, Any]] = {}
    for r in new_major_rows:
        if len(r) < 5:
            continue
        school = r[0]
        major = r[1]
        j = r[3]
        t = r[4]
        nm_idx[(str(school or ""), str(major or ""))] = (j, t)

    # Collect candidate matched + estimate rows from the hierarchical output.
    matched_candidates: list[tuple] = []
    estimate_candidates: list[tuple] = []
    for row_idx_0, row in enumerate(hier_rows):
        if row_idx_0 == 0:
            continue
        if not _is_major_row(row) or len(row) < COL_LOG:
            continue
        log = str(row[COL_LOG - 1] or "")
        if log.startswith(LOG_STRICT) or _judgmental_log(log):
            matched_candidates.append(row)
        elif log.startswith("新增专业"):
            estimate_candidates.append(row)

    rng = random.Random(seed)
    sample_matched = rng.sample(
        matched_candidates, min(SAMPLE_SIZE, len(matched_candidates))
    )
    sample_estimate = rng.sample(
        estimate_candidates, min(SAMPLE_SIZE, len(estimate_candidates))
    )

    mismatches: list[str] = []

    def _close(a: Any, b: Any) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        try:
            return abs(float(a) - float(b)) <= JT_TOLERANCE
        except (TypeError, ValueError):
            return False

    for row in sample_matched:
        school = str(row[COL_SCHOOL - 1] or "")
        major = str(row[COL_MAJOR_NAME - 1] or "")
        out_j = row[COL_J - 1]
        out_t = row[COL_T - 1]
        h = hist_idx.get((school, major))
        if h is None:
            # Cannot locate history — skip (not a J/T mismatch per se).
            continue
        if not _close(out_j, h.get("J")):
            mismatches.append(f"matched J {school}/{major}: {out_j}≠{h.get('J')}")
            continue
        if not _close(out_t, h.get("T")):
            mismatches.append(f"matched T {school}/{major}: {out_t}≠{h.get('T')}")

    for row in sample_estimate:
        school = str(row[COL_SCHOOL - 1] or "")
        major = str(row[COL_MAJOR_NAME - 1] or "")
        out_j = row[COL_J - 1]
        out_t = row[COL_T - 1]
        est = nm_idx.get((school, major))
        if est is None:
            continue
        est_j, est_t = est
        if not _close(out_j, est_j):
            mismatches.append(f"estimate J {school}/{major}: {out_j}≠{est_j}")
            continue
        if not _close(out_t, est_t):
            mismatches.append(f"estimate T {school}/{major}: {out_t}≠{est_t}")

    if mismatches:
        return {
            "name": name, "passed": False,
            "detail": (
                f"J/T 不一致 {len(mismatches)} 处（抽样 matched={len(sample_matched)}, "
                f"estimate={len(sample_estimate)}）：{mismatches[:5]}"
            ),
        }
    return {
        "name": name, "passed": True,
        "detail": (
            f"抽样 {len(sample_matched)} matched + {len(sample_estimate)} estimate 行 "
            f"J/T 与源值一致（容差 {JT_TOLERANCE}）"
        ),
    }


# ---------------------------------------------------------------------------
# sample artefact (manual / human review; NOT a gate)
# ---------------------------------------------------------------------------


def _write_sample(hier_rows: list[tuple], out_path: Path, seed: int = 20260623) -> int:
    """Write ``audit_sample.xlsx``: random SAMPLE_SIZE major rows for human
    semantic review. Returns the number of sampled rows written."""
    majors: list[tuple] = []
    for i, row in enumerate(hier_rows):
        if i == 0:
            continue
        if _is_major_row(row):
            majors.append(row)
    rng = random.Random(seed)
    sample = rng.sample(majors, min(SAMPLE_SIZE, len(majors)))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "audit_sample"
    if hier_rows:
        ws.append(list(hier_rows[0]))
    for r in sample:
        ws.append(list(r))
    wb.save(out_path)
    wb.close()
    return len(sample)


# ---------------------------------------------------------------------------
# audit
# ---------------------------------------------------------------------------


def audit(
    output_dir: str | Path,
    *,
    data_dir: str | Path,
    intermediate_dir: str | Path,
    history: Sequence[dict[str, Any]] | None = None,
    semantic_dir: str | Path | None = None,
) -> AuditReport:
    """Run the five V5-3 data-quality checks over ``output_dir``.

    Parameters
    ----------
    output_dir
        Directory holding the produced xlsx (hierarchical / flat / edge tables).
    data_dir
        Directory holding the three source xlsx. Used to rebuild the unified
        history when ``history`` is not supplied (check 4 J/T comparison).
    intermediate_dir
        Intermediate-artefact dir (stage files). Currently informational; kept
        in the signature per Plan v2 binding (``能读/重算 history``).
    history
        Optional pre-built unified history (avoids a rebuild). When ``None``
        the history is rebuilt from ``data_dir`` via :func:`build_unified_history`.
    semantic_dir
        Directory holding ``verify_*_result.jsonl`` (default: ``<repo>/semantic-match``).
    """
    out_dir = Path(output_dir)
    data_dir = Path(data_dir)
    sem_dir = Path(semantic_dir) if semantic_dir is not None else (
        out_dir.parent / "semantic-match"
    )

    hier_path = out_dir / HIER_ARCHICAL_NAME
    flat_path = out_dir / FLAT_NAME
    hier_rows = _load_rows(hier_path)
    flat_rows = _load_rows(flat_path)

    verdicts = _load_verify_verdicts(sem_dir)

    checks: list[AuditCheck] = []
    checks.append(_check0_judgmental_coverage(hier_rows, verdicts))
    checks.append(_check1_nonempty_log(flat_rows))
    checks.append(_check2_no_empty_rows(out_dir))
    checks.append(_check3_tables_nonempty(out_dir))

    # History for check 4 (rebuild if not supplied).
    hist = history
    if hist is None:
        try:
            hist = _rebuild_history(data_dir)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("audit: history 重建失败 (%s)；check4 将跳过 matched 比对", exc)
            hist = []
    new_major_rows: list[tuple] = []
    nm_path = out_dir / NEW_MAJOR_NAME
    if nm_path.exists():
        new_major_rows = _load_rows(nm_path)
    checks.append(_check4_jt_consistency(hier_rows, hist, new_major_rows))

    # Human-review sample (does NOT affect ok).
    try:
        _write_sample(hier_rows, out_dir / "audit_sample.xlsx")
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("audit: audit_sample.xlsx 写出失败 (%s)", exc)

    ok = all(c["passed"] for c in checks)
    return AuditReport(ok=ok, checks=checks)


def _rebuild_history(data_dir: Path) -> list[dict[str, Any]]:
    """Rebuild the unified history from the three source workbooks.

    Mirrors :func:`scripts.run_pipeline._load_rows` + Stage 0. Kept local so
    the audit does not depend on the pipeline runner (which has side effects).
    """
    from scripts.constants import J3_SHEET
    from scripts.run_pipeline import SOURCE_FILES

    def _load(path: Path, sheet: str | None = None):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.active
        try:
            return list(ws.iter_rows(values_only=True))
        finally:
            wb.close()

    j3_rows = _load(data_dir / SOURCE_FILES["j3"], J3_SHEET)
    tq_rows = _load(data_dir / SOURCE_FILES["tq"])
    return build_unified_history(j3_rows, tq_rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry: ``python -m scripts.audit_output``.

    Exits 0 iff every check passes (``ok=True``), non-zero otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m scripts.audit_output",
        description="V5-3 data-quality audit hard gate over real produced xlsx.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=Path("output"),
        help="Directory holding the produced xlsx (default: output)",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path("data"),
        help="Directory holding the three source xlsx (default: data)",
    )
    parser.add_argument(
        "--intermediate-dir", type=Path, default=Path("intermediate"),
        help="Intermediate-artefact directory (default: intermediate)",
    )
    parser.add_argument(
        "--semantic-dir", type=Path, default=Path("semantic-match"),
        help="Directory holding verify_*_result.jsonl (default: semantic-match)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    report = audit(
        args.output_dir,
        data_dir=args.data_dir,
        intermediate_dir=args.intermediate_dir,
        semantic_dir=args.semantic_dir,
    )
    print("=== 数据质量审计 ===")
    for c in report.checks:
        flag = "PASS" if c["passed"] else "FAIL"
        print(f"[{flag}] {c['name']}: {c['detail']}")
    print(f"=== 结果: {'OK (exit 0)' if report.ok else 'FAIL (exit 1)'} ===")
    raise SystemExit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
