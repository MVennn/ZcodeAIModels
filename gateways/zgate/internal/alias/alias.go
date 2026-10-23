// Package alias reads ~/.zcode/v2/model-alias-map.json and resolves a display
// name (or a legacy id) to the upstream target it stands for.
//
// The file is rewritten by tools/model_alias.py while ZCode is running, so it is
// re-read whenever its mtime changes; a broken file keeps the previous snapshot
// instead of dropping every route.
package alias

import (
	"encoding/json"
	"os"
	"sync"
	"time"
)

// Hop is one step of a merged chain: its own upstream id, host and channel.
type Hop struct {
	Upstream  string  `json:"upstream"`
	Base      string  `json:"base"`
	Channel   string  `json:"channel"`
	Price     float64 `json:"price"`
	Original  string  `json:"original"`
	BaseModel string  `json:"base_model"`
}

// Target is one upstream behind a display name.
type Target struct {
	Channel   string   `json:"channel"`
	Region    string   `json:"region"`
	Upstream  string   `json:"upstream"`
	BaseModel string   `json:"base_model"`
	Base      string   `json:"base"`
	Protocol  string   `json:"protocol"`
	Original  string   `json:"original"`
	Price     float64  `json:"price"`
	Group     string   `json:"group"`
	Fallbacks []string `json:"fallbacks"`
	Chain     []Hop    `json:"chain"`
	LegacyIDs []string `json:"legacy_ids"`
}

type file struct {
	Version     int               `json:"version"`
	GeneratedAt string            `json:"generated_at"`
	Slot        string            `json:"slot"`
	Models      map[string]Target `json:"models"`
	Legacy      map[string]string `json:"legacy"`
}

// Map is a hot-reloading view of the alias file.
type Map struct {
	path  string
	mu    sync.RWMutex
	mtime time.Time
	data  *file
}

// New returns a Map bound to path; a missing file is not an error.
func New(path string) *Map {
	m := &Map{path: path}
	m.Reload()
	return m
}

// Path is the file this map watches.
func (m *Map) Path() string { return m.path }

// Reload re-reads the file when it changed. It is cheap enough to call per request.
func (m *Map) Reload() {
	stat, err := os.Stat(m.path)
	if err != nil {
		return
	}
	m.mu.RLock()
	same := m.data != nil && stat.ModTime().Equal(m.mtime)
	m.mu.RUnlock()
	if same {
		return
	}
	raw, err := os.ReadFile(m.path)
	if err != nil {
		return
	}
	var next file
	if err := json.Unmarshal(raw, &next); err != nil {
		return
	}
	m.mu.Lock()
	m.data = &next
	m.mtime = stat.ModTime()
	m.mu.Unlock()
}

// Count is how many display names the file carries (0 when it is missing).
func (m *Map) Count() int {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.data == nil {
		return 0
	}
	return len(m.data.Models)
}

// Resolve maps a display name or a legacy id to its target.
func (m *Map) Resolve(model string) (Target, bool) {
	if model == "" {
		return Target{}, false
	}
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.data == nil {
		return Target{}, false
	}
	if t, ok := m.data.Models[model]; ok {
		return t, true
	}
	if display, ok := m.data.Legacy[model]; ok {
		if t, ok := m.data.Models[display]; ok {
			return t, true
		}
	}
	return Target{}, false
}
