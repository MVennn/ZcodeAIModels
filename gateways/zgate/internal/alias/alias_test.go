package alias

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

const sample = `{
  "version": 1,
  "models": {
    "W/0.03/DeepSeek-41-Fs": {"channel":"WB","upstream":"global:deepseek-v4.1-flash-sg","base":"http://127.0.0.1:7863/v1","protocol":"chat","fallbacks":["cn:deepseek-v4.1-flash"]},
    "O/0.09/Claude-Haiku-55": {"channel":"OC","upstream":"claude-haiku-5.5","base":"https://opencode.ai/zen/go/v1","protocol":"messages"}
  },
  "legacy": {"global:deepseek-v4.1-flash-sg": "W/0.03/DeepSeek-41-Fs"}
}`

func writeMap(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "map.json")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestResolveDisplayAndLegacy(t *testing.T) {
	m := New(writeMap(t, sample))
	if m.Count() != 2 {
		t.Fatalf("count=%d", m.Count())
	}
	if target, ok := m.Resolve("W/0.03/DeepSeek-41-Fs"); !ok || target.Upstream != "global:deepseek-v4.1-flash-sg" {
		t.Fatalf("display name not resolved: %+v ok=%v", target, ok)
	}
	if target, ok := m.Resolve("global:deepseek-v4.1-flash-sg"); !ok || target.Channel != "WB" {
		t.Fatalf("legacy id not resolved: %+v ok=%v", target, ok)
	}
	if _, ok := m.Resolve("not-configured"); ok {
		t.Fatalf("unknown model must not resolve")
	}
}

func TestReloadPicksUpNewFile(t *testing.T) {
	path := writeMap(t, `{"models":{},"legacy":{}}`)
	m := New(path)
	if m.Count() != 0 {
		t.Fatalf("expected empty map")
	}
	time.Sleep(20 * time.Millisecond)
	if err := os.WriteFile(path, []byte(sample), 0o644); err != nil {
		t.Fatal(err)
	}
	// Some filesystems keep the same mtime at this resolution; force a distinct one.
	future := time.Now().Add(2 * time.Second)
	_ = os.Chtimes(path, future, future)
	m.Reload()
	if m.Count() != 2 {
		t.Fatalf("reload did not pick up the new file: %d", m.Count())
	}
}

func TestBrokenFileKeepsPreviousSnapshot(t *testing.T) {
	path := writeMap(t, sample)
	m := New(path)
	if err := os.WriteFile(path, []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	future := time.Now().Add(2 * time.Second)
	_ = os.Chtimes(path, future, future)
	m.Reload()
	if m.Count() != 2 {
		t.Fatalf("broken file must keep the last good snapshot, got %d", m.Count())
	}
}
