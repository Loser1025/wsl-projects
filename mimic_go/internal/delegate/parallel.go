package delegate

import (
	"context"
	"fmt"
	"sync"

	"mimic/internal/llm"
	"mimic/internal/tools"
)

// maxParallelTeamTasks はdelegate_to_team_parallelの同時実行数上限
// （Python版 _MAX_PARALLEL_TEAM_TASKS を踏襲）。
const maxParallelTeamTasks = 3

// maxParallelTasks はdelegate_to_team_parallelが1回で受け付けるタスク数の上限
// （Python版 tools.py::delegate_to_team_parallel の10件上限チェックを踏襲）。
const maxParallelTasks = 10

// RunTeamTasksParallel は複数タスクを独立したResearcher→Workerパイプラインとして
// 実行する（Python版 team.py::run_team_tasks_parallel の移植。同時実行数は
// maxParallelTeamTasksでバッチ分割し、各バッチ内はgoroutineで並列実行する）。
func RunTeamTasksParallel(ctx context.Context, client *llm.Client, baseRegistry *tools.Registry, tasks []string, projectDir, verifyCmd string) []string {
	results := make([]string, len(tasks))

	for batchStart := 0; batchStart < len(tasks); batchStart += maxParallelTeamTasks {
		batchEnd := batchStart + maxParallelTeamTasks
		if batchEnd > len(tasks) {
			batchEnd = len(tasks)
		}
		var wg sync.WaitGroup
		for i := batchStart; i < batchEnd; i++ {
			wg.Add(1)
			go func(idx int, task string) {
				defer wg.Done()
				defer func() {
					if r := recover(); r != nil {
						results[idx] = fmt.Sprintf("[delegate_to_team: ⚠ 予期しないエラー]\n%v", r)
					}
				}()
				res, err := RunTeamTask(ctx, client, baseRegistry, task, projectDir, verifyCmd)
				if err != nil {
					results[idx] = fmt.Sprintf("[delegate_to_team: ⚠ 予期しないエラー]\n%v", err)
					return
				}
				results[idx] = res
			}(i, tasks[i])
		}
		wg.Wait()
	}
	return results
}
