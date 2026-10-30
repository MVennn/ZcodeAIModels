package router

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"zgate/internal/alias"
	"zgate/internal/bridge"
	"zgate/internal/config"
	"zgate/internal/keys"
	"zgate/internal/logx"
	"zgate/internal/supervisor"
)

// 这里测两件事：hop.proxy 真的换出口；地区受限的 403 会落到链上的下一跳。
// 前者用「上游主机名不可解析，只有经代理才通」证，后者用两跳各自的状态码证。

func newEgressServer(t *testing.T, mapJSON string) *Server {
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
	cfg := &config.Config{Session: "test-session"}
	ks := keys.Set{OC: "oc-key", WB: "wb-key"}
	sup := supervisor.New(nil, dir, log)
	client := &http.Client{Transport: NewEgressRouter(&http.Transport{})}
	return New(cfg, ks, alias.New(mapPath), sup, client, log)
}

func okBody() string {
	return `{"id":"x","object":"chat.completion","choices":[{"index":0,"message":{"role":"assistant","content":"ok"}}]}`
}

func TestHopProxyIsUsed(t *testing.T) {
	var mu sync.Mutex
	var seen []string
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		seen = append(seen, r.URL.String())
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(okBody()))
	}))
	defer proxy.Close()

	// 上游主机名故意不可解析：只有真的走了 proxy 才可能拿到 200。
	srv := newEgressServer(t, `{
		"models":{"M":{"channel":"OC","upstream":"m","base":"http://origin.invalid","protocol":"chat",
			"chain":[{"upstream":"m","base":"http://origin.invalid","channel":"OC","protocol":"chat","price":0.1,"proxy":"`+proxy.URL+`"}]}},
		"legacy":{}
	}`)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode != 200 {
		t.Fatalf("status %d: %s", resp.StatusCode, raw)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(seen) != 1 || seen[0] != "http://origin.invalid/chat/completions" {
		t.Fatalf("proxy did not receive the absolute-form request: %v", seen)
	}
}

func TestHopWithoutProxyStaysDirect(t *testing.T) {
	srv := newEgressServer(t, `{
		"models":{"M":{"channel":"OC","upstream":"m","base":"http://origin.invalid","protocol":"chat",
			"chain":[{"upstream":"m","base":"http://origin.invalid","channel":"OC","protocol":"chat","price":0.1}]}},
		"legacy":{}
	}`)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	if resp.StatusCode == 200 {
		t.Fatalf("unresolvable origin without a proxy should fail, got 200: %s", raw)
	}
}

func TestRegionBlockedFallsThroughToNextHop(t *testing.T) {
	var mu sync.Mutex
	var calls []string
	blocked := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls = append(calls, "blocked")
		mu.Unlock()
		w.WriteHeader(403)
		_, _ = w.Write([]byte(`{"error":{"message":"unsupported_country_region_territory","type":"invalid_request_error"}}`))
	}))
	defer blocked.Close()
	allowed := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		calls = append(calls, "allowed")
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(okBody()))
	}))
	defer allowed.Close()

	srv := newEgressServer(t, `{
		"models":{"M":{"channel":"OC","upstream":"m","base":"`+blocked.URL+`","protocol":"chat",
			"chain":[
				{"upstream":"m","base":"`+blocked.URL+`","channel":"OC","protocol":"chat","price":0.1},
				{"upstream":"m","base":"`+allowed.URL+`","channel":"OC","protocol":"chat","price":0.1}
			]}},
		"legacy":{}
	}`)
	front := httptest.NewServer(srv.Handler())
	defer front.Close()

	// 第一跳 403 地区受限 → 必须换到第二跳并拿到 200；原样返回 403 就是回归。
	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	mu.Lock()
	defer mu.Unlock()
	if resp.StatusCode != 200 {
		t.Fatalf("region block did not fall through: status %d, calls %v, body %s", resp.StatusCode, calls, raw)
	}
	if len(calls) != 2 || calls[0] != "blocked" || calls[1] != "allowed" {
		t.Fatalf("expected blocked then allowed, got %v", calls)
	}
}

func TestRegionBlockedIsNotHopFatal(t *testing.T) {
	// hopFatal=true 会把这一跳冷却掉，链后面的跳全被跳过 —— 地区受限不能算 hopFatal。
	if hopFatal(403, []byte(`{"error":{"message":"unsupported_country_region_territory"}}`)) {
		t.Fatal("region block must not be hopFatal")
	}
	if hopFatal(403, []byte(`{"error":{"message":"This model is not available in your country"}}`)) {
		t.Fatal("region block must not be hopFatal")
	}
}

func TestChainAcceptRegionMarkers(t *testing.T) {
	// chainAccept 返回 true = 认这一跳的响应；false = 换下一跳。
	region := []byte(`{"error":{"message":"RegionError: This model is not available in your country"}}`)
	if chainAccept(403, region) {
		t.Fatal("region block must fall through to the next hop")
	}
	if !chainAccept(403, []byte(`{"error":{"message":"invalid api key"}}`)) {
		t.Fatal("a plain 403 must not fall through")
	}
	if !chainAccept(400, []byte(`{"error":{"message":"bad request"}}`)) {
		t.Fatal("a plain 400 must not fall through")
	}
	if chainAccept(400, []byte(`{"error":{"code":"model_unavailable"}}`)) {
		t.Fatal("model_unavailable must fall through")
	}
	if chainAccept(429, nil) {
		t.Fatal("429 must fall through")
	}
}

func TestRegionBlockedHelper(t *testing.T) {
	// 两种真实写法（chat 端点 vs responses 端点）都要认。
	for _, body := range []string{
		`{"type":"error","error":{"type":"RegionError","message":"This model is not available in your country"}}`,
		`{"model":"gpt-6-luna","error":{"code":"unsupported_country_region_territory","message":"Country, region, or territory not supported"}}`,
	} {
		if !regionBlocked(403, []byte(body)) {
			t.Fatalf("region block not detected: %s", body)
		}
	}
	if regionBlocked(403, []byte(`{"error":{"message":"invalid api key"}}`)) {
		t.Fatal("plain 403 must not be treated as a region block")
	}
	if regionBlocked(429, []byte(`{"error":{"type":"RegionError"}}`)) {
		t.Fatal("429 is throttling, not a region block")
	}
}

func TestTransportFailureRetriesSameHop(t *testing.T) {
	// 复刻 2026-10-31 凌晨那次：机场节点对 opencode.ai 的大包短暂黑洞，
	// 连接在请求发出后被动断开（EOF）。这一跳只出现一次，没有下一跳可落，
	// 唯一能救的就是「重试同一跳一次」。
	var mu sync.Mutex
	n := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		n++
		cur := n
		mu.Unlock()
		if cur == 1 {
			if hj, ok := w.(http.Hijacker); ok {
				if conn, _, err := hj.Hijack(); err == nil {
					_ = conn.Close() // 不写任何字节就断开 → 客户端拿到 EOF
					return
				}
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(okBody()))
	}))
	defer srv.Close()

	srv2 := newEgressServer(t, `{
		"models":{"M":{"channel":"OC","upstream":"m","base":"`+srv.URL+`","protocol":"chat",
			"chain":[{"upstream":"m","base":"`+srv.URL+`","channel":"OC","protocol":"chat","price":0.1}]}},
		"legacy":{}
	}`)
	front := httptest.NewServer(srv2.Handler())
	defer front.Close()

	resp, raw := postJSON(t, front.URL+"/v1/chat/completions",
		`{"model":"M","messages":[{"role":"user","content":"hi"}],"max_tokens":8}`)
	mu.Lock()
	got := n
	mu.Unlock()
	if resp.StatusCode != 200 {
		t.Fatalf("transport failure was not retried: status %d, body %s", resp.StatusCode, raw)
	}
	if got != 2 {
		t.Fatalf("expected exactly 2 attempts (1 fail + 1 retry), got %d", got)
	}
}

func TestTransportFailedMarkers(t *testing.T) {
	cases := []struct {
		status int
		body   string
		want   bool
	}{
		{502, `Post "https://x/y": EOF`, true},
		{502, `Post "https://x/y": net/http: TLS handshake timeout`, true},
		{502, `read tcp 1.2.3.4: connection reset by peer`, true},
		{502, `dial tcp 1.2.3.4: connection refused`, true},
		{502, `bridge upstream error: boom`, false}, // 普通 5xx，重试没有意义
		{200, `EOF`, false},                        // 成功响应里出现 EOF 字样不算
	}
	for _, c := range cases {
		if got := transportFailed(bridge.Result{Status: c.status, Body: []byte(c.body)}); got != c.want {
			t.Fatalf("transportFailed(%d, %q) = %v, want %v", c.status, c.body, got, c.want)
		}
	}
}

func TestHopKeySeparatesEgress(t *testing.T) {
	direct := alias.Hop{Channel: "OC", Upstream: "gpt-6-luna"}
	viaAirport := alias.Hop{Channel: "OC", Upstream: "gpt-6-luna", Proxy: "http://10.0.0.1:7896"}
	if hopKey(direct) == hopKey(viaAirport) {
		t.Fatal("直连与机场必须是两个冷却键，否则直连的 403 会把兜底跳冷却掉")
	}
}

func TestProxyOfRoundTrip(t *testing.T) {
	ctx := WithProxy(context.Background(), "http://127.0.0.1:7896")
	if got := ProxyOf(ctx); got != "http://127.0.0.1:7896" {
		t.Fatalf("ProxyOf = %q", got)
	}
	// 空代理表示直连：不覆盖外层（下一跳会重新设自己的值）。
	if got := ProxyOf(WithProxy(ctx, "")); got != "http://127.0.0.1:7896" {
		t.Fatalf("empty proxy must not clear the outer value, got %q", got)
	}
	if got := ProxyOf(context.Background()); got != "" {
		t.Fatalf("no proxy expected, got %q", got)
	}
}
