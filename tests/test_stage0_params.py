"""代码通用化参数化测试（#6/#7/#8）—— build_history_early 接受
one_line / batches / low_cols 参数，覆盖默认（不特化当前数据）。

agent 跑 run_pipeline 时通过 CLI 传这些参数（--one-line / --supplement-batches /
--supplement-low-cols），不用改代码。这些测试锁住「参数 override 真生效」。
"""

from __future__ import annotations

from scripts import stage0_merge


def _tq_row(
    batch: str = "本科提前批A类", school: str = "X大学", major: str = "数学", low=500
) -> tuple:
    """构造补充表行：低分放在默认列 10/14/18（TQ_LOW_2025/2024/2023）。"""
    row = [""] * 19
    row[0] = batch
    row[3] = school
    row[5] = major
    row[6] = "物理"
    row[10] = low
    row[14] = low
    row[18] = low
    return tuple(row)


def test_build_history_early_one_line_override() -> None:
    """#7: one_line 参数覆盖 constants.ONE_LINE（agent 传参，不改代码）。"""
    rows = [_tq_row(low=500)]
    out_default = stage0_merge.build_history_early(rows)  # 默认 ONE_LINE
    out_override = stage0_merge.build_history_early(
        rows, one_line={2025: 400, 2024: 400, 2023: 400}
    )
    # override 一段线 400 < 默认（441/444/443）→ 录取分 − 一段线 更大 → J 更大
    assert out_default[0]["J"] is not None
    assert out_override[0]["J"] > out_default[0]["J"]


def test_build_history_early_batches_override() -> None:
    """#8: batches 参数过滤补充表要取的批次（不写死提前批 A/B）。"""
    rows = [_tq_row(batch="本科提前批A类"), _tq_row(batch="自定义特殊批")]
    # 默认只取提前批 A/B → 1 行（「自定义特殊批」被排除）
    out_default = stage0_merge.build_history_early(rows)
    assert len(out_default) == 1
    # override batches 含「自定义特殊批」→ 2 行
    out_override = stage0_merge.build_history_early(
        rows, batches=frozenset({"本科提前批A类", "自定义特殊批"})
    )
    assert len(out_override) == 2


def test_build_history_early_low_cols_override() -> None:
    """#8: low_cols 参数指定低分列位置（补充表列顺序不同时覆盖）。"""
    row = list(_tq_row(low=500))
    row[7] = 520  # 把低分也放在列 7（模拟列顺序不同的补充表）
    rows = [tuple(row)]
    # override low_cols 读列 7 = 520
    out = stage0_merge.build_history_early(
        rows,
        one_line={2025: 400, 2024: 400, 2023: 400},
        low_cols={2025: 7, 2024: 7, 2023: 7},
    )
    assert out[0]["J"] == 120.0  # 520 − 400


def test_build_history_early_defaults_match_current_behavior() -> None:
    """参数全 None = 当前行为（提前批 A/B + TQ 列 + ONE_LINE），向后兼容。"""
    rows = [
        _tq_row(batch="本科提前批A类", low=500),
        _tq_row(batch="本科提前批B类", low=480),
    ]
    out = stage0_merge.build_history_early(rows)  # 全默认
    assert len(out) == 2
    assert all(r["J"] is not None for r in out)  # 线差都算出来了


def test_build_dagluben_early_batches_override() -> None:
    """#9: build_dagluben_early batches 参数覆盖（大绿本批次名变化时）。"""
    from scripts.constants import BATCH_EARLY_A

    def _dl_row(batch: str) -> tuple:
        row = [""] * 12
        row[0] = batch
        row[3] = "X大学"
        row[4] = "01"  # 代号
        row[5] = "数学"  # 名称
        return tuple(row)

    rows = [_dl_row(BATCH_EARLY_A), _dl_row("自定义特殊批")]
    out_default = stage0_merge.build_dagluben_early(rows)
    assert len(out_default) == 1  # 默认只取 提前批 A/B + 飞行
    out_override = stage0_merge.build_dagluben_early(
        rows, batches=frozenset({BATCH_EARLY_A, "自定义特殊批"})
    )
    assert len(out_override) == 2  # override 含「自定义特殊批」
