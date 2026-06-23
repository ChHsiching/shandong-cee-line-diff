# 录取数据匹配 iteration-2 实施计划

> **For agentic workers:** 用 superpowers:subagent-driven-development 或 executing-plans 按 task 执行；步骤用 `- [ ]` 跟踪。**ecc:plan 确认门**：每 slice 实施前重述需求+风险，WAIT 用户确认再动代码。
> 承接 iteration-1（已实现管线，commit 见 git log）。iteration-2 = precision-first 硬化（spec v5 V5-0~V5-6）。

**Goal:** 保证主表零错配（判断型匹配经二次复核）+ T 策略明确 + 数据质量审计硬门 + 精度统一，产出经审计的完整正确数据。

**Architecture:** 在 iteration-1 管线上增量——(A) estimate 升级 (J,T) + 单年 T 日志；(B) 新增判断型二次复核（agent 复核 coarse+agent 匹配，存疑→特殊）；(C) audit_output.py 硬门；(D) 锁定+skill v5。源文件只读不变。

**Tech Stack:** Python 3.14 + `.venv`（pytest 9.1.1 + openpyxl 3.1.5 + ruff）；agent 经 Agent 工具并行（复核）。

## Global Constraints（spec v5）

- 主表零错配（V5-0）：仅严格精确构造确定；判断型（coarse 全部 + agent）须二次复核，存疑→特殊表。
- T 策略（V5-1）：单年历史 T 留空+日志"(单年数据，无标准差)"；新增估算 (J,T) 同校同选科均值（T 排除 None）。
- 精度（V5-6）：新算的（line_diff + estimate）舍入 2 位；matched 保留源值；stage2_apply 按 2 位对齐比较。
- 数据质量审计（V5-3）为完成硬门：主表零错配/0空日志/0空行/J-T一致/字段映射回归。
- 三源字节不改（SHA256 校验）；conventional commits、无 Co-Authored-By；`git add`/`git commit` 分两次 Bash（hook 拦复合）。

## File Structure（增量）

```
scripts/
├── stage3_newmajor.py   # 改：estimate 返回 (J,T)（EstimateResult 加 T 字段）
├── verify_judgment.py   # 新：判断型二次复核（build_verify_batches/write_prompts/apply_verify）
├── audit_output.py      # 新：数据质量审计硬门（5 检查）
├── run_pipeline.py      # 改：接入复核 apply（存疑→特殊）+ 单年 T 日志 + audit 集成
└── models.py            # 改：EstimateResult 加 T；VerifyResult 新增
tests/
├── test_newmajor.py            # 改：estimate (J,T) + None 处理
├── test_verify_judgment.py     # 新：复核契约 + 黄金样例
├── test_audit.py               # 新：审计 5 检查
└── test_output_quality.py      # 改：字段映射回归补齐所有 writer
semantic-match/verify_prompt.md  # 新：复核 agent prompt
semantic-match/RUN_VERIFY.md     # 新：复核 harness 派发手册
```

接口契约：
- `estimate(new_major_row, school_history) -> EstimateResult{value, T, level, log, n}`（加 T）。
- `verify_judgment.build_verify_batches(judgment_matches, history, batch_size=20) -> list[Batch]`；`apply_verify(result_jsonl, matches) -> (confirmed, demoted_to_special)`。
- `audit_output.audit(output_dir, semantic_dir) -> AuditReport`（5 检查，exit 0 通过）。

---

## Slice A — T 策略明确（issue #10）

**风险**：estimate 改返回结构影响调用方；单年 T 日志定位。
**需求重述**：新增估算给 (J,T)；单年历史匹配 T 留空+日志说明。

### Task A1：estimate 升级返回 (J,T) —— TDD
**Files:** `scripts/stage3_newmajor.py`、`scripts/models.py`、`tests/test_newmajor.py`
- [ ] RED：测试 estimate 返回 EstimateResult 含 `T`——退化0 T=同校同选科历史 T 均值（排除 None）；退化1 T=同校全专业 T 均值；退化2 T=None。
- [ ] GREEN：`_level0_value`/`_level1_value` 同时算 J 均值与 T 均值（T 排除 None，全无则 None）；EstimateResult 加 `T` 字段；round 2。
- [ ] run_pipeline 用 `est.get("T")` 填主表新增行 T。
- [ ] Commit `feat(stage3): estimate returns J and T with 2-decimal rounding`

### Task A2：单年历史 T 日志 —— TDD
**Files:** `scripts/run_pipeline.py`（_build_main_results）、`tests/test_e2e.py`
- [ ] RED：匹配到 history T=None 的行，日志含「(单年数据，无标准差)」。
- [ ] GREEN：strict/coarse/semantic 命中后，若 matched_hist T is None → log 追加该说明。
- [ ] Commit `feat(output): annotate single-year matches with no-stddev log note`

### Task A3：重跑 + 验证
- [ ] `run_pipeline --with-agent-results`；新增行 T 非空率上升；单年匹配有说明；精度 ≤2 位。
- [ ] Commit `chore(stage3): smoke verify T policy`

**Slice A 完成标志**：新增 (J,T) 齐、单年有说明、精度 ≤2、pytest 全绿。→ 更新 #10。

---

## Slice B — 判断型二次复核（issue #11，核心）

**风险**：复核 agent 判定可靠性；存疑下放特殊表的接线。
**需求重述**：所有判断型匹配（coarse 全部 + agent 语义，~5500）经二次 agent 复核；确定留主表，存疑→特殊表。

### Task B1：verify_judgment 编排纯函数 —— TDD
**Files:** `scripts/verify_judgment.py`、`tests/test_verify_judgment.py`
- [ ] RED→GREEN：`build_verify_batches(judgment_matches, history, batch_size=20)`（每条带大绿本专业+候选+原匹配+判定要求）；`write_prompts`；`apply_verify(result_jsonl)`（verdict∈{确定,存疑}、reason 非空、src_row_idx 唯一）。契约：verdict 越界/缺字段→拒。
- [ ] `semantic-match/verify_prompt.md`：复核任务（"该配对是否确定正确？方向/性别/合作/校区/招生类别是否真对齐？不确定→存疑"）。
- [ ] Commit `feat(verify): judgment-match second-pass verification orchestration`

### Task B2：黄金样例 —— TDD
**Files:** `tests/test_verify_judgment.py`、`tests/golden/verify_pairs.json`
- [ ] 已知正确配对（如 严格匹配的样本）须判「确定」；`投资学(量化投资)↔投资学` 须判「存疑」（标 manual，agent 派发后断言）。
- [ ] Commit `test(verify): golden pairs for certainty judgment`

### Task B3：apply 接线 + harness 派发文档
**Files:** `scripts/run_pipeline.py`、`semantic-match/RUN_VERIFY.md`
- [ ] run_pipeline：复核结果（若 verify_result.jsonl 存在）→ apply_verify；「存疑」匹配从主表移除、进特殊表（J/T 空+日志「复核存疑：<原因>」）。
- [ ] RUN_VERIFY.md：harness 侧派发复核（读 verify_batch_*_prompt.json → Agent → verify_*_result.jsonl → apply_verify）。全量 ~5500 ÷ 20 ≈ 275 批为生产步骤。
- [ ] Commit `feat(verify): apply certainty verdicts, demote uncertain to special`

### Task B4：重跑 + 验证
- [ ] 派发复核（subagent 并行，同 Stage2 模式）→ apply → 重跑；主表只含「严格精确 + 复核确定」；存疑单列特殊表。
- [ ] Commit `chore(verify): smoke run second-pass verification`

**Slice B 完成标志**：主表经复核、存疑单列特殊、pytest 全绿。→ 更新 #11。

---

## Slice C — 数据质量审计硬门（issue #12）

**风险**：审计误报/漏报。
**需求重述**：audit_output.py 对真实产出 5 检查，exit 0 为完成门。

### Task C1：audit_output.py —— TDD
**Files:** `scripts/audit_output.py`、`tests/test_audit.py`
- [ ] RED→GREEN：`audit(output_dir)` 五检查——①主表抽样语义复核（manual/agent 抽样，记录）；②每本科专业行日志非空；③每张产出表 0 全空数据行；④字段映射回归（真实字段名）；⑤随机 ≥30 匹配行 J/T 与近三年原值一致。返回 AuditReport，全过 exit 0。
- [ ] Commit `feat(audit): data-quality gate over real output`

### Task C2：集成完成门
- [ ] run_pipeline 末尾调 audit（或独立 `python -m scripts.audit_output`）；README/SKILL 记"完成前必跑"。
- [ ] Commit `feat(audit): wire audit as completion gate`

**Slice C 完成标志**：audit 真实产出 exit 0。→ 更新 #12。

---

## Slice D — 锁定 + skill v5（issue #13）

### Task D1：字段映射回归全锁定
**Files:** `tests/test_output_quality.py`
- [ ] 所有边界表 writer（被删/特殊/改名/新增校/停招）用真实字段名测（防陷阱 A 复发）。
- [ ] Commit `test(output): lock field-mapping for all edge writers`

### Task D2：端到端验收
- [ ] 全管线 + audit exit 0；主表零错配、T 齐全、专科标注、边界表无空行、精度 ≤2。
- [ ] Commit `test(e2e): iteration-2 acceptance via audit gate`

### Task D3：skill v5 + README
**Files:** `skills/cee-admission-match/SKILL.md`、`README.md`
- [ ] SKILL.md 更新：precision-first（判断型复核）+ 数据质量审计硬门 + 年度复用前必跑审计 + 精度 2 位。
- [ ] README 更新 iteration-2 复核/审计步骤。
- [ ] Commit `docs(skill): v5 with precision-first and audit gate`

**Slice D 完成标志**：回归锁定、端到端过审计门、skill v5。→ 更新 #13。

---

## Self-Review

**Spec 覆盖**：V5-0 主表零错配→Slice B；V5-1 T 策略→Slice A；V5-2 分层版专科（已实现，D 验收）；V5-3 审计门→Slice C；V5-4 Bug 教训→Slice D 锁定+skill；V5-5 grilling 决策（贯穿）；V5-6 精度→Slice A（已实现 hotfix，A 验收）。无遗漏。
**占位**：复核/审计 agent 派发为 harness 侧（设计明确，给 prompt+契约+RUN 文档），非占位。
**类型一致**：estimate→EstimateResult{value,T,...}、build_verify_batches/apply_verify、audit 跨 task 一致。

## Execution Handoff

计划存 `docs/superpowers/plans/2026-06-23-cee-admission-match-iter2.md`。执行（属后续阶段）：subagent-driven 或 inline；ecc:plan 确认门每 slice 前重述+WAIT。
