"""Stage 2 helper — let the agent emit results WITHOUT hand-writing JSON.

痛点（fresh-test handoff 2026-07-08 痛点 2）：agent 手写 ``batch_NN_result.jsonl``
易出 JSON 转义错——专业名含英文双引号时（如「法学类(...)(含"法学+英语"...)」）、
含弯引号逐字复制时、J/T 要从候选回填却编造时。本 helper 把这三类坑全消除：

  agent 只需对每条 item 给「选了第几个候选（0 起）/ null + 一句理由」，
  helper 读 ``batch_NN_prompt.json`` 反填 ``match``（候选 major 逐字）、
  ``J`` / ``T``（候选原值，不编造）、``school`` / ``major``（item 原值），
  再用 ``json.dumps`` 写合法 jsonl。

agent 端零手写 JSON、零字符串逐字复制、零 J/T 编造。decisions 可作为 Python
dict 传入（``build_results``），也可写成 TSV 文件由 CLI 读（``parse_decisions_tsv``）——
TSV 一行 ``src_row_idx<TAB>cand_index<TAB>reason``，cand 为 ``-`` 或空表示 null。

契约由 :mod:`scripts.stage2_apply` 在 apply 时硬验；本 helper 按构造即可通过
（match 取自候选 major、J/T 取自候选），但仍校验 cand 越界 / 漏判，在写文件前截住。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

__all__ = [
    "DecisionsError",
    "build_results",
    "parse_decisions_tsv",
    "write_results_jsonl",
    "main",
]


class DecisionsError(ValueError):
    """Raised when a decision is out of range / missing / malformed — caught at
    write time so the agent never produces a bad jsonl that only blows up at
    ``apply_results`` later."""


def build_results(
    prompt: dict[str, Any], decisions: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill one result dict per ``prompt`` item from ``decisions``.

    ``decisions[src_row_idx] = {"cand": <int 0-based>|None, "reason": <str>}``.
    ``cand`` indexes into the item's ``candidates`` list; the helper copies that
    candidate's ``major`` / ``J`` / ``T`` verbatim (no agent string copying, no
    J/T fabrication). ``cand=None`` → ``match=J=T=null``.

    Raises :class:`DecisionsError` if a decision is missing for an item or
    ``cand`` is out of range — before any file is written.
    """
    items = prompt.get("items", [])
    out: list[dict[str, Any]] = []
    for item in items:
        idx = item.get("src_row_idx")
        if idx not in decisions:
            raise DecisionsError(
                f"src_row_idx={idx} 缺 decision（每条 item 都要判，不能漏）"
            )
        dec = decisions[idx]
        cand = dec.get("cand")
        reason = (dec.get("reason") or "").strip()
        candidates = item.get("candidates", [])
        if cand is None:
            match: str | None = None
            j: float | None = None
            t: float | None = None
        else:
            if not isinstance(cand, int) or cand < 0 or cand >= len(candidates):
                raise DecisionsError(
                    f"src_row_idx={idx} cand={cand!r} 越界（该 item 有 "
                    f"{len(candidates)} 个候选，cand 须是 0..{len(candidates) - 1}）"
                )
            chosen = candidates[cand]
            match = chosen.get("major")
            j = chosen.get("J")
            t = chosen.get("T")
        out.append(
            {
                "src_row_idx": idx,
                "school": item.get("school", ""),
                "major": item.get("major", ""),
                "match": match,
                "J": j,
                "T": t,
                "reason": reason,
            }
        )
    return out


def parse_decisions_tsv(text: str) -> dict[int, dict[str, Any]]:
    """Parse a TSV decisions file into the ``decisions`` dict.

    Each line: ``src_row_idx<TAB>cand<TAB>reason`` (split max 2, so reason may
    contain tabs). ``cand`` = ``-`` / empty → ``None`` (null match). Blank lines
    ignored. ``src_row_idx`` must parse as int.

    TSV frees the agent from JSON escaping entirely — it writes plain text via
    echo / Write, the helper does all the JSON via :func:`write_results_jsonl`.
    """
    out: dict[int, dict[str, Any]] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        if line.strip() == "":
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise DecisionsError(f"第 {lineno} 行列数 <2（要 src_row_idx<TAB>cand[<TAB>reason]）")
        idx_str, cand_str = parts[0].strip(), parts[1].strip()
        reason = parts[2].strip() if len(parts) > 2 else ""
        try:
            idx = int(idx_str)
        except ValueError as exc:
            raise DecisionsError(f"第 {lineno} 行 src_row_idx={idx_str!r} 不是整数") from exc
        if cand_str in ("", "-", "null", "NULL", "None"):
            cand: int | None = None
        else:
            try:
                cand = int(cand_str)
            except ValueError as exc:
                raise DecisionsError(
                    f"第 {lineno} 行 cand={cand_str!r} 不是整数也不是 - / null"
                ) from exc
        out[idx] = {"cand": cand, "reason": reason}
    return out


def write_results_jsonl(results: list[dict[str, Any]], out_path: str | Path) -> Path:
    """Write one JSON object per line (``ensure_ascii=False``). Valid JSON by
    construction (``json.dumps`` handles all escaping — the whole point)."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


# --- verify（二次复核）-------------------------------------------------------
# verify 结果格式更简单（{src_row_idx, verdict, reason}，无候选/J/T），但 reason
# 仍是手写文本、含引号/弯引号时手写 JSON 会炸。同样的 TSV→jsonl 思路消除它。


def build_verify_results(
    items: list[dict[str, Any]], decisions: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fill ``{src_row_idx, verdict, reason}`` per verify item from decisions.

    ``decisions[src_row_idx] = {"verdict": "确定"|"存疑", "reason": <str>}``.
    Raises :class:`DecisionsError` on missing decision or bad verdict.
    """
    allowed = {"确定", "存疑"}
    out: list[dict[str, Any]] = []
    for item in items:
        idx = item.get("src_row_idx")
        if idx not in decisions:
            raise DecisionsError(f"src_row_idx={idx} 缺 decision（每条都要判）")
        verdict = decisions[idx].get("verdict")
        if verdict not in allowed:
            raise DecisionsError(
                f"src_row_idx={idx} verdict={verdict!r} 不在 {allowed}"
            )
        reason = (decisions[idx].get("reason") or "").strip()
        out.append({"src_row_idx": idx, "verdict": verdict, "reason": reason})
    return out


def parse_verify_decisions_tsv(text: str) -> dict[int, dict[str, Any]]:
    """TSV: ``src_row_idx<TAB>verdict<TAB>reason`` (verdict = 确定 / 存疑)."""
    out: dict[int, dict[str, Any]] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        if line.strip() == "":
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            raise DecisionsError(f"第 {lineno} 行列数 <2")
        idx_str, verdict = parts[0].strip(), parts[1].strip()
        reason = parts[2].strip() if len(parts) > 2 else ""
        try:
            idx = int(idx_str)
        except ValueError as exc:
            raise DecisionsError(f"第 {lineno} 行 src_row_idx 不是整数") from exc
        out[idx] = {"verdict": verdict, "reason": reason}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.write_batch_result",
        description=(
            "把 agent 的 TSV 决策转成合法 result jsonl（消除手写 JSON / 转义坑）。"
            " --mode batch: decisions 每行 src_row_idx<TAB>cand_index(或-)<TAB>reason，"
            " prompt=batch_NN_prompt.json。"
            " --mode verify: decisions 每行 src_row_idx<TAB>verdict(确定/存疑)<TAB>reason，"
            " prompt=verify_batch_NN.json。"
        ),
    )
    parser.add_argument("--mode", choices=["batch", "verify"], default="batch")
    parser.add_argument(
        "--prompt", required=True, type=Path, help="对应的 prompt/batch json"
    )
    parser.add_argument("--decisions", required=True, type=Path, help="TSV decisions")
    parser.add_argument("--out", required=True, type=Path, help="输出 result jsonl")
    args = parser.parse_args()

    payload = json.loads(args.prompt.read_text(encoding="utf-8"))
    decisions_text = args.decisions.read_text(encoding="utf-8")
    if args.mode == "batch":
        decisions = parse_decisions_tsv(decisions_text)
        results = build_results(payload, decisions)
    else:
        items = payload.get("items", [])
        decisions = parse_verify_decisions_tsv(decisions_text)
        results = build_verify_results(items, decisions)
    write_results_jsonl(results, args.out)
    print(f"写出 {len(results)} 条 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
