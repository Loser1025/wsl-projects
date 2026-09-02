package tools

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	skillBodyMaxChars    = 6000
	skillSummaryDescMax  = 200
	skillSummaryTotalMax = 1500
	scratchpadMaxChars   = 800
)

// skillToolAliases はClaude Code固有のツール名→Mimic側の対応ツール名
// （Python版 skills.py::_TOOL_ALIASES の移植）。
var skillToolAliases = map[string]string{
	"Read":      "read_file",
	"Write":     "write_file",
	"Edit":      "edit_file",
	"MultiEdit": "edit_file",
	"Bash":      "run_bash",
	"Grep":      "grep_codebase",
	"Glob":      "grep_codebase",
	"WebFetch":  "fetch_webpage",
	"WebSearch": "web_search",
	"TodoWrite": "update_scratchpad",
	"Task":      "delegate_to_specialist",
}

var skillAliasRe = func() *regexp.Regexp {
	names := make([]string, 0, len(skillToolAliases))
	for k := range skillToolAliases {
		names = append(names, regexp.QuoteMeta(k))
	}
	sort.Strings(names)
	return regexp.MustCompile(`\b(` + strings.Join(names, "|") + `)\b`)
}()

// buildAliasHint は本文中に出現するClaude Code固有ツール名を検出し、Mimic側の
// 対応ツールへの読み替えヒントを返す（Python版 _build_alias_hint の移植）。
// 該当なしなら空文字列。
func buildAliasHint(body string) string {
	matches := skillAliasRe.FindAllString(body, -1)
	if len(matches) == 0 {
		return ""
	}
	seen := make(map[string]bool)
	var found []string
	for _, m := range matches {
		if !seen[m] {
			seen[m] = true
			found = append(found, m)
		}
	}
	sort.Strings(found)
	var lines []string
	for _, name := range found {
		lines = append(lines, fmt.Sprintf("  %s → %s", name, skillToolAliases[name]))
	}
	return "\n\n[ハーネス注記: ツール名の読み替え]\n" +
		"このSkillはClaude Code向けに書かれており、本文中のツール名はMimicのツール体系と異なります。" +
		"実行時は以下のように読み替えてください:\n" + strings.Join(lines, "\n")
}

// ── Skill使用トラッキング（P1: 信頼スコアリング統合の下地。Python版 mark_loaded/
// pop_used の移植）。Python版はthreading.localでスレッド単位に隔離するが、
// Go版はin-process実行（Director直接呼び出し／読み取り専用Specialistの単一
// goroutine内完結呼び出し）でのみ使う前提のため、単純なミューテックス保護の
// パッケージレベル集合で代替する。
var (
	skillUsageMu sync.Mutex
	skillUsage   = map[string]bool{}
)

// MarkSkillLoaded はload_skillツール実行時に呼ぶ。
func MarkSkillLoaded(name string) {
	skillUsageMu.Lock()
	skillUsage[name] = true
	skillUsageMu.Unlock()
}

// PopUsedSkills は使用済みskill名集合を取り出してクリアする。
func PopUsedSkills() []string {
	skillUsageMu.Lock()
	defer skillUsageMu.Unlock()
	out := make([]string, 0, len(skillUsage))
	for k := range skillUsage {
		out = append(out, k)
	}
	skillUsage = map[string]bool{}
	return out
}

type skill struct {
	name        string
	description string
	path        string
}

// skillRegistry はPython版 SkillRegistry の移植。
type skillRegistry struct {
	mu     sync.Mutex
	skills map[string]skill
	dirs   []string
}

var globalSkillRegistry = &skillRegistry{skills: make(map[string]skill)}

var frontmatterRe = regexp.MustCompile(`(?s)\A---\s*\n(.*?)\n---\s*\n?(.*)\z`)

func parseFrontmatter(text string) (map[string]string, string) {
	m := frontmatterRe.FindStringSubmatch(text)
	if m == nil {
		return map[string]string{}, text
	}
	meta := make(map[string]string)
	for _, line := range strings.Split(m[1], "\n") {
		trimmed := strings.TrimRight(line, " \t")
		if trimmed == "" || strings.HasPrefix(strings.TrimSpace(trimmed), "#") {
			continue
		}
		if len(trimmed) > 0 && (trimmed[0] == ' ' || trimmed[0] == '\t') {
			continue // ネストしたキーはトップレベルnameで扱わないためスキップ
		}
		idx := strings.Index(trimmed, ":")
		if idx < 0 {
			continue
		}
		key := strings.TrimSpace(trimmed[:idx])
		val := strings.TrimSpace(trimmed[idx+1:])
		val = strings.Trim(val, `"'`)
		if key != "" {
			meta[key] = val
		}
	}
	return meta, strings.Trim(m[2], "\n")
}

func defaultSkillDirs() []string {
	home, _ := os.UserHomeDir()
	cwd, _ := os.Getwd()
	dirs := []string{filepath.Join(home, ".claude", "skills")}
	cwdSkills := filepath.Join(cwd, ".claude", "skills")
	if cwdSkills != dirs[0] {
		dirs = append(dirs, cwdSkills)
	}
	return dirs
}

func (sr *skillRegistry) scan(dirs []string) int {
	found := make(map[string]skill)
	for _, d := range dirs {
		matches, _ := filepath.Glob(filepath.Join(d, "*", "SKILL.md"))
		sort.Strings(matches)
		for _, mdPath := range matches {
			data, err := os.ReadFile(mdPath)
			if err != nil {
				continue
			}
			meta, _ := parseFrontmatter(string(data))
			name := meta["name"]
			if name == "" {
				name = filepath.Base(filepath.Dir(mdPath))
			}
			desc := meta["description"]
			if name == "" {
				continue
			}
			found[name] = skill{name: name, description: desc, path: mdPath}
		}
	}
	sr.mu.Lock()
	for k, v := range found {
		sr.skills[k] = v
	}
	sr.dirs = dirs
	sr.mu.Unlock()
	return len(found)
}

func (sr *skillRegistry) rescan() int {
	sr.mu.Lock()
	dirs := append([]string(nil), sr.dirs...)
	sr.mu.Unlock()
	if len(dirs) == 0 {
		return 0
	}
	return sr.scan(dirs)
}

func (sr *skillRegistry) listSummaries() []skill {
	sr.mu.Lock()
	defer sr.mu.Unlock()
	out := make([]skill, 0, len(sr.skills))
	for _, s := range sr.skills {
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].name < out[j].name })
	return out
}

func (sr *skillRegistry) loadBody(name string) string {
	sr.mu.Lock()
	sk, ok := sr.skills[name]
	sr.mu.Unlock()
	if !ok {
		names := []string{}
		for _, s := range sr.listSummaries() {
			names = append(names, s.name)
		}
		available := strings.Join(names, ", ")
		if available == "" {
			available = "(なし)"
		}
		return fmt.Sprintf("エラー: Skill '%s' が見つかりません。利用可能: %s", name, available)
	}
	data, err := os.ReadFile(sk.path)
	if err != nil {
		return fmt.Sprintf("エラー: %s を読めませんでした (%v)", sk.path, err)
	}
	_, body := parseFrontmatter(string(data))
	aliasHint := buildAliasHint(body)
	if len(body) <= skillBodyMaxChars {
		return fmt.Sprintf("[Skill: %s]\n%s\n%s%s", name, strings.Repeat("─", 60), body, aliasHint)
	}
	// 本文超過時はread_tool_cacheでページング継続できるようキャッシュする
	// （Python版 skills.py: 6000字超過分をcache_tool_output/read_tool_cache経由で提供する仕様の移植）。
	return fmt.Sprintf("[Skill: %s]\n%s\n%s%s", name, strings.Repeat("─", 60), CacheObs("load_skill:"+name, body, skillBodyMaxChars), aliasHint)
}

func registerSkillTools(r *Registry) {
	r.Register("load_skill",
		"Skill（.claude/skills/<name>/SKILL.md）の本文をロードする。本文はプレーンな手順・知識のMarkdownであり、コードとして実行はされない。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"name": map[string]any{"type": "string", "description": "Skill名（一覧のname）"},
			},
			"required": []string{"name"},
		},
		func(args map[string]any) (string, error) {
			name := argString(args, "name")
			MarkSkillLoaded(name)
			return globalSkillRegistry.loadBody(name), nil
		})

	r.Register("list_skills",
		"利用可能なSkill一覧（name+description）を再取得する。ディレクトリを再スキャンする。",
		map[string]any{"type": "object", "properties": map[string]any{}},
		func(args map[string]any) (string, error) {
			if len(globalSkillRegistry.listSummaries()) == 0 {
				globalSkillRegistry.scan(defaultSkillDirs())
			} else {
				globalSkillRegistry.rescan()
			}
			skills := globalSkillRegistry.listSummaries()
			if len(skills) == 0 {
				return "利用可能なSkillはありません（.claude/skills/ 配下にSKILL.mdが見つかりません）", nil
			}
			cwd, _ := os.Getwd()
			trust := loadSkillTrust(cwd)
			var lines []string
			for _, s := range skills {
				desc := s.description
				if len(desc) > skillSummaryDescMax {
					desc = desc[:skillSummaryDescMax]
				}
				badge := "（※未検証）"
				if t, ok := trust[s.name]; ok && t.PassCount > 0 {
					badge = fmt.Sprintf("（検証通過%d回）", t.PassCount)
				}
				lines = append(lines, fmt.Sprintf("- %s%s: %s", s.name, badge, desc))
			}
			return strings.Join(lines, "\n"), nil
		})

	r.Register("update_scratchpad",
		"作業メモを更新する（800字以内）。ゴール・完了済み・次のステップ・発見事項を記録し記憶喪失を防ぐ。",
		map[string]any{
			"type": "object",
			"properties": map[string]any{
				"content": map[string]any{"type": "string", "description": "スクラッチパッドに書き込む内容（800字以内、所定フォーマットで記述）"},
			},
			"required": []string{"content"},
		},
		func(args map[string]any) (string, error) {
			content := argString(args, "content")
			if len(content) > scratchpadMaxChars {
				content = content[:scratchpadMaxChars] + "\n…（上限800字で切り捨て）"
			}
			setScratchpad(content)
			return fmt.Sprintf("スクラッチパッドを更新しました（%d文字）", len(content)), nil
		})
}

// ReloadSkills はSkillディレクトリを明示的に再スキャンする（Python版
// `/skills reload`サブコマンド ↔ SkillRegistry.rescan の移植）。
func ReloadSkills() string {
	var n int
	if len(globalSkillRegistry.listSummaries()) == 0 {
		n = globalSkillRegistry.scan(defaultSkillDirs())
	} else {
		n = globalSkillRegistry.rescan()
	}
	return fmt.Sprintf("Skillを再スキャンしました（%d件）", n)
}

// SkillContextHeaderSection は「利用可能なSkill」一覧を毎ターンのsystemPromptに
// 常時掲載するためのセクション文字列を返す（Python版 skills.py::
// SkillRegistry.context_header_section の移植。name+descriptionのみで
// 本文はload_skill(name)を呼ぶまで見せないProgressive Disclosureを実現する）。
// Skillが1件も無ければ空文字を返す。
func SkillContextHeaderSection() string {
	if len(globalSkillRegistry.listSummaries()) == 0 {
		globalSkillRegistry.scan(defaultSkillDirs())
	} else {
		globalSkillRegistry.rescan()
	}
	skills := globalSkillRegistry.listSummaries()
	if len(skills) == 0 {
		return ""
	}
	cwd, _ := os.Getwd()
	trust := loadSkillTrust(cwd)

	var lines []string
	total := 0
	for i, s := range skills {
		desc := s.description
		if len(desc) > skillSummaryDescMax {
			desc = desc[:skillSummaryDescMax]
		}
		badge := "（※未検証）"
		if t, ok := trust[s.name]; ok && t.PassCount > 0 {
			badge = fmt.Sprintf("（検証通過%d回）", t.PassCount)
		}
		line := fmt.Sprintf("- %s%s: %s", s.name, badge, desc)
		if total+len(line) > skillSummaryTotalMax {
			lines = append(lines, fmt.Sprintf("…他 %d 件（省略）", len(skills)-i))
			break
		}
		lines = append(lines, line)
		total += len(line)
	}
	return "\n\n## 利用可能なSkill（name+descriptionのみ。本文は load_skill(name) で取得）\n" +
		strings.Join(lines, "\n") + "\n"
}

// ScratchpadHistoryEntry は1回のupdate_scratchpad呼び出し（Director自身の分）。
type ScratchpadHistoryEntry struct {
	TS      string
	Content string
}

const scratchpadHistoryKeep = 50

var (
	scratchpadMu      sync.Mutex
	currentScratch    = "【現在の進捗】タスクを開始しました。"
	scratchpadHistory []ScratchpadHistoryEntry
)

func setScratchpad(text string) {
	scratchpadMu.Lock()
	currentScratch = text
	scratchpadHistory = append(scratchpadHistory, ScratchpadHistoryEntry{
		TS:      time.Now().Format("2006-01-02T15:04:05"),
		Content: text,
	})
	if len(scratchpadHistory) > scratchpadHistoryKeep {
		scratchpadHistory = scratchpadHistory[len(scratchpadHistory)-scratchpadHistoryKeep:]
	}
	scratchpadMu.Unlock()
}

// GetScratchpad は現在のスクラッチパッド内容を返す（TUIのScratchpadタブ表示用）。
func GetScratchpad() string {
	scratchpadMu.Lock()
	defer scratchpadMu.Unlock()
	return currentScratch
}

// GetScratchpadHistory はDirector自身のupdate_scratchpad呼び出し履歴を時系列で
// 返す（Python版 app.py::_refresh_scratchpad_tab の履歴表示部分の移植）。
func GetScratchpadHistory() []ScratchpadHistoryEntry {
	scratchpadMu.Lock()
	defer scratchpadMu.Unlock()
	out := make([]ScratchpadHistoryEntry, len(scratchpadHistory))
	copy(out, scratchpadHistory)
	return out
}
