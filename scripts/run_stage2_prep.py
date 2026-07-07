"""PRODUCTION-RUN orchestration (not a pipeline feature; coverage-exempt).
STEP A: 把 Stage1.5 未命中里「有同校候选」的项重排成聚焦 agent 批；
无候选项自动写 null 结果（归新增）。"""

import json
import glob

SM_DIR = "semantic-match"
FOCUS_SIZE = 20


def main():
    cand_items = []
    null_results = []
    seen_idx = set()
    for f in sorted(glob.glob(f"{SM_DIR}/batch_*_prompt.json")):
        data = json.load(open(f, encoding="utf-8"))
        for it in data.get("items", []):
            idx = it["src_row_idx"]
            if idx in seen_idx:
                continue
            seen_idx.add(idx)
            cands = it.get("candidates") or []
            if cands:
                cand_items.append(it)
            else:
                null_results.append(
                    {
                        "src_row_idx": idx,
                        "match": None,
                        "J": None,
                        "T": None,
                        "reason": "无同校候选，归新增",
                    }
                )

    # 聚焦批
    n_batches = (len(cand_items) + FOCUS_SIZE - 1) // FOCUS_SIZE
    for i in range(n_batches):
        chunk = cand_items[i * FOCUS_SIZE : (i + 1) * FOCUS_SIZE]
        out = {"batch": i + 1, "items": chunk}
        with open(
            f"{SM_DIR}/agent_batch_{i + 1:03d}.json", "w", encoding="utf-8"
        ) as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)

    # 无候选 null 结果
    with open(f"{SM_DIR}/auto_null_result.jsonl", "w", encoding="utf-8") as fh:
        for r in null_results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"有候选(聚焦批): {len(cand_items)} 项 → {n_batches} 批 (agent_batch_*.json)")
    print(f"无候选(自动null): {len(null_results)} 项 → auto_null_result.jsonl")
    print(f"合计: {len(cand_items) + len(null_results)} 项")


if __name__ == "__main__":
    main()
