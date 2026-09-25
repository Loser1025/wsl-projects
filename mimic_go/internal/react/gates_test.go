package react

import "testing"

func TestDetectCommandOffload(t *testing.T) {
	tools := []string{"run_bash", "read_file"}
	cases := []struct {
		name  string
		text  string
		tools []string
		want  bool
	}{
		{"丸投げ検知", "以下のコマンドを実行してください: go test ./...", tools, true},
		{"手動修正依頼", "手動で修正してください。", tools, true},
		{"実行ツール無し", "実行してください。", []string{"read_file"}, false},
		{"免除語ログイン", "ログインしてから実行してください。", tools, false},
		{"免除語この環境では実行できない", "この環境では実行できないため、お手元で実行してください。", tools, false},
		{"通常の完了報告", "テストを実行し、全て成功しました。", tools, false},
		{"空文字", "", tools, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := detectCommandOffload(c.text, c.tools); got != c.want {
				t.Errorf("detectCommandOffload(%q) = %v, want %v", c.text, got, c.want)
			}
		})
	}
}

func TestDetectUnverifiedClaim(t *testing.T) {
	cases := []struct {
		name              string
		text              string
		turnHadUnverified bool
		want              bool
	}{
		{"未検証なのに完了断言", "修正しました。完了です。", true, true},
		{"未検証タグ自体がある場合は許容", "修正しましたが、※未検証です。", true, false},
		{"確認できていない明記は許容", "対応しましたが動作未確認です。", true, false},
		{"ターン内に未検証委任が無ければ無視", "完了しました。", false, false},
		{"空文字", "", true, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := detectUnverifiedClaim(c.text, c.turnHadUnverified); got != c.want {
				t.Errorf("detectUnverifiedClaim(%q, %v) = %v, want %v", c.text, c.turnHadUnverified, got, c.want)
			}
		})
	}
}

func TestDetectUnverifiedDirectWrite(t *testing.T) {
	cases := []struct {
		name                   string
		text                   string
		directWriteSinceVerify bool
		want                   bool
	}{
		{"直接書き込み後の未検証断言", "実装しました。", true, true},
		{"検証済みなら対象外", "実装しました。", false, false},
		{"未検証を自己申告していれば許容", "実装しましたが未検証です。", true, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := detectUnverifiedDirectWrite(c.text, c.directWriteSinceVerify); got != c.want {
				t.Errorf("detectUnverifiedDirectWrite(%q, %v) = %v, want %v", c.text, c.directWriteSinceVerify, got, c.want)
			}
		})
	}
}
