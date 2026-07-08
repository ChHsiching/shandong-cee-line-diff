# 技术参考（REFERENCE）

> 本文件是 `shandong-cee-line-diff` skill 的**技术细节参考**——执行 SKILL.md 各步骤时遇到问题或需要具体参数时查阅。

## 管线各阶段的技术细节

### 数据预处理（Stage 0）

**统一往年数据**（原则：有现成线差/标准差的直接用，没有的才现场算）：
- 主统计表（近三年线差统计）：常规批也好、提前批也好，**只要带现成线差/标准差就直接用，不重算**。
- 补充录取数据（如果有）：主统计表没统计到的录取数据，只有录取分，现场算线差 = 录取分 − 当年一段线。**补充表可能有 0/1/多个，批次不限（不一定是提前批）——以实际文件为准**；没有就全用主统计表的现成数据。
- **今年的例子（仅参考，下次以实际为准）**：补充表是「山东省高考提前批录取数据」，录取最低分列 2025=第 10 列、2024=第 14 列、2023=第 18 列（0 开始数）；提前批 A 类/B 类合并。但这是今年的情况——下次补充表的数量 / 批次 / 列位置都可能不同，按实际文件结构读，不要硬记。

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
PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.audit_output \
    --output-dir output --data-dir data \
    --intermediate-dir intermediate --semantic-dir semantic-match
```

exit 0 才算完成。**实际检查（`audit_output.py` 共 5 项）**：

| check | 说明 |
|------|------|
| `judgmental_coverage` | 每个 agent 判断型匹配都有复核结果且判「确定」；没复核 / 判存疑的不留主表 |
| `nonempty_log` | 每个本科专业都有匹配方式标注（不能空） |
| `no_empty_rows` | 每张产出表没有全空行 |
| `tables_nonempty` | 每张产出表至少 1 行数据 |
| `jt_consistency` | 匹配到的线差 / 标准差与往年源数据一致（容差 0.011） |

> **以下尚未实现审计**（fresh-test 2026-07-08 痛点 4 指出，待补）：① 每个消失 / 新增校有网查记录（改名表 `is_rename=true` 行备注非空且含官方链接）；② 核心专业名列无残留括号；③ 未能匹配表不该有大类变体残留（X / X类，待 OPP-1 domain policy 定了再加）。目前靠 agent 自查 + 改名表 `note` 直填备注保证。

## run_pipeline CLI 参数（覆盖默认，不特化数据）

`scripts.run_pipeline` 接受以下参数（默认值是今年的情况，数据不同时通过 CLI 覆盖，**不用改代码**）：

| 参数 | 默认（今年） | 说明 |
|------|------------|------|
| `--dl-file <名>` | 山东省2026年大绿本招生计划.xlsx | 大绿本文件名 |
| `--j3-file <名>` | 近三年学校批次专业线差统计.xlsx | 近三年统计表文件名 |
| `--tq-file <名>` | 山东省高考提前批录取数据.xlsx | 补充表文件名（不存在则跳过） |
| `--one-line <年=分,...>` | 2025=443,2024=444,2023=441 | 一段线 |
| `--supplement-batches <名,...>` | 本科提前批A类,本科提前批B类 | 补充表要取的批次名（逗号分隔） |
| `--supplement-low-cols <年=列,...>` | 2025=10,2024=14,2023=18 | 补充表录取低分列位置（0 开始数） |
| `--dagluben-early-batches <名,...>` | 1.提前批A类,2.提前批B类,3.提前批—飞行技术(军队) | 大绿本提前批的批次名 |
| `--flight-batch <名>` | 3.提前批—飞行技术(军队) | 飞行技术批次名 |

例：明年大绿本改名 + 一段线变 + 补充表批次名不同：
```
PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_pipeline --data-dir data --out-dir output \
    --dl-file 山东省2027年大绿本招生计划.xlsx \
    --one-line 2025=440,2024=442,2023=439 \
    --supplement-batches 提前批A,提前批B \
    --supplement-low-cols 2025=10,2024=14,2023=18
```

## 怎么跑 pipeline（开箱即用）

plugin 自带 SessionStart hook，**新开 session 自动建好 Python venv + openpyxl**（在 plugin 根 `.venv`）。agent 不用自己建 venv。

定位 plugin 根 $P（含 scripts/ + .venv）：
```bash
P=$(dirname $(dirname $(dirname $(find ~/.claude/plugins ~/.zcode/skills ~/.codex ~/.local/share 2>/dev/null -name SKILL.md -path "*shandong-cee-line-diff*" | sort -V | tail -1))))
```

跑 pipeline（`PYTHONPATH=$P` 前缀 + plugin venv python）：
```bash
PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match
```

查任何产出 xlsx：`PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.show_table output/<表>.xlsx --head 20`

**如果 `$P/.venv` 不存在**（hook 没跑成，如 python3 缺失），fallback 手动建一次：
```bash
python3 -m venv "$P/.venv" && "$P/.venv/bin/pip" install -q openpyxl
```

## 管线串联命令

跑一次完整整理要串联确定性管线 + agent 派发（agent / WebSearch 是 harness 侧，Python 不能调）。**所有命令加 `PYTHONPATH=$P` 前缀**（见上「怎么跑 pipeline」）。

**关键顺序：改名必须早于语义匹配**——改名校的专业在改名前的 batch 里会拿到空候选（旧校名 history 还没并入新校名）。所以先派改名 agent、apply 后重生成 batch，再派语义 agent。

1. **第一次跑管线**（写出 batch prompt + 改名候选，不 apply）：
   `PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match`
   → 严格匹配 + **无改名的** Stage2 batch prompt（改名校这时空候选，正常）+ 改名候选。
2. **派 agent 跑改名配对**（先于语义！）：读 `semantic-match/rename_prompt.md` + `rename_candidates.jsonl`，派 subagent 网查每所消失/新增校，结果写 `semantic-match/rename_result.jsonl`（每行 `{new_school, old_school, confidence, is_rename, note}`——`note` 可选，is_rename=true 时填「结论 + 官方链接 moe.gov.cn/gov.cn/.edu.cn」，直接进改名表备注列）；网查详情写 `research/<新校名>.md`（每校一个）。
3. **第二次跑管线**（apply 改名 → 重生成改名感知 batch）：
   `PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match --with-agent-results`
   → 旧校名 history 并入新校名，**改名校的专业这次有候选了**，Stage2 batch prompt 重新生成（改名感知）。
4. **派 agent 跑语义匹配**：读新生成的 `semantic-match/batch_NN_prompt.json`（自带 `matching_rule`），每批派 subagent（**并发 ≤6**，多了触发 429）。结果**用 helper 写、不手写 JSON**：agent 每条判写成 TSV `src_row_idx<TAB>cand_index(0起/-)<TAB>reason` 存 `decisions_NN.tsv`，再 `python -m scripts.write_batch_result --mode batch --prompt semantic-match/batch_NN_prompt.json --decisions semantic-match/decisions_NN.tsv --out semantic-match/batch_NN_result.jsonl`（helper 反填 match/J/T，消除双引号/弯引号转义坑）。
5. **第三次跑管线**（apply 语义结果）：
   `PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match --with-agent-results`
   → apply batch_*_result.jsonl。**注意：run_pipeline 不产出 verify prompt**——下一步单独跑。
6. **产出 verify prompt**（独立步骤，run_pipeline 不代劳，**别漏**）：
   `PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_stage_verify_prep --data-dir data --out-dir output --semantic-dir semantic-match`
   → 抽判断型匹配 + 往年同核心数，写 `semantic-match/verify_batch_NN.json`（每 item 自带 `requirement`）。
7. **派 agent 跑二次复核**：读 `semantic-match/verify_batch_NN.json`（每 item 的 `requirement`），派 subagent（并发 ≤6）。结果用 helper 写：TSV `src_row_idx<TAB>verdict(确定/存疑)<TAB>reason` 存 `verify_decisions_NN.tsv`，再 `python -m scripts.write_batch_result --mode verify --prompt semantic-match/verify_batch_NN.json --decisions semantic-match/verify_decisions_NN.tsv --out semantic-match/verify_batch_NN_result.jsonl`。
8. **第四次跑管线**（apply 复核结果，产出最终 8 张表）：
   `PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.run_pipeline --data-dir data --out-dir output --semantic-dir semantic-match --with-agent-results`
9. **跑审计**：`PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.audit_output --output-dir output --data-dir data --semantic-dir semantic-match`（exit 0 才算完成）。

每一步查中间结果用 `PYTHONPATH=$P "$P/.venv/bin/python" -m scripts.show_table output/<表>.xlsx [--head N] [--grep 词]`。

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
