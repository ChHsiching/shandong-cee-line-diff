#!/usr/bin/env bash
#
# shandong-cee-line-diff — ZCode 一键安装器
#
# 说明：Claude Code 用原生 `claude plugin install`，Codex/其他用 `npx skills add`；
#       本脚本仅服务 ZCode（它无 CLI 安装命令，只能把 skill 文件放进 ~/.zcode/skills/）。
#
# 用法（任意目录）：
#   curl -fsSL https://raw.githubusercontent.com/ChHsiching/shandong-cee-line-diff/main/install.sh | bash
#   ./install.sh --target <dir>     # 自定义目录（默认 ~/.zcode/skills/shandong-cee-line-diff）
#
set -euo pipefail

REPO="ChHsiching/shandong-cee-line-diff"
SKILL="shandong-cee-line-diff"
TARGET="${ZCODE_SKILLS_DIR:-$HOME/.zcode/skills}/$SKILL"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target) shift; [[ $# -gt 0 ]] || { echo "✗ --target 需要一个路径" >&2; exit 1; }; TARGET="$1"; shift ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "✗ 未知参数: $1。" >&2
       echo "  （Claude Code 请用：claude plugin install shandong-cee-line-diff@shandong-cee-line-diff）" >&2
       echo "  （其他 agent 请用：npx skills add ChHsiching/shandong-cee-line-diff）" >&2
       exit 1 ;;
  esac
done

command -v git >/dev/null 2>&1 || { echo "✗ 未找到 git，请先安装 git。" >&2; exit 1; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "→ 克隆 $REPO …"
git clone --depth 1 "https://github.com/${REPO}.git" "$TMP/repo" >&2

# ZCode 要求 SKILL.md 在 <skill-name>/ 顶；把 skill 目录内容 + 管线脚本铺平到目标（自包含可跑）
mkdir -p "$(dirname "$TARGET")"
rm -rf "$TARGET"
mkdir -p "$TARGET"
cp -r "$TMP/repo/skills/$SKILL/." "$TARGET/"        # SKILL.md + REFERENCE.md
cp -r "$TMP/repo/scripts" "$TARGET/"                # 管线脚本
cp -r "$TMP/repo/tests" "$TARGET/"                  # 测试
mkdir -p "$TARGET/data"
cp "$TMP/repo/data/README.md" "$TARGET/data/" 2>/dev/null || true

echo "✓ 已安装 $SKILL → $TARGET（自包含：SKILL.md + REFERENCE.md + scripts + tests）"
echo ""
echo "  下一步："
echo "    1. 把三个原始 xlsx 放进: $TARGET/data/   （见 $TARGET/data/README.md）"
echo "    2. 配 Python:  cd \"$TARGET\" && python3 -m venv .venv && .venv/bin/pip install openpyxl pytest ruff"
echo "    3. ZCode 聊天调用:  \$$SKILL 帮我整理 data/ 下的山东高考录取数据"
