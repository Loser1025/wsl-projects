package mcpserver

import (
	"testing"
	"time"

	"mimic/internal/tools"
)

func newSlowEchoRegistry(delay time.Duration) *tools.Registry {
	r := tools.NewRegistry()
	r.Register("slow_echo", "遅延してから引数を返すテスト用ツール",
		map[string]any{"type": "object"},
		func(args map[string]any) (string, error) {
			time.Sleep(delay)
			s, _ := args["msg"].(string)
			return "echo:" + s, nil
		})
	return r
}

func TestJobRegistry_StartReturnsImmediately(t *testing.T) {
	registry := newSlowEchoRegistry(200 * time.Millisecond)
	jr := NewJobRegistry()

	start := time.Now()
	jobID := jr.Start(registry, "slow_echo", `{"msg":"hi"}`)
	elapsed := time.Since(start)

	if jobID == "" {
		t.Fatal("job_idが空文字")
	}
	if elapsed >= 100*time.Millisecond {
		t.Errorf("Startがブロックしている: elapsed=%v", elapsed)
	}

	done, _, found := jr.Result(jobID)
	if !found {
		t.Fatal("開始直後なのにjobが見つからない")
	}
	if done {
		t.Error("開始直後なのにdone=trueになった")
	}
}

func TestJobRegistry_ResultAfterCompletion(t *testing.T) {
	registry := newSlowEchoRegistry(30 * time.Millisecond)
	jr := NewJobRegistry()
	jobID := jr.Start(registry, "slow_echo", `{"msg":"hi"}`)

	deadline := time.Now().Add(2 * time.Second)
	for {
		done, result, found := jr.Result(jobID)
		if !found {
			t.Fatal("jobが見つからない")
		}
		if done {
			if result != "echo:hi" {
				t.Errorf("result = %q, want %q", result, "echo:hi")
			}
			return
		}
		if time.Now().After(deadline) {
			t.Fatal("タイムアウト: ジョブが完了しなかった")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

func TestJobRegistry_UnknownJobNotFound(t *testing.T) {
	jr := NewJobRegistry()
	if _, _, found := jr.Result("job-does-not-exist"); found {
		t.Error("存在しないjob_idなのにfound=trueになった")
	}
}

func TestJobRegistry_MultipleJobsIndependent(t *testing.T) {
	registry := newSlowEchoRegistry(20 * time.Millisecond)
	jr := NewJobRegistry()
	id1 := jr.Start(registry, "slow_echo", `{"msg":"a"}`)
	id2 := jr.Start(registry, "slow_echo", `{"msg":"b"}`)
	if id1 == id2 {
		t.Fatalf("job_idが重複した: %q", id1)
	}

	time.Sleep(200 * time.Millisecond)
	_, r1, _ := jr.Result(id1)
	_, r2, _ := jr.Result(id2)
	if r1 != "echo:a" || r2 != "echo:b" {
		t.Errorf("結果が混線している: r1=%q r2=%q", r1, r2)
	}
}
