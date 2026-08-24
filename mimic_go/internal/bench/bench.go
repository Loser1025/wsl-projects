// Package bench はGo版mimic-goの実測ベンチマーク基盤を実装する
// （Python版 mimic_bench.py の縮小移植）。新しいベンチマーク問題集は作らず、
// 既存の .mimic/ 配下の実績ログ（skill_trust.json / sessions/*.jsonl）を
// 集計してMarkdownレポートを出すだけ、という方針もそのまま踏襲する。
//
// 対象外（Go版に土台となる機能が無いため）:
//   - MCPサーバー別集計（mcp_policy.json — internal/mcp未実装）
//   - プロジェクト別verify_cmd実績（verify_cmds.json — verify_cmd学習機構は未実装）
package bench

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type skillStat struct {
	Pass      int
	Fail      int
	Total     int
	Rate      *float64
	LowSample bool
	LastUsed  string
}

type snapshot struct {
	GeneratedAt  string               `json:"generated_at"`
	Skills       map[string]skillStat `json:"skills"`
	SessionUsage map[string]int       `json:"session_usage"`
}

const minSample = 5 // これ未満の使用回数は「参考値」として区別表示する

type trustEntry struct {
	PassCount int    `json:"pass_count"`
	FailCount int    `json:"fail_count"`
	LastUsed  string `json:"last_used"`
}

func collectSkillStats(projectDir string) map[string]skillStat {
	out := make(map[string]skillStat)
	raw, err := os.ReadFile(filepath.Join(projectDir, ".mimic", "skill_trust.json"))
	if err != nil {
		return out
	}
	var data map[string]trustEntry
	if err := json.Unmarshal(raw, &data); err != nil {
		return out
	}
	for name, e := range data {
		total := e.PassCount + e.FailCount
		var rate *float64
		if total > 0 {
			r := float64(e.PassCount) / float64(total)
			rate = &r
		}
		out[name] = skillStat{
			Pass: e.PassCount, Fail: e.FailCount, Total: total,
			Rate: rate, LowSample: total < minSample, LastUsed: e.LastUsed,
		}
	}
	return out
}

// collectSessionUsage はsessions/*.jsonlのactionエントリを走査し、
// load_skillの呼び出し回数を集計する（skill_trust.jsonにはない「実際に
// 何回呼ばれたか」の生カウント）。壊れた行は無視する。
func collectSessionUsage(projectDir string) map[string]int {
	out := make(map[string]int)
	sessionsDir := filepath.Join(projectDir, ".mimic", "sessions")
	matches, _ := filepath.Glob(filepath.Join(sessionsDir, "*.jsonl"))
	for _, f := range matches {
		data, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var entry struct {
				Type string `json:"type"`
				Tool string `json:"tool"`
				Args struct {
					Name string `json:"name"`
				} `json:"args"`
			}
			if err := json.Unmarshal([]byte(line), &entry); err != nil {
				continue
			}
			if entry.Type == "action" && entry.Tool == "load_skill" && entry.Args.Name != "" {
				out[entry.Args.Name]++
			}
		}
	}
	return out
}

func historyDir(projectDir string) string {
	return filepath.Join(projectDir, ".mimic", "bench_history")
}

func snapshotPath(projectDir string) string {
	return filepath.Join(historyDir(projectDir), time.Now().Format("2006-01-02")+".json")
}

func saveSnapshot(projectDir string, snap snapshot) error {
	if err := os.MkdirAll(historyDir(projectDir), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(snapshotPath(projectDir), data, 0o644)
}

// loadPreviousSnapshot は今日以外で最新のスナップショットを読む
// （今日分は今まさに作っている最中なので除外する）。
func loadPreviousSnapshot(projectDir string) *snapshot {
	today := snapshotPath(projectDir)
	matches, _ := filepath.Glob(filepath.Join(historyDir(projectDir), "*.json"))
	var candidates []string
	for _, f := range matches {
		if f != today {
			candidates = append(candidates, f)
		}
	}
	if len(candidates) == 0 {
		return nil
	}
	sort.Sort(sort.Reverse(sort.StringSlice(candidates)))
	data, err := os.ReadFile(candidates[0])
	if err != nil {
		return nil
	}
	var snap snapshot
	if err := json.Unmarshal(data, &snap); err != nil {
		return nil
	}
	return &snap
}

func rateStr(rate *float64) string {
	if rate == nil {
		return "—"
	}
	return fmt.Sprintf("%.0f%%", *rate*100)
}

func diffPt(prev, cur *float64) string {
	if prev == nil || cur == nil {
		return ""
	}
	delta := int(((*cur - *prev) * 100) + 0.5)
	if delta == 0 {
		return "  前回比 ±0pt"
	}
	sign := ""
	if delta > 0 {
		sign = "+"
	}
	return fmt.Sprintf("  前回比 %s%dpt", sign, delta)
}

func buildReport(generatedAt string, skills map[string]skillStat, usage map[string]int, previous *snapshot) string {
	var lines []string
	lines = append(lines, fmt.Sprintf("# Mimic-Go ベンチマークレポート — %s", generatedAt[:10]), "")

	lines = append(lines, "## Skill別 通過率")
	if len(skills) == 0 && len(usage) == 0 {
		lines = append(lines, "（Skill使用実績なし）")
	} else {
		names := make(map[string]bool)
		for n := range skills {
			names[n] = true
		}
		for n := range usage {
			names[n] = true
		}
		sorted := make([]string, 0, len(names))
		for n := range names {
			sorted = append(sorted, n)
		}
		sort.Strings(sorted)
		var prevSkills map[string]skillStat
		if previous != nil {
			prevSkills = previous.Skills
		}
		for _, name := range sorted {
			s, ok := skills[name]
			callCount := usage[name]
			if !ok {
				lines = append(lines, fmt.Sprintf("- %s: 呼び出しあり(%d回)だが検証結果は未記録", name, callCount))
				continue
			}
			lowFlag := ""
			if s.LowSample {
				lowFlag = "（参考値・件数少）"
			}
			var prevRate *float64
			if prevSkills != nil {
				if p, ok := prevSkills[name]; ok {
					prevRate = p.Rate
				}
			}
			diff := diffPt(prevRate, s.Rate)
			callSuffix := ""
			if callCount > 0 {
				callSuffix = fmt.Sprintf("  呼び出し%d回", callCount)
			}
			lines = append(lines, fmt.Sprintf("- %s: %s (%d/%d)%s%s%s",
				name, rateStr(s.Rate), s.Pass, s.Total, lowFlag, diff, callSuffix))
		}
	}
	lines = append(lines, "")
	lines = append(lines, "## MCPサーバー別 / プロジェクト別verify_cmd実績")
	lines = append(lines, "（Go版では未実装のため対象外 — MCPクライアント・verify_cmd学習機構が未移植）")

	return strings.Join(lines, "\n")
}

// Run は集計→スナップショット保存→レポート生成→latest_report.mdへの書き出しまで行う。
// 戻り値: レポート本文（呼び出し元がそのまま表示できるように）。
func Run(projectDir string) (string, error) {
	previous := loadPreviousSnapshot(projectDir)
	skills := collectSkillStats(projectDir)
	usage := collectSessionUsage(projectDir)
	generatedAt := time.Now().Format("2006-01-02T15:04:05")

	if err := saveSnapshot(projectDir, snapshot{GeneratedAt: generatedAt, Skills: skills, SessionUsage: usage}); err != nil {
		return "", err
	}
	report := buildReport(generatedAt, skills, usage, previous)

	if err := os.MkdirAll(historyDir(projectDir), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(filepath.Join(historyDir(projectDir), "latest_report.md"), []byte(report), 0o644); err != nil {
		return "", err
	}
	return report, nil
}
