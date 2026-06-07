#!/bin/bash
# resume_script.sh - 中断された作業を再開するためのスクリプト
# 最新のセッション: mimic_tui (2026-06-07_19-16.jsonl)
# 作成日: $(date)

set -e

echo "=== 中断された作業の再開を開始します ==="
echo ""

# 1. 作業ディレクトリに移動
echo "[1/5] 作業ディレクトリに移動: /home/loser/wsl-projects/mimic_tui"
cd /home/loser/wsl-projects/mimic_tui || {
    echo "ERROR: mimic_tui ディレクトリが見つかりません"
    exit 1
}

# 2. 仮想環境をアクティベート
echo "[2/5] 仮想環境をアクティベート"
if [ -f "../.venv/bin/activate" ]; then
    source "../.venv/bin/activate"
    echo "仮想環境: アクティベート済み"
else
    echo "WARNING: 仮想環境が見つかりません。システムPythonを使用します。"
fi

# 3. 依存関係を確認
echo "[3/5] 依存関係を確認"
if [ -f "pyproject.toml" ]; then
    echo "pyproject.toml が存在します。"
    if command -v pip &>/dev/null; then
        echo "pip が利用可能です。"
    else
        echo "WARNING: pip が見つかりません。"
    fi
else
    echo "WARNING: pyproject.toml が見つかりません。"
fi

# 4. mimic_tui を起動
echo "[4/5] mimic_tui を起動"
echo "コマンド: python3 -m mimic_tui"
echo ""
echo "=== mimic_tui を起動します ==="
echo "中断されたセッション: 2026-06-07_19-16.jsonl"
echo "最後のエラー: Rate limit exceeded (429)"
echo ""

# mimic_tui を起動
python3 -m mimic_tui

echo ""
echo "=== mimic_tui が終了しました ==="
