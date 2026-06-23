# 山东省高考录取数据匹配整理 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **ecc:plan 确认门**：每个 slice 实施前重述需求+风险，WAIT 用户确认再动代码。

**Goal:** 把 2026 大绿本本科专业与近三年录取线差按专业名语义一一对应，产出带线差+日志的整理表与边界表，并沉淀可年度复用 skill。

**Architecture:** 只读三段式数据管线——Stage0 预处理合并（脚本）→ Stage1 严格（脚本）→ Stage1.5 核心名粗筛自动接受（脚本）→ Stage2 agent 语义（禁脚本）→ Stage3 边界（新增估算/被删/特殊）→ 学校改名分支（agent+WebSearch）→ 输出 + skill。源文件永不修改（哈希校验）。

**Tech Stack:** Python 3.14.2 + `.venv`（实测：pytest 9.1.1 + openpyxl 3.1.5 已装）；agent 经 Agent 工具并行；WebSearch 用于改名网查。

## Plan v2 修订（code-architect + tdd-guide 把关后，**绑定**，覆盖前文冲突处）

**verify_command**：`.venv/bin/python -m pytest`（统一）。agent/WebSearch/skill 相关测试标 `@pytest.mark.manual`，CI 跑 `-m "not manual"`。

**新增/调整文件**（覆盖下文 File Structure）：
- `scripts/constants.py`：一段线 `{2023:443,2024:444,2025:441}`；列索引（近三年 J=idx9/T=idx19/2023线差 K=idx10/2024线差 L=idx11/2025线差 M=idx12；补充表低分 25=idx10/24=idx14/23=idx18）；批次字符串常量；专科小标题关键词；`FLIGHT_BATCH='3.提前批—飞行技术(军队)'`。
- `scripts/models.py`：TypedDict 契约 `HistoryRow`/`DaglubenRow`/`MatchResult`/`EstimateResult`。
- `scripts/write_outputs.py`（主表分层+扁平 J/T/日志回填）与 `scripts/write_edge_tables.py`（边界三表+改名表）**分离**，避免跨 Slice 1/5/6 改同一文件。
- `scripts/stage2_apply.py`：agent jsonl → 主表回填纯函数（TDD）。
- `pytest.ini`：`testpaths=tests`、注册 `manual` marker、`addopts=--cov=scripts --cov-fail-under=80 -m "not manual"`。
- `tests/conftest.py`：rootdir、共享 fixture（`tmp_xlsx` factory、最小分层结构 workbook）。
- `tests/baseline_hashes.py`：三源 sha256 常量（Task 1.1 `git mv` **后**采集，供 Task 1.7 不变性契约）。
- `intermediate/` 文件加 slice 前缀（`s1_history_regular.csv`、`s2_unified_history.csv`、`s5_post_stage2_unmatched.json`…），防并行覆盖。

**接口契约补强**（覆盖下文接口契约块）：
- `split_school` 无类别返回 `("校名","")`；`diff_brackets` 无括号返回 `[]`。
- `line_diff.compute(low_scores_by_year, provincial_lines)`（重命名防两 dict 传反；`provincial_lines` 取自 constants）。
- `estimate(new_major_row, school_history) -> EstimateResult{value:float|None, level:0|1|2, log:str, n:int}`（TypedDict 替代裸 tuple）。
- 各 stage 返回具名类型 `list[MatchResult]`/`list[HistoryRow]`/`list[DaglubenRow]`。

**TDD 纪律（tdd-guide）**：
- 小样本构造 = **RED 判据**；「行数 N / 命中率 X%」= **smoke 层**（不参与 RED，归 Task 7.1 端到端契约），杜绝「先实现后补测」。
- Slice 4（agent 语义）/ 6.2（改名检测）/ 6.3（WebSearch）= **不可纯 TDD**：编排/格式化纯函数正常 TDD；匹配/网查用 契约测试 + 黄金样例回归集（Slice 4 预标 10-20 条已知正确配对，命中率 ≥80% 为 regression PASS）+ `@pytest.mark.manual` 抽样人工核验，不阻断 CI。

**依赖顺序修正（code-architect CRITICAL）**：
- **Slice 6 内部：先 Task 6.2 改名检测 → 后 Task 6.1 边界（被删/飞行/特殊）**。理由：被删判定须先识别改名校，否则改名校历史专业被误塞被删表。
- Slice 5（新增）→ Slice 6 交接：`intermediate/s5_post_stage2_unmatched.json`（Stage2 仍未归类的大绿本专业清单）。
- 近三年「可用年份数」= K/L/M（2023/2024/2025线差）非空计数（列已确认存在），常规批与提前批口径统一。

**幂等（code-architect）**：改名网查产物 `research/<school>.md` 带时间戳；改名表备注列加 `manual_reviewed` 布尔——重跑不覆盖已人工编辑备注。

**Python 3.14 烟雾**：Task 1.2 前置 `import openpyxl; openpyxl.load_workbook(data/近三年..., read_only=True)` 确认无 DeprecationWarning。

## Global Constraints（所有 task 隐含遵守，逐字来自 spec §3/§4）

- 一段线：2023=443 / 2024=444 / 2025=441。
- 提前批线差 = 录取低分 − 当年一段线；统计线差 = 可用年份均值（单年用该年）；标准差同口径（单年空）。
- 三源文件字节级不改（读取前后 SHA256 校验）。
- 范围：仅 提前批 + 常规批一段、仅本科；专科全排除。
- 提前批 AB 类无差别，合并；近三年 825 `提前批` 弃用（先重叠验证）。
- 选科 = 非差异化；招生类别 = 差异化（普通/中外合作/地方专项/走读/边防预科…）。
- 输出不覆盖大绿本原列。
- 命名：文件/目录 UTF-8；commit 用 conventional commits、无 Co-Authored-By；`git add` 与 `git commit` 分两次 Bash 调用（PreToolUse hook 会拦含 `git commit` 的复合命令）。

## File Structure（锁定分解）

```
cee-admission-data/
├── data/                          # 三源 xlsx（git mv 自根目录；只读）
├── scripts/
│   ├── io_source.py               # 只读加载 + 哈希校验（所有脚本的入口依赖）
│   ├── normalize.py               # NFKC/去空白/校名类别剥离/剥忽略类括号/核心名/差异化抽取（纯函数）
│   ├── line_diff.py               # 提前批线差计算（纯函数）
│   ├── stage0_merge.py            # Stage0：统一历史表 + 大绿本本科专业表
│   ├── stage1_strict.py           # Stage1 严格匹配
│   ├── stage1_5_coarse.py         # Stage1.5 核心名粗筛自动接受
│   ├── stage3_newmajor.py         # 新增专业估算（逐级退化）
│   ├── stage3_edges.py            # 被删/飞行/特殊 + 改名检测
│   ├── rename_websearch.py        # 改名网查写备注（最后一步）
│   ├── write_outputs.py           # 分层版 + 扁平版 + 各边界表
│   └── run_pipeline.py            # 串联全管线
├── semantic-match/                # agent 语义匹配产物（jsonl）
├── research/                      # 改名网查原始记录
├── intermediate/                  # 统一历史表、大绿本本科专业表（parquet/csv）
├── output/                        # 最终产物
└── tests/                         # pytest（纯函数单测 + 管线契约快照）
```

接口契约（纯函数，后续 task 依赖这些签名）：
- `normalize.nfk(s) -> str`
- `normalize.split_school(s) -> tuple[str, str]`  # (base校名, 招生类别)
- `normalize.strip_ignore_brackets(name) -> str`
- `normalize.core_of(name) -> str`
- `normalize.diff_brackets(name) -> list[tuple[str,str]]`  # [("性别"|"合作"|"其他", value)]
- `line_diff.compute(year_lows: dict[int,int|None], one_lines: dict[int,int]) -> tuple[float|None, float|None]`  # (统计线差, 标准差)
- `io_source.load_source(path) -> workbook`；`io_source.sha256(path) -> str`；`io_source.assert_unchanged(path, before_hash)`

---

## Slice 1 — 骨架 + 常规批严格匹配端到端（tracer，issue #2）

**风险**：源文件被误改（高代价）；分层结构判错专业行；归一化漏剥类别导致大批漏配。
**需求重述**：tracer 最小通路——常规批一段 → 严格匹配 → 分层+扁平输出，源只读。

### Task 1.1：骨架与源迁移
**Files:** Create `data/`(git mv 三源)、`scripts/`、`tests/`、`intermediate/`、`output/`、`README.md`
- [ ] `mkdir -p scripts tests intermediate output semantic-match research`
- [ ] `git mv 山东省2026年大绿本招生计划.xlsx 近三年学校批次专业线差统计.xlsx 山东省高考提前批录取数据.xlsx data/`
- [ ] 写 `README.md`（项目说明 + 目录 + 源文件只读铁律）
- [ ] Commit：`git add` 后单独 `git commit -m "chore: scaffold project layout and relocate sources to data"`

### Task 1.2：io_source.py（只读 + 哈希校验）—— TDD
**Files:** `scripts/io_source.py`、`tests/test_io_source.py`
**Produces:** `load_source`, `sha256`, `assert_unchanged`
- [ ] 写失败测试：给定一个最小 xlsx，`sha256` 稳定；`assert_unchanged` 在哈希一致时静默、不一致时抛 `RuntimeError`；`load_source` 返回 read_only workbook。
- [ ] 跑 `pytest tests/test_io_source.py -v` → FAIL（未实现）。
- [ ] 实现 `io_source.py`：`openpyxl.load_workbook(read_only=True, data_only=True)`；`hashlib.sha256`。
- [ ] 跑 → PASS。
- [ ] Commit `feat(io): add read-only source loader with sha256 immutability guard`

### Task 1.3：normalize.py（归一化纯函数）—— TDD
**Files:** `scripts/normalize.py`、`tests/test_normalize.py`
**Produces:** `nfk`, `split_school`, `strip_ignore_brackets`, `core_of`, `diff_brackets`（prototype 已验证，内联）
- [ ] 写失败测试（含实证样例）：`split_school("三亚学院(中外合作办学)") == ("三亚学院","中外合作办学")`；`split_school("山东中医药大学(地方专项计划)") == ("山东中医药大学","地方专项计划")`；`strip_ignore_brackets("临床医学(色盲考生不予录取)") == "临床医学"`；`strip_ignore_brackets("数学与应用数学(男,通用标准合格)")` 保留性别括号；`core_of("经济学类(经济学、国民经济管理)") == "经济学类"`；`diff_brackets("理科试验班类(严济慈物理学拔尖人才班)(含物理学)")` 性别=""、合作=""、其他含"严济慈…"。
- [ ] 跑 → FAIL。
- [ ] 实现（直接采用 prototype 验证过的逻辑：NFKC + `re.sub(r"\s+","")`；类别关键词 `合作|专项|走读|边防|预科|民族班|定向`；IGNORE 词表；GENDER 男/女）。来源：prototype（任务3）。
- [ ] 跑 → PASS。
- [ ] Commit `feat(normalize): add nfk/school-split/ignore-strip/core/diff pure functions`

### Task 1.4：stage0_merge.py（常规批一段）—— TDD
**Files:** `scripts/stage0_merge.py`、`tests/test_stage0.py`
**Consumes:** `io_source`, `normalize`；**Produces:** `build_history_regular(wb_j3) -> list[dict]`、`build_dagluben_regular(wb_dl) -> list[dict]`
- [ ] 写失败测试：`build_history_regular` 过滤 `batch=="常规批一段线"`，行数 28269，每行含 school(base)/cat/major/stripped/core/J/T；`build_dagluben_regular` 取 `批次=="4.常规批"` 且 E&F 非空，排除小标题含「专科」，行数 ≈ 23887（专科在常规批为 0，应等于 23887）。
- [ ] 跑 → FAIL。
- [ ] 实现：按 normalize 处理 schoolname/majorname；J=列10、T=列20（0-based 9/19）。
- [ ] 跑 → PASS。
- [ ] 落 `intermediate/history_regular.csv` + `intermediate/dagluben_regular.csv`。
- [ ] Commit `feat(stage0): build regular-batch history and dagluben tables`

### Task 1.5：stage1_strict.py —— TDD
**Files:** `scripts/stage1_strict.py`、`tests/test_stage1.py`
**Consumes:** stage0 产物；**Produces:** `match_strict(dagluben, history) -> list[match_result]`，键 `(school, cat, stripped)`
- [ ] 写失败测试：构造 1 命中 + 1 未命中，断言命中取 J/T、日志「严格匹配：归一化专业名+招生类别一致」，未命中标 `unmatched`。
- [ ] 跑 → FAIL → 实现 → PASS。
- [ ] 跑全量：常规批严格命中率 ~57.8%（断言在 55%-61%）。
- [ ] Commit `feat(stage1): strict match on school+category+stripped-name`

### Task 1.6：write_outputs.py（分层+扁平，常规批部分）
**Files:** `scripts/write_outputs.py`、`tests/test_outputs.py`
- [ ] 测试：分层版复制大绿本全部行 + 行尾 3 列，仅专业行填值，非专业行留空，原列未被覆盖（列数 = 12+3）；扁平版仅专业行。
- [ ] 实现 → PASS。
- [ ] 落 `output/大绿本_附线差_分层版.xlsx`、`output/大绿本_附线差_扁平版.xlsx`（常规批部分）。
- [ ] Commit `feat(output): hierarchical + flat outputs for regular batch`

### Task 1.7：源哈希不变性契约测试
- [ ] `tests/test_immutability.py`：跑前后对三源 `sha256` 比对基线（基线哈希写入测试常量），不一致即 FAIL。
- [ ] Commit `test: add source-file immutability contract`

**Slice 1 完成标志**：常规批严格匹配 ~57.8%、源哈希不变、分层+扁平产出。→ 更新 issue #2。

---

## Slice 2 — 提前批并入（issue #3，blocked by #2）

**风险**：825 弃用误丢独有数据；线差单年/多年口径错。
**需求重述**：补充表算线差并入、AB 合并、弃 825（先验证）、删专科提前批。

### Task 2.1：line_diff.py —— TDD
**Files:** `scripts/line_diff.py`、`tests/test_line_diff.py`
**Produces:** `compute(year_lows, one_lines) -> (统计线差, 标准差)`
- [ ] 测试：`compute({2025:524,2024:568,2023:500},{2025:441,2024:444,2023:443})` → 线差 {83,124,57}，统计线差=mean≈88.0，标准差≈std；单年 `{2025:500}:{441:441}` → (59, None)；全无 → (None,None)。
- [ ] FAIL → 实现（`statistics.mean`/`pstdev`，过滤 None）→ PASS。
- [ ] Commit `feat(line-diff): compute statistical line-diff and stddev from low scores`

### Task 2.2：stage0_merge 扩展提前批
**Files:** 修改 `scripts/stage0_merge.py`；`tests/test_stage0.py`
**Produces:** `build_history_early(wb_tq) -> list[dict]`
- [ ] 测试：过滤 `本科提前批A类+B类`（删专科提前批），行数 1707，batch 统一 `提前批`，每行 J/T 由 `line_diff.compute` 算出，保留 `来源表`。
- [ ] 实现：低分列 25=idx10/24=idx14/23=idx18（0-based）。→ PASS。
- [ ] Commit `feat(stage0): merge early-batch supplement with computed line-diff`

### Task 2.3：825 重叠验证
**Files:** `scripts/verify_825.py`、`tests/test_verify_825.py`
- [ ] 测试 + 实现：取近三年 `提前批` 825 行的 `(schoolcode, nfk(majorname))`，判断是否全部 ∈ 补充表（本科）的同键集；输出独有行到 `intermediate/j3_early_only.csv`。
- [ ] 断言：独有行数 = 0 或少量（若有，单列待人工，不静默丢）。报告独有数。
- [ ] Commit `feat(stage0): verify 825 early-batch rows are covered by supplement`

### Task 2.4：统一历史表合并 + Stage1 覆盖提前批
- [ ] `build_unified_history() = history_regular + history_early`（≈29976）；大绿本提前批 A/B 合并池；Stage1 覆盖。
- [ ] 契约测试：统一历史表行数 ≈ 29976（±50）。
- [ ] Commit `feat(stage0-1): unified history table and early-batch strict match`

**Slice 2 完成标志**：统一历史表 ~29976、提前批线差口径正确、825 验证。→ 更新 issue #3。

---

## Slice 3 — Stage1.5 核心名粗筛 + 三规则固化（issue #4，blocked by #3）

**风险**：签名全等误用（prototype 已证 0%）；消歧误配。
**需求重述**：核心名唯一自动接受 + 括号子集消歧；专科排除、选科非差异化、招生类别差异化。

### Task 3.1：stage1_5_coarse.py —— TDD
**Files:** `scripts/stage1_5_coarse.py`、`tests/test_stage1_5.py`
**Consumes:** stage1 未命中 + `core_idx`；**Produces:** `match_coarse(unmatched, core_idx) -> (auto_accepted, still_unmatched)`
- [ ] 测试（实证样例）：人大「经济学类(经济学、国民经济管理、…)」core=经济学类，同校同类别唯一候选「经济学类」→ 自动接受；北航「数学与应用数学(拔尖学生培养计划)(含…)」→ 近三年「数学与应用数学(拔尖学生培养计划)」；多候选「计算机类(图灵…)」且候选括号非子集 → 仍 unmatched。
- [ ] FAIL → 实现（prototype 算法：核心名匹配；唯一→接受；多候选→候选 diff_brackets 的「性别/合作/其他」均 ⊂ 大绿本全名则兼容，唯一兼容→接受）→ PASS。
- [ ] 全量：累计自动 ~74.4%（断言 72%-78%）。
- [ ] Commit `feat(stage1-5): core-name coarse match with bracket-subset disambiguation`

### Task 3.2：专科排除完整化 + 选科/类别规则
**Files:** 修改 stage0/1/1.5；`tests/test_rules.py`
- [ ] 测试：大绿本小标题含「专科」181 行被排除（不进 dagluben 表）；选科差异不阻断匹配（构造 物理 vs 物理和化学 同核心名 → 仍匹配，日志含「选科政策漂移，已忽略」）；招生类别不同（普通 vs 中外合作）→ 不匹配（不同轨道）。
- [ ] 实现 → PASS。
- [ ] Commit `feat(rules): exclude 专科, non-differentiate 选科, differentiate 招生类别`

**Slice 3 完成标志**：累计自动 ~74.4%、专科排除、选科/类别规则。→ 更新 issue #4。

---

## Slice 4 — Stage2 agent 语义匹配（issue #5，blocked by #4）

**风险**：agent 误判、成本失控、并发不稳。**禁脚本**——此 slice 无纯函数 TDD，靠 prompt 设计 + 抽样人工核验 + 契约（每专业至多 1 对应）。
**需求重述**：对 Stage1.5 未命中者，并行 agent 逐个语义匹配。

### Task 4.1：agent 批处理编排
**Files:** `scripts/stage2_agent.py`（仅编排，不含匹配逻辑——匹配由 agent 思考）
- [ ] 设计：把未命中者按同校分组，每组连同同校候选集（按基础专业名预筛）打包成 agent prompt；并发派发（Agent 工具，批大小由 plan 时调参，起步 20/批）。
- [ ] Prompt 模板（写入 `semantic-match/prompt.md`）：给定大绿本专业（校名+全名+选科+招生类别）+ 候选列表，输出 JSON `{match: <候选majorname|null>, J, T, reason: "<六要素对齐理由，≤30字>"}`；强调六要素差异化（核心名/性别/合作/校区/方向/招生类别）、选科非差异化、忽略色盲等；至多 1 对应。
- [ ] 产物落 `semantic-match/batch_NN.jsonl`。

### Task 4.2：契约 + 抽检
- [ ] `tests/test_stage2_contract.py`：每条结果 `match` 要么 null 要么 ∈ 候选集；`reason` 非空；每大绿本专业至多 1 结果。
- [ ] 抽样 50 条人工核验（记录到 `semantic-match/spotcheck.md`）。
- [ ] Commit `feat(stage2): agent semantic matching orchestration and contract`

**Slice 4 完成标志**：未命中者由 agent 处理、契约成立、抽样通过。→ 更新 issue #5。

---

## Slice 5 — Stage3 新增专业估算（issue #6，blocked by #5）

**风险**：选科集合包含判定错；退化口径不透明。
**需求重述**：新增专业逐级退化估算。

### Task 5.1：stage3_newmajor.py —— TDD
**Files:** `scripts/stage3_newmajor.py`、`tests/test_newmajor.py`
**Produces:** `estimate(major, school_history) -> (value, level, log)`
- [ ] 测试：新专业选科「物理和化学」→ 退化0 取同校 subject 集合包含「物理和化学」的历史专业均值；无同选科→退化1 同校全专业均值；整校空→退化2 (None, 2, "新校/无历史，无法估算")。选科集合包含：近三年「物理 | 物理和化学」按 ` | ` 拆分后任一年份变体 ⊇ 新专业选科即纳入。
- [ ] FAIL → 实现 → PASS。
- [ ] Commit `feat(stage3): new-major estimation with graded fallback`

### Task 5.2：新增表 + 特殊标记
- [ ] 落 `output/新增专业.xlsx`（含估算值/退化级别/日志）；主产出对应行 J 填估算值、加标记列。
- [ ] Commit `feat(output): new-major table with estimation markers`

**Slice 5 完成标志**：新增估算退化链、新增表。→ 更新 issue #6。

---

## Slice 6 — 边界 + 学校改名分支（issue #7，blocked by #6）

> **执行顺序（v2 CRITICAL）**：先 **Task 6.2 改名检测** → 再 **Task 6.1 边界**（被删/飞行/特殊）→ Task 6.3 网查。被删判定须先识别改名校，否则改名校历史专业误塞被删表。下文任务编号保留，但按此顺序执行。

**风险**：改名误配（字符串相似度已证不可靠）；网查耗时。
**需求重述**：被删/飞行/特殊 + 改名检测+改名表+最后网查备注，不自动重匹配。

### Task 6.1：stage3_edges.py（被删/飞行/特殊）
**Files:** `scripts/stage3_edges.py`、`tests/test_edges.py`
- [ ] 测试：被删 = 近三年有 + 该校在 2026 大绿本存在 + 2026 缺；飞行技术 2 行归提前批池匹配不成→特殊；无法匹配→特殊。
- [ ] 实现 → 落 `output/被删旧专业.xlsx`、`output/停招消失校表.xlsx`、`output/特殊情况.xlsx`。
- [ ] Commit `feat(stage3): deleted/flight/special edge tables`

### Task 6.2：改名检测（agent 语义配对）
**Files:** `scripts/rename_detect.py`、`semantic-match/rename_prompt.md`
- [ ] 取 Stage0 后大绿本独有校(59) 与历史独有校(58)；agent 语义配对（**禁字符串相似度**），输出 `(新校名, 候选旧校名, 置信度)`。
- [ ] 落 `output/学校改名表.xlsx`（含该校 2026 本科专业数、备注占位）；改名校专业在主产出 J/T 留空 + 日志「疑似改名校(见改名表)，待人工核验」。
- [ ] 未配对大绿本独有校→`output/新增校表.xlsx`；历史独有校→`output/停招消失校表.xlsx`。
- [ ] Commit `feat(rename): agent-based rename pairing and rename table`

### Task 6.3：改名网查写备注（最后一步）
**Files:** `scripts/rename_websearch.py`、`research/`
- [ ] 全部其他数据处理完后，对改名表每所学校 WebSearch 查询（旧名/更名时间/是否同源），写入 `research/<school>.md` 与改名表备注列。
- [ ] Commit `feat(rename): web-search remarks for renamed schools`

**Slice 6 完成标志**：边界表齐全、改名表+网查备注、改名校专业 J 留空。→ 更新 issue #7。

---

## Slice 7 — 端到端验收 + skill 沉淀（issue #8，blocked by #7）

**风险**：分层/扁平不一致；skill 漏关键步骤。
**需求重述**：全管线跑通过验收；沉淀可复用 skill。

### Task 7.1：run_pipeline.py 串联 + 端到端契约
**Files:** `scripts/run_pipeline.py`、`tests/test_e2e.py`
- [ ] 串联 Stage0→1→1.5→2→3→边界→改名网查→输出。
- [ ] 端到端契约：三源哈希不变；每个本科专业行 100% 归类（匹配/新增/被删/特殊/改名）；专科 181 全排除；分层与扁平同源一致（同专业行 J/T/日志相等）；覆盖率统计打印。
- [ ] Commit `feat(pipeline): end-to-end runner with contract tests`

### Task 7.2：skill 沉淀（writing-great-skills）
- [ ] 调 `Skill("writing-great-skills")`，把稳定步骤（合并口径/校名类别剥离/六要素签名/核心名粗筛/语义 prompt/边界三表/估算退化/改名网查）写为可复用 skill（落 `.claude/skills/` 或项目 skills 目录）。
- [ ] 验证：skill 能独立运行（dry-run 说明）。
- [ ] Commit `feat(skill): distill reusable annual admission-match skill`

### Task 7.3：README + 收尾
- [ ] README 文档化目录、管线阶段、如何复跑、一段线表、验收标准。
- [ ] Commit `docs: document pipeline, usage, and acceptance`

**Slice 7 完成标志**：端到端过验收、skill 可复用、README 完整。→ 更新 issue #8。

---

## Self-Review（写完后自查）

**Spec 覆盖**：§3 决策表逐项 → Slice1(只读/归一化/严格/分层扁平)、Slice2(提前批线差/AB/弃825/删专科提前批)、Slice3(核心名粗筛/专科排除/选科/类别)、Slice4(agent语义)、Slice5(新增退化)、Slice6(被删/飞行/特殊/改名/网查)、Slice7(验收/skill)；§5 匹配键 → normalize.py + stage1/1.5；§6 各 Stage 对应 slice；§7 输出 → write_outputs + 各表；§8 目录 → File Structure；§9 日志 → 各 stage 日志串；§10 skill → Slice7；§12 验收 → Slice7 契约。无遗漏。
**占位扫描**：Stage2 agent 与改名检测为设计描述（非纯函数，spec 明确禁脚本/defer prompt），已给 prompt 模板与契约，非占位。
**类型一致**：`compute->(float|None,float|None)`、`split_school->(str,str)`、`diff_brackets->list[tuple[str,str]]` 跨 task 一致。

## Execution Handoff

计划已存 `docs/superpowers/plans/2026-06-23-cee-admission-match.md`。两种执行方式（Phase 1 只产出计划，执行属后续阶段）：

1. **Subagent-Driven（推荐）** — 每个 task 派新子代理、task 间复核、迭代快。
2. **Inline Execution** — 本会话内按 executing-plans 批量执行 + 检查点。

（ecc:plan 确认门：每个 slice 实施前重述需求+风险，等用户确认再动代码。）
