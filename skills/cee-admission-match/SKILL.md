---
name: cee-admission-match
description: 山东高考 CEE 录取数据整理——大绿本招生计划匹配近三年线差。Use when the user provides 山东/CEE/高考 admission xlsx (大绿本招生计划/近三年线差统计/提前批录取数据) and wants them matched into a unified table with 线差+标准差+结构化日志列. Annual reuse; auto-asks 一段线/scope.
---

# 山东省高考录取数据匹配整理（年度复用，v5）

> **单一真相源**：完整设计、列索引、决策依据见
> `docs/superpowers/specs/2026-06-23-cee-admission-match-design.md`（spec，v5）与
> `docs/superpowers/plans/2026-06-23-cee-admission-match.md`（iteration-1）+
> `docs/superpowers/plans/2026-06-23-cee-admission-match-iter2.md`（iteration-2）。
> 本 skill 是年度执行的浓缩；与 spec/plan 冲突时以 spec/plan 为准。

## 自主启动流程（收到文件后按此执行）

> 收到山东省高考数据 xlsx（或提及 大绿本/近三年线差/提前批录取/CEE）时，按以下 7 步自主执行。每步有完成判据；不确定的用 **AskUserQuestion** 问，**不静默停**。

### Step 1：识别三源 + 验证列布局
- 读 `data/`（或用户指定路径）下 xlsx，按内容识别：**大绿本**（含「批次/学校代码/代号/名称」）、**近三年线差统计**（含「batch/schoolcode/统计线差」）、**提前批录取数据**（含「批次名称/录取低分」）。
- **验证列布局**：读各表 header，确认列索引与 `constants.py`（J3_STAT_LINE_DIFF=9 / TQ_LOW_2025=10 等）一致。若列变 → 更新 constants + 告知用户。
- **完成判据**：三源识别完毕 + 列布局匹配 constants（或已更新 constants 并验证）。

### Step 2：问必要参数（AskUserQuestion，不静默停）
- **一段线**：数据覆盖哪些年份？各年山东一段线值？（不能从数据推断时**必须问**）。
- **范围确认**：仅提前批+常规批一段、仅本科（默认是，确认即可）。
- **已知改名校**（可选）：用户是否知道某些学校改名了？
- **完成判据**：一段线已确认 + `constants.ONE_LINE` 已更新。

### Step 3：更新常量 + 基线
- 更新 `constants.ONE_LINE`（Step 2）+ `tests/baseline_hashes.py`（三源 SHA256）。
- **完成判据**：ONE_LINE + baseline_hashes 反映当年数据。

### Step 4：跑确定性管线
- `.venv/bin/python -m scripts.run_pipeline`（Stage0→1→1.5→3，不调 agent）。
- **完成判据**：管线跑通，主表+边界表产出，agent prompt 已生成待派发。

### Step 5：派发 agent（harness 侧）
- `semantic-match/RUN.md`：Stage2 语义匹配 agent。
- `semantic-match/RUN_VERIFY.md`：**判断型二次复核**（precision-first：粗筛+语义全部须复核）。
- `research/RUN_RENAME.md`：改名检测 + WebSearch 网查。
- **完成判据**：三套 agent result jsonl 齐全（batch_*_result / verify_*_result / rename_result）。

### Step 6：回填 + 审计硬门
- `.venv/bin/python -m scripts.run_pipeline --with-agent-results`（回填最终主表+边界表）。
- `.venv/bin/python -m scripts.audit_output` → **exit 0 才算完成**（主表零错配/0空匹配阶段/0空行/J-T一致）。
- **完成判据**：audit exit 0。

### Step 7：产出报告
- 生成 `output/数据整理报告.md`（markdown，讲清表格关系/作用/口径/阶段分布/列说明，基于真实当年数字）。
- **完成判据**：报告文档产出 + audit exit 0 + `.venv/bin/python -m pytest` 全绿 + `ruff check` 无错。

## 铁律

- **三源 xlsx 字节级只读**：读取前后 SHA256 校验（`io_source.assert_unchanged`），
  以只读方式打开（`openpyxl.load_workbook(read_only=True)`）。
- **范围**：仅 提前批 + 常规批一段、仅本科；专科全排除（小标题含「专科」即弃）。
- **一段线**：2023=443 / 2024=444 / 2025=441（`constants.ONE_LINE`）。
- **输出不覆盖大绿本原列**：行尾追加 7 列（近三年统计线差 / 近三年线差标准差 / 匹配阶段 / 单年数据 / 选科漂移 / 复核结果 / 原因备注）。原 12 列 + 7 行尾列 = 19 列。前 2 列填 J/T；后 5 列由 `split_log(log)` 解析旧单一匹配日志得来（iteration-3 结构化拆列，信息无损）。
- **precision-first（v5 核心，spec V5-0）**：只有严格精确构造的匹配才算「确定」；
  **所有判断型匹配**（粗筛自动接受 + agent 语义匹配）**必须经二次 agent 复核**
  （`semantic-match/RUN_VERIFY.md` 派发 `verify_*_result.jsonl`）。verdict=确定 留主表；
  verdict=存疑 → J/T 置空 + 日志「复核存疑：<原因>」，下放特殊表。**存疑→特殊，不留在主表**。
  主表零错配是完成硬门（经复核后主表只含「严格精确 + 复核确定」）。
- **精度 2 位（spec V5-6）**：所有**新算**的值（line_diff + estimate）舍入 2 位；
  matched 行保留源值（不改写）；`stage2_apply` 按 2 位对齐比较。
- **T 策略（spec V5-1）**：
  - 单年历史匹配：T 留空 + 日志追加「(单年数据，无标准差)」（三处 stage 锚点）。
  - 新增估算：J 与 T 同时给——退化 0 = 同校同选科历史 J/T 均值（T 排除 None）；
    退化 1 = 同校全专业 J/T 均值；退化 2 = value=None，T=None。
- **数据质量审计硬门（spec V5-3，年度复用前必跑）**：宣告「完成」前必须对**真实产出 xlsx**
  跑 `python -m scripts.audit_output`，**exit 0 才算完成**（pytest 全绿 ≠ 产出正确）。
  陷阱 B：合成 fixture 全绿但真实产出字段映射错位 → 必须真实源审计。

## 管线阶段（确定性脚本 + harness 侧 agent）

### Stage 0 预处理合并

- **统一历史表**：常规批一段线（近三年，J/T 已存于 J/T 列）+ 提前批（补充表，现场算
  J/T = 录取低分 − 一段线，低分列 2025=idx10/2024=idx14/2023=idx18）。AB 类无差别合并。
  近三年 825 行 `提前批` 弃用（先 `verify_825` 重叠验证）。
- **大绿本本科专业表**：常规批（`4.常规批`）+ 提前批 AB（`1.提前批A类`/`2.提前批B类`），
  专业行 = 代号(E)+名称(F) 均非空；小标题含「专科」排除。

### 归一化（`normalize.py`，纯函数）

- `nfk`：NFKC + 去全部空白。
- `split_school`：校名括号剥离招生类别（合作/专项/走读/边防/预科/民族班/定向/公费/航海）。
  返回 `(基础校名, 招生类别)`；无类别返回 `(校名, "")`。
- `strip_ignore_brackets`：剥忽略类括号（身高/体重/色盲/色弱/视力/体检/标准/合格/语种/
  单科/年龄/特殊类型招生控制线/不低于），**保留性别括号（男/女）**。
- `core_of`：去全部括号得核心名。
- `diff_brackets`：抽差异化括号 `[("性别"|"合作"|"其他", value)]`。

### Stage 1 严格匹配

- 键 = `(基础校名, normalise_cat(招生类别), 剥忽略类括号后的归一化全名)`。
- 招生类别：`普通计划` / `""` 折叠为同一普通轨道；其他（中外合作/地方专项…）须精确匹配。
- 命中率 ~58%。

### Stage 1.5 核心名粗筛

- 键 = `(基础校名, normalise_cat(招生类别), 核心名)`。
- 唯一候选 → 自动接受（签名全等禁用，实测 0%）；多候选 → 括号子集消歧
  （候选每个 diff_bracket 均为大绿本全名子串 → 兼容；唯一兼容 → 接受）。
- 选科漂移不阻断，日志记「选科政策漂移，已忽略」。
- 累计自动 ~77%。

### Stage 2 agent 语义匹配（harness 侧，禁脚本）

- 对 Stage 1.5 未命中者，按 `(校名, 招生类别)` + 核心名兼容性（精确或子串包含）预筛候选。
- 批次 prompt（`build_batches` + `write_prompts`，批大小 20）：每 item 含大绿本专业全信息
  + 候选列表 + 输出 schema。
- agent 输出 `batch_NN_result.jsonl`，每行 `{src_row_idx, school, major, match, J, T, reason}`。
- **契约硬拒**：`match` null 或逐字 ∈ 候选集；J/T 必须与所选候选原样一致；每 src_row_idx
  至多一行；reason 非空 ≤30 字。违反抛 `Stage2ContractError`（带 file:line）。
- 六要素差异化：核心名 / 性别 / 合作 / 校区 / 方向 / 招生类别；选科非差异化；忽略色盲等。

### Stage 2.5 判断型二次复核（harness 侧 agent，v5 precision-first / spec V5-0）

- **所有判断型匹配**（粗筛自动接受 + Stage2 agent 语义，约 5500 条）**必须经二次 agent 复核**
  才能留主表——只有严格精确构造的匹配算「确定」。
- `scripts/verify_judgment.py`（`build_verify_batches` + `write_prompts`）产批次 prompt；
  harness 按 `semantic-match/RUN_VERIFY.md` 派发 agent → `verify_*_result.jsonl`
  （`{src_row_idx, verdict ∈ {确定, 存疑}, reason}`）。
- `run_pipeline --with-agent-results` 在 `_build_main_results` 之前 `apply_verify`：
  verdict=确定 → 保留主表；verdict=存疑 → idx 从 coarse/semantic/classified 剔除，
  自然落 `remaining_unmatched → 特殊表`，日志「复核存疑：<原因>」（绕过 generic 兜底）。
- **契约**：verdict 越界 / 缺字段 / src_row_idx 重复 → 拒。主表经复核后零判断型错配。

### Stage 3 边界

- **新增专业估算**（逐级退化）：
  - 退化 0：同校 + 选科集合包含（近三年 subject 按 ` | ` 拆年份变体，任一年份变体 ⊇ 新专业）
    的历史专业 J 均值。
  - 退化 1：同校无同选科 → 同校全部有 J 者均值。
  - 退化 2：整校无历史 → value=None，log「新校/无历史，无法估算」。
  - 日志透明记退化级别与样本量。
- **改名检测**（harness 侧 agent）：大绿本独有校 × 历史独有校，字符串相似度仅作 top-k
  预筛提案，**最终配对禁字符串相似度**（须语义判断同源/更名/转设/合并）。产物
  `rename_result.jsonl` → `apply_rename` 建改名表 + 返回 confirmed 改名校集。
- **被删旧专业**：近三年有 + 该校(基础校名)在 2026 大绿本 + 2026 缺该专业 + 非改名校
  （confirmed 改名校的历史专业排除，v2 CRITICAL 顺序：先改名检测后被删）。
- **飞行/特殊**：飞行技术(军队) 提前批池匹配不成 → 特殊；剩余无法匹配 → 特殊。

### 改名网查（harness 侧 WebSearch，最后一步）

- 对改名表每所学校 WebSearch（`format_query`：新校名+旧校名+更名/转设/前身/同源/高校）。
- 写 `research/<school>_YYYYMMDD.md`（时间戳防覆盖）。
- `merge_remark`（幂等）：`manual_reviewed=True` 的备注不覆盖；空网查不清空已有备注。
- 不自动重匹配——改名校专业 J/T 留空 + 日志「疑似改名校(见改名表)，待人工核验」。

## 输出（`output/`）

| 文件 | 内容 |
|------|------|
| `大绿本_附线差_分层版.xlsx` | 原表全行 + 行尾 7 列（J/T + 匹配阶段/单年数据/选科漂移/复核结果/原因备注，仅专业行填值；专科行匹配阶段=专科（超范围）） |
| `大绿本_附线差_扁平版.xlsx` | 仅专业行（本科，剔除专科）+ 行尾 7 结构列 |
| `新增专业.xlsx` | 估算值 / 退化级别 / 样本量 / 日志 |
| `被删旧专业.xlsx` | 近三年 J/T + 日志「近三年有、2026 大绿本无」 |
| `特殊情况.xlsx` | 飞行不成 / 剩余无法匹配 |
| `学校改名表.xlsx` | 新校名 / 候选旧校名 / 置信度 / 专业数 / 备注 / 人工已核验 |
| `新增校表.xlsx` | 未配对的大绿本独有校 |
| `停招消失校表.xlsx` | 未配对的历史独有校 |

分层版与扁平版**同源**：同一 MatchResult 列表，同专业行 7 列行尾逐行相等。

**主表 5 结构化列**（iteration-3，替换原单一「匹配日志」列，便于筛选）：

| 列 | 取值 | 解析自原日志 |
|----|------|------|
| 匹配阶段 | 严格匹配 / 粗筛匹配 / 语义匹配 / 新增专业 / 特殊情况 / 疑似改名校 / 新校无历史 / 专科（超范围） / 复核存疑 | 日志前缀 |
| 单年数据 | `是` / 空 | 日志含「（单年数据，无标准差）」 |
| 选科漂移 | `是` / 空 | 日志含「选科政策漂移，已忽略」 |
| 复核结果 | `确定` / 空 | 判断型阶段（粗筛+语义）经二次复核确定；严格构造确定/新增/特殊/改名 留空 |
| 原因备注 | 自由文本 | 去前缀+去标记后的剩余细节 |

flag 列「是」即满足、「非空」即可筛。边界表（新增/被删/特殊/改名/新增校/停招）仍保留原单一日志列（不拆）。

## 完成判据（v5，每项必过才算完成）

- `output/` 下 8 张表齐全；`.venv/bin/python -m pytest` 全绿且覆盖率 ≥80%、`ruff check` 无错。
- **数据质量审计 exit 0**（主表零错配[判断型经复核确定] / 0 空匹配阶段 / 0 全空行 / 字段映射回归 / J-T 一致[精度区分]）。
- 三源 SHA256 不变；每个本科专业行 100% 归类。
- 精度 ≤2 位；新增估算 (J,T) 齐；单年 T 空+单年数据=是；专科全排除；改名表备注已填。
- `output/数据整理报告.md` 已生成。

> 年度复用的 7 步执行流程见上方「自主启动流程」。

## 数据质量审计硬门（v5 spec V5-3）

**完成前必跑**——pytest 全绿 ≠ 产出正确（陷阱 B：合成 fixture 全绿但真实产出字段映射错位）。
宣告「完成」前必须对**真实产出 xlsx** 跑审计脚本，**exit 0 才算完成门**：

```bash
.venv/bin/python -m scripts.audit_output \
    --output-dir output --data-dir data \
    --intermediate-dir intermediate --semantic-dir semantic-match
```

五检查（`scripts/audit_output.py`）：

| # | 检查 | 说明 |
|---|------|------|
| 0 | 复核覆盖完备性 | 主表每个判断型匹配行（匹配阶段 ∈ {粗筛匹配, 语义匹配}）的 src_row_idx 必须出现在 `verify_*_result.jsonl` 且 verdict=确定；jsonl 缺失 → fail「复核未派发」 |
| 1 | 每本科专业行匹配阶段非空 | 0 缺失（读「匹配阶段」列，按列名不按索引） |
| 2 | 每张产出表 0 全空数据行 | 分层/扁平/新增/被删/改名/新增校/停招消失/特殊 |
| 3 | 字段映射回归 | 所有产出表含至少 1 行数据（writer header 锁定在 test_output_quality） |
| 4 | J/T 一致性（精度区分） | matched 行（匹配阶段 ∈ {严格,粗筛,语义}）比近三年源值；新增估算行（匹配阶段=新增专业）比 `round(估算,2)`（容差 0.011） |

副作用产物 `output/audit_sample.xlsx`（随机 30 条主表行）供人工语义核验，**不计 exit 0**。

## 关键常量速查

- 一段线：`{2023:443, 2024:444, 2025:441}`（`constants.ONE_LINE`）。
- 近三年列（0-based）：批次=0 / 校名=2 / 专业=3 / 选科=4 / 统计线差 J=9 / 标准差 T=19。
- 提前批低分列：2025=10 / 2024=14 / 2023=18。
- 大绿本批次：`4.常规批` / `1.提前批A类` / `2.提前批B类` / `3.提前批—飞行技术(军队)`。
- 专科关键词：「专科」（小标题含即排除）。

## 故障排查

| 症状 | 处理 |
|------|------|
| `RuntimeError: source file changed` | 源被误改；从 git 恢复 `data/`，重跑 |
| Stage2 契约违反 | 看 `Stage2ContractError` 的 file:line，修该 jsonl 行后重跑 `--with-agent-results` |
| 匹配率远低于 77% | 检查归一化（校名类别剥离/忽略类括号）是否漏 case；核心名粗筛口径 |
| 被删数异常大 | 改名 agent 未跑（被删为上界）；先跑改名检测排除改名校 |
| 审计 `judgmental_coverage` FAIL「复核未派发」 | `semantic-match/verify_*_result.jsonl` 缺失；按 `RUN_VERIFY.md` 派发判断型二次复核后重跑 |
| 审计 `judgmental_coverage` FAIL verdict≠确定 | 主表判断型行未全部判「确定」；查示例 idx，复核存疑者已下放特殊则正常（重审 idx 是否漏 demote） |
| 审计 `jt_consistency` FAIL | matched 比源值不等 → 修 Stage2 jsonl J/T；新增估算不等 → 查 estimate round(2) |
| 审计 `no_empty_rows` / `tables_nonempty` FAIL | 字段映射回归（陷阱 A）：查 writer 是否把字段名映射到表头列名 |
