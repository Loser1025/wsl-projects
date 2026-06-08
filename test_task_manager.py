#!/usr/bin/env python3
"""
実装したTaskManagerクラスをテストするスクリプト
"""
import asyncio
from task_manager import TaskManager

# テスト用の非同期タスクを定義
async def sample_task(task_id: int, duration: int) -> str:
    """
    テスト用の非同期タスク
    
    Args:
        task_id (int): タスクのID
        duration (int): タスクの実行時間（秒）
        
    Returns:
        str: タスクの結果メッセージ
    """
    print(f"タスク {task_id} を開始します（実行時間: {duration}秒）")
    await asyncio.sleep(duration)
    print(f"タスク {task_id} が完了しました")
    return f"タスク {task_id} の結果"

# テスト用のエラーを発生させる非同期タスクを定義
async def error_task(task_id: int) -> str:
    """
    テスト用のエラーを発生させる非同期タスク
    
    Args:
        task_id (int): タスクのID
        
    Raises:
        Exception: タスクの実行エラー
    """
    print(f"エラータスク {task_id} を開始します")
    await asyncio.sleep(1)
    raise Exception(f"タスク {task_id} でエラーが発生しました")

async def main():
    """
    TaskManagerのテストを実行するメイン関数
    """
    # テスト1: 基本的な動作確認
    print("=== テスト1: 基本的な動作確認 ===")
    manager1 = TaskManager(max_concurrency=2)
    tasks1 = [
        lambda: sample_task(1, 2),
        lambda: sample_task(2, 1),
        lambda: sample_task(3, 3),
        lambda: sample_task(4, 1),
    ]
    await manager1.run_tasks(tasks1)
    
    print("\n結果:")
    for task_id, result in manager1.get_results():
        print(f"タスク {task_id}: {result}")
    
    print("\nエラー:")
    for task_id, error in manager1.get_errors():
        print(f"タスク {task_id}: {error}")
    
    # テスト2: エラー処理の確認
    print("\n=== テスト2: エラー処理の確認 ===")
    manager2 = TaskManager(max_concurrency=2)
    tasks2 = [
        lambda: sample_task(1, 1),
        lambda: error_task(2),
        lambda: sample_task(3, 1),
        lambda: error_task(4),
    ]
    await manager2.run_tasks(tasks2)
    
    print("\n結果:")
    for task_id, result in manager2.get_results():
        print(f"タスク {task_id}: {result}")
    
    print("\nエラー:")
    for task_id, error in manager2.get_errors():
        print(f"タスク {task_id}: {error}")
    
    # テスト3: 最大同時実行数の確認
    print("\n=== テスト3: 最大同時実行数の確認 ===")
    manager3 = TaskManager(max_concurrency=1)
    tasks3 = [
        lambda: sample_task(1, 2),
        lambda: sample_task(2, 1),
        lambda: sample_task(3, 1),
    ]
    await manager3.run_tasks(tasks3)
    
    print("\n結果:")
    for task_id, result in manager3.get_results():
        print(f"タスク {task_id}: {result}")

if __name__ == "__main__":
    asyncio.run(main())