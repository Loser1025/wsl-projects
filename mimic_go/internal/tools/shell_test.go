package tools

import "testing"

func TestWorkerOutsideWriteWarning(t *testing.T) {
	t.Setenv("MIMIC_NO_AUTOGIT", "1")
	t.Chdir(t.TempDir())

	cases := []struct {
		name       string
		command    string
		wantWarned bool
	}{
		{"相対パスへのリダイレクトは警告なし", "echo hi > local.txt", false},
		{"作業ディレクトリ外への絶対パスリダイレクト", "echo hi > /etc/passwd", true},
		{"/tmp配下は除外", "echo hi > /tmp/scratch.txt", false},
		{"cpでの外部コピー", "cp a.txt /etc/hosts", true},
		{"ddでの外部書き込み(新規追加パターン)", "dd if=/dev/zero of=/etc/passwd bs=1 count=1", true},
		{"sed -iでの外部編集(新規追加パターン)", "sed -i 's/a/b/' /etc/hosts", true},
		{"installでの外部配置(新規追加パターン)", "install foo.txt /usr/local/bin/foo", true},
		{"rsyncでの外部同期(新規追加パターン)", "rsync -a src/ /home/user/backup/", true},
		{"何もしないコマンド", "ls -la", false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := workerOutsideWriteWarning(c.command) != ""
			if got != c.wantWarned {
				t.Errorf("workerOutsideWriteWarning(%q) warned=%v, want %v", c.command, got, c.wantWarned)
			}
		})
	}
}

func TestWorkerOutsideWriteWarning_DisabledWithoutNoAutoGit(t *testing.T) {
	t.Setenv("MIMIC_NO_AUTOGIT", "")
	if got := workerOutsideWriteWarning("echo hi > /etc/passwd"); got != "" {
		t.Errorf("MIMIC_NO_AUTOGIT未設定時は警告なしのはず: %q", got)
	}
}

func TestSudoPassword_UnsetReturnsNotOK(t *testing.T) {
	t.Setenv("SUDO_PASSWORD", "")
	if pw, ok := sudoPassword(); ok || pw != nil {
		t.Errorf("SUDO_PASSWORD未設定なのにok=%v pw=%q（ハードコードされた既定値に戻っていないか確認）", ok, pw)
	}
}

func TestSudoPassword_SetReturnsValue(t *testing.T) {
	t.Setenv("SUDO_PASSWORD", "correct-horse-battery-staple")
	pw, ok := sudoPassword()
	if !ok {
		t.Fatal("SUDO_PASSWORD設定済みなのにok=falseになった")
	}
	if string(pw) != "correct-horse-battery-staple\n" {
		t.Errorf("pw = %q, want %q", pw, "correct-horse-battery-staple\n")
	}
}
