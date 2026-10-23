package supervisor

import (
	"testing"
	"time"

	"zgate/internal/config"
	"zgate/internal/logx"
)

func at(hour, minute int) time.Time {
	return time.Date(2026, 10, 23, hour, minute, 0, 0, time.Local)
}

func TestParseWindows(t *testing.T) {
	got := parseWindows([]string{"08:58-09:15", " 20:55 - 21:20 ", "bad", "10:00-10:00", "25:00-26:00"})
	if len(got) != 2 {
		t.Fatalf("want 2 valid windows, got %d: %+v", len(got), got)
	}
	if got[0].start != 8*60+58 || got[0].end != 9*60+15 {
		t.Fatalf("first window wrong: %+v", got[0])
	}
	if got[1].start != 20*60+55 || got[1].end != 21*60+20 {
		t.Fatalf("second window wrong: %+v", got[1])
	}
}

func TestInAnyWindow(t *testing.T) {
	windows := parseWindows([]string{"08:58-09:15", "23:00-01:00"})
	cases := []struct {
		when time.Time
		want bool
	}{
		{at(9, 0), true},
		{at(8, 57), false},
		{at(9, 15), false},
		{at(23, 30), true},
		{at(0, 30), true},
		{at(12, 0), false},
	}
	for _, c := range cases {
		if got := inAnyWindow(windows, c.when); got != c.want {
			t.Fatalf("inAnyWindow(%s)=%v want %v", c.when.Format("15:04"), got, c.want)
		}
	}
	if inAnyWindow(nil, at(9, 0)) {
		t.Fatal("empty windows must never match")
	}
}

func TestApplyConfigUpdatesPolicyAndWindows(t *testing.T) {
	dir := t.TempDir()
	log, err := logx.Open(dir, "sup.log", 1)
	if err != nil {
		t.Fatal(err)
	}
	defer log.Close()

	sup := New(map[string]config.Child{
		"qoder": {Policy: "always", Windows: []string{"09:00-09:10"}},
	}, dir, log)

	applied, stale, added := sup.ApplyConfig(map[string]config.Child{
		"qoder":   {Policy: "ondemand", IdleSeconds: 60, Windows: []string{"20:55-21:20"}},
		"new-one": {Policy: "ondemand"},
	})
	if len(applied) != 1 || applied[0] != "qoder" {
		t.Fatalf("applied=%v", applied)
	}
	if len(stale) != 0 {
		t.Fatalf("stale=%v", stale)
	}
	if len(added) != 1 || added[0] != "new-one" {
		t.Fatalf("added=%v", added)
	}

	state := sup.States()["qoder"].(map[string]any)
	if state["policy"] != "ondemand" {
		t.Fatalf("policy not applied: %v", state["policy"])
	}
	windows := state["windows"].([]string)
	if len(windows) != 1 || windows[0] != "20:55-21:20" {
		t.Fatalf("windows not applied: %v", windows)
	}

	_, stale, _ = sup.ApplyConfig(map[string]config.Child{
		"qoder": {Policy: "ondemand"},
	})
	if len(stale) != 0 {
		t.Fatalf("stale=%v", stale)
	}
}

func TestBackoffGrowsAndCaps(t *testing.T) {
	if backoff(1) != time.Second || backoff(2) != 2*time.Second || backoff(3) != 4*time.Second {
		t.Fatalf("backoff sequence wrong: %v %v %v", backoff(1), backoff(2), backoff(3))
	}
	if backoff(20) != time.Minute {
		t.Fatalf("backoff must cap at 1m, got %v", backoff(20))
	}
	if backoff(0) != 0 {
		t.Fatalf("backoff(0) must be 0")
	}
}

func TestNormalizeDefaults(t *testing.T) {
	child := config.Child{}
	normalize(&child)
	if child.Policy != "ondemand" || child.IdleSeconds != 300 || child.StartTimeoutSeconds != 25 {
		t.Fatalf("defaults wrong: %+v", child)
	}
}
