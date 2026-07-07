#!/usr/bin/env bash
# SessionStart hook: 自动建 plugin venv + 装 openpyxl（幂等）。
# 建在 ${CLAUDE_PLUGIN_ROOT}/.venv（plugin 根，agent 能 find 到）。
# plugin update 覆盖 plugin 根时，hook 重建（幂等）。
# agent 用 skill 时环境已就绪——不用每次在工作目录建 .venv。
set -euo pipefail

VENV="${CLAUDE_PLUGIN_ROOT}/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" >/dev/null 2>&1 || {
    echo "[setup-env] venv 创建失败（python3 可能缺失），agent 首次跑会提示建环境" >&2
    exit 0  # 不阻塞 session——agent 可以 fallback 自己建
  }
  "$VENV/bin/pip" install -q openpyxl >/dev/null 2>&1 || true
fi
