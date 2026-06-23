---
name: cee-admission-match
description: 把山东省高考大绿本本科专业与近三年录取线差按专业名语义一一对应，产出带线差与日志的整理表与边界表。年度复用——每年录取数据发布后用本 skill 重跑。
disable-model-invocation: true
---

# 山东省高考录取数据匹配整理（年度复用）

> **单一真相源**：完整设计、列索引、决策依据见
> `docs/superpowers/specs/2026-06-23-cee-admission-match-design.md`（spec）与
> `docs/superpowers/plans/2026-06-23-cee-admission-match.md`（plan）。
> 本 skill 是年度执行的浓缩；与 spec/plan 冲突时以 spec/plan 为准。

## 何时使用

- 每年山东省高考录取数据发布后，需要把当年大绿本本科专业与近三年录取线差对应起来。
- 输入：三个 xlsx（大绿本招生计划 / 近三年线差统计 / 提前批录取数据）。
- 输出：带 J/T/日志的分层版 + 扁平版主表，以及新增/被删/特殊/改名/新增校/停招校边界表。

## 铁律

- **三源 xlsx 字节级只读**：读取前后 SHA256 校验（`io_source.assert_unchanged`），
  以只读方式打开（`openpyxl.load_workbook(read_only=True)`）。
- **范围**：仅 提前批 + 常规批一段、仅本科；专科全排除（小标题含「专科」即弃）。
- **一段线**：2023=443 / 2024=444 / 2025=441（`constants.ONE_LINE`）。
- **输出不覆盖大绿本原列**：行尾追加 J/T/日志 3 列。

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
| `大绿本_附线差_分层版.xlsx` | 原表全行 + 行尾 J/T/日志 3 列（仅专业行填值） |
| `大绿本_附线差_扁平版.xlsx` | 仅专业行 + J/T/日志 |
| `新增专业.xlsx` | 估算值 / 退化级别 / 样本量 / 日志 |
| `被删旧专业.xlsx` | 近三年 J/T + 日志「近三年有、2026 大绿本无」 |
| `特殊情况.xlsx` | 飞行不成 / 剩余无法匹配 |
| `学校改名表.xlsx` | 新校名 / 候选旧校名 / 置信度 / 专业数 / 备注 / 人工已核验 |
| `新增校表.xlsx` | 未配对的大绿本独有校 |
| `停招消失校表.xlsx` | 未配对的历史独有校 |

分层版与扁平版**同源**：同一 MatchResult 列表，同专业行 J/T/日志逐行相等。

## 年度复用步骤

1. 替换 `data/` 下三个 xlsx（文件名不变；若改名同步改 `constants.py` 列索引 +
   `run_pipeline.SOURCE_FILES`）。
2. 更新 `constants.ONE_LINE`（新年份一段线）+ `tests/baseline_hashes.py`（三源 SHA256）。
3. `.venv/bin/python -m scripts.run_pipeline`（确定性链，不调 agent）。
4. harness 侧：`semantic-match/RUN.md` 派发 Stage2 agent；`research/RUN_RENAME.md`
   派发改名检测 + 网查。
5. `run_pipeline --with-agent-results` 回填最终主表 + 边界表。

**完成判据**：`output/` 下 8 张表齐全；`.venv/bin/python -m pytest` 全绿且覆盖率 ≥80%、`ruff check` 无错；三源 SHA256 不变；每个本科专业行 100% 归类（匹配/新增/被删/特殊/改名五类之一）；改名表备注已填（网查或人工）。

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
