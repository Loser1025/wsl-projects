package llm

import (
	"math"
	"sync"
	"time"
)

// tokenBucket はRPM専用のトークンバケットレートリミッター
// （Python版 utils.TokenBucket の縮小移植。RPD日次カウンタは
// 実運用での使用頻度が低いため本バッチでは未移植）。
type tokenBucket struct {
	mu         sync.Mutex
	rpmLimit   float64
	tokens     float64
	lastRefill time.Time
	refillRate float64 // トークン/秒
}

func newTokenBucket(rpmLimit int) *tokenBucket {
	return &tokenBucket{
		rpmLimit:   float64(rpmLimit),
		tokens:     float64(rpmLimit),
		lastRefill: time.Now(),
		refillRate: float64(rpmLimit) / 60.0,
	}
}

func (tb *tokenBucket) refill(now time.Time) {
	elapsed := now.Sub(tb.lastRefill).Seconds()
	tb.tokens = math.Min(tb.rpmLimit, tb.tokens+elapsed*tb.refillRate)
	tb.lastRefill = now
}

// acquire は (成功したか, 待つべき秒数) を返す。
func (tb *tokenBucket) acquire() (bool, float64) {
	tb.mu.Lock()
	defer tb.mu.Unlock()
	now := time.Now()
	tb.refill(now)
	if tb.tokens >= 1.0-1e-5 {
		tb.tokens = math.Max(0, tb.tokens-1.0)
		return true, 0
	}
	if tb.refillRate <= 0 {
		return false, math.Inf(1)
	}
	return false, (1.0-tb.tokens)/tb.refillRate + 0.01
}

func (tb *tokenBucket) waitTime() float64 {
	tb.mu.Lock()
	defer tb.mu.Unlock()
	now := time.Now()
	tb.refill(now)
	if tb.tokens >= 1.0-1e-5 {
		return 0
	}
	if tb.refillRate <= 0 {
		return math.Inf(1)
	}
	return (1.0 - tb.tokens) / tb.refillRate
}

const (
	cooldownBase = 60.0  // 429後の基本クールダウン（秒）
	cooldownMax  = 600.0 // 最大クールダウン（10分）
)

// KeyManager は複数APIキーのローテーション + RPM制御 + 429時の指数バックオフ
// クールダウンを管理する（Python版 config.KeyManager の移植）。
type KeyManager struct {
	mu            sync.Mutex
	keys          []string
	buckets       []*tokenBucket
	keyIndex      int
	cooldownUntil []time.Time
	count429      []int
}

func NewKeyManager(keys []string, rpmLimit int) *KeyManager {
	buckets := make([]*tokenBucket, len(keys))
	for i := range keys {
		buckets[i] = newTokenBucket(rpmLimit)
	}
	return &KeyManager{
		keys:          keys,
		buckets:       buckets,
		cooldownUntil: make([]time.Time, len(keys)),
		count429:      make([]int, len(keys)),
	}
}

// Acquire は使用するキーと待ち時間(秒)を返す。待ち時間0なら即使用可。
func (km *KeyManager) Acquire() (string, float64) {
	km.mu.Lock()
	defer km.mu.Unlock()
	now := time.Now()
	n := len(km.keys)
	if n == 0 {
		return "", 0
	}
	for offset := 0; offset < n; offset++ {
		idx := (km.keyIndex + offset) % n
		if now.Before(km.cooldownUntil[idx]) {
			continue
		}
		if ok, _ := km.buckets[idx].acquire(); ok {
			km.keyIndex = (idx + 1) % n
			return km.keys[idx], 0
		}
	}
	// 全キーがビジー/クールダウン中 → 最も早く使えるキーを返す
	best := 0
	bestReady := math.Inf(1)
	for i := 0; i < n; i++ {
		cd := math.Max(0, km.cooldownUntil[i].Sub(now).Seconds())
		ready := math.Max(cd, km.buckets[i].waitTime())
		if ready < bestReady {
			bestReady = ready
			best = i
		}
	}
	return km.keys[best], bestReady
}

// Report429 は429を受けたキーに指数バックオフクールダウンを設定する。
func (km *KeyManager) Report429(apiKey string) {
	km.mu.Lock()
	defer km.mu.Unlock()
	for i, k := range km.keys {
		if k == apiKey {
			km.count429[i]++
			cooldown := math.Min(cooldownBase*math.Pow(2, float64(km.count429[i]-1)), cooldownMax)
			km.cooldownUntil[i] = time.Now().Add(time.Duration(cooldown * float64(time.Second)))
			km.buckets[i].mu.Lock()
			km.buckets[i].tokens = 0
			km.buckets[i].mu.Unlock()
			return
		}
	}
}

// ReportSuccess は成功時に連続429カウントをリセットする。
func (km *KeyManager) ReportSuccess(apiKey string) {
	km.mu.Lock()
	defer km.mu.Unlock()
	for i, k := range km.keys {
		if k == apiKey {
			km.count429[i] = 0
			return
		}
	}
}
