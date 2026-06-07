"""
architect_agent.py — マルチエージェントアーキテクトの明確な定義

このファイルは、マルチエージェントシステムにおける ArchitectAgent の役割、責任範囲、
ツールセット、および他エージェントとの比較を明確化するための定義ファイルです。

関連ファイル:
  - multi_agent.py: RoleAgentBase, ArchitectAgent, OperatorAgent, ScribeAgent, MultiAgentOrchestrator
  - agent.py: OpenRouterAgent（汎用 ReAct エージェント）
  - orchestrator.py: WorkflowGraph, PlanStep, AgentOrchestrator
"""

from __future__ import annotations
from typing import Optional, Callable

# =============================================================================
# ArchitectAgent の明確な定義
# =============================================================================

class ArchitectAgentDefinition:
    """
    ArchitectAgent の役割、責任範囲、ツールセットを明確化する定義クラス。
    
    このクラスは、マルチエージェントシステムにおける ArchitectAgent の
    1. 役割と責任範囲
    2. 許可されるツールセット
    3. 行動指針
    4. 協調メカニズム
    5. 成否判定基準
    
    を文書化します。
    """
    
    # --- 基本情報 ---
    ROLE_NAME = "Architect"
    ROLE_DESCRIPTION = "コード設計・ファイル修正・リポジトリ構造の把握"
    ROLE_CATEGORY = "Design & Implementation"
    
    # --- 許可ツールセット ---
    ALLOWED_TOOLS = [
        # リポジトリ構造分析
        "get_repo_map",
        
        # ファイル読み取り
        "read_file",
        "read_tool_cache",
        "smart_read",
        "search_in_file",
        "file_info",
        
        # ファイル編集（独占ツール）
        "write_file",
        "edit_file",
        "patch_file",
        
        # 進捗管理
        "update_scratchpad",
    ]
    
    # --- 禁止ツールセット（明示的な制限） ---
    FORBIDDEN_TOOLS = [
        # 実行系ツール（OperatorAgentの責務）
        "run_bash",
        "run_pipeline",
        
        # Web調査系ツール（OperatorAgentの責務）
        "web_search",
        "fetch_webpage",
        
        # 記憶管理系ツール（ScribeAgentの責務）
        "search_history",
    ]
    
    # --- 行動指針 ---
    ACTION_GUIDELINES = [
        "1. まず get_repo_map または smart_read でコード構造を把握する",
        "2. 必要なファイルを read_file / search_in_file で確認してから編集する",
        "3. 編集完了後は必ず以下の形式で報告する:",
        "   - 変更ファイル: <パス1>, <パス2>",
        "   - テストコマンド: <pytest/npm test 等の具体的コマンド>",
        "4. 実装後に update_scratchpad で進捗を記録する",
        "5. bash コマンドの実行は行わない（それは執行担当の責務）",
    ]
    
    # --- 協調メカニズム ---
    COLLABORATION_STEPS = [
        {
            "step": 1,
            "label": "architect",
            "description": "リポジトリ構造把握・設計・実装",
            "on_failure": "abort",
            "on_success": "goto:verify",
        },
        {
            "step": 4,
            "label": "replan",
            "description": "エラー修正・別アプローチで再設計",
            "on_failure": "abort",
            "on_success": "goto:operator",
        },
    ]
    
    # --- 成否判定基準 ---
    SUCCESS_CRITERIA = {
        "primary": "書き込みツール（write_file/edit_file/patch_file）を呼び出したか",
        "secondary": "分析・要約・評価などの読み取り専用タスクか（キーワード: 分析, 要約, 評価, 考察, まとめ, レポート, 調査結果, 結論, 比較, 解説, 説明, 確認結果, レビュー）",
        "failure": "ファイル変更なしかつ分析結果なし",
    }
    
    # --- 状態共有項目 ---
    SHARED_STATE_ITEMS = [
        "changed_files",  # 変更されたファイル一覧
        "test_command",   # 実行すべきテストコマンド
    ]
    
    @classmethod
    def get_definition(cls) -> dict:
        """ArchitectAgent の完全な定義を辞書形式で返す。"""
        return {
            "role_name": cls.ROLE_NAME,
            "role_description": cls.ROLE_DESCRIPTION,
            "role_category": cls.ROLE_CATEGORY,
            "allowed_tools": cls.ALLOWED_TOOLS,
            "forbidden_tools": cls.FORBIDDEN_TOOLS,
            "action_guidelines": cls.ACTION_GUIDELINES,
            "collaboration_steps": cls.COLLABORATION_STEPS,
            "success_criteria": cls.SUCCESS_CRITERIA,
            "shared_state_items": cls.SHARED_STATE_ITEMS,
        }
    
    @classmethod
    def get_comparison_data(cls) -> dict:
        """他エージェントとの比較用データを返す。"""
        return {
            "role": cls.ROLE_NAME,
            "specialization": "Code Design & Implementation",
            "exclusive_tools": ["get_repo_map", "write_file", "edit_file", "patch_file"],
            "shared_tools": ["read_file", "smart_read", "search_in_file", "file_info", "update_scratchpad"],
            "restrictions": ["No command execution (run_bash, run_pipeline)", "No web search"],
            "collaboration_role": "Design & Fix Implementation",
            "workflow_steps": [1, 4],
            "dependency": "OperatorAgent (for testing), ScribeAgent (for memory management)",
        }


# =============================================================================
# 他エージェントの定義（比較用）
# =============================================================================

class OperatorAgentDefinition:
    """OperatorAgent の定義（比較用）"""
    
    ROLE_NAME = "Operator"
    ROLE_DESCRIPTION = "コマンド実行・テスト・コードベース探索・Web 調査"
    ROLE_CATEGORY = "Execution & Validation"
    
    ALLOWED_TOOLS = [
        "run_bash",
        "run_pipeline",
        "read_file",
        "read_tool_cache",
        "file_info",
        "smart_read",
        "search_in_file",
        "grep_codebase",
        "web_search",
        "fetch_webpage",
        "update_scratchpad",
    ]
    
    FORBIDDEN_TOOLS = [
        "write_file",
        "edit_file",
        "patch_file",
        "search_history",
    ]
    
    ACTION_GUIDELINES = [
        "1. 設計担当の実装を run_bash でテスト・検証する",
        "2. エラーが出た場合は完全なスタックトレースを出力する",
        "3. 最終的に成功 / 失敗を明確に報告する",
        "4. ファイルの直接編集は行わない（それは設計担当の責務）",
    ]
    
    COLLABORATION_STEPS = [
        {"step": 2, "label": "verify", "description": "実装確認（ファイル変更検証）"},
        {"step": 3, "label": "operator", "description": "テスト実行・動作検証"},
    ]
    
    SUCCESS_CRITERIA = {
        "verify": "ファイル変更の確認（確認完了、変更あり、差分を確認などのキーワード）",
        "operator": "テスト成功（[SUCCESS]、成功、完了、問題なし、テスト合格、正常動作、All tests passedなどのキーワード）",
        "failure": "テスト失敗（[FAILURE、Exception:、Traceback、失敗、エラー:、FAILEDなどのキーワード）",
    }
    
    SHARED_STATE_ITEMS = ["changed_files", "test_command", "last_error"]
    
    @classmethod
    def get_comparison_data(cls) -> dict:
        return {
            "role": cls.ROLE_NAME,
            "specialization": "Command Execution & Testing",
            "exclusive_tools": ["run_bash", "run_pipeline", "web_search", "fetch_webpage"],
            "shared_tools": ["read_file", "smart_read", "search_in_file", "file_info", "update_scratchpad"],
            "restrictions": ["No file editing (write_file, edit_file, patch_file)"],
            "collaboration_role": "Validation & Testing",
            "workflow_steps": [2, 3],
            "dependency": "ArchitectAgent (for implementation), ScribeAgent (for memory management)",
        }


class ScribeAgentDefinition:
    """ScribeAgent の定義（比較用）"""
    
    ROLE_NAME = "Scribe"
    ROLE_DESCRIPTION = "作業記憶の管理・要約・コンテキスト圧縮"
    ROLE_CATEGORY = "Memory Management"
    
    ALLOWED_TOOLS = [
        "update_scratchpad",
        "search_history",
        "read_file",
    ]
    
    FORBIDDEN_TOOLS = [
        "run_bash",
        "run_pipeline",
        "write_file",
        "edit_file",
        "patch_file",
        "web_search",
        "fetch_webpage",
        "get_repo_map",
        "smart_read",
        "search_in_file",
        "grep_codebase",
    ]
    
    ACTION_GUIDELINES = [
        "1. update_scratchpad で常に以下の形式で保存する:",
        "   【ゴール】【完了済み】【次のステップ】【発見・注意】",
        "2. 必ず 800 文字以内に収める",
        "3. 重要な制約・エラー・発見事項を優先的に残す",
    ]
    
    COLLABORATION_STEPS = [
        {"step": 5, "label": "scribe", "description": "作業記憶圧縮・保存"},
    ]
    
    SUCCESS_CRITERIA = {
        "primary": "常に成功（記憶圧縮は失敗してもスキップ）",
    }
    
    SHARED_STATE_ITEMS = ["current_memory"]
    
    @classmethod
    def get_comparison_data(cls) -> dict:
        return {
            "role": cls.ROLE_NAME,
            "specialization": "Memory Compression & Management",
            "exclusive_tools": ["compact_memory"],
            "shared_tools": ["update_scratchpad", "read_file"],
            "restrictions": ["No execution tools", "No file editing tools", "No web search tools"],
            "collaboration_role": "Memory Compression",
            "workflow_steps": [5],
            "dependency": "ArchitectAgent & OperatorAgent (for task results)",
        }


class OpenRouterAgentDefinition:
    """OpenRouterAgent（汎用）の定義（比較用）"""
    
    ROLE_NAME = "OpenRouterAgent"
    ROLE_DESCRIPTION = "汎用 ReAct ループエージェント（OpenRouter API 経由）"
    ROLE_CATEGORY = "General Purpose"
    
    ALLOWED_TOOLS = ["*" ]  # 全ツール（動的設定）
    FORBIDDEN_TOOLS = []
    
    ACTION_GUIDELINES = [
        "1. ストリーミング/非ストリーミングの ReAct ループを実行",
        "2. ツール呼び出しの並列/逐次実行（書き込みツールは逐次）",
        "3. コンテキスト管理（自動トリム、圧縮、キャッシュ）",
        "4. エラーハンドリング（リトライ、バックオフ、コンテキスト超過対応）",
    ]
    
    COLLABORATION_STEPS = []  # 単体動作
    
    SUCCESS_CRITERIA = {
        "primary": "ツール実行結果に基づく成否判定",
    }
    
    SHARED_STATE_ITEMS = []
    
    @classmethod
    def get_comparison_data(cls) -> dict:
        return {
            "role": cls.ROLE_NAME,
            "specialization": "General Purpose ReAct Agent",
            "exclusive_tools": [],
            "shared_tools": ["All tools (dynamic)"],
            "restrictions": [],
            "collaboration_role": "Standalone Operation",
            "workflow_steps": [],
            "dependency": "None (self-contained)",
        }


# =============================================================================
# 比較評価レポート生成
# =============================================================================

def generate_comparison_report() -> str:
    """
    全エージェントの比較評価レポートを生成する。
    """
    agents = [
        ArchitectAgentDefinition,
        OperatorAgentDefinition,
        ScribeAgentDefinition,
        OpenRouterAgentDefinition,
    ]
    
    report_lines = []
    report_lines.append("# 🏆マルチエージェントシステム - エージェント比較評価レポート")
    report_lines.append("")
    report_lines.append("## 📌 総括")
    report_lines.append("")
    report_lines.append("このレポートは、マルチエージェントシステムにおける各エージェントの役割、責任範囲、ツールセット、および協調メカニズムを比較評価した結果です。")
    report_lines.append("")
    
    # 個別評価
    report_lines.append("## 🔍 1. 個別エージェント評価")
    report_lines.append("")
    
    for agent_class in agents:
        data = agent_class.get_comparison_data()
        report_lines.append(f"### {data['role']}")
        report_lines.append("")
        report_lines.append(f"- **専門分野**: {data['specialization']}")
        report_lines.append(f"- **独占ツール**: {', '.join(data['exclusive_tools']) if data['exclusive_tools'] else 'なし'}")
        report_lines.append(f"- **共用ツール**: {', '.join(data['shared_tools'])}")
        report_lines.append(f"- **制限**: {', '.join(data['restrictions']) if data['restrictions'] else 'なし'}")
        report_lines.append(f"- **協調役割**: {data['collaboration_role']}")
        report_lines.append(f"- **ワークフローステップ**: {data['workflow_steps']}")
        report_lines.append(f"- **依存関係**: {data['dependency']}")
        report_lines.append("")
    
    # 比較表
    report_lines.append("## 📊 2. 比較表")
    report_lines.append("")
    report_lines.append("| エージェント | 専門分野 | 独占ツール | 共用ツール | 制限 | 協調役割 |")
    report_lines.append("|------------|----------|------------|------------|------|----------|")
    
    for agent_class in agents:
        data = agent_class.get_comparison_data()
        report_lines.append(
            f"| {data['role']} | {data['specialization']} | {', '.join(data['exclusive_tools']) if data['exclusive_tools'] else '-'} | {len(data['shared_tools'])}種 | {len(data['restrictions'])}項目 | {data['collaboration_role']} |"
        )
    
    report_lines.append("")
    
    # 重複・不足・特化点
    report_lines.append("## 🎯 3. 分析結果")
    report_lines.append("")
    report_lines.append("### ✅ 重複の回避")
    report_lines.append("")
    report_lines.append("- **ツール重複**: `read_file`, `smart_read`, `search_in_file`, `file_info`, `update_scratchpad`は全エージェントで共通")
    report_lines.append("  - **目的の違い**:")
    report_lines.append("    - **Architect**: 設計前のコード構造分析")
    report_lines.append("    - **Operator**: 検証時のテスト結果確認")
    report_lines.append("    - **Scribe**: 記憶圧縮のための補助的使用")
    report_lines.append("")
    
    report_lines.append("### ⚠️ 不足点")
    report_lines.append("")
    report_lines.append("- **ArchitectAgent**:")
    report_lines.append("  - Web調査機能なし（Operatorに依存）")
    report_lines.append("  - テストコマンドの妥当性検証なし")
    report_lines.append("")
    report_lines.append("- **ScribeAgent**:")
    report_lines.append("  - 自動圧縮メカニズムなし（手動トリガーに依存）")
    report_lines.append("")
    report_lines.append("- **OpenRouterAgent**:")
    report_lines.append("  - 単体ではマルチエージェントの協調機能なし")
    report_lines.append("")
    
    report_lines.append("### 🎯 特化点")
    report_lines.append("")
    report_lines.append("| エージェント | 特化分野 | 独自機能 | 効果 |")
    report_lines.append("|--------------|----------|----------|------|")
    report_lines.append("| ArchitectAgent | コード設計・実装 | `get_repo_map`, ファイル編集ツール | コードベースの一貫性保証 |")
    report_lines.append("| OperatorAgent | 実行・検証 | `run_bash`, `run_pipeline`, Web調査ツール | エラー報告の厳格化 |")
    report_lines.append("| ScribeAgent | 記憶管理 | `compact_memory`, 800文字制限 | コンテキストのノイズ削減 |")
    report_lines.append("")
    
    # 全体評価
    report_lines.append("## 🌟 4. 全体評価 (★★★★☆)")
    report_lines.append("")
    report_lines.append("### ✅ メリット")
    report_lines.append("")
    report_lines.append("1. **役割分離の徹底**: 各エージェントの責任範囲がツール・行動指針・協調ステップの3層で明確化")
    report_lines.append("2. **協調メカニズム**: `MultiAgentOrchestrator`によるステップごとの成否判定とルーティング")
    report_lines.append("3. **拡張性**: `RoleAgentBase`を継承する設計により、新たな役割エージェントの追加が容易")
    report_lines.append("")
    report_lines.append("### ❌ デメリット")
    report_lines.append("")
    report_lines.append("1. **依存性**: Architectの出力にOperatorが依存（報告フォーマットが崩れると全ワークフローが停止）")
    report_lines.append("2. **柔軟性の低さ**: 固定されたステップにより、動的なタスクへの対応が制限")
    report_lines.append("")
    
    # 改善提案
    report_lines.append("## 💡 5. 改善提案")
    report_lines.append("")
    report_lines.append("1. **Architectのテスト設計支援**: テストコマンドの自動生成や妥当性チェックを追加")
    report_lines.append("2. **Scribeの自動圧縮**: コンテキスト長が閾値を超えた場合に自動で`compact_memory`をトリガー")
    report_lines.append("3. **ワークフローの動的最適化**: タスクの複雑さに応じて、ステップの並列実行やスキップを許容")
    report_lines.append("")
    
    return "\n".join(report_lines)


# =============================================================================
# メイン実行
# =============================================================================

if __name__ == "__main__":
    # 比較レポートを生成してファイルに保存
    report = generate_comparison_report()
    
    # レポートをファイルに保存
    with open("/home/loser/wsl-projects/mimic_tui/agent_comparison_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    
    print("✅ 比較評価レポートを生成しました: agent_comparison_report.md")
    
    # 各エージェントの定義をJSON形式で保存
    import json
    
    definitions = {
        "ArchitectAgent": ArchitectAgentDefinition.get_definition(),
        "OperatorAgent": OperatorAgentDefinition.get_definition(),
        "ScribeAgent": ScribeAgentDefinition.get_definition(),
        "OpenRouterAgent": OpenRouterAgentDefinition.get_definition(),
    }
    
    with open("/home/loser/wsl-projects/mimic_tui/agent_definitions.json", "w", encoding="utf-8") as f:
        json.dump(definitions, f, ensure_ascii=False, indent=2)
    
    print("✅ エージェント定義を保存しました: agent_definitions.json")
