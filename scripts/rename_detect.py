"""Slice 6 Task 6.2 — school rename detection (pure-function layer).

Per Plan v2 CRITICAL order + spec §6 Stage 3 改名 + Slice 4 architecture:
the agent semantic pairing **cannot be invoked from a Python script** (Agent
is a harness tool), so this module ships only the testable pure layer. The
harness dispatches the agent against the candidate set this module produces
and feeds the jsonl back through :func:`apply_rename`.

Three pure stages:

  1. :func:`prep_rename_candidates` — compute大绿本独有校 (in大绿本 but absent
     from history) and历史独有校 (in history but absent from大绿本); for each
     独有校, pre-screen the opposite pool with :class:`difflib.SequenceMatcher`
     top-k similarity. **Similarity is a proposal only** — spec §6 Stage 3
     explicitly states字符串相似度不可靠; the final pairing is the agent's
     semantic judgement.
  2. :func:`write_rename_prompt` — persist the candidate set as
     ``semantic-match/rename_candidates.jsonl`` and the agent task description
     as ``semantic-match/rename_prompt.md``. The prompt forbids pure-string
     judgement and fixes the output schema.
  3. :func:`apply_rename` — read agent result jsonl, enforce the rename
     contract (confidence∈[0,1], required fields non-empty, new_school ∈
     大绿本独有校), build the学校改名表, and return the set of confirmed-renamed
     大绿本 school names (consumed by :func:`scripts.stage3_edges.deleted_majors`
     to exclude renamed schools' historical majors).

Renamed-school majors: the main-output writer leaves their J/T empty with log
``疑似改名校(见改名表)，待人工核验`` (spec §9 改名). That step lives in
:func:`scripts.write_edge_tables.mark_rename_in_main` (Slice 6 Task 6.2).
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Sequence

from scripts.models import DaglubenRow, HistoryRow, RenameRow

__all__ = [
    "RenameContractError",
    "REQUIRED_KEYS",
    "OUTPUT_SCHEMA",
    "prep_rename_candidates",
    "write_rename_prompt",
    "apply_rename",
    "RENAME_PROMPT_TEXT",
]

# --- agent output schema (embedded into rename_prompt.md) --------------------
REQUIRED_KEYS: tuple[str, ...] = (
    "new_school",
    "old_school",
    "confidence",
    "is_rename",
)

OUTPUT_SCHEMA: dict[str, object] = {
    "description": (
        "每条候选输出一行 JSON,写入 rename_result.jsonl。字段:"
        " new_school(大绿本校名,逐字等于候选 new_school),"
        " old_school(从候选 candidate_old_schools 中选取,或 null 若无),"
        " confidence(agent 语义置信度,∈[0,1]),"
        " is_rename(true=确认构成改名/转设,false=候选不构成改名)。"
        " 每个 new_school 至多一行。"
    ),
    "required_keys": list(REQUIRED_KEYS),
    "hard_rules": (
        "1) 禁止用字符串相似度/编辑距离单独判断——须基于语义(是否同源/更名/"
        "转设/合并)。2) old_school 必须逐字来自 candidate_old_schools 或为 null。"
        "3) confidence 严格 ∈[0,1]。"
    ),
}

# The agent task prompt (spec §6 Stage 3 改名 + Plan v2 binding). Written to
# semantic-match/rename_prompt.md by write_rename_prompt. Kept as a module
# constant so tests can assert the contract text (禁字符串相似度) is present.
RENAME_PROMPT_TEXT = """\
# 学校改名/转设 — Agent 语义配对任务

> 本任务由 harness 派发 (Agent 工具)。输入: `rename_candidates.jsonl`
> (每行一个大绿本独有校 + 候选旧校名列表)。输出: `rename_result.jsonl`
> (每个 new_school 至多一行 JSON)。

## 背景

2026 大绿本里出现一些「独有校」(在 2026 招生但不在近三年历史里)；近三年里
也有「独有校」(近三年招生但 2026 不在)。一部分是学校**改名/转设/合并**所致。

**字符串相似度不可靠**(spec §6 Stage 3 实证)：例如「甲大学」与「甲学院」字面
相近却可能是两所不同的学校;反之「滨州学院」与「山东航空学院」字面差异大却
是同一所学校更名。**必须基于语义判断**(是否同源、更名、转设、合并)。

## 任务

对 `rename_candidates.jsonl` 中每个 `new_school`：

1. 审查其 `candidate_old_schools`(已用字符串相似度预筛 top-k，**仅作提案**)。
2. 用语义判断: 该 new_school 是否与某候选 old_school 是**同一所学校的改名/
   转设/合并**? 如是, 选出最可能的 old_school; 若候选均不构成, 选 null。
3. 给出 `confidence` ∈ [0,1] 的语义置信度(非字符串相似度)。
4. `is_rename`: true=确认改名/转设; false=候选不构成改名(该校可能是真新增校)。

## 输出 schema (逐行写入 `semantic-match/rename_result.jsonl`)

```json
{"new_school": "<逐字等于输入的 new_school>",
 "old_school": "<来自 candidate_old_schools, 或 null>",
 "confidence": <0.0-1.0>,
 "is_rename": <true|false>}
```

## 硬约束 (违反将使整批被拒绝)

- **禁止**仅凭字符串相似度/编辑距离判断 — 须有语义理由(可记于内部思考,
  最终 jsonl 只需四字段)。
- `old_school` 必须逐字来自 `candidate_old_schools` 或为 `null`。
- `confidence` 严格 ∈ [0,1] (越界整批拒)。
- 每个 `new_school` 至多一行。
- 字段缺一不可。
"""


class RenameContractError(ValueError):
    """Raised when an agent rename-result line violates the contract."""


# ---------------------------------------------------------------------------
# 1. prep_rename_candidates
# ---------------------------------------------------------------------------


def _similarity(a: str, b: str) -> float:
    """Wrapper over :class:`difflib.SequenceMatcher` ratio (0-1)."""
    return SequenceMatcher(None, a or "", b or "").ratio()


def prep_rename_candidates(
    dgl_schools: Sequence[str],
    hist_schools: Sequence[str],
    topk: int = 5,
) -> list[dict[str, object]]:
    """Build rename candidate set: 大绿本独有校 × 历史独有校.

    Parameters
    ----------
    dgl_schools
        All distinct school base-names appearing in 2026 大绿本 (Stage 0 output).
    hist_schools
        All distinct school base-names appearing in the unified history table
        (Stage 0 output, regular + early batches).
    topk
        Per unique大绿本 school, keep the top-``k`` most string-similar
        历史独有校 as **proposal candidates** for the agent. ``topk <= 0`` keeps
        all. Similarity is **only a pre-screen** (spec §6: 字符串相似度不可靠).

    Returns
    -------
    list[dict]
        One dict per大绿本独有校: ``{"new_school": str,
        "candidate_old_schools": list[str]}`` (candidates sorted by descending
        similarity). Input order is preserved among unique-school entries.
    """
    dgl_set = {s for s in dgl_schools if s}
    hist_set = {s for s in hist_schools if s}

    dgl_only = [s for s in dgl_schools if s in dgl_set - hist_set]
    hist_only_list = list(hist_set - dgl_set)

    # No history-only schools → nothing to pair → empty candidate set.
    if not hist_only_list:
        return []

    # Deduplicate大绿本独有校 while preserving first-appearance order.
    seen: set[str] = set()
    dgl_only_unique: list[str] = []
    for s in dgl_only:
        if s not in seen:
            seen.add(s)
            dgl_only_unique.append(s)

    out: list[dict[str, object]] = []
    for new_school in dgl_only_unique:
        scored = sorted(
            hist_only_list,
            key=lambda old: _similarity(new_school, old),
            reverse=True,
        )
        if topk > 0:
            scored = scored[:topk]
        out.append({"new_school": new_school, "candidate_old_schools": scored})
    return out


# ---------------------------------------------------------------------------
# 2. write_rename_prompt
# ---------------------------------------------------------------------------


def write_rename_prompt(
    candidates: Sequence[dict[str, object]],
    out_dir: Path,
) -> list[Path]:
    """Write the rename candidate jsonl + the agent task prompt md.

    Two artefacts in ``out_dir`` (default: ``semantic-match/``):
      - ``rename_prompt.md`` — agent task description (RENAME_PROMPT_TEXT).
      - ``rename_candidates.jsonl`` — one JSON line per大绿本独有校, carrying
        ``new_school`` and ``candidate_old_schools``.

    Returns the list of written paths (prompt first, candidates second) so
    callers can assert both exist.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = out_dir / "rename_prompt.md"
    prompt_path.write_text(RENAME_PROMPT_TEXT, encoding="utf-8")

    cand_path = out_dir / "rename_candidates.jsonl"
    lines = [
        json.dumps(
            {"new_school": c["new_school"],
             "candidate_old_schools": c["candidate_old_schools"]},
            ensure_ascii=False,
        )
        for c in candidates
    ]
    cand_path.write_text("\n".join(lines), encoding="utf-8")

    return [prompt_path, cand_path]


# ---------------------------------------------------------------------------
# 3. apply_rename
# ---------------------------------------------------------------------------


def _parse_line(raw: str, path: Path, lineno: int) -> dict[str, object]:
    raw = raw.strip()
    if not raw:
        raise RenameContractError(f"{path.name}:{lineno}: 空行")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RenameContractError(
            f"{path.name}:{lineno}: JSON 解析失败 — {exc.msg}"
        ) from exc
    if not isinstance(obj, dict):
        raise RenameContractError(f"{path.name}:{lineno}: 顶层不是 JSON 对象")
    missing = [k for k in REQUIRED_KEYS if k not in obj]
    if missing:
        raise RenameContractError(
            f"{path.name}:{lineno}: 缺少必需字段 {missing}"
        )
    return obj


def apply_rename(
    result_jsonl_paths: Iterable[Path],
    dgl_rows: Sequence[DaglubenRow],
    hist_rows: Sequence[HistoryRow],
) -> tuple[list[RenameRow], set[str]]:
    """Read agent rename-result jsonl, enforce contract, build改名表.

    Parameters
    ----------
    result_jsonl_paths
        Paths to ``rename_result.jsonl`` files written by the harness after
        agent dispatch. Each line: ``{new_school, old_school, confidence,
        is_rename}``.
    dgl_rows
        The full大绿本本科专业 table (Stage 0 output). Used to (a) compute
        ``major_count_2026`` per renamed school and (b) derive the大绿本独有校
        set for the ``new∈独有校`` contract.
    hist_rows
        The unified history table. Used to derive历史独有校 for the contract.

    Returns
    -------
    (rename_table, confirmed_new_schools)
        ``rename_table``: list[RenameRow] for schools the agent confirmed as
        renamed (``is_rename=True``). Each row carries ``major_count_2026``,
        empty ``remark``, ``manual_reviewed=False``.
        ``confirmed_new_schools``: the set of大绿本 school names confirmed
        renamed — consumed by :func:`scripts.stage3_edges.deleted_majors` to
        exclude renamed schools' historical majors from the被删 table.

    Contract (hard rejects on first violation):
      - All four required keys present per line.
      - ``confidence`` is a float in ``[0, 1]``.
      - ``new_school`` non-empty and ∈ 大绿本独有校.
      - ``old_school`` non-empty when ``is_rename=True``.
      - Each ``new_school`` appears at most once.
    """
    dgl_schools = {r.get("school", "") for r in dgl_rows if r.get("school")}
    hist_schools = {r.get("school", "") for r in hist_rows if r.get("school")}
    dgl_unique = dgl_schools - hist_schools

    # major_count_2026 per school (大绿本 本科专业行数).
    major_count: dict[str, int] = {}
    for d in dgl_rows:
        school = d.get("school", "")
        if school:
            major_count[school] = major_count.get(school, 0) + 1

    rename_table: list[RenameRow] = []
    confirmed: set[str] = set()
    seen: set[str] = set()

    for path in result_jsonl_paths:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        for lineno, raw in enumerate(text.splitlines(), start=1):
            if raw.strip() == "":
                continue
            obj = _parse_line(raw, path, lineno)

            new_raw = obj["new_school"]
            old_raw = obj["old_school"]
            conf_raw = obj["confidence"]
            is_rename_raw = obj["is_rename"]

            # is_rename type check first — drives all downstream semantics.
            if not isinstance(is_rename_raw, bool):
                raise RenameContractError(
                    f"{path.name}:{lineno}: is_rename 不是布尔 ({is_rename_raw!r})"
                )

            # confidence range always enforced (regardless of is_rename).
            if (not isinstance(conf_raw, (int, float))) or isinstance(
                conf_raw, bool
            ):
                raise RenameContractError(
                    f"{path.name}:{lineno}: confidence 不是数值 ({conf_raw!r})"
                )
            conf: float = float(conf_raw)
            if not (0.0 <= conf <= 1.0):
                raise RenameContractError(
                    f"{path.name}:{lineno}: confidence={conf} 不在 [0,1]"
                )

            if not isinstance(new_raw, str) or new_raw.strip() == "":
                raise RenameContractError(
                    f"{path.name}:{lineno}: new_school 为空或非字符串"
                )
            new_school: str = new_raw.strip()

            # is_rename=False lines: the agent judged this is NOT a rename.
            # Such a school may be a真新增校 (not in大绿本独有校 because the agent
            # is reporting on a candidate that turned out unrelated). We
            # validate field presence/range but do NOT enforce new∈独有校 —
            # we simply drop the line (it is not a rename).
            if not is_rename_raw:
                # old_school may be null/empty for non-rename; nothing to keep.
                continue

            # is_rename=True: enforce the full contract on kept rows.
            if new_school not in dgl_unique:
                raise RenameContractError(
                    f"{path.name}:{lineno}: new_school={new_school!r} "
                    f"不是大绿本独有校(必须在2026大绿本且不在历史中)"
                )
            if new_school in seen:
                raise RenameContractError(
                    f"{path.name}:{lineno}: new_school={new_school!r} "
                    f"重复出现(每校至多一行)"
                )
            seen.add(new_school)

            # old_school: must be a non-empty string when is_rename=True.
            if not isinstance(old_raw, str) or old_raw.strip() == "":
                raise RenameContractError(
                    f"{path.name}:{lineno}: is_rename=True 但 old_school 为空"
                )
            rename_table.append(
                RenameRow(
                    new_school=new_school,
                    old_school=old_raw.strip(),
                    confidence=conf,
                    is_rename=True,
                    major_count_2026=major_count.get(new_school, 0),
                    remark="",
                    manual_reviewed=False,
                )
            )
            confirmed.add(new_school)

    return rename_table, confirmed
