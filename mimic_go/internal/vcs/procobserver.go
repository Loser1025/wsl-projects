package vcs

import (
	"bufio"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"
)

// Linux /proc を使った軽量プロセス監視（Python版 proc_observer.py::ProcessMonitor
// の縮小移植）。ツール呼び出し1回ごとにバックグラウンドでポーリングし、
// その間のCPU使用率最大値・RSS増分を計測する。/proc が無い環境（非Linux）では
// 常にゼロ値を返す（ベストエフォート、致命的エラーにはしない）。

var jiffyOnce sync.Once
var jiffyHz float64 = 100 // Linuxの一般的なデフォルト

func getJiffy() float64 {
	jiffyOnce.Do(func() {
		// getconf CLK_TCKを実測する（Python版 os.sysconf("SC_CLK_TCK") の移植。
		// Goの標準ライブラリにはsysconf相当が無いため`getconf`コマンドを使う。
		// 失敗した場合はLinuxの一般的なデフォルト100Hzにフォールバックする。
		out, err := exec.Command("getconf", "CLK_TCK").Output()
		if err == nil {
			if v, perr := strconv.ParseFloat(strings.TrimSpace(string(out)), 64); perr == nil && v > 0 {
				jiffyHz = v
				return
			}
		}
		jiffyHz = 100
	})
	return jiffyHz
}

// readSelfStat は/proc/self/statからutime/stime（秒換算の累積CPU時間）を返す。
func readSelfStat() (utime, stime float64, ok bool) {
	data, err := os.ReadFile("/proc/self/stat")
	if err != nil {
		return 0, 0, false
	}
	// commフィールドに空白や括弧が含まれうるため、最後の ")" 以降をフィールド分割する。
	s := string(data)
	idx := strings.LastIndexByte(s, ')')
	if idx < 0 || idx+2 >= len(s) {
		return 0, 0, false
	}
	fields := strings.Fields(s[idx+2:])
	// ")"の次のフィールドが state(3番目)なので、utime(14番目)/stime(15番目)は
	// 0-indexedでこの配列の10, 11番目に当たる。
	if len(fields) < 12 {
		return 0, 0, false
	}
	ut, err1 := strconv.ParseFloat(fields[10], 64)
	st, err2 := strconv.ParseFloat(fields[11], 64)
	if err1 != nil || err2 != nil {
		return 0, 0, false
	}
	jiffy := getJiffy()
	return ut / jiffy, st / jiffy, true
}

// readSelfRSS は/proc/self/statusのVmRSSをMB単位で返す。
func readSelfRSS() float64 {
	f, err := os.Open("/proc/self/status")
	if err != nil {
		return 0
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "VmRSS:") {
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				if kb, err := strconv.ParseFloat(fields[1], 64); err == nil {
					return kb / 1024.0
				}
			}
		}
	}
	return 0
}

// readSelfThreadCount は/proc/self/statusのThreadsフィールドを返す
// （Python版 proc_observer.py::Sample.thread_count の移植）。
func readSelfThreadCount() int {
	f, err := os.Open("/proc/self/status")
	if err != nil {
		return 0
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "Threads:") {
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				if n, err := strconv.Atoi(fields[1]); err == nil {
					return n
				}
			}
		}
	}
	return 0
}

// readSelfFDCount は/proc/self/fd配下のエントリ数（オープンFD数）を返す
// （Python版 proc_observer.py::_count_fds の移植）。
func readSelfFDCount() int {
	entries, err := os.ReadDir("/proc/self/fd")
	if err != nil {
		return 0
	}
	return len(entries)
}

// ProcSummary はProcessMonitor.Stopの計測結果（Python版 proc_observer.py::Summary
// の移植。cpu_avg_pct/samples/duration_sec/fd_max/thread_countも含めて対応する）。
type ProcSummary struct {
	CPUMaxPct   float64
	CPUAvgPct   float64
	RSSStartMB  float64
	RSSDeltaMB  float64
	FDMax       int
	ThreadCount int
	Samples     int
	DurationSec float64
}

// ProcessMonitor は自プロセス（os.Getpid相当、Go版はランタイム全体）の
// CPU/RSSを一定間隔でポーリングするバックグラウンド監視。
type ProcessMonitor struct {
	interval time.Duration
	stopCh   chan struct{}
	doneCh   chan struct{}

	mu          sync.Mutex
	cpuMax      float64
	cpuSum      float64
	rssStart    float64
	rssLatest   float64
	fdMax       int
	threadCount int
	samples     int
	startTime   time.Time
}

// NewProcessMonitor はintervalごとにポーリングするモニタを作る
// （Python版と同じく既定0.3秒）。
func NewProcessMonitor() *ProcessMonitor {
	return &ProcessMonitor{interval: 300 * time.Millisecond}
}

// Start はバックグラウンドポーリングを開始する。
func (m *ProcessMonitor) Start() {
	m.stopCh = make(chan struct{})
	m.doneCh = make(chan struct{})
	m.rssStart = readSelfRSS()
	m.rssLatest = m.rssStart
	m.fdMax = readSelfFDCount()
	m.threadCount = readSelfThreadCount()
	m.startTime = time.Now()

	go func() {
		defer close(m.doneCh)
		prevUt, prevSt, ok := readSelfStat()
		prevTime := time.Now()
		ticker := time.NewTicker(m.interval)
		defer ticker.Stop()
		for {
			select {
			case <-m.stopCh:
				return
			case now := <-ticker.C:
				ut, st, curOk := readSelfStat()
				elapsed := now.Sub(prevTime).Seconds()
				if ok && curOk && elapsed > 0 {
					pct := (ut - prevUt + (st - prevSt)) / elapsed * 100.0
					if pct > 100 {
						pct = 100
					}
					if pct < 0 {
						pct = 0
					}
					m.mu.Lock()
					if pct > m.cpuMax {
						m.cpuMax = pct
					}
					m.cpuSum += pct
					m.samples++
					m.mu.Unlock()
				}
				prevUt, prevSt, ok = ut, st, curOk
				prevTime = now
				fd := readSelfFDCount()
				threads := readSelfThreadCount()
				m.mu.Lock()
				m.rssLatest = readSelfRSS()
				if fd > m.fdMax {
					m.fdMax = fd
				}
				if threads > m.threadCount {
					m.threadCount = threads
				}
				m.mu.Unlock()
			}
		}
	}()
}

// Stop はポーリングを止め、計測サマリを返す。
func (m *ProcessMonitor) Stop() ProcSummary {
	if m.stopCh != nil {
		close(m.stopCh)
		<-m.doneCh
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	cpuAvg := 0.0
	if m.samples > 0 {
		cpuAvg = m.cpuSum / float64(m.samples)
	}
	return ProcSummary{
		CPUMaxPct:   m.cpuMax,
		CPUAvgPct:   cpuAvg,
		RSSStartMB:  m.rssStart,
		RSSDeltaMB:  m.rssLatest - m.rssStart,
		FDMax:       m.fdMax,
		ThreadCount: m.threadCount,
		Samples:     m.samples,
		DurationSec: time.Since(m.startTime).Seconds(),
	}
}

// Current はポーリングを止めずに現時点のサマリを返す
// （Python版 ProcessMonitor.current() の移植。/statsのライブ表示等で使う）。
func (m *ProcessMonitor) Current() ProcSummary {
	m.mu.Lock()
	defer m.mu.Unlock()
	cpuAvg := 0.0
	if m.samples > 0 {
		cpuAvg = m.cpuSum / float64(m.samples)
	}
	return ProcSummary{
		CPUMaxPct:   m.cpuMax,
		CPUAvgPct:   cpuAvg,
		RSSStartMB:  m.rssStart,
		RSSDeltaMB:  m.rssLatest - m.rssStart,
		FDMax:       m.fdMax,
		ThreadCount: m.threadCount,
		Samples:     m.samples,
		DurationSec: time.Since(m.startTime).Seconds(),
	}
}
