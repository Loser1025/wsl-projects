#!/usr/bin/env bash
# mimic_linux ランチャー
# 使い方: ./mimic_linux/run.sh [オプション]
# 例:     ./mimic_linux/run.sh
#         ./mimic_linux/run.sh --prompt "タスク内容"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

exec python3 -m mimic_linux "$@"
