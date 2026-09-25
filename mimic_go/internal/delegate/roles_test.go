package delegate

import (
	"strings"
	"testing"
)

func TestSaveSpecialistRole_PassIncludedInSection(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)

	SaveSpecialistRole("テスト用のロール定義その1", "write", true)
	section := LoadSavedRolesSection(10)
	if !strings.Contains(section, "テスト用のロール定義その1") {
		t.Errorf("成功ロールが注入対象に含まれていない: %q", section)
	}
}

func TestSaveSpecialistRole_MoreFailsThanPassesExcluded(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)

	role := "失敗しがちなロール定義"
	SaveSpecialistRole(role, "write", false)
	SaveSpecialistRole(role, "write", false)
	SaveSpecialistRole(role, "write", true) // Pass=1, Fail=2 → 依然としてFail優勢

	section := LoadSavedRolesSection(10)
	if strings.Contains(section, role) {
		t.Errorf("失敗の方が多いロールが注入対象から除外されていない: %q", section)
	}
}

func TestSaveSpecialistRole_EqualPassFailIncluded(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)

	role := "五分五分のロール定義"
	SaveSpecialistRole(role, "write", false)
	SaveSpecialistRole(role, "write", true) // Pass=1, Fail=1 → FailCount > PassCountではない

	section := LoadSavedRolesSection(10)
	if !strings.Contains(section, role) {
		t.Errorf("Fail>Passでないロールが除外されてしまった: %q", section)
	}
}

func TestLoadSavedRolesSection_EmptyWhenNoRoles(t *testing.T) {
	tmp := t.TempDir()
	t.Chdir(tmp)
	if got := LoadSavedRolesSection(10); got != "" {
		t.Errorf("ロール未保存なのに空文字以外が返された: %q", got)
	}
}
