# 山东省高考录取数据匹配整理

把 2026 大绿本本科专业（主键）与近三年录取线差（外键）按专业名语义一一对应，
产出带线差与匹配日志的整理表（分层版 + 扁平版）与边界表，并沉淀可年度复用的 skill。

## 目录结构

```
cee-admission-data/
├── data/                  # 三个源 xlsx —— 只读，永不修改（哈希校验）
├── scripts/               # Stage0 预处理 / Stage1 严格 / Stage1.5 粗筛 / 输出
├── intermediate/          # 中间产物（统一历史表、大绿本本科专业表 CSV）
├── semantic-match/        # Stage2 agent 语义匹配工作产物（jsonl + prompt）
├── research/              # 学校改名网查记录（WebSearch 原始 + 整理）
├── output/                # 最终产物（分层版、扁平版、各边界表）
├── tests/                 # pytest：纯函数单测 + 管线契约
└── docs/superpowers/      # spec / 实施计划
```

## 源文件（`data/`，只读铁律）

| 文件 | 用途 |
|------|------|
| `山东省2026年大绿本招生计划.xlsx` | 2026 招生计划（主键源，分层结构） |
| `近三年学校批次专业线差统计.xlsx` | 近三年 学校/批次/专业 线差统计（常规批 J/T 源） |
| `山东省高考提前批录取数据.xlsx` | 提前批原始录取数据（提前批 J/T 计算源） |

**铁律：三个源文件字节级不可修改。** 管线读取前后均做 SHA256 校验
（`tests/test_immutability.py` 契约）。`data/` 下文件以只读方式打开
（`openpyxl.load_workbook(..., read_only=True)`）。

## 运行

```bash
.venv/bin/python -m pytest          # 全量测试，覆盖率 ≥80%
.venv/bin/python -m scripts.run_pipeline   # 端到端管线（Slice 7 起）
```

## 关键常量

- 一段线：2023 = 443 / 2024 = 444 / 2025 = 441（`scripts/constants.py`）
- 范围：仅 提前批 + 常规批一段、仅本科；专科全排除。

## 设计与计划

- 设计 spec：`docs/superpowers/specs/2026-06-23-cee-admission-match-design.md`
- 实施计划：`docs/superpowers/plans/2026-06-23-cee-admission-match.md`
