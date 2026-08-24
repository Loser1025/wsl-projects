package tools

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
)

const (
	skillBodyMaxChars    = 6000
	skillSummaryDescMax  = 200
	skillSummaryTotalMax = 1500
	scratchpadMaxChars   = 800
)

type skill struct {
	name        string
	description string
	path        string
}

// skillRegistry はPython版 SkillRegistry の縮小移植。トラストスコアリング・
// ツール名エイリアスヒント・使用トラッキング(P1/P2)は本バッチでは未移植。
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
	total := len(body)
	if total <= skillBodyMaxChars {
		return fmt.Sprintf("[Skill: %s]\n%s\n%s", name, strings.Repeat("─", 60), body)
	}
	head := body[:skillBodyMaxChars]
	return fmt.Sprintf(
		"[Skill: %s  本文 %d文字中 先頭 %d文字]\n%s\n%s\n%s\n⚠ 本文が長いため切り詰めました（フェーズ2では続きの再取得手段は未移植）。",
		name, total, skillBodyMaxChars, strings.Repeat("─", 60), head, strings.Repeat("─", 60))
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
			return globalSkillRegistry.loadBody(argString(args, "name")), nil
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
			var lines []string
			for _, s := range skills {
				desc := s.description
				if len(desc) > skillSummaryDescMax {
					desc = desc[:skillSummaryDescMax]
				}
				lines = append(lines, fmt.Sprintf("- %s: %s", s.name, desc))
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

var (
	scratchpadMu   sync.Mutex
	currentScratch = "【現在の進捗】タスクを開始しました。"
)

func setScratchpad(text string) {
	scratchpadMu.Lock()
	currentScratch = text
	scratchpadMu.Unlock()
}

func getScratchpad() string {
	scratchpadMu.Lock()
	defer scratchpadMu.Unlock()
	return currentScratch
}
