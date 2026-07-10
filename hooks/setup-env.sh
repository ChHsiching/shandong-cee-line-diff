#!/usr/bin/env bash
# SessionStart hook: 自动建 plugin venv + 装 openpyxl（幂等）。
# 建在 ${CLAUDE_PLUGIN_ROOT}/.venv（plugin 根，agent 的 Step 0 在此找 .venv）。
# plugin 更新覆盖 plugin 根时，hook 重建（幂等）。不阻塞 session——失败时 agent
# 仍可按 SKILL 的 fallback 自己建。
set -euo pipefail

VENV="${CLAUDE_PLUGIN_ROOT}/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" >/dev/null 2>&1 || {
    echo "[setup-env] venv 创建失败（python3 可能缺失），agent 首次跑会按 fallback 自建" >&2
    exit 0  # 不阻塞 session
  }
  "$VENV/bin/pip" install -q openpyxl >/dev/null 2>&1 || true
fi
