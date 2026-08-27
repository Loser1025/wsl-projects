package vcs

import (
	"bufio"
	"os"
	"strconv"
	"strings"
	"sync"
)

// システム全体のCPU/メモリ使用率（Python版 proc_observer.py::get_system_cpu_percent /
// get_system_mem_info の移植）。TUIの■ SYSTEMステータスパネルで使う。

var (
	systemStatsMu     sync.Mutex
	prevCPUIdle       float64
	prevCPUTotal      float64
	havePrevCPUSample bool
)

// GetSystemCPUPercent は/proc/statから前回呼び出しとの差分でシステム全体の
// CPU使用率(%)を返す。初回呼び出しは差分が取れないため0.0を返す。
func GetSystemCPUPercent() float64 {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return 0
	}
	defer f.Close()
	scanner := bufio.NewScanner(f)
	if !scanner.Scan() {
		return 0
	}
	fields := strings.Fields(scanner.Text())
	if len(fields) < 6 || fields[0] != "cpu" {
		return 0
	}
	var values []float64
	for _, s := range fields[1:] {
		v, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return 0
		}
		values = append(values, v)
	}
	idle := values[3] + values[4] // idle + iowait
	total := 0.0
	for _, v := range values {
		total += v
	}

	systemStatsMu.Lock()
	defer systemStatsMu.Unlock()
	prevIdle, prevTotal, had := prevCPUIdle, prevCPUTotal, havePrevCPUSample
	prevCPUIdle, prevCPUTotal, havePrevCPUSample = idle, total, true
	if !had {
		return 0
	}
	dIdle := idle - prevIdle
	dTotal := total - prevTotal
	if dTotal <= 0 {
		return 0
	}
	pct := (1.0 - dIdle/dTotal) * 100.0
	if pct < 0 {
		pct = 0
	}
	if pct > 100 {
		pct = 100
	}
	return pct
}

// GetSystemMemInfo は/proc/meminfoからシステム全体の(使用量MB, 総容量MB)を返す。
// 読めない場合は(0,0)。
func GetSystemMemInfo() (usedMB, totalMB float64) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0, 0
	}
	defer f.Close()

	info := make(map[string]float64)
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		key, rest, ok := strings.Cut(line, ":")
		if !ok {
			continue
		}
		fields := strings.Fields(rest)
		if len(fields) == 0 {
			continue
		}
		v, err := strconv.ParseFloat(fields[0], 64)
		if err != nil {
			continue
		}
		info[key] = v // kB
	}
	total := info["MemTotal"]
	avail := info["MemAvailable"]
	return (total - avail) / 1024.0, total / 1024.0
}
