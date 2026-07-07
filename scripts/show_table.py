"""读 xlsx 表的简单 CLI——agent 查数据不用每次现写 openpyxl 代码。

用法:
    python -m scripts.show_table <xlsx> [--head N] [--sheet NAME] [--grep 词]

打印到终端（tab 分隔）。``--head`` 只看前 N 行；``--grep`` 只打印含关键词的行
（不限于前 N）。sheet 默认第一个。

专为 skill 执行时查产出表 / 中间数据用，不是管线一环（不读入任何业务逻辑）。
"""

from __future__ import annotations

import argparse

import openpyxl


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.show_table",
        description="读 xlsx 表内容打印到终端（agent 查数据用）。",
    )
    parser.add_argument("xlsx", help="xlsx 文件路径")
    parser.add_argument(
        "--head", type=int, default=20, help="只看前 N 行（默认 20；--grep 时忽略）"
    )
    parser.add_argument("--sheet", default=None, help="sheet 名（默认第一个）")
    parser.add_argument("--grep", default=None, help="只打印含该关键词的行")
    args = parser.parse_args()

    wb = openpyxl.load_workbook(args.xlsx, read_only=True, data_only=True)
    try:
        ws = wb[args.sheet] if args.sheet else wb.active
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            cells = ["" if v is None else str(v) for v in row]
            line = "\t".join(cells)
            if args.grep:
                if args.grep in line:
                    print(line)
                continue
            if i >= args.head:
                break
            print(line)
    finally:
        wb.close()


if __name__ == "__main__":
    main()
