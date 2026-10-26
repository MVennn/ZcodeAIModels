package router

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"zgate/internal/alias"
	"zgate/internal/config"
	"zgate/internal/keys"
	"zgate/internal/logx"
	"zgate/internal/supervisor"
)

type capture struct {
	mu       sync.Mutex
	requests []map[string]any
	auth     []string
}

func (c *capture) handler(statusFor func(model string) int) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(raw, &body)
		model, _ := body["model"].(string)

		c.mu.Lock()
		c.requests = append(c.requests, body)
		c.auth = append(c.auth, r.Header.Get("Authorization"))
		c.mu.Unlock()

		status := 200
		if statusFor != nil {
			status = statusFor(model)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		if status != 200 {
			_, _ = w.Write([]byte(`{"error":{"message":"upstream says no","type":"server_error"}}`))
			return
		}
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","created":1,"model":"` + model +
			`","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
	}
}

func newServer(t *testing.T, mapJSON string, upstreamBase string) (*Server, *logx.Logger) {
	t.Helper()
	dir := t.TempDir()
	mapPath := filepath.Join(dir, "model-alias-map.json")
	if err := os.WriteFile(mapPath, []byte(mapJSON), 0o644); err != nil {
		t.Fatal(err)
	}
	log, err := logx.Open(dir, "test.log", 1)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(log.Close)
	cfg := &config.Config{
		Session: "test-session",
		Upstreams: map[string]config.Upstream{
			"OC": {Base: upstreamBase},
			"WB": {Base: upstreamBase},
			"QD": {Base: upstreamBase},
		},
	}
	ks := keys.Set{OC: "oc-key", WB: "wb-key", QD: "qd-key"}
	sup := supervisor.New(nil, dir, log)
	return New(cfg, ks, alias.New(mapPath), sup, &http.Client{}, log), log
}

func postJSON(t *testing.T, url string, body string) (*http.Response, []byte) {
	t.Helper()
	resp, err := http.Post(url, "application/json", strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	return resp, raw
}

func TestAliasRewriteAndAuth(t *testing.T) {
	cap := &capture{}
	upstream := httptest.NewServer(cap.handler(nil))
	defer upstream.Close()

	srv, _ := newServer(t, `{
		"models":{"W/0.03/DeepSeek-41-Fs":{"channel":"WB","upstream":"global:deepseek-v4.1-flash-sg","base":"`+upstream.URL+`","protocol":"chat","fallbacks":["cn:deepseek-v4.1-flash"]}},
		"legacy":{}
	}`, upstream.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"W/0.03/DeepSeek-41-Fs","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 200 {
		t.Fatalf("status %d: %s", resp.StatusCode, raw)
	}
	if len(cap.requests) != 1 {
		t.Fatalf("expected 1 upstream call, got %d", len(cap.requests))
	}
	if cap.requests[0]["model"] != "global:deepseek-v4.1-flash-sg" {
		t.Fatalf("upstream model not rewritten: %v", cap.requests[0]["model"])
	}
	if cap.auth[0] != "Bearer wb-key" {
		t.Fatalf("wrong auth header: %q", cap.auth[0])
	}
}

func TestFallbackChainRetriesOn503(t *testing.T) {
	cap := &capture{}
	upstream := httptest.NewServer(cap.handler(func(model string) int {
		if model == "primary" {
			return 503
		}
		return 200
	}))
	defer upstream.Close()

	srv, _ := newServer(t, `{
		"models":{"W/0.00/M":{"channel":"WB","upstream":"primary","base":"`+upstream.URL+`","protocol":"chat","fallbacks":["backup"]}},
		"legacy":{}
	}`, upstream.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"W/0.00/M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 200 {
		t.Fatalf("fallback did not recover: %d %s", resp.StatusCode, raw)
	}
	if len(cap.requests) != 2 {
		t.Fatalf("expected 2 attempts, got %d", len(cap.requests))
	}
	if cap.requests[1]["model"] != "backup" {
		t.Fatalf("second attempt used %v", cap.requests[1]["model"])
	}
}

func TestPrefixFallbackWhenMapIsEmpty(t *testing.T) {
	cap := &capture{}
	upstream := httptest.NewServer(cap.handler(nil))
	defer upstream.Close()

	srv, _ := newServer(t, `{"models":{},"legacy":{}}`, upstream.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"cn:space-bunny","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 200 {
		t.Fatalf("prefix fallback failed: %d %s", resp.StatusCode, raw)
	}
	if cap.requests[0]["model"] != "cn:space-bunny" {
		t.Fatalf("WB prefix must pass through unchanged, got %v", cap.requests[0]["model"])
	}
}

func TestQoderModelOnlySupportsChat(t *testing.T) {
	srv, _ := newServer(t, `{"models":{},"legacy":{}}`, "http://127.0.0.1:1")
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/messages", `{"model":"qoder:DeepSeek-Flash","messages":[]}`)
	if resp.StatusCode != 400 {
		t.Fatalf("want 400 for non-chat Qoder model, got %d %s", resp.StatusCode, raw)
	}
	if !strings.Contains(string(raw), "only support chat/completions") {
		t.Fatalf("unexpected error body: %s", raw)
	}
}

func TestHealthExposesNoKeys(t *testing.T) {
	srv, _ := newServer(t, `{"models":{},"legacy":{}}`, "http://127.0.0.1:1")
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, err := http.Get(front.URL + "/health")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(resp.Body)
	text := string(raw)
	for _, secret := range []string{"oc-key", "wb-key", "qd-key"} {
		if strings.Contains(text, secret) {
			t.Fatalf("/health leaked a key: %s", secret)
		}
	}
	var body map[string]any
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Fatalf("health is not JSON: %s", raw)
	}
	if body["ok"] != true || body["workbuddy"].(map[string]any)["key"] != true {
		t.Fatalf("health shape wrong: %s", raw)
	}
}

func TestNormalizePath(t *testing.T) {
	cases := map[string]string{
		"/v1/chat/completions": "/chat/completions",
		"/chat/completions":    "/chat/completions",
		"/v1":                  "/",
		"/v1/":                 "/",
	}
	for in, want := range cases {
		r := httptest.NewRequest("POST", in, nil)
		got, _ := normalizePath(r)
		if got != want {
			t.Fatalf("normalizePath(%q)=%q want %q", in, got, want)
		}
	}

	// The query part must keep its "?" so base+path+search stays a valid URL.
	r := httptest.NewRequest("POST", "/v1/chat/completions?stream=1", nil)
	gotPath, gotSearch := normalizePath(r)
	if gotPath != "/chat/completions" || gotSearch != "?stream=1" {
		t.Fatalf("normalizePath with query = (%q,%q), want (/chat/completions,?stream=1)", gotPath, gotSearch)
	}
}

func TestQueryStringIsForwarded(t *testing.T) {
	var gotPath, gotQuery string
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath, gotQuery = r.URL.Path, r.URL.RawQuery
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","choices":[]}`))
	}))
	defer upstream.Close()

	srv, _ := newServer(t, `{"models":{},"legacy":{}}`, upstream.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, err := http.Post(front.URL+"/v1/chat/completions?stream=1", "application/json",
		strings.NewReader(`{"model":"deepseek-v4.1-flash","stream":true}`))
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if gotPath != "/chat/completions" || gotQuery != "stream=1" {
		t.Fatalf("upstream got path=%q query=%q, want /chat/completions?stream=1", gotPath, gotQuery)
	}
}

func TestAdminReloadAppliesPolicy(t *testing.T) {
	dir := t.TempDir()
	cfgPath := filepath.Join(dir, "zgate.json")
	writeConfig := func(children string) {
		body := `{"listen":"127.0.0.1:7871","children":` + children + `}`
		if err := os.WriteFile(cfgPath, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	writeConfig(`{"qoder":{"policy":"always"}}`)

	cfg, err := config.Load(cfgPath)
	if err != nil {
		t.Fatal(err)
	}
	log, err := logx.Open(dir, "test.log", 1)
	if err != nil {
		t.Fatal(err)
	}
	defer log.Close()
	sup := supervisor.New(cfg.Children, dir, log)
	srv := New(cfg, keys.Set{}, alias.New(filepath.Join(dir, "missing.json")), sup, &http.Client{}, log)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	writeConfig(`{"qoder":{"policy":"ondemand","idleSeconds":60,"windows":["09:00-09:10"]}}`)
	resp, err := http.Post(front.URL+"/admin/reload", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 {
		t.Fatalf("reload failed: %d %s", resp.StatusCode, raw)
	}
	state := sup.States()["qoder"].(map[string]any)
	if state["policy"] != "ondemand" {
		t.Fatalf("policy not reloaded: %v", state["policy"])
	}

	getResp, err := http.Get(front.URL + "/admin/reload")
	if err != nil {
		t.Fatal(err)
	}
	getResp.Body.Close()
	if getResp.StatusCode != 405 {
		t.Fatalf("GET must be rejected, got %d", getResp.StatusCode)
	}
}

func TestFallbackChainRetriesOnModelUnavailable(t *testing.T) {
	cap := &capture{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(raw, &body)
		model, _ := body["model"].(string)
		cap.mu.Lock()
		cap.requests = append(cap.requests, body)
		cap.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		if model == "primary" {
			w.WriteHeader(400)
			_, _ = w.Write([]byte(`{"error":{"code":"model_unavailable","message":"cooling down"}}`))
			return
		}
		_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","model":"` + model +
			`","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
	}))
	defer upstream.Close()

	srv, _ := newServer(t, `{
		"models":{"W/0.00/M":{"channel":"WB","upstream":"primary","base":"`+upstream.URL+`","protocol":"chat","fallbacks":["backup"]}},
		"legacy":{}
	}`, upstream.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"W/0.00/M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 200 {
		t.Fatalf("model_unavailable should fall back, got %d %s", resp.StatusCode, raw)
	}
	if len(cap.requests) != 2 || cap.requests[1]["model"] != "backup" {
		t.Fatalf("fallback did not run: %v", cap.requests)
	}
}

func TestPlain400IsNotRetried(t *testing.T) {
	cap := &capture{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var body map[string]any
		_ = json.Unmarshal(raw, &body)
		cap.mu.Lock()
		cap.requests = append(cap.requests, body)
		cap.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(400)
		_, _ = w.Write([]byte(`{"error":{"code":"invalid_request","message":"bad tool schema"}}`))
	}))
	defer upstream.Close()

	srv, _ := newServer(t, `{
		"models":{"W/0.00/M":{"channel":"WB","upstream":"primary","base":"`+upstream.URL+`","protocol":"chat","fallbacks":["backup"]}},
		"legacy":{}
	}`, upstream.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, _ := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"W/0.00/M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 400 {
		t.Fatalf("plain 400 must pass through, got %d", resp.StatusCode)
	}
	if len(cap.requests) != 1 {
		t.Fatalf("plain 400 must not retry, got %d attempts", len(cap.requests))
	}
}

func TestChainSpansChannels(t *testing.T) {
	var hits []string
	var auth []string
	serve := func(name string, status int) *httptest.Server {
		return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			raw, _ := io.ReadAll(r.Body)
			var body map[string]any
			_ = json.Unmarshal(raw, &body)
			hits = append(hits, name+":"+body["model"].(string))
			auth = append(auth, r.Header.Get("Authorization"))
			w.Header().Set("Content-Type", "application/json")
			if status != 200 {
				w.WriteHeader(status)
				_, _ = w.Write([]byte(`{"error":{"message":"nope","code":"model_unavailable"}}`))
				return
			}
			_, _ = w.Write([]byte(`{"id":"x","object":"chat.completion","model":"m","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}`))
		}))
	}
	wb := serve("WB", 400)
	oc := serve("OC", 200)
	defer wb.Close()
	defer oc.Close()

	mapJSON := `{"models":{"DeepSeek-Test":{"channel":"WB","upstream":"wb-a","base":"` + wb.URL + `","protocol":"chat",
		"chain":[
			{"upstream":"wb-a","base":"` + wb.URL + `","channel":"WB","price":0.03},
			{"upstream":"oc-b","base":"` + oc.URL + `","channel":"OC","price":0.11}
		]}},"legacy":{}}`
	srv, _ := newServer(t, mapJSON, wb.URL)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"DeepSeek-Test","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 200 {
		t.Fatalf("chain did not fall through: %d %s", resp.StatusCode, raw)
	}
	if len(hits) != 2 || hits[0] != "WB:wb-a" || hits[1] != "OC:oc-b" {
		t.Fatalf("unexpected hops: %v", hits)
	}
	if auth[0] != "Bearer wb-key" || auth[1] != "Bearer oc-key" {
		t.Fatalf("per-hop auth wrong: %v", auth)
	}
}
