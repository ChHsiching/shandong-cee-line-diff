# Stage 2 — Agent 语义匹配运行指南（harness 侧）

> Slice 4（issue #5）只实现了「可 TDD 的纯函数层」：批次预处理
> （`scripts/stage2_agent.build_batches` / `write_prompts`）与结果应用
> （`scripts.stage2_apply.apply_results`）。**真正的 agent 派发是 harness 侧
> 步骤**——Python 脚本不能调用 Agent 工具，必须由拥有 Agent 工具的会话按下
> 列流程执行。全量约 5000+ 行的 agent 跑属**生产步骤**，不进 CI。

## 前提

- Stage 0 / 1 / 1.5 已跑完，产出 `intermediate/s2_unified_history.*` 与
  Stage 1.5 的 `still_unmatched` 清单（`list[DaglubenRow]`）。
- 一段线常量（`scripts/constants.py` 的 `ONE_LINE`）已就位。
- 当前工作目录 = 仓库根。

## 步骤 1：生成批次 prompt 文件

在拥有 Python 与 `.venv` 的会话中（无需 Agent 工具）：

```python
from pathlib import Path
from scripts.stage0_merge import build_unified_history   # Slice 2 产物
from scripts.stage1_5_coarse import match_coarse, build_core_idx
# …(Slice 1–3 已有的 Stage 0/1/1.5 串联，产出 unmatched: list[DaglubenRow])
from scripts.stage2_agent import build_batches, write_prompts

history = build_unified_history(...)          # list[HistoryRow]
unmatched = <Stage 1.5 的 still_unmatched>     # list[DaglubenRow]

batches = build_batches(unmatched, history, batch_size=20)
paths = write_prompts(batches, Path("semantic-match"))
print(f"生成 {len(paths)} 个批次 prompt 文件，覆盖 {len(unmatched)} 行")
```

产物：`semantic-match/batch_01_prompt.json` … `batch_NN_prompt.json`。每个文件
是一个 JSON 对象：

```json
{
  "batch": 1,
  "items": [
    {
      "src_row_idx": 1234,
      "school": "甲大学",
      "school_cat": "",
      "major": "计算机类(图灵)",
      "core": "计算机类",
      "subject": "物理和化学",
      "batch": "4.常规批",
      "candidates": [
        {"major": "计算机类", "core": "计算机类", "J": 80.0, "T": 1.0},
        {"major": "计算机类(网络)", "core": "计算机类", "J": 78.0, "T": 0.9}
      ]
    }
  ],
  "output_schema": { ... 见 prompt.md ... }
}
```

候选集已按 `(school, 招生类别)` + 核心名兼容性（精确或子串包含）预筛，agent
只需在所给候选里做语义判断。

## 步骤 2：派发 Agent（harness 侧，需 Agent 工具）

对每个 `batch_NN_prompt.json`，用 `Agent` 工具派发一个子代理：

- `subagent_type`: `general-purpose`
- `description`: 「Stage2 语义匹配 batch NN」
- `prompt`：让子代理读 `semantic-match/batch_NN_prompt.json` 本身——文件自带
  `matching_rule`（基数规则，单一真理源：一对一/一对多可以、多对一不行；培养
  模式标签拔尖/卓越/创新/试验班等永远非身份；中外合作/师范/性别/类别/真方向
  在一对多时吸收、一对一时才算不同）+ `output_schema` + `items`（每条含
  candidates）。要求 agent 按 `matching_rule` 判断每条 item。
  **不要另写规则文档**——规则就在 prompt 文件里，照着 `matching_rule` 走。

**结果用 helper 写、不要手写 JSON**（专业名含英文双引号/弯引号时手写 JSON 必炸）：
agent 把每条判定写成 TSV——一行 `src_row_idx<TAB>cand_index(0起，或 - 表 null)<TAB>reason`，
存成 `decisions_NN.tsv`，再跑：

```bash
PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.write_batch_result \
  --mode batch --prompt semantic-match/batch_NN_prompt.json \
  --decisions semantic-match/decisions_NN.tsv \
  --out semantic-match/batch_NN_result.jsonl
```

helper 读 prompt 反填 `match`（候选 major 逐字）+ `J`/`T`（候选原值）+ `school`/`major`，
`json.dumps` 出合法 jsonl——agent 零手写 JSON、零字符串逐字复制、零 J/T 编造。cand 越界 / 漏判会在写文件前报错。

并发建议：起步 20 条/批、5–10 批并发；根据 harness 限额调。全量约 5000 行 ÷
20 ≈ 250 批。

**关键约束（agent 必须遵守，否则编排层会拒绝整批）**：

- `match` 要么 `null`，要么逐字等于某 `candidate.major`。
- `J` / `T` 从所选候选原样回填（不要编造）；`match=null` 时两者必须为 `null`。
- 每个 `src_row_idx` 至多出现一行。
- `reason` 非空、≤30 字（超长会被自动截断，但空会被拒）。

## 步骤 3：收集结果并回填主表

所有批次跑完后，结果散落在 `semantic-match/batch_*_result.jsonl`。在 Python
会话中合并回填：

```python
from pathlib import Path
from scripts.stage2_apply import apply_results

result_paths = sorted(Path("semantic-match").glob("batch_*_result.jsonl"))
results = apply_results(result_paths, unmatched, history)
# results: list[MatchResult]，含 matched/J/T/log（log 内嵌 reason）
```

- `matched=True` 的行：`J`/`T` 已就位，`log=语义匹配：<reason>`；若选科漂移，
  追加 `；选科政策漂移，已忽略`。
- `matched=False` 的行：`J`/`T=None`，`log=语义匹配：无对应：<reason>`，交给
  Slice 5（新增估算）/ Slice 6（边界/改名）。

**契约违反**会抛 `Stage2ContractError`，消息含 `<file>:<line>` 定位，例如：
`batch_03_result.jsonl:17: src_row_idx=1234 match='量子力学' 不在候选集内
(候选数=2) — agent 越界/幻觉`。修复对应行后重跑步骤 3（幂等：不修改源文件）。

## 步骤 4：黄金样例回归（manual）

`tests/golden/semantic_pairs.json` 内含 15 条人工预确认的正确配对（覆盖六要素
各维度）。在主会话中，agent 跑完后断言命中率 ≥ 80%：

```python
import json
from pathlib import Path
golden = json.loads(Path("tests/golden/semantic_pairs.json").read_text(encoding="utf-8"))
pairs = golden["pairs"]
hit = 0
for p in pairs:
    # 在 results 中找 src_row_idx 对应行(需先按 school+major 映射 idx)，
    # 比对 matched major 是否 == p["expected_match"]。
    ...
rate = hit / len(pairs)
assert rate >= golden["threshold_hit_rate"], f"golden hit rate {rate:.0%} < 80%"
```

此回归不进 CI（`test_golden_pair_hit_rate` 标 `@pytest.mark.manual` 且直接
`pytest.skip`）；由主会话在 agent 产物就绪后人工运行。

## 不变性

- 三源 xlsx 字节级未改（`tests/test_immutability.py` 始终守护）。
- 本流程只写 `semantic-match/batch_*_prompt.json` / `batch_*_result.jsonl`，
  不碰 `data/`、不改大绿本原列。
- `apply_results` 对同一组输入幂等（重跑得到同样的 MatchResult）。

## 故障排查

| 症状 | 原因 | 处理 |
|------|------|------|
| `Stage2ContractError: 不在候选集内` | agent 返回了候选集外的专业 | 检查该批次 prompt 的 candidates 是否被错误预筛（核心名兼容性过严），或 agent 误判；修正后重派该批 |
| `Stage2ContractError: 重复出现` | 同一 src_row_idx 在多个 result 文件出现 | 删除重复行；通常是批次边界重叠或重跑未清旧产物 |
| `Stage2ContractError: J…不一致` | agent 编造/抄错 J/T | 该批重派，强调「J/T 必须从候选原样回填」 |
| 命中率远低于 80% | prompt 不清晰 / 候选预筛过严 / 大量改名 | 先看 `semantic_pairs.json` 失败样本的维度分布，针对性调整 prompt 或交 Slice 6 改名分支 |
