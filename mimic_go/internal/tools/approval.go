package tools

import (
	"fmt"
	"sync"
)

// ApprovalHandler は write_file/edit_file/patch_file 実行前の承認判断を行う
// コールバック（Python版 tools.py::_write_approval_handler の移植）。
// toolName・path・preview（変更内容の要約）を受け取り、実行してよければtrueを返す。
type ApprovalHandler func(toolName, path, preview string) bool

var (
	approvalMu      sync.Mutex
	approvalHandler ApprovalHandler
)

// SetWriteApprovalHandler は書き込み系ツール実行前の承認ハンドラを登録する。
// nilを渡すと承認なし（Worker等、TUI外での実行時のデフォルト——Python版が
// _write_approval_handler未設定時に無条件許可するのと同じ挙動）。
func SetWriteApprovalHandler(h ApprovalHandler) {
	approvalMu.Lock()
	approvalHandler = h
	approvalMu.Unlock()
}

// writeRejectedPrefix はユーザーが承認を拒否したことを示す特別なprefix。
// internal/react のループがこのprefixを検出してターンを即中断する
// （Python版 UserRejectedWriteError を捕捉してrun_reactを即returnする挙動の移植）。
const writeRejectedPrefix = "エラー: 書き込みが拒否されました"

// requestWriteApproval はハンドラが設定されていれば呼び出す。
// 拒否された場合は writeRejectedPrefix で始まるエラー文字列を返し、
// 承認された/ハンドラ未設定の場合は空文字列を返す。
func requestWriteApproval(toolName, path, preview string) string {
	approvalMu.Lock()
	h := approvalHandler
	approvalMu.Unlock()
	if h == nil {
		return ""
	}
	if h(toolName, path, preview) {
		return ""
	}
	return fmt.Sprintf("%s: %s", writeRejectedPrefix, path)
}

// IsWriteRejected は registry.Call の出力が承認拒否によるものかを判定する。
func IsWriteRejected(output string) bool {
	return len(output) >= len(writeRejectedPrefix) && output[:len(writeRejectedPrefix)] == writeRejectedPrefix
}

// HostExecApprovalHandler は run_host_command 実行前の承認判断を行うコールバック
// （Python版 tools.py::_host_exec_approval_handler の移植）。command・reasonを
// 受け取り、実行してよければtrueを返す。
type HostExecApprovalHandler func(command, reason string) bool

var (
	hostExecApprovalMu sync.Mutex
	hostExecApproval   HostExecApprovalHandler
)

// SetHostExecApprovalHandler はrun_host_command実行前の承認ハンドラを登録する。
// nilを渡すと未登録扱いになり、run_host_commandは常に拒否される
// （Python版が非対話実行時に常に拒否するのと同じ安全側の既定動作）。
func SetHostExecApprovalHandler(h HostExecApprovalHandler) {
	hostExecApprovalMu.Lock()
	hostExecApproval = h
	hostExecApprovalMu.Unlock()
}

// requestHostExecApproval はrun_host_commandから呼ぶ。ハンドラが無ければ
// (false, false)を返し、呼び出し元は「未登録のため拒否」を報告すること。
func requestHostExecApproval(command, reason string) (approved, handlerRegistered bool) {
	hostExecApprovalMu.Lock()
	h := hostExecApproval
	hostExecApprovalMu.Unlock()
	if h == nil {
		return false, false
	}
	return h(command, reason), true
}

// RequestMCPApproval はMCPツール呼び出し前に承認を要求する（Python版
// mcp_client.py::_make_tool_fn が _request_write_approval を呼ぶのと同じ経路を、
// internal/mcp から internal/tools を経由して使うためのエクスポート版）。
// MCP呼び出しの引数には通常 write_file 等のような明確な "path" が無いため、
// Python版と同じく "?" を渡す。
func RequestMCPApproval(toolName, preview string) string {
	return requestWriteApproval(toolName, "?", preview)
}
