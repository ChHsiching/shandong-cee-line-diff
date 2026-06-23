"""Project-wide constants for the admission-data pipeline.

Centralised per Plan v2 so that column indices, batch strings, and the
provincial one-line cutoffs are never magic numbers scattered across stages.
All indices are 0-based column positions in the source workbooks.
"""

from __future__ import annotations

# --- Provincial one-line cutoffs (一段线) -----------------------------------
# 来源：近三年「说明」口径：线差 = low_score − 山东一段线
ONE_LINE: dict[int, int] = {
    2023: 443,
    2024: 444,
    2025: 441,
}

# --- 近三年 (近三年学校批次专业线差统计.xlsx) column indices ----------------
# Sheet 「统计结果」, 0-based.
J3_SHEET = "统计结果"
J3_BATCH = 0
J3_SCHOOLCODE = 1
J3_SCHOOLNAME = 2
J3_MAJORNAME = 3
J3_SUBJECT = 4
J3_REMARKS = 5
J3_BASE_MAJOR = 6      # 基础专业名 (G)
J3_IS_BRACKET = 7      # 是否括号专业 (H)
J3_BRACKET = 8         # 括号内容 (I)
J3_STAT_LINE_DIFF = 9  # 统计线差 (J) — the primary value we back-fill
J3_DIFF_2023 = 10      # 2023线差 (K)
J3_DIFF_2024 = 11      # 2024线差 (L)
J3_DIFF_2025 = 12      # 2025线差 (M)
J3_YEARS_AVAILABLE = 16
J3_STDDEV = 19         # 线差标准差 (T)

# --- 提前批补充表 (山东省高考提前批录取数据.xlsx) low-score column indices ----
# Per-row 「录取低分」per year, 0-based: year 2025 -> col 10, 2024 -> 14,
# 2023 -> 18 (confirmed by spec §2.3 / Plan v2).
TQ_LOW_2025 = 10
TQ_LOW_2024 = 14
TQ_LOW_2023 = 18

# --- 大绿本 (山东省2026年大绿本招生计划.xlsx) batch strings ------------------
BATCH_REGULAR = "4.常规批"
BATCH_EARLY_A = "1.提前批A类"
BATCH_EARLY_B = "2.提前批B类"
FLIGHT_BATCH = "3.提前批—飞行技术(军队)"

# --- 近三年 batch strings --------------------------------------------------
J3_BATCH_REGULAR = "常规批一段线"
J3_BATCH_REGULAR_SEG2 = "常规批二段线"  # deleted
J3_BATCH_EARLY = "提前批"               # the 825 rows — deprecated, verified first

# --- 提前批补充表 batch strings --------------------------------------------
TQ_BATCH_EARLY_A = "本科提前批A类"
TQ_BATCH_EARLY_B = "本科提前批B类"
TQ_BATCH_EARLY = "提前批"  # unified label after merging A+B

# --- 专科 exclusion --------------------------------------------------------
# 小标题 (大绿本 B 列) containing this keyword marks 专科 (vocational) rows,
# which are fully excluded per spec §3. Also used as a marker in major names.
ZHUANKE_KEYWORD = "专科"

# --- 招生类别 (招生类别) keywords stripped from school names ---------------
# Per spec §5.2 / §5.1: these bracket suffixes on 近三年 school names encode
# the admission track and must be split off before aligning school names.
SCHOOL_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "合作",      # 中外合作办学 / 校企合作
    "专项",      # 地方专项 / 高校专项
    "走读",
    "边防",      # 边防军人子女预科班
    "预科",
    "民族班",
    "定向",
    "公费",      # 公费师范 / 公费农科
    "航海",
)

# --- 忽略类 (IGNORE) bracket keywords --------------------------------------
# Per spec §5.3: candidate客观要求 inside brackets do not affect identity.
# Gender (男/女) is the explicit exception and is kept.
IGNORE_BRACKET_KEYWORDS: tuple[str, ...] = (
    "身高", "体重", "色盲", "色弱", "视力", "体检", "标准", "合格",
    "语种", "单科", "年龄", "特殊类型招生控制线", "不低于",
)

# --- Match log strings (spec §9) ------------------------------------------
LOG_STRICT = "严格匹配：归一化专业名+招生类别一致"

# Stage 1.5 core-name coarse match logs (spec §9 粗筛 + Plan v2 binding).
# Task spec overrides the generic「签名唯一对齐」wording with two specific logs.
LOG_COARSE_UNIQUE = "粗筛匹配：核心名唯一"
LOG_COARSE_DISAMBIG_PREFIX = "粗筛匹配：括号子集消歧"
LOG_SUBJECT_DRIFT = "选科政策漂移，已忽略"
