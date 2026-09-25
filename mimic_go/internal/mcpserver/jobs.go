package mcpserver

import (
	"fmt"
	"sync"

	"mimic/internal/tools"
)

// JobRegistry はdelegate_to_worker等の重いツール呼び出しを非同期実行し、
// 完了を後から問い合わせられるようにする（Claude Code等のMCPクライアントが
// 1回のtools/callで数分〜数十分ブロックされるのを避けるための仕組み。
// internal/delegate/worker.goのMaxDelegationConcurrency=3による並列実行の
// 恩恵を、呼び出し側が「投げっぱなしにして後で回収する」形で活かせるようにする）。
type JobRegistry struct {
	mu    sync.Mutex
	jobs  map[string]*jobState
	count int
}

type jobState struct {
	done   bool
	result string
}

func NewJobRegistry() *JobRegistry {
	return &JobRegistry{jobs: make(map[string]*jobState)}
}

// Start はregistry.Call(toolName, argsJSON)をバックグラウンドで実行し、
// 即座にjob_idを返す（呼び出し元はブロックしない）。
func (jr *JobRegistry) Start(registry *tools.Registry, toolName, argsJSON string) string {
	jr.mu.Lock()
	jr.count++
	jobID := fmt.Sprintf("job-%d", jr.count)
	jr.jobs[jobID] = &jobState{}
	jr.mu.Unlock()

	go func() {
		result := registry.Call(toolName, argsJSON)
		jr.mu.Lock()
		jr.jobs[jobID].done = true
		jr.jobs[jobID].result = result
		jr.mu.Unlock()
	}()

	return jobID
}

// Result はjobIDの現在の状態を返す。found=falseはjobID自体が存在しないこと
// （タイプミス、またはプロセス再起動でジョブ台帳が失われた等）を示す。
func (jr *JobRegistry) Result(jobID string) (done bool, result string, found bool) {
	jr.mu.Lock()
	defer jr.mu.Unlock()
	j, ok := jr.jobs[jobID]
	if !ok {
		return false, "", false
	}
	return j.done, j.result, true
}
