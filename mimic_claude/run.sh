#!/usr/bin/env bash
# mimic_claude ランチャー (Textual TUI版)
# 使い方: ./mimic_claude/run.sh [オプション]
# 例:     ./mimic_claude/run.sh
#         ./mimic_claude/run.sh --prompt "タスク内容"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

exec python3 -m mimic_claude "$@"
