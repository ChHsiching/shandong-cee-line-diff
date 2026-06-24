# 管线阶段与参考（REFERENCE）

> 本文件是 `shandong-cee-line-diff` skill 的**详细参考**——SKILL.md 自主启动流程执行到具体阶段时按需查阅。

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
- `core_of`：去**全部**括号得核心名——**循环** `re.sub(r"\([^()]*\)","",s)` 直到无括号残留（嵌套如「1+3(一年国内加三年芬兰)」单次 sub 只剥内层留外层致污染，必须循环）。
- `diff_brackets`：抽差异化括号 `[("性别"|"合作"|"其他", value)]`。

### Stage 1 严格匹配

- 键 = `(基础校名, normalise_cat(招生类别), 剥忽略类括号后的归一化全名)`。
- 招生类别：`普通计划` / `""` 折叠为同一普通轨道；其他（中外合作/地方专项…）须精确匹配。
- 命中率 ~58%。

### Stage 1.5 核心名粗筛

- 键 = `(基础校名, normalise_cat(招生类别), 核心名)`。
- 唯一候选 → 自动接受（签名全等禁用，实测 0%）；多候选 → 括号子集消歧
  （候选每个 diff_bracket 均是大绿本全名子串 → 兼容；唯一兼容 → 接受）。
- 选科漂移不阻断，日志记「选科政策漂移，已忽略」。
- 累计自动 ~77%。

### Stage 2 agent 语义匹配（harness 侧，禁脚本）

- 对 Stage 1.5 未命中者，按 `(校名, 招生类别)` + 核心名兼容性（精确或子串包含）预筛候选。
- 批次 prompt（`build_batches` + `write_prompts`，批大小 20）：每 item 含大绿本专业全信息
  + 候选列表 + 输出 schema。
- agent 输出 `batch_NN_result.jsonl`，每行 `{src_row_idx, school, major, match, J, T, reason}`。
- **契约硬拒**：`match` null 或逐字 ∈ 候选集；J/T 必须与所选候选原样一致；每 src_row_idx
  至多一行；reason 非空 ≤30 字。违反抛 `Stage2ContractError`（带 file:line）。

### Stage 2.5 判断型二次复核（harness 侧 agent，precision-first）

- **所有判断型匹配**（粗筛 + 语义，约 5500 条）**必须经二次 agent 复核**才能留主表。
- `verify_judgment.py`（`build_verify_batches` + `write_prompts`）产批次 prompt；
  harness 按 `RUN_VERIFY.md` 派发 → `verify_*_result.jsonl`（`{src_row_idx, verdict, reason}`）。
- `apply_verify`：verdict=确定 → 保留主表；verdict=存疑 → 移特殊表（日志「复核存疑：<原因>」）。

### Stage 3 边界

- **新增专业估算**（逐级退化）：退化0 同校同选科 J/T 均值 → 退化1 同校全专业均值 → 退化2 整校无历史 value=None。
- **新方向估算**（消化「无法匹配」大头）：核心名在近三年同校、仅方向/班级/校区不同的 2026 专业 → 同校同核心名/同选科历史均值估 J/T，归新增专业类（**不丢到无法匹配**）。
- **改名检测 + 联动**（agent + WebSearch）：大绿本独有校 × 历史独有校，字符串相似度仅预筛；**最终须语义判断 + WebSearch 网查**（D1：查**所有**消失/新增校含独立学院转设，不止相似度候选——实证 13→28）。改名表支持**多旧校名**（合并记全部前身）。**联动**：Stage0 建新名↔旧名映射，主表把旧名校近三年线差并入新名校（改名校专业不再留空）。
- **被删旧专业**：近三年有 + 该校在 2026 大绿本 + 2026 缺 + 非改名校（先改名后被删）。**排除校不在 2026 者**（归停招消失范畴，勿混入）。
- **飞行/特殊**：飞行技术(军队) 不成 → 特殊；新方向估算后剩余仍无法匹配 → 特殊。

### 改名网查（harness 侧 WebSearch，最后一步）

- 对改名表每所学校 WebSearch；写 `research/<school>.md`（带时间戳）。
- `merge_remark`（幂等）：`manual_reviewed=True` 不覆盖。
- 改名联动应用后，改名校 2026 专业已并入旧名历史（J/T 填值，不再留空）；网查备注仅供溯源，`manual_reviewed=True` 锁定不覆盖。

## 数据质量审计硬门（spec V5-3）

**完成前必跑**——pytest 全绿 ≠ 产出正确。必须对**真实产出 xlsx** 跑审计，**exit 0 才算完成门**：

```bash
.venv/bin/python -m scripts.audit_output \
    --output-dir output --data-dir data \
    --intermediate-dir intermediate --semantic-dir semantic-match
```

| # | 检查 | 说明 |
|---|------|------|
| 0 | 复核覆盖完备性 | 判断型匹配行（匹配阶段 ∈ {粗筛匹配, 语义匹配}）须在 `verify_*_result.jsonl` 且 verdict=确定 |
| 1 | 匹配阶段非空 | 每本科专业行匹配阶段列非空（按列名读） |
| 2 | 0 全空数据行 | 每张产出表无全空行 |
| 3 | 字段映射回归 | 所有产出表含 ≥1 行数据 |
| 4 | J/T 一致性 | matched 比近三年源值；新增估算比 round(估算,2)（容差 0.011） |
| 5 | 改名覆盖 | 每个消失/新增校都有 WebSearch 网查记录（`research/*.md`）；改名校已入改名表并应用联动（旧名移出停招消失） |
| 6 | 核心名干净 | 主表/边界 核心名列无残留括号（core_of 嵌套循环已修，污染=0） |
| 7 | 无法匹配收敛 | 无法匹配仅剩真无近三年同核心名者（新方向估算已消化变体；复核存疑仅剩实质冲突） |

副作用：`output/audit_sample.xlsx`（随机 30 条）供人工语义核验，不计 exit 0。

## 故障排查

| 症状 | 处理 |
|------|------|
| `RuntimeError: source file changed` | 源被误改；从 git 恢复 `data/`，重跑 |
| Stage2 契约违反 | 看 `Stage2ContractError` 的 file:line，修该 jsonl 行后重跑 |
| 匹配率远低于 77% | 检查归一化（校名类别剥离/忽略类括号）；核心名粗筛口径 |
| 被删数异常大 | 改名 agent 未跑（被删为上界）；先跑改名检测 |
| 审计 `judgmental_coverage` FAIL | `verify_*_result.jsonl` 缺失或 verdict≠确定；派发复核后重跑 |
| 审计 `jt_consistency` FAIL | matched 比源值不等 → 修 Stage2 jsonl J/T；估算不等 → 查 estimate round(2) |
| 审计 `no_empty_rows` FAIL | 字段映射回归（陷阱 A）：查 writer 字段名→列名 remap |
