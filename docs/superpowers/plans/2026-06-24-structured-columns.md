# 主表结构化多列输出 实施计划（iteration-3）

> **For agentic workers:** 用 subagent-driven-development 或 executing-plans 按 task 执行；`- [ ]` 跟踪。
> **ecc:plan 确认门**：slice 实施前重述需求+风险，WAIT 用户确认再动代码。

**Goal:** 把主表单一「匹配日志」列拆成 5 个结构化列（匹配阶段/单年数据/选科漂移/复核结果/原因备注），便于筛选，信息无损。

**Architecture:** 新增 split_log 纯函数解析现有日志字符串→5 列；write_outputs 行尾列 3→7；audit 检查① 改匹配阶段非空；skill 更新。不动匹配逻辑。

**Tech Stack:** Python 3.14 + `.venv`（pytest 9.1.1 + openpyxl 3.1.5 + ruff）。

## Global Constraints

- 5 列：匹配阶段 / 单年数据 / 选科漂移 / 复核结果 / 原因备注（spec §2.1）。
- flag 是/空；复核结果仅粗筛+语义填「确定」（严格构造确定留空）。
- 仅主表（分层+扁平）拆；边界表保留原日志列。
- 信息无损：5 列覆盖原日志全部内容。
- 主表行尾总列 = 12(原) + 7(J/T + 5结构) = 19。
- 三源字节不改；conventional commits、无 Co-Authored-By；git add/commit 分两次 Bash。

## File Structure（增量）

```
scripts/
├── structured_log.py   # 新：split_log(log)->StructuredLog 纯函数
├── write_outputs.py    # 改：行尾 7 列（J/T + 5结构列），移除单一日志列
├── audit_output.py     # 改：检查① 0空日志 → 匹配阶段非空
└── models.py           # 改：StructuredLog TypedDict
tests/
├── test_structured_log.py   # 新：split_log 各日志类型
├── test_outputs.py          # 改：19 列 + 5 列值
└── test_audit.py            # 改：检查① 匹配阶段非空
skills/cee-admission-match/SKILL.md  # 改：主表 5 结构列说明
```

接口：`split_log(log: str) -> StructuredLog{匹配阶段:str, 单年数据:str, 选科漂移:str, 复核结果:str, 原因备注:str}`。

---

## Slice 1 — 主表结构化多列（issue #15）

**风险**：解析遗漏某日志类型→信息丢失；write_outputs 列数/顺序错；audit 检查① 改动破坏 exit 0。
**需求重述**：日志拆 5 列，无损，主表分层+扁平一致，audit 仍 exit 0。

### Task 1：split_log 纯函数 —— TDD
**Files:** `scripts/structured_log.py`、`scripts/models.py`、`tests/test_structured_log.py`
- [ ] RED：split_log 各日志类型样例——
  - `严格匹配：归一化专业名+招生类别一致；（单年数据，无标准差）` → 阶段=严格匹配、单年=是、漂移=空、复核=空、备注=归一化专业名+招生类别一致。
  - `粗筛匹配：核心名唯一` → 阶段=粗筛匹配、复核=确定、备注=核心名唯一。
  - `粗筛匹配：括号子集消歧（不限选考科目类专业）；选科政策漂移，已忽略` → 阶段=粗筛匹配、漂移=是、复核=确定、备注=括号子集消歧（不限选考科目类专业）。
  - `语义匹配：核心名法学对齐` → 阶段=语义匹配、复核=确定、备注=核心名法学对齐。
  - `新增专业：估算=同校同选科(19)均值=225.25` → 阶段=新增专业、备注=估算=同校同选科(19)均值=225.25。
  - `特殊情况：未匹配，见特殊情况表` → 阶段=特殊情况、备注=未匹配，见特殊情况表。
  - `复核存疑：方向不同` → 阶段=特殊情况（复核存疑已移特殊表，主表无；但解析函数应能处理）、备注=复核存疑：方向不同（或 阶段=复核存疑）。
  - `疑似改名校(见改名表)，待人工核验` → 阶段=疑似改名校、备注=见改名表，待人工核验。
  - `新校/无历史，无法估算` → 阶段=新校无历史、备注=无法估算。
  - `专科：不在本次整理范围（仅本科）` → 阶段=专科（超范围）、备注=空。
- [ ] GREEN：实现 split_log（前缀映射 + 标记检测 + 剩余去前缀）。
- [ ] Commit `feat(structured-log): split match-log into 5 structured columns`

### Task 2：write_outputs 5 列输出 —— TDD
**Files:** `scripts/write_outputs.py`、`tests/test_outputs.py`
- [ ] RED：分层+扁平行尾 7 列（近三年统计线差/线差标准差/匹配阶段/单年数据/选科漂移/复核结果/原因备注），总 19 列；5 列值=split_log 结果；专科行匹配阶段=专科（超范围）。
- [ ] GREEN：write_hierarchical + write_flat 用 split_log 解析每个 MatchResult.log → 7 列；移除原单一 HEADER_LOG（改为 5 个 HEADER_*）。
- [ ] Commit `feat(output): structured 7-column row-end (J/T + 5 structured)`

### Task 3：audit 检查① 调整 —— TDD
**Files:** `scripts/audit_output.py`、`tests/test_audit.py`
- [ ] RED：检查①「匹配阶段非空」（替换原「日志非空」）；真实产出 exit 0。
- [ ] GREEN：audit 读扁平版「匹配阶段」列（第 15 列），断言每本科专业行非空。
- [ ] Commit `feat(audit): check1 匹配阶段非空`

### Task 4：skill 更新 + 端到端
- [ ] rerun `run_pipeline --with-agent-results`；扁平版 19 列、5 结构列填值、audit exit 0。
- [ ] SKILL.md 主表输出说明改为 5 结构列 + 完成判据。
- [ ] Commit `docs(skill): main-table 5 structured columns`

**Slice 1 完成标志**：主表 19 列（5 结构列填值）、audit exit 0、5 列覆盖原日志、筛选可用、skill 更新。→ 更新 #15。

## Self-Review
spec 覆盖：§2.1 五列→Task1/2；§2.2 19列→Task2；§3 已定细节（边界表不动、备注去前缀、专科阶段）→Task1/2；§4 接口测试→Task1/2/3；§6 验收→Task4。无占位；split_log 输出 StructuredLog 跨 task 一致。

## Execution Handoff
计划存 `docs/superpowers/plans/2026-06-24-structured-columns.md`。Phase 2 执行：subagent-driven（1 slice，exec + review）。
