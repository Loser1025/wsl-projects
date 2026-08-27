package vcs

import (
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"
)

// ToolCallRecord は1回のツール呼び出しの計測結果
// （Python版 monitoring.py::ToolCallRecord の移植。CPUMaxPct/RSSDeltaMBは
// internal/vcs/procobserver.go の ProcessMonitor によるバックグラウンド
// ポーリング計測値。呼び出し元が計測しない場合は0のままでよい）。
type ToolCallRecord struct {
	Tool       string
	Elapsed    time.Duration
	Status     string // "ok" | "error"
	Occurred   time.Time
	CPUMaxPct  float64
	RSSDeltaMB float64
}

func (r ToolCallRecord) oneLine() string {
	icon := "✓"
	if r.Status != "ok" {
		icon = "✗"
	}
	return fmt.Sprintf("%s %s %.2fs | CPU:max%.0f%% | MEM:%+.0fMB", icon, r.Tool, r.Elapsed.Seconds(), r.CPUMaxPct, r.RSSDeltaMB)
}

// ToolCallLog はセッション中の全ツール呼び出しを記録する。
type ToolCallLog struct {
	mu      sync.Mutex
	records []ToolCallRecord
}

func NewToolCallLog() *ToolCallLog {
	return &ToolCallLog{}
}

func (l *ToolCallLog) Add(r ToolCallRecord) {
	l.mu.Lock()
	l.records = append(l.records, r)
	l.mu.Unlock()
}

func (l *ToolCallLog) Records() []ToolCallRecord {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]ToolCallRecord{}, l.records...)
}

// StatsText は /stats コマンド用のサマリテキストを返す。
func (l *ToolCallLog) StatsText() string {
	recs := l.Records()
	if len(recs) == 0 {
		return "  (このセッションでのツール呼び出しなし)"
	}

	total := len(recs)
	errors := 0
	var totalElapsed time.Duration
	slowest := recs[0]
	counts := make(map[string]int)
	cpuMax := 0.0
	rssDeltaSum := 0.0
	for _, r := range recs {
		if r.Status == "error" {
			errors++
		}
		totalElapsed += r.Elapsed
		if r.Elapsed > slowest.Elapsed {
			slowest = r
		}
		counts[r.Tool]++
		if r.CPUMaxPct > cpuMax {
			cpuMax = r.CPUMaxPct
		}
		rssDeltaSum += r.RSSDeltaMB
	}
	ok := total - errors

	type toolCount struct {
		name  string
		count int
	}
	var tc []toolCount
	for name, c := range counts {
		tc = append(tc, toolCount{name, c})
	}
	sort.Slice(tc, func(i, j int) bool { return tc[i].count > tc[j].count })
	if len(tc) > 5 {
		tc = tc[:5]
	}
	var topParts []string
	for _, t := range tc {
		topParts = append(topParts, fmt.Sprintf("%d×%s", t.count, t.name))
	}

	avg := totalElapsed.Seconds() / float64(total)
	return strings.Join([]string{
		fmt.Sprintf("  呼び出し数 : %d 回  (成功:%d  エラー:%d)", total, ok, errors),
		fmt.Sprintf("  合計時間   : %.1fs", totalElapsed.Seconds()),
		fmt.Sprintf("  平均時間   : %.2fs", avg),
		fmt.Sprintf("  最遅       : %s %.2fs", slowest.Tool, slowest.Elapsed.Seconds()),
		fmt.Sprintf("  CPU最大    : %.0f%%", cpuMax),
		fmt.Sprintf("  MEM増分合計: %+.0fMB", rssDeltaSum),
		"  使用頻度   : " + strings.Join(topParts, "  "),
	}, "\n")
}

// RecentText は直近n件の呼び出し履歴を返す。
func (l *ToolCallLog) RecentText(n int) string {
	recs := l.Records()
	if len(recs) > n {
		recs = recs[len(recs)-n:]
	}
	if len(recs) == 0 {
		return "  (なし)"
	}
	var lines []string
	for _, r := range recs {
		lines = append(lines, "  "+r.oneLine())
	}
	return strings.Join(lines, "\n")
}
