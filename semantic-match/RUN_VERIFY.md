# RUN_VERIFY — 判断型二次复核 harness 派发手册（V5-0，iteration-2 Slice B）

主表零错配（precision-first）要求所有**判断型**匹配（粗筛核心名唯一/消歧 + agent 语义匹配，全量 ~5500 条）必须经二次 agent 复核；确定入主表，存疑移特殊表。agent 派发是 harness 侧步骤（Python 不能调 Agent 工具），本手册描述如何执行。

## 全量规模（预期）

- 粗筛判断型（核心名唯一 + 括号子集消歧）：~4775
- agent 语义匹配：~763
- 合计判断型：~5500
- 按 20/批切：~275 批

> 这是**生产步骤**（非单测），运行后才计入完成门。

## 前置

1. 已跑 `scripts/run_pipeline.py`（确定性链，Stage2 可不带 agent 结果，判断型匹配已在 `main_results` 里带粗筛/语义日志）。
2. 已跑 `scripts/run_stage_verify_prep.py`（见下）产出 `semantic-match/verify_batch_NN.json`。

## STEP 1 — 抽判断型匹配成批（确定性）

```bash
.venv/bin/python -m scripts.run_stage_verify_prep
```

读当前产出/中间产物，抽出所有判断型匹配（`main_results` 中 `matched=True` 且日志以「粗筛」或「语义匹配」开头），每条带其大绿本行 + 匹配的近三年候选 + 判定要求，按 20/批写成 `semantic-match/verify_batch_NN.json`。结尾报告判断型匹配总数（预期 ~5500）。

## STEP 2 — harness 侧派发复核 agent

对每个 `verify_batch_NN.json`，派发一个 `Agent(general-purpose)`，prompt 用 `semantic-match/verify_prompt.md`（任务+输出 schema），输入即该 batch 文件内容，输出写到 `semantic-match/verify_batch_NN_result.jsonl`。

并行模式同 Stage2 语义匹配（见 `semantic-match/RUN.md`）。

结果文件每行：
```json
{"src_row_idx": <int>, "verdict": "确定"|"存疑", "reason": "<≤30字 非空>"}
```

## STEP 3 — apply 回主线

`scripts/run_pipeline.py` 在 `_build_main_results` **之前**检测 `semantic-match/verify_*_result.jsonl`：若存在，则 `apply_verify` 得 `verdict_by_idx`，过滤 `coarse_results`/`semantic_results`（剔除存疑 idx）+ 同步从 `classified_idx` 移除 → 存疑行自然落 `remaining_unmatched → flight_and_special`，日志注「复核存疑：<原因>」（绕过 `LOG_SPECIAL_UNMATCHED` 兜底覆盖）。

重跑：
```bash
.venv/bin/python -m scripts.run_pipeline --with-agent-results
```

主表只含「严格精确 + 复核确定」；存疑单列 `output/特殊情况.xlsx`。

## STEP 4 — 黄金回归（@manual）

```bash
.venv/bin/python -m pytest tests/test_verify_judgment.py -m manual -k golden
```

断言：
- ≥95% 预确认正确配对判「确定」（阈值见 `tests/golden/verify_pairs.json` `threshold_certainty`）。
- `投资学(量化投资)↔投资学` 须判「存疑」（反例，方向不同）。

## 契约（硬拒，apply_verify 抛 `VerifyContractError`）

- `verdict ∈ {确定, 存疑}`
- `reason` 非空
- `src_row_idx` 唯一（每专业至多 1 结果）
- `src_row_idx` ∈ 判断型匹配集
- 每行合法 JSON，含 `src_row_idx`/`verdict`/`reason`
