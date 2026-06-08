#!/usr/bin/env python3
"""
非同期タスクを最大同時実行数を制限して管理・実行するクラス
"""
import asyncio
from typing import List, Callable, Any

class TaskManager:
    """
    非同期タスクを最大同時実行数を制限して管理・実行するクラス
    
    Attributes:
        max_concurrency (int): 最大同時実行数
        semaphore (asyncio.Semaphore): 同時実行数を制限するセマフォ
        results (List[Any]): タスクの実行結果を保存するリスト
        errors (List[Exception]): タスクの実行エラーを保存するリスト
    """
    
    def __init__(self, max_concurrency: int):
        """
        TaskManagerを初期化する
        
        Args:
            max_concurrency (int): 最大同時実行数
        """
        if max_concurrency <= 0:
            raise ValueError("max_concurrency は1以上である必要があります")
        
        self.max_concurrency = max_concurrency
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.results = []
        self.errors = []
    
    async def _run_task(self, task: Callable[[], Any], task_id: int) -> None:
        """
        単一のタスクを実行する
        
        Args:
            task (Callable[[], Any]): 実行する非同期タスク
            task_id (int): タスクのID
        """
        async with self.semaphore:
            try:
                result = await task()
                self.results.append((task_id, result))
            except Exception as e:
                self.errors.append((task_id, e))
    
    async def run_tasks(self, tasks: List[Callable[[], Any]]) -> None:
        """
        タスクリストを最大同時実行数を制限して実行する
        
        Args:
            tasks (List[Callable[[], Any]]): 実行する非同期タスクのリスト
        """
        task_ids = list(range(len(tasks)))
        await asyncio.gather(*[self._run_task(task, task_id) for task_id, task in zip(task_ids, tasks)])
    
    def get_results(self) -> List[Any]:
        """
        タスクの実行結果を取得する
        
        Returns:
            List[Any]: タスクの実行結果のリスト
        """
        return self.results
    
    def get_errors(self) -> List[Exception]:
        """
        タスクの実行エラーを取得する
        
        Returns:
            List[Exception]: タスクの実行エラーのリスト
        """
        return self.errors