#!/usr/bin/env bash
#
# shandong-cee-line-diff — 一键 skill 安装器
#
#   默认        : ZCode       (~/.zcode/skills/shandong-cee-line-diff)
#   --claude    : Claude Code  (~/.claude/skills/...)
#   --codex     : Codex        (~/.codex/skills/...)
#   --target <dir> : 自定义安装路径
#
# 任意目录执行（curl 管道）：
#   curl -fsSL https://raw.githubusercontent.com/ChHsiching/shandong-cee-line-diff/main/install.sh | bash
#
# 动作：浅克隆仓库到临时目录 → 整体复制到目标 skills 目录（自包含：SKILL.md+scripts+tests）→ 删除临时克隆。
# 克隆不含任何原始数据（data/ 下 xlsx 由用户自行放入）。
#
set -euo pipefail

REPO="ChHsiching/shandong-cee-line-diff"
SKILL="shandong-cee-line-diff"

# --- 选择安装目标 ---
TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --claude) TARGET="$HOME/.claude/skills/$SKILL"; shift ;;
    --codex)  TARGET="$HOME/.codex/skills/$SKILL";  shift ;;
    --target) shift
              [[ $# -gt 0 ]] || { echo "✗ --target 需要一个路径" >&2; exit 1; }
              TARGET="$1"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "✗ 未知参数: $1（可用: --claude | --codex | --target <dir>）" >&2; exit 1 ;;
  esac
done
[[ -z "$TARGET" ]] && TARGET="$HOME/.zcode/skills/$SKILL"   # 默认 ZCode

# --- 依赖检查 ---
command -v git >/dev/null 2>&1 || { echo "✗ 未找到 git，请先安装 git。" >&2; exit 1; }

# --- 浅克隆到临时目录，复制到目标，删除临时克隆 ---
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "→ 克隆 $REPO …"
git clone --depth 1 "https://github.com/${REPO}.git" "$TMP/repo" >&2

mkdir -p "$(dirname "$TARGET")"
rm -rf "$TARGET"
cp -r "$TMP/repo" "$TARGET"
rm -rf "$TARGET/.git"
mkdir -p "$TARGET/data"

echo "✓ 已安装 $SKILL → $TARGET"
echo ""
echo "  下一步："
echo "    1. 把三个原始 xlsx 放进: $TARGET/data/   （见 $TARGET/data/README.md）"
echo "    2. 配 Python:  cd \"$TARGET\" && python3 -m venv .venv && .venv/bin/pip install openpyxl pytest ruff"
echo "    3. 调用 (ZCode):       \$$SKILL 帮我整理 data/ 下的山东高考录取数据"
echo "       (Claude Code):      Skill(\"$SKILL\")"
