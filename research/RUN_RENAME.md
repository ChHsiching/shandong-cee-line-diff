# Slice 6 Task 6.3 — 学校改名网查运行指南（harness 侧）

> Slice 6 (issue #7) 按 Plan v2 CRITICAL 顺序的最后一步。本流程由拥有
> WebSearch 工具的会话执行——Python 脚本不能调用 WebSearch。网查是**人工辅助
> 步骤**：把改名表每所学校的实际改名/转设情况写入备注，供人工据此手动关联主
> 产出。**不进 CI**，**不自动重匹配**（spec §6 Stage 3 改名）。

## 前提（顺序）

1. **Task 6.2 改名检测已完成**：agent 已对 `semantic-match/rename_candidates.jsonl`
   做语义配对，产物 `semantic-match/rename_result.jsonl` 经
   `apply_rename` 读入，产出 `RenameRow` 列表 + `confirmed_new_schools` 集合。
2. **Task 6.1 边界已完成**：`deleted_majors(..., renamed_dgl_schools=confirmed)`
   已排除改名校；`output/被删旧专业.xlsx`、`output/新增校表.xlsx`、
   `output/停招消失校表.xlsx`、`output/特殊情况.xlsx` 已落盘。
3. **改名表已落盘**：`output/学校改名表.xlsx`（含 `manual_reviewed` 列，初值 False）。

若 6.2/6.1 未完成，**先回去做完**——网查依赖改名表行就绪。

## 步骤 1：生成网查查询（Python，无需 WebSearch）

对改名表每行构造查询字符串：

```python
from scripts.rename_detect import apply_rename, write_rename_prompt
from scripts.rename_websearch import format_query
# rename_rows, _ = apply_rename(...)  # 来自 Task 6.2

for row in rename_rows:
    q = format_query(row["new_school"], row["old_school"])
    print(q)   # 例：山东航空学院 滨州学院 更名 转设 前身 同源 高校
```

## 步骤 2：逐校 WebSearch + 写 research/<school>.md（harness 侧，需 WebSearch）

对每所改名校执行：

1. 用 `WebSearch` 工具查询 `format_query(new, old)` 的结果。
2. 把网查原始结果 + 整理摘要写入 `research/<new_school>.md`（UTF-8，带时间戳）：
   ```markdown
   # 山东航空学院（原滨州学院）网查记录

   - 查询时间：2026-06-23
   - 查询串：山东航空学院 滨州学院 更名 转设 前身 同源 高校
   - 网查结论：
     - 20XX 年 X 月，教育部批复「滨州学院」更名为「山东航空学院」…
     - 同源：是 / 否
     - 备注：…
   - 原始来源：[教育部公告 / 学校官网 / 新闻链接 …]
   ```
3. 时间戳文件名避免覆盖：`research/<new_school>_YYYYMMDD.md`。

## 步骤 3：合并备注到改名表（Python，幂等）

把每个 `research/<new_school>.md` 的摘要合并回改名表备注列：

```python
from pathlib import Path
from scripts.rename_websearch import merge_remark

for row in rename_rows:
    md_path = Path("research") / f"{row['new_school']}_YYYYMMDD.md"
    research_md = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    row = merge_remark(research_md, row)   # 返回新行, 不原地改
```

**幂等契约（Plan v2 binding）**：
- `merge_remark` **不覆盖** `manual_reviewed=True` 的备注——人工已核验的备注优先。
- 若 `research_md` 为空，保留原备注（网查无结果不清空已有内容）。
- 合并后 `manual_reviewed` 仍为 False（网查 ≠ 人工确认）；人工确认后自行置 True。

## 步骤 4：人工核验（manual）

人工逐行读 `output/学校改名表.xlsx` 的备注 + `research/<school>.md`：
- 若网查确认同源/改名：把对应主产出行（`is_rename_pending=True`）手动关联到旧校名历史
  （本 slice **不实现**自动重匹配，留 Slice 7 端到端）。
- 核验完把该行 `manual_reviewed` 置 True，后续重跑网查不会覆盖备注。

## 不变性

- 三源 xlsx 字节级未改（`tests/test_immutability.py` 始终守护）。
- 本流程只写 `research/*.md` 和 `output/学校改名表.xlsx` 的备注列，不碰 `data/`。
- `merge_remark` 对同一组输入幂等（重跑得到同样的备注）。

## 故障排查

| 症状 | 原因 | 处理 |
|------|------|------|
| WebSearch 无结果 | 校名过新/过冷门 | research md 写「网查无结果」，备注留空，人工另查 |
| 网查结论与 agent 配对矛盾 | agent 误配 / 网查误判 | 以网查为准；把该行 `is_rename` 置 False 并移出改名表（归新增校/停招校表） |
| 重跑覆盖了人工备注 | 未置 `manual_reviewed=True` | 人工核验后必须置 True；`merge_remark` 才会跳过 |
