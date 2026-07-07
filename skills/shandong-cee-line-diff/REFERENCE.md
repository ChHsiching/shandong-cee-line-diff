# 技术参考（REFERENCE）

> 本文件是 `shandong-cee-line-diff` skill 的**技术细节参考**——执行 SKILL.md 各步骤时遇到问题或需要具体参数时查阅。

## 管线各阶段的技术细节

### 数据预处理（Stage 0）

**统一往年数据**：
- 常规批：直接用近三年表里已有的线差和标准差。
- 提前批：现场算线差 = 录取最低分 − 当年一段线。低分列位置：2025 年数据 = 第 10 列，2024 年 = 第 14 列，2023 年 = 第 18 列（0 开始数）。标准差同理算。
- 提前批 A 类和 B 类合并在一起，不分。
- 近三年里标记为「提前批」的 825 行是旧口径弃用的（和补充表没重叠），直接丢掉。

**大绿本本科专业表**：
- 取常规批（`4.常规批`）+ 提前批 A/B（`1.提前批A类`/`2.提前批B类`）。
- 专业行判定：代号（E 列）和名称（F 列）都非空。
- 小标题含「专科」的行排除。

### 专业名归一化（`normalize.py`）

专业名在匹配前要归一化，消除不影响专业身份的差异：

- **统一全角半角 + 去所有空白**：全角括号 → 半角，空格/tab/换行全去掉。
- **剥掉校名里的招生类别**：校名里的括号如 `(中外合作办学)`、`(地方专项计划)` 要剥出来单独记录，用基础校名匹配。
- **剥掉描述性括号**：体检要求（身高/体重/色盲/色弱/视力/体检标准）、语种、单科成绩、年龄、学费、培养模式、章程引用——这些不影响专业身份，剥掉后再比。**性别（男/女）不能剥**——性别不同的专业是不同专业。
- **去所有括号得到核心专业名**：循环去除括号（包括嵌套括号，如「1+3(一年国内加三年芬兰)」），直到一个括号都不剩。核心名相同的专业才是匹配候选。

### 程序严格匹配（Stage 1）

- 匹配键 = `(基础校名, 招生类别, 归一化后的专业全名)`。
- 「普通计划」和空字符串视为同一类别；其他类别（中外合作/地方专项等）必须精确一致。
- 命中率约 58%。

### agent 语义匹配的批次管理（Stage 2）

- 对严格匹配没命中的专业，按 `(校名, 招生类别)` + 核心专业名相同或包含来预筛候选。
- 每 20 个专业打包一个批次 prompt（`build_batches` + `write_prompts`）。
- agent 输出 `batch_NN_result.jsonl`，每行一个 JSON：`{src_row_idx, school, major, match, J, T, reason}`。
- **输出格式检查**（违反就报错，指出哪个文件哪一行）：
  - `match` 字段要么是 null（没匹配上），要么必须和某个候选的专业名逐字一致。
  - `J` 和 `T` 必须和所选候选的值完全一致（不能自己算）。
  - 每个 `src_row_idx` 至多出现一次。
  - `reason` 非空，不超过 30 字。

### 二次复核的批次管理（Stage 2.5）

- 所有 agent 匹配的（不包含程序严格匹配的），全部重新打包给另一个 agent 复核。
- 复核输出 `{src_row_idx, verdict, reason}`，verdict 只能是「确定」或「存疑」。
- 确定 → 留在主表；存疑 → 移到特殊情况表。

### 估算（Stage 3）

无法匹配的专业，如果往年同校有类似专业，按以下顺序找参考值：

1. **同校 + 同选科的其他专业的线差均值**（最精确）。
2. 同校 + 所有专业的线差均值（选科不同时的退化）。
3. 整所学校往年完全没有在山东招生 → 无法估算，留空。

### 改名检测（Stage 3）

- 大绿本有但往年没有的学校 × 往年有但大绿本没有的学校 → 可能改名的候选。
- 字符串相似度只用来预筛候选，**最终判断必须上网搜索确认**（搜索每个消失/新增的学校是否改名/转设/合并）。
- 一个新校名可能由多个旧校合并而来，全部前身都要记录。
- 改名确认后，旧校名的往年线差数据并入新校名——改名的学校今年招的专业直接用旧校名的往年数据。

## 审计检查项

完成前必须跑：

```bash
.venv/bin/python -m scripts.audit_output \
    --output-dir output --data-dir data \
    --intermediate-dir intermediate --semantic-dir semantic-match
```

exit 0 才算完成。检查内容：

| 检查 | 说明 |
|------|------|
| 每个 agent 匹配的都有复核结果且判「确定」 | 没复核的 or 判存疑的不能留主表 |
| 每个本科专业都有匹配方式标注 | 不能有空 |
| 每张产出表没有全空行 | |
| 每张产出表至少有 1 行数据 | |
| 匹配到的线差和标准差与往年源数据一致 | 容差 0.011（舍入误差） |
| 每个消失/新增的学校都有网查记录 | 改名的已确认并应用 |
| 核心专业名列没有残留括号 | 去括号要干净（含嵌套） |
| 无法匹配的只剩下往年真的没有同核心专业名的 | 不应该有大类变体混在里面 |

## 管线串联命令

跑一次完整整理要串联确定性管线 + agent 派发（agent / WebSearch 是 harness 侧，Python 不能调）：

1. **第一次跑管线**（写出 agent prompt + 候选，不 apply）：
   `.venv/bin/python -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match`
2. **派 agent 跑语义匹配**：读 `semantic-match/batch_NN_prompt.json`，每批派 subagent，结果写 `semantic-match/batch_NN_result.jsonl`（每行 `{src_row_idx, school, major, match, J, T, reason}`）。
3. **派 agent 跑改名配对**：读 `semantic-match/rename_prompt.md` + `rename_candidates.jsonl`，派 subagent 网查每所消失/新增校，结果写 `semantic-match/rename_result.jsonl`（每行 `{new_school, old_school, confidence, is_rename}`）；网查详情写 `research/<校名>.md`。
4. **第二次跑管线**（apply 语义 + 改名结果，产出 verify prompt）：
   `.venv/bin/python -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match --with-agent-results`
5. **派 agent 跑二次复核**：读 `semantic-match/verify_batch_NN.json`，派 subagent，结果写 `semantic-match/verify_batch_NN_result.jsonl`（每行 `{src_row_idx, verdict, reason}`）。
6. **第三次跑管线**（apply 复核结果，产出最终 8 张表）：
   `.venv/bin/python -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match --with-agent-results`
7. **跑审计**：`.venv/bin/python -m scripts.audit_output --output-dir output --data-dir data --semantic-dir semantic-match`（exit 0 才算完成）。

每一步查中间结果用 `python -m scripts.show_table <产出表> [--head N] [--grep 词]`。

## 故障排查

| 症状 | 怎么处理 |
|------|---------|
| 源文件被修改了 | 从 git 恢复 `data/` 目录，重新跑 |
| agent 输出格式不对 | 看报错里的文件名和行号，修那一行后重跑 |
| 匹配率远低于预期 | 检查归一化（校名类别有没有剥对、描述性括号有没有剥干净） |
| 被删旧专业数量异常大 | 可能是改名检测没跑（被删是上界），先跑改名检测 |
| 审计说复核覆盖不完 | agent 二次复核的结果文件缺失或没判确定，重新派发复核后重跑 |
| 审计说线差不一致 | 匹配到的 → 检查 agent 输出的 J/T 是否和候选一致；估算的 → 检查估算有没有正确舍入到 2 位小数 |
| 审计说有空行 | 输出脚本的字段名和列名没对上，检查 writer 的字段映射 |
