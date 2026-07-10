"""Project-wide constants for the admission-data pipeline.

Centralised so that column indices, batch strings, and the
provincial one-line cutoffs are never magic numbers scattered across stages.
All indices are 0-based column positions in the source workbooks.
"""

from __future__ import annotations

# --- Provincial one-line cutoffs (一段线) -----------------------------------
ONE_LINE: dict[int, int] = {
    2023: 443,
    2024: 444,
    2025: 441,
}

# --- 近三年 column indices (0-based) -----------------------------------------
J3_SHEET = "统计结果"
J3_BATCH = 0
J3_SCHOOLCODE = 1
J3_SCHOOLNAME = 2
J3_MAJORNAME = 3
J3_SUBJECT = 4
J3_REMARKS = 5
J3_BASE_MAJOR = 6
J3_IS_BRACKET = 7
J3_BRACKET = 8
J3_STAT_LINE_DIFF = 9
J3_DIFF_2023 = 10
J3_DIFF_2024 = 11
J3_DIFF_2025 = 12
J3_YEARS_AVAILABLE = 16
J3_STDDEV = 19

# --- 提前批 low-score column indices -----------------------------------------
TQ_LOW_2025 = 10
TQ_LOW_2024 = 14
TQ_LOW_2023 = 18

# --- 大绿本 batch strings ----------------------------------------------------
BATCH_REGULAR = "4.常规批"
BATCH_EARLY_A = "1.提前批A类"
BATCH_EARLY_B = "2.提前批B类"
FLIGHT_BATCH = "3.提前批—飞行技术(军队)"

# --- 近三年 batch strings ----------------------------------------------------
J3_BATCH_REGULAR = "常规批一段线"
J3_BATCH_REGULAR_SEG2 = "常规批二段线"
J3_BATCH_EARLY = "提前批"

# --- 提前批补充表 batch strings ----------------------------------------------
TQ_BATCH_EARLY_A = "本科提前批A类"
TQ_BATCH_EARLY_B = "本科提前批B类"
TQ_BATCH_EARLY = "提前批"

# --- 专科 exclusion ----------------------------------------------------------
# 识别专科行的关键字集合。「定向培养军士生」是高职专科层（2 年制军士 NCO 训练），
# 实测 46 条军士生提前批行（威海/滨州职业等专科校）曾因 bracket 只写「军士生」、
# 不含「专科」而漏进本科池（Def-2，fresh-test 2026-07-09）。
ZHUANKE_KEYWORDS: tuple[str, ...] = ("专科", "军士生", "定向培养军士")
# Backward-compat alias（旧名只查「专科」，新代码用 ZHUANKE_KEYWORDS 集合）。
ZHUANKE_KEYWORD = "专科"

# --- 招生类别 keywords stripped from school names ----------------------------
SCHOOL_CATEGORY_KEYWORDS: tuple[str, ...] = (
    "合作",
    "专项",
    "走读",
    "边防",
    "预科",
    "民族班",
    "定向",
    "公费",
    "航海",
)

# --- 忽略类 bracket keywords -------------------------------------------------
IGNORE_BRACKET_KEYWORDS: tuple[str, ...] = (
    "身高",
    "体重",
    "色盲",
    "色弱",
    "视力",
    "体检",
    "标准",
    "合格",
    "语种",
    "单科",
    "年龄",
    "特殊类型招生控制线",
    "不低于",
)

# --- Match log strings (大白话) ----------------------------------------------
LOG_STRICT = "严格匹配：归一化后专业名完全一致"

# Stage 1.5 candidate-generation log (prefix：detail format for parser).
# 备注要让没有前置知识的人也能看懂前因后果（用户口径 2026-07-09：别冷不丁甩
# 一句黑话）。「核心名匹配」是 stage 前缀（structured_log 按首个「：」切分），
# 冒号后是给读者看的因果说明：同校、核心名相同、往年只此一条→直接沿用线差。
LOG_COARSE_CANDIDATE = (
    "核心名匹配：今年该专业与往年同校某条记录的核心名相同"
    "（核心名=去掉方向、校区等括号后的专业主干名），"
    "且往年只有这一条记录，按规则直接沿用它的线差"
)

# 选科跨年差异标注
LOG_SUBJECT_NOTE = "选科要求跨年不同，不影响匹配"

# Stage 2 agent semantic-match logs
LOG_SEMANTIC_PREFIX = "agent 语义匹配"
LOG_SEMANTIC_NULL_PREFIX = "agent 判断：没找到语义相同的往年专业"

# Stage 3 edge logs
LOG_DELETED = "往年有这个专业，今年该校停招了"
LOG_RENAME_PENDING = "这所学校可能改了名字，往年数据需要人工关联（见改名表）"
LOG_GONE_SCHOOL = "这所学校今年没有在山东招生"
LOG_FLIGHT_UNMATCHED = "飞行技术(军队)类专业，无法匹配"
LOG_SPECIAL_UNMATCHED = "未能匹配：详见未能匹配的专业表"
LOG_ZHUANKE_OUT_OF_SCOPE = "专科：不在本次整理范围（仅本科）"

# V5-0 second-pass verification: prefix for存疑 verdicts
LOG_VERIFY_DEMOTE_PREFIX = "二次复核认为可能有误"
