# CLAUDE.md — shandong-cee-line-diff

本项目是 `shandong-cee-line-diff` skill 仓库——把山东省高考（CEE）大绿本招生计划与近三年录取线差按专业语义匹配整理成带线差/标准差/结构化日志的表。仓库根 `SKILL.md` 为 skill 入口，`scripts/` 为参考实现；`data/` 下三个原始 xlsx 由用户自行放入（不入库）。

## 数据资产（项目根目录）

| 文件 | 内容 |
|------|------|
| 山东省2026年大绿本招生计划.xlsx | 2026 年招生计划（大绿本） |
| 山东省高考提前批录取数据.xlsx | 高考提前批录取数据 |
| 近三年学校批次专业线差统计.xlsx | 近三年 学校 / 批次 / 专业 的线差统计 |

`.remember/` 为会话记忆缓冲目录，与代码无关。

## Harness 工具可用性（Phase Zero，实测日期 2026-06-23）

**铁律：唯一判据是「实际调用成功并拿到结果」。** 仅返回 `Tool loaded.`、或工具出现在 deferred 清单里，都【不算】证据。

本 harness 启动时只有 `ToolSearch` 是顶层可直接调用的工具；其余工具（Skill / Agent / AskUserQuestion / Read / Write / Edit / Bash / Glob / Grep / Task\* / Web\* / 各 MCP 工具等）都需先 `ToolSearch select:<Name>` 载入 schema，再用真实参数发起调用并确认返回结果，方可判为可用。

实测结论（已逐项真调）：

| 工具 | 载入 | 实测调用 | 结果 |
|------|------|----------|------|
| Skill | `ToolSearch select:Skill` | `Skill({ skill: "ecc:ecc-guide" })` | ✅ 返回 skill 正文 |
| Agent | `ToolSearch select:Agent` | `Agent({ subagent_type: "general-purpose", description: "probe", prompt: "只回复数字 42" })` | ✅ 返回 `42` |
| AskUserQuestion | `ToolSearch select:AskUserQuestion` | `AskUserQuestion({ questions: [...] })` | ✅ 用户成功作答 |

> 复测确认（2026-06-23 当日复跑）：三项 probe 结果与上表完全一致；一次 `ToolSearch select:Skill,Agent,AskUserQuestion`（逗号分隔）即可同时载入三者 schema——**批量 `select:` 已验证可用**，不必逐个载入。

### 正确调用范式

1. 需要某工具时，先 `ToolSearch select:<ToolName>[,<Other>...]` 载入其 schema。
2. 立即用真实参数发起调用，确认返回结果后再据此推进。
3. 不要把 `Tool loaded.` 当作「工具可用」的证据——它只表示 schema 已就绪。

## 交叉引用

- **派发子代理**（载入 Agent、校验 ECC `subagent_type` 名称、写自包含 prompt、区分 Agent 与 Task\*）→ 技能 `chhsich-skills:ecc-subagent-invocation`。
- **ECC agents / skills / commands / hooks / install profiles 总览**→ 命令 `/ecc:ecc-guide`（即技能 `ecc:ecc-guide`）。
- 本 harness 中 **Agent（子代理派发）** 与 **Task\*（todo 跟踪）** 是两套不同工具，不要混淆。

## 工作约定

- `.xlsx` 需借助库处理（如 pandas / openpyxl），勿在 Bash 里 `cat` 二进制 xlsx。
- 文件名与内容含中文，统一 UTF-8。
- 数据改动不可逆或外发前先与用户确认。

## Agent skills

### Issue tracker

GitHub Issues（`ChHsiching/shandong-cee-line-diff`，经 `gh` CLI）；外部 PR **不**作为 triage 面。详见 `docs/agents/issue-tracker.md`。

### Triage labels

五个 canonical role 与 label 字符串一一对应：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`。详见 `docs/agents/triage-labels.md`。

### Domain docs

Single-context —— 根目录单一 `CONTEXT.md` + `docs/adr/`。详见 `docs/agents/domain.md`。
