//go:build windows

package supervisor

import (
	"path/filepath"
	"testing"
	"time"

	"zgate/internal/config"
	"zgate/internal/logx"
)

func newTestSup(t *testing.T, child config.Child) (*Supervisor, *logx.Logger) {
	t.Helper()
	dir := t.TempDir()
	log, err := logx.Open(dir, "sup.log", 1)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(log.Close)
	return New(map[string]config.Child{"dummy": child}, dir, log), log
}

func TestOnDemandStartAndIdleStop(t *testing.T) {
	if testing.Short() {
		t.Skip("spawns a real child process")
	}
	sup, _ := newTestSup(t, config.Child{
		Policy:      "ondemand",
		IdleSeconds: 1,
		Exe:         "cmd",
		Args:        []string{"/c", "ping", "-n", "120", "127.0.0.1"},
		Cwd:         filepath.Clean(t.TempDir()),
		Health:      "",
	})
	defer sup.Stop()
	sup.Start()

	if err := sup.Ensure("dummy"); err != nil {
		t.Fatalf("ensure: %v", err)
	}
	state := sup.States()["dummy"].(map[string]any)
	if state["state"] != "running" {
		t.Fatalf("expected running, got %v", state["state"])
	}

	// The monitor ticks every 5s; idle is 1s, so one tick must reclaim it.
	deadline := time.Now().Add(12 * time.Second)
	for time.Now().Before(deadline) {
		state = sup.States()["dummy"].(map[string]any)
		if state["state"] == "stopped" {
			return
		}
		time.Sleep(500 * time.Millisecond)
	}
	t.Fatalf("idle child was not reclaimed: %v", sup.States()["dummy"])
}

func TestAlwaysRestartsAfterCrash(t *testing.T) {
	if testing.Short() {
		t.Skip("spawns a real child process")
	}
	sup, _ := newTestSup(t, config.Child{
		Policy: "always",
		Exe:    "cmd",
		Args:   []string{"/c", "ping", "-n", "120", "127.0.0.1"},
		Cwd:    filepath.Clean(t.TempDir()),
	})
	defer sup.Stop()
	sup.Start()

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if sup.States()["dummy"].(map[string]any)["state"] == "running" {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	first := sup.States()["dummy"].(map[string]any)
	if first["state"] != "running" {
		t.Fatalf("always child never started: %v", first)
	}

	sup.mu.Lock()
	proc := sup.kids["dummy"].proc
	sup.mu.Unlock()
	if proc == nil {
		t.Fatal("no process handle")
	}
	_ = proc.Kill()

	deadline = time.Now().Add(20 * time.Second)
	for time.Now().Before(deadline) {
		state := sup.States()["dummy"].(map[string]any)
		if state["state"] == "running" && state["pid"] != first["pid"] {
			return
		}
		time.Sleep(500 * time.Millisecond)
	}
	t.Fatalf("always child was not restarted: %v", sup.States()["dummy"])
}
