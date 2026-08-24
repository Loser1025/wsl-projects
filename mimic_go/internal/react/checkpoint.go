package react

import (
	"encoding/json"
	"os"
	"path/filepath"

	"mimic/internal/llm"
)

// SaveCheckpoint は現在の会話履歴をpathへ永続化する
// （Python版 .mimic_checkpoint.json 相当）。中断・クラッシュ後に
// LoadCheckpointで復元できるようにするためのもの。書き込みは
// tmpファイル経由のrenameでアトミックに行う。
func SaveCheckpoint(path string, history []llm.Message) error {
	if path == "" {
		return nil
	}
	if dir := filepath.Dir(path); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return err
		}
	}
	data, err := json.MarshalIndent(history, "", "  ")
	if err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// LoadCheckpoint はpathに保存済みの履歴があれば読み込んで返す。
// ファイルが存在しない場合はnil, nilを返す（エラー扱いしない）。
func LoadCheckpoint(path string) ([]llm.Message, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var history []llm.Message
	if err := json.Unmarshal(data, &history); err != nil {
		return nil, err
	}
	return history, nil
}

// ClearCheckpoint はターン正常完了後にチェックポイントを削除する。
// 削除失敗（未作成含む）は呼び出し側にとって無害なため無視する。
func ClearCheckpoint(path string) {
	if path == "" {
		return
	}
	_ = os.Remove(path)
}
