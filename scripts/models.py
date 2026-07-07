"""TypedDict contracts for data rows flowing through the pipeline.

Per Plan v2: typed contracts replace bare tuples/dicts so downstream stages
and tests can rely on stable shapes. TypedDict (not dataclass) keeps the rows
JSON/CSV-serialisable for intermediate artefacts.

Coverage note: this module is type-only (TypedDict bodies carry no runtime
logic); it is omitted from coverage via pytest.ini ``[coverage:run] omit``.
"""

from __future__ import annotations

from typing import TypedDict


class HistoryRow(TypedDict, total=False):
    """A row in the unified近三年 history table (Stage 0 output, regular
    batch in Slice 1; early batch merged in Slice 2)."""

    school: str            # 基础校名 (类别已剥离)
    school_cat: str        # 招生类别 (从校名/小标题剥离；普通为 "")
    major: str             # 归一化后专业全名
    stripped: str          # 剥忽略类括号后的归一化全名 (严格匹配键之一)
    core: str              # 核心名 (去全部括号)
    subject: str           # 选考科目要求 (非差异化)
    J: float | None        # 统计线差
    T: float | None        # 线差标准差
    source_table: str      # 来源表 (常规批一段线 / 提前批)


class DaglubenRow(TypedDict, total=False):
    """A专业行 from the大绿本本科专业表 (Stage 0 output, the match left side)."""

    school: str            # 学校名 (大绿本已无类别后缀)
    school_cat: str        # 招生类别 (来自小标题 B 列；普通计划为 "")
    major: str             # 归一化后专业全名 (F 列)
    stripped: str          # 剥忽略类括号后
    core: str              # 核心名
    subject: str           # 选考科目要求 (G 列)
    batch: str             # 原始批次字符串
    # Original 大绿本 row index (1-based, into the source workbook) so the
    # hierarchical output can find and extend the right row.
    src_row_idx: int


class MatchResult(TypedDict, total=False):
    """One 大绿本专业 row paired with a history J/T (or marked unmatched)."""

    src_row_idx: int        # -> DaglubenRow.src_row_idx
    school: str
    school_cat: str
    major: str
    matched: bool
    J: float | None         # 统计线差 (matched) or estimate (新增) or None
    T: float | None         # 线差标准差
    log: str                # 匹配日志 (spec §9)


class EstimateResult(TypedDict, total=False):
    """Result of新增专业 estimation (Stage 3, Slice 5).

    Per V5-1 (iteration-2): carries **both** J (``value``) and T (``T``) —
    each is the mean over the matching degradation level's history rows,
    with T computed only over rows that actually carry a T (rows whose T is
    None are excluded; if no compatible row has a T, T is None).
    """

    value: float | None     # 统计线差估算 (J)
    T: float | None         # 线差标准差估算 (V5-1)
    level: int              # 0 同校同选科 / 1 同校全专业 / 2 整校无历史
    log: str
    n: int                  # 样本量


class VerifyResult(TypedDict, total=False):
    """One judgmental-match second-pass verification verdict (V5-0, Slice B).

    The verification agent re-examines a previously-decided match and returns
    either「确定」(confirmed — keep in main table) or「存疑」(uncertain —
    demote to special table). It never alters J/T, only the row's fate.
    """

    src_row_idx: int        # -> DaglubenRow.src_row_idx of the verified match
    verdict: str            # "确定" | "存疑"
    reason: str             # 非空 reason for the verdict


class VerifyApplyResult(TypedDict, total=False):
    """Outcome of applying verification verdicts back into the pipeline.

    Per Plan v2 binding: ``confirmed`` keeps the original MatchResult (verdict
    「确定」); ``demoted`` carries the存疑 rows as EdgeRows (so they flow to the
    特殊表), enriched with the dagluben core/subject/batch; ``verdict_by_idx``
    maps every seen src_row_idx to its verdict for downstream filtering.
    """

    confirmed: list        # list[MatchResult] (verdict=确定)
    demoted: list          # list[EdgeRow] (verdict=存疑)
    verdict_by_idx: dict   # dict[int, str]


class StructuredLog(TypedDict):
    """The 5 structured columns parsed from the single log string.

    Key order is FIXED and matches the appended column order in write_outputs
    (J/T + these 5 = 7 row-end columns).

    - ``匹配方式``: 严格匹配 / agent 语义匹配 / 新增专业 / 未能匹配 /
      二次复核认为可能有误 / 可能改名的学校 / 新校无历史 / 专科（超范围）.
    - ``仅一年数据`` / ``选科要求跨年变化`` / ``二次复核``: flag columns — ``"是"``
      when the marker is present, ``""`` otherwise.
    - ``原因说明``: free-text detail in plain language.

    Total=True so write_outputs can rely on ``StructuredLog.values()``
    yielding exactly 5 strings in order.
    """

    匹配方式: str
    仅一年数据: str
    选科要求跨年变化: str
    二次复核: str
    原因说明: str


class RenameRow(TypedDict, total=False):
    """One row of 学校改名表 (Slice 6 Task 6.2).

    A candidate rename pairing produced by the agent semantic step. The
    harness applies agent jsonl via :func:`scripts.rename_detect.apply_rename`
    to build this table; the school's大绿本 majors are then left with J/T
    empty in the main output and flagged for human review (spec §6 Stage 3
    改名). ``manual_reviewed`` guards备注 idempotency against re-runs of the
    rename web-search step (Plan v2 binding).
    """

    new_school: str           # 2026 大绿本校名 (改名后)
    old_school: str           # 候选旧校名 (改名前)
    confidence: float         # agent 置信度 [0,1]
    is_rename: bool           # agent 最终判定（False = 候选不构成改名）
    major_count_2026: int     # 该校 2026 本科专业数（辅助人工核验）
    remark: str               # 备注（最后一步网查写入；可被人工编辑）
    manual_reviewed: bool     # 备注 是否已经人工编辑（True 则网查不覆盖）
