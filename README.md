# 山东省高考录取数据匹配整理

把 2026 大绿本本科专业（主键）与近三年录取线差（外键）按专业名语义一一对应，
产出带线差与匹配日志的整理表（分层版 + 扁平版）与边界表，并沉淀可年度复用 skill。

## 安装 / 下载本 skill

本仓库既是数据整理工具，也是 `cee-admission-match` skill 的下载源。
Skill 采用开放格式（SKILL.md），各 AI coding agent 均原生支持。

### Claude Code

```bash
git clone git@github.com:ChHsiching/cee-admission-data.git
# 方式1：含代码+skill+目录结构（推荐）
cd cee-admission-data && python3 -m venv .venv && .venv/bin/pip install pytest openpyxl ruff pytest-cov
# 方式2：仅装 skill
cp -r skills/cee-admission-match ~/.claude/skills/
```

### ZCode（智谱）

ZCode skill 目录为 `~/.zcode/skills/`（[官方文档](https://zcode.z.ai/cn/docs/skill)）。

```bash
git clone git@github.com:ChHsiching/cee-admission-data.git
cp -r cee-admission-data/skills/cee-admission-match ~/.zcode/skills/
```

或直接在 ZCode 桌面应用中：**设置 → 技能 → 导入** → 自动扫描 Claude Code 的 skill 目录 → 一键导入（支持软链/复制）。

聊天中调用：输入 `$` → 选 `cee-admission-match`，或 `$cee-admission-match 帮我整理 data/ 下的数据`。

### OpenAI Codex

```bash
# 在 Codex CLI 中输入 $，选择 Skill Installer，粘贴仓库 URL：
github.com/ChHsiching/cee-admission-data
```

### 其他 agent（OpenCode / Cursor / VS Code Copilot 等）

用 [npx skills](https://skillsmp.com) 工具安装：

```bash
npx skills add ChHsiching/cee-admission-data
```

或手动 clone 后复制 `skills/cee-admission-match/` 到你的 agent 的 skills 目录。

### 使用

替换 `data/` 下三个 xlsx 为当年数据 → 调用 `Skill("cee-admission-match")` →
skill 自主启动（识别文件 → AskUserQuestion 问一段线/范围 → 跑管线 → 派发 agent →
审计 exit 0 → 产出报告）。

## 目录结构

```
cee-admission-data/
├── data/                  # 三个源 xlsx —— 只读，永不修改（SHA256 校验）
├── scripts/               # 全部脚本（纯函数为主，CLI 入口）
│   ├── constants.py            # 一段线 / 列索引 / 批次字符串 / 日志常量
│   ├── models.py               # TypedDict 契约（HistoryRow/DaglubenRow/...）
│   ├── io_source.py            # 只读加载 + SHA256 不变性守卫
│   ├── normalize.py            # NFKC / 校名类别剥离 / 忽略类括号 / 核心名 / 差异化抽取
│   ├── line_diff.py            # 提前批线差 = low − 一段线（统计线差 + 标准差）
│   ├── stage0_merge.py         # 统一历史表（常规批一段 + 提前批）+ 大绿本本科专业表
│   ├── stage1_strict.py        # Stage1 严格 3-tuple 匹配
│   ├── stage1_5_coarse.py      # Stage1.5 核心名粗筛 + 括号子集消歧
│   ├── stage2_agent.py         # Stage2 agent 批次编排（纯函数，不调 agent）
│   ├── stage2_apply.py         # Stage2 agent jsonl → 主表回填（契约硬拒）
│   ├── stage3_newmajor.py      # 新增专业逐级退化估算（0/1/2）
│   ├── stage3_edges.py         # 被删 / 飞行 / 特殊 + 改名检测纯层
│   ├── rename_detect.py        # 改名 agent 候选预筛 + 契约回填
│   ├── rename_websearch.py     # 改名网查备注合并（幂等）
│   ├── verify_825.py           # 825 提前批弃用前重叠验证
│   ├── write_outputs.py        # 分层版 + 扁平版主产出
│   ├── write_edge_tables.py    # 边界三表 + 改名/新增校/停招校表
│   ├── run_newmajor_smoke.py   # Slice5 新增专业烟雾（真实数据）
│   ├── run_rename_smoke.py     # Slice6 改名候选烟雾（真实数据）
│   └── run_pipeline.py         # 端到端管线（Slice7）
├── intermediate/          # 中间产物（统一历史表、大绿本本科专业表 CSV）
├── semantic-match/        # Stage2 agent 语义匹配工作产物（prompt + result jsonl）
│   ├── prompt.md               # Stage2 agent 任务 prompt（六要素规则）
│   ├── RUN.md                  # Stage2 agent harness 侧运行指南
│   ├── rename_prompt.md        # 改名 agent 任务 prompt
│   ├── rename_candidates.jsonl # 改名候选（大绿本独有校 × 历史独有校）
│   └── batch_NN_prompt.json    # Stage2 批次 prompt（run_pipeline 生成）
├── research/              # 改名网查记录（WebSearch 原始 + 整理）
│   └── RUN_RENAME.md           # 改名网查 harness 侧运行指南
├── output/                # 最终产物（分层版、扁平版、各边界表）
├── tests/                 # pytest：纯函数单测 + 管线契约（覆盖率 ≥80%）
├── skills/                # 年度复用 skill 草稿
└── docs/superpowers/      # spec / 实施计划
```

## 源文件（`data/`，只读铁律）

| 文件 | 用途 |
|------|------|
| `山东省2026年大绿本招生计划.xlsx` | 2026 招生计划（主键源，分层结构） |
| `近三年学校批次专业线差统计.xlsx` | 近三年 学校/批次/专业 线差统计（常规批 J/T 源） |
| `山东省高考提前批录取数据.xlsx` | 提前批原始录取数据（提前批 J/T 计算源） |

**铁律：三个源文件字节级不可修改。** 管线读取前后均做 SHA256 校验
（`scripts/io_source.assert_unchanged` + `tests/test_immutability.py` 契约）。
`data/` 下文件以只读方式打开（`openpyxl.load_workbook(..., read_only=True)`）。
基线哈希见 `tests/baseline_hashes.py`。

## 一段线

| 年份 | 一段线 |
|------|--------|
| 2023 | 443 |
| 2024 | 444 |
| 2025 | 441 |

来源：`scripts/constants.py` 的 `ONE_LINE`。提前批线差 = 录取低分 − 当年一段线；
统计线差 = 可用年份均值（单年用该年），标准差同口径（单年空）。

## 管线阶段

```
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 0  预处理合并（脚本，确定性）                                    │
│   build_unified_history: 常规批一段(28269) + 提前批(1707) = 29976     │
│   build_dagluben: 常规批(23887) + 提前批AB(1585) = 25472 (专科排除)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 1  严格匹配（脚本）键=(校名, 招生类别, 剥忽略类括号全名)           │
│   ~58% 命中；未命中进 Stage 1.5                                        │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 1.5  核心名粗筛（脚本）键=(校名, 招生类别, 核心名)                │
│   唯一候选→接受；多候选→括号子集消歧；累计自动 ~77%                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 2  agent 语义匹配（harness 侧，禁脚本）                          │
│   run_pipeline 产 batch_NN_prompt.json → harness 派 agent →           │
│   batch_NN_result.jsonl → apply_results 回填主表                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3  边界（脚本 + harness 侧改名）                                 │
│   新增专业：identify + estimate(退化0/1/2) → 新增专业.xlsx             │
│   改名检测：prep候选 → harness agent → apply_rename → 学校改名表.xlsx  │
│   被删旧专业：近三年有+2026该校在+2026缺+非改名校                       │
│   飞行/特殊：FLIGHT_BATCH 不成 + 剩余无法匹配 → 特殊情况.xlsx           │
└──────────────────────────────┬──────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 输出（write_outputs / write_edge_tables）                              │
│   大绿本_附线差_分层版.xlsx  （原表全行 + 行尾 J/T/日志 3 列）           │
│   大绿本_附线差_扁平版.xlsx  （仅专业行 + J/T/日志）                    │
│   新增专业.xlsx / 被删旧专业.xlsx / 特殊情况.xlsx                       │
│   学校改名表.xlsx / 新增校表.xlsx / 停招消失校表.xlsx                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 如何复跑

### 1. 确定性管线（脚本，CI 友好）

```bash
.venv/bin/python -m pytest                    # 全量测试，覆盖率 ≥80%
.venv/bin/python -m scripts.run_pipeline      # 端到端确定性链（不调 agent）
```

`run_pipeline` 默认不应用 agent 结果——它会生成 `semantic-match/batch_NN_prompt.json`
与改名候选，并记录日志「Stage2 待 harness 派发」「改名 待 harness 派发」。这是
**确定性链**：严格 + 粗筛 + 新增估算 + 边界表，源哈希前后不变。

如已在 harness 侧跑完 agent 且产物就位，加 `--with-agent-results` 回填：

```bash
.venv/bin/python -m scripts.run_pipeline --with-agent-results
```

### 2. Stage2 agent 语义匹配（harness 侧，需 Agent 工具）

Python 不能调用 Agent 工具。`run_pipeline` 已生成批次 prompt 后，由拥有 Agent
工具的会话按 `semantic-match/RUN.md` 派发：每批 20 条、并发 5–10 批、agent 输出
`batch_NN_result.jsonl`。跑完后 `--with-agent-results` 重跑管线即可回填。

### 2b. 判断型二次复核（iteration-2 Slice B / issue #11，spec V5-0 precision-first）

**v5 核心**：只有严格精确构造的匹配才算「确定」；**所有判断型匹配**（粗筛自动接受 +
Stage2 agent 语义，~5500 条）**必须经二次 agent 复核**才能留主表。按
`semantic-match/RUN_VERIFY.md` 派发：`run_stage_verify_prep.py` 产批次 prompt →
harness 派发 agent → `verify_*_result.jsonl`（`{src_row_idx, verdict, reason}`）。
verdict=确定 留主表；verdict=存疑 → J/T 置空 + 日志「复核存疑：<原因>」下放特殊表
（主表零判断型错配）。跑完后 `run_pipeline --with-agent-results` 自动 `apply_verify`。

### 3. 学校改名网查（harness 侧，需 WebSearch）

改名检测 + 网查是最后一步，见 `research/RUN_RENAME.md`：harness 对改名表每所学校
WebSearch 查询（旧名/更名/转设/同源），写入 `research/<school>.md`，再由
`rename_websearch.merge_remark`（幂等）合并备注。

## 数据质量审计硬门（iteration-2 Slice C / issue #12，spec V5-3）

**完成前必跑**——pytest 全绿 ≠ 产出正确（陷阱 B）。宣称"完成"前必须对**真实产出 xlsx**
跑数据质量审计脚本，exit 0 才算完成门：

```bash
.venv/bin/python -m scripts.audit_output \
    --output-dir output --data-dir data \
    --intermediate-dir intermediate --semantic-dir semantic-match
# exit 0 = 通过；exit 1 = 定位修复后重跑
```

五检查（`scripts/audit_output.py`）：

| # | 检查 | 说明 |
|---|------|------|
| 0 | 复核覆盖完备性 | 主表每个判断型匹配行（粗筛/语义日志）的 src_row_idx 必须出现在 `semantic-match/verify_*_result.jsonl` 且 verdict=确定；jsonl 缺失 → fail「复核未派发」 |
| 1 | 每本科专业行匹配日志非空 | 0 缺失 |
| 2 | 每张产出表 0 全空数据行 | 分层/扁平/新增/被删/改名/新增校/停招消失/特殊 |
| 3 | 字段映射回归 | 所有产出表含至少 1 行数据（writer header 锁定在 test_output_quality） |
| 4 | J/T 一致性（精度区分） | matched 行比近三年源值；新增估算行比 `round(估算,2)`（容差 0.011） |

副作用产物 `output/audit_sample.xlsx`（随机 30 条主表行）供人工语义核验，**不计 exit 0**
（`@manual`）。

## 验收标准（Slice 7 / issue #8）

- [x] `pytest` exit 0，覆盖率 ≥80%（实测 96%）。
- [x] `run_pipeline` 确定性链在小样本 e2e 通过（`tests/test_e2e.py`）。
- [x] 每个大绿本本科专业行 100% 归类（匹配 / 新增 / 特殊 / 改名占位）。
- [x] 专科行全排除（fixture + 真实数据 25472 = 23887 常规 + 1585 提前，专科 181 排除）。
- [x] 分层与扁平同源一致（同一 MatchResult 列表，J/T/日志逐行相等）。
- [x] 三源哈希不变（`tests/test_immutability.py` + 运行前后 `assert_unchanged`）。
- [x] README 完整；skill 草稿存在（`skills/cee-admission-match/SKILL.md`）。

### 真实数据确定性跑归类分布（2026-06-23）

| 归类 | 行数 | 口径 |
|------|------|------|
| 大绿本本科专业总数 | 25,472 | 常规批 23,887 + 提前批AB 1,585 |
| 严格匹配 | 14,852 | 58.3% |
| 粗筛自动接受 | 4,775 | 累计 77.1% |
| Stage2 待 agent | 5,845 | 已生成 293 批 prompt |
| 新增专业（估算） | 4,363 | 退化 0/1/2 |
| 特殊情况 | 1,482 | 待 Stage2 agent 收敛 |
| 被删旧专业（上界） | 16,829 | 待改名 agent 排除改名校 |
| 新增校 / 停招消失校 | 59 / 58 | 改名候选 59 所 |

注：未应用 Stage2/改名 agent 时，匹配置为严格+粗筛口径，被删/新增校为上界。

## 年度复用

本管线设计为**年度可复用**：每年换新三源 xlsx 后，按以下步骤复跑。

1. **替换 `data/` 下三个 xlsx**（文件名保持不变；若改名则同步改 `scripts/constants.py`
   的列索引与 `run_pipeline.SOURCE_FILES`）。
2. **更新一段线**：编辑 `scripts/constants.py` 的 `ONE_LINE`（新年份的山东一段线），
   并更新 `tests/baseline_hashes.py` 的三源 SHA256 基线。
3. **跑确定性链**：`.venv/bin/python -m scripts.run_pipeline`，确认源哈希不变、
   归类分布合理。
4. **harness 侧 Stage2 agent**：按 `semantic-match/RUN.md` 派发语义匹配。
5. **harness 侧判断型复核（iteration-2 / v5）**：按 `semantic-match/RUN_VERIFY.md`
   派发**判断型二次复核**（粗筛 + 语义全部须复核，~5500 条 ÷ 20 ≈ 275 批）——主表零判断型
   错配的硬门（spec V5-0 precision-first）。
6. **harness 侧改名网查**：按 `research/RUN_RENAME.md` 派发改名检测 + 网查。
7. **回填**：`run_pipeline --with-agent-results` 产出最终主表 + 边界表（apply Stage2 +
   复核 + 改名）。
8. **审计硬门（年度复用前必跑，spec V5-3）**：

   ```bash
   .venv/bin/python -m scripts.audit_output \
       --output-dir output --data-dir data \
       --intermediate-dir intermediate --semantic-dir semantic-match
   # 必须 exit 0 才算完成（陷阱 B：pytest 全绿 ≠ 真实产出正确）
   ```

   或一键端到端验收：`.venv/bin/python -m scripts.run_iter2_acceptance`（重跑管线 +
   审计，exit 0 即过；可作 `pytest -m manual` 单点跑）。

可复用的核心步骤已沉淀为 skill 草稿 `skills/cee-admission-match/SKILL.md`
（合并口径 / 归一化 / 六要素 / 核心名粗筛 / agent prompt / 边界三表 / 估算退化 / 改名网查）。

## 设计与计划

- 设计 spec：`docs/superpowers/specs/2026-06-23-cee-admission-match-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-23-cee-admission-match.md`

## 范围与口径

- 范围：仅 提前批 + 常规批一段、仅本科；专科全排除。
- 提前批 AB 类无差别，合并；近三年 825 `提前批` 弃用（先重叠验证，见 `verify_825.py`）。
- 选科 = 非差异化（日志记「选科政策漂移，已忽略」）；招生类别 = 差异化（普通/中外合作/地方专项…）。
- 输出不覆盖大绿本原列（行尾追加 J/T/日志 3 列）。
- 命名：文件/目录 UTF-8；commit 用 conventional commits、无 Co-Authored-By。
