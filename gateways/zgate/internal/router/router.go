// Package router is the HTTP front door on 127.0.0.1:7871.
//
// It is a behaviour-preserving port of tools/unified-router.js: the same alias
// map, the same prefix fallback, the same fallback chain for WorkBuddy regions
// and the same error envelopes, so ZCode's four chat providers keep working
// without touching provider_config.json.
package router

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"zgate/internal/alias"
	"zgate/internal/bridge"
	"zgate/internal/config"
	"zgate/internal/keys"
	"zgate/internal/logx"
	"zgate/internal/supervisor"
)

// Server holds the long-lived state of the front door.
type Server struct {
	cfgMu   sync.RWMutex
	cfg     *config.Config
	keys    keys.Set
	aliases *alias.Map
	sup     *supervisor.Supervisor
	client  *http.Client
	log     *logx.Logger
	started time.Time
}

// New wires the server. client is shared with the bridge.
func New(cfg *config.Config, ks keys.Set, am *alias.Map, sup *supervisor.Supervisor, client *http.Client, log *logx.Logger) *Server {
	return &Server{cfg: cfg, keys: ks, aliases: am, sup: sup, client: client, log: log, started: time.Now()}
}

var hopByHop = map[string]bool{
	"connection":          true,
	"proxy-connection":    true,
	"keep-alive":          true,
	"proxy-authenticate":  true,
	"proxy-authorization": true,
	"te":                  true,
	"trailer":             true,
	"transfer-encoding":   true,
	"upgrade":             true,
}

// Config returns the current configuration; it can be swapped by /admin/reload.
func (s *Server) Config() *config.Config {
	s.cfgMu.RLock()
	defer s.cfgMu.RUnlock()
	return s.cfg
}

func (s *Server) setRuntime(cfg *config.Config, ks keys.Set) {
	s.cfgMu.Lock()
	s.cfg = cfg
	s.keys = ks
	s.cfgMu.Unlock()
}

// keyset returns the current credentials; /admin/reload can swap them.
func (s *Server) keyset() keys.Set {
	s.cfgMu.RLock()
	defer s.cfgMu.RUnlock()
	return s.keys
}

// Handler is the whole routing table.
func (s *Server) Handler() http.Handler { return http.HandlerFunc(s.serveHTTP) }

func (s *Server) serveHTTP(w http.ResponseWriter, r *http.Request) {
	defer func() {
		if rec := recover(); rec != nil {
			s.log.Errorf("panic on %s %s: %v", r.Method, r.URL.Path, rec)
			writeJSON(w, 500, errorBody("unified-router error: panic", "proxy_error"))
		}
	}()

	path, search := normalizePath(r)
	if path == "/health" {
		s.health(w)
		return
	}
	if path == "/admin/reload" {
		s.reload(w, r)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		writeJSON(w, 400, errorBody("invalid request body", "invalid_request_error"))
		return
	}
	_ = r.Body.Close()

	model := ""
	if len(body) > 0 && strings.Contains(r.Header.Get("Content-Type"), "application/json") {
		var probe struct {
			Model string `json:"model"`
		}
		if err := json.Unmarshal(body, &probe); err == nil {
			model = probe.Model
		}
	}

	isChat := path == "/chat/completions"
	if !isChat && (isQoder(model) || isWorkBuddy(model)) {
		writeJSON(w, 400, errorBody("WorkBuddy/Qoder models only support chat/completions", "invalid_request_error"))
		return
	}

	s.aliases.Reload()
	if target, ok := s.aliases.Resolve(model); ok {
		s.routeAlias(w, r, body, model, target, path, search, isChat)
		return
	}
	s.routeFallback(w, r, body, model, path, search, isChat)
}

func (s *Server) routeAlias(w http.ResponseWriter, r *http.Request, body []byte, model string, t alias.Target, path, search string, isChat bool) {
	if len(t.Chain) > 0 {
		s.routeChain(w, r, body, model, t, path, search, isChat)
		return
	}
	channel := t.Channel
		key := s.keyset().For(channel)
	if key == "" {
		writeJSON(w, 502, errorBody(channel+" key not configured", "configuration_error"))
		return
	}
	protocol := t.Protocol
	if protocol == "" {
		protocol = "chat"
	}
	if protocol != "chat" {
		if !isChat {
			writeJSON(w, 400, errorBody(channel+" bridged models only support chat/completions", "invalid_request_error"))
			return
		}
		if err := s.prepare(channel); err != nil {
			writeJSON(w, 503, errorBody("upstream not ready: "+err.Error(), "upstream_error"))
			return
		}
		s.log.Infof("%s %s%s model=%s -> %s:%s", r.Method, path, search, model, channel, protocol)
		result := bridge.Forward(s.client, bridge.Options{
			Protocol:      protocol,
			Base:          t.Base,
			Key:           key,
			Body:          body,
			UpstreamModel: t.Upstream,
			DisplayModel:  model,
			Ctx:           r.Context(),
		})
		writeResult(w, result)
		return
	}

	chain := append([]string{t.Upstream}, t.Fallbacks...)
	headers := s.forwardHeaders(r, body, channel, key)
	if err := s.prepare(channel); err != nil {
		writeJSON(w, 503, errorBody("upstream not ready: "+err.Error(), "upstream_error"))
		return
	}
	if len(chain) > 1 {
		s.log.Infof("%s %s%s model=%s -> %s (%s)", r.Method, path, search, model, channel, strings.Join(chain, " -> "))
		s.forwardChain(w, r, body, t.Base, path, search, headers, chain, 0)
		return
	}
	rewritten, ok := rewriteModel(body, t.Upstream)
	if !ok {
		writeJSON(w, 400, errorBody("invalid JSON body", "invalid_request_error"))
		return
	}
	s.log.Infof("%s %s%s model=%s -> %s", r.Method, path, search, model, channel)
	s.forward(w, r, rewritten, t.Base, path, search, headers)
}

func (s *Server) routeFallback(w http.ResponseWriter, r *http.Request, body []byte, model, path, search string, isChat bool) {
	channel := "OC"
	cfg := s.Config()
	base := cfg.Upstreams["OC"].Base
	label := "opencode"
	ks := s.keyset()
	key := ks.OC
	switch {
	case isChat && isQoder(model):
		channel, label, key = "QD", "qoder", ks.QD
		base = cfg.Upstreams["QD"].Base
		if key == "" {
			writeJSON(w, 502, errorBody("Qoder key not configured", "configuration_error"))
			return
		}
		rewritten, ok := rewriteModel(body, trimPrefixFold(model, "qoder:"))
		if !ok {
			writeJSON(w, 400, errorBody("invalid JSON body for Qoder model", "invalid_request_error"))
			return
		}
		body = rewritten
	case isChat && isWorkBuddy(model):
		channel, label, key = "WB", "workbuddy", ks.WB
		base = cfg.Upstreams["WB"].Base
		if key == "" {
			writeJSON(w, 502, errorBody("WorkBuddy key not configured", "configuration_error"))
			return
		}
	default:
		if key == "" {
			writeJSON(w, 502, errorBody("OpenCode-Go key not configured", "configuration_error"))
			return
		}
	}
	headers := s.forwardHeaders(r, body, channel, key)
	if err := s.prepare(channel); err != nil {
		writeJSON(w, 503, errorBody("upstream not ready: "+err.Error(), "upstream_error"))
		return
	}
	s.log.Infof("%s %s%s model=%s -> %s", r.Method, path, search, orDash(model), label)
	s.forward(w, r, body, base, path, search, headers)
}

// prepare starts an on-demand child and marks the channel as recently used.
func (s *Server) prepare(channel string) error {
	upstream, ok := s.Config().Upstreams[channel]
	if !ok || upstream.Child == "" {
		return nil
	}
	s.sup.Touch(upstream.Child)
	if err := s.sup.Ensure(upstream.Child); err != nil {
		s.log.Warnf("通道 %s 的子进程未就绪: %v", channel, err)
		return err
	}
	return nil
}

func (s *Server) forwardHeaders(r *http.Request, body []byte, channel, key string) http.Header {
	h := http.Header{}
	for name, values := range r.Header {
		if hopByHop[strings.ToLower(name)] || strings.EqualFold(name, "host") ||
			strings.EqualFold(name, "content-length") ||
			// The transport disables transparent decompression, so forwarding
			// Accept-Encoding would hide error bodies from chainAccept.
			strings.EqualFold(name, "accept-encoding") {
			continue
		}
		for _, v := range values {
			h.Add(name, v)
		}
	}
	if h.Get("User-Agent") == "" {
		h.Set("User-Agent", "unified-router/1.0")
	}
	switch channel {
	case "WB", "QD":
		h.Set("Authorization", "Bearer "+key)
	case "OC":
		h.Set("Authorization", "Bearer "+key)
		h.Set("User-Agent", "opencode-cli/1.0")
		if h.Get("X-Opencode-Session") == "" && h.Get("x-opencode-session") == "" {
			h.Set("X-Opencode-Session", s.Config().Session)
		}
	}
	return h
}

func (s *Server) forward(w http.ResponseWriter, r *http.Request, body []byte, base, path, search string, headers http.Header) {
	s.doForwardWith(w, r, body, base, path, search, headers, nil, nil)
}

func (s *Server) forwardChain(w http.ResponseWriter, r *http.Request, body []byte, base, path, search string, headers http.Header, chain []string, index int) {
	if index >= len(chain) {
		writeJSON(w, 502, errorBody("all upstreams failed: "+strings.Join(chain, " -> "), "proxy_error"))
		return
	}
	rewritten, ok := rewriteModel(body, chain[index])
	if !ok {
		writeJSON(w, 400, errorBody("invalid JSON body", "invalid_request_error"))
		return
	}
	retry := func(reason string) {
		if index+1 < len(chain) {
			s.log.Infof("[router] %s -> %s, fallback %s", chain[index], reason, chain[index+1])
			s.forwardChain(w, r, body, base, path, search, headers, chain, index+1)
			return
		}
		writeJSON(w, 502, errorBody("unified-router upstream error: "+reason, "proxy_error"))
	}
	s.doForwardWith(w, r, rewritten, base, path, search, headers, chainAccept, retry)
}

func (s *Server) doForwardWith(w http.ResponseWriter, r *http.Request, body []byte, base, path, search string, headers http.Header,
	accept func(status int, head []byte) bool, retry func(reason string)) {

	target := strings.TrimRight(base, "/") + path + search
	req, err := http.NewRequestWithContext(r.Context(), r.Method, target, bytes.NewReader(body))
	if err != nil {
		writeJSON(w, 502, errorBody("unified-router upstream error: "+err.Error(), "proxy_error"))
		return
	}
	req.Header = headers.Clone()
	if len(body) > 0 {
		req.ContentLength = int64(len(body))
	}
	resp, err := s.client.Do(req)
	if err != nil {
		if retry != nil {
			retry(err.Error())
			return
		}
		writeJSON(w, 502, errorBody("unified-router upstream error: "+err.Error(), "proxy_error"))
		return
	}
	defer resp.Body.Close()

	var head []byte
	if accept != nil {
		// Peek at error bodies: a 400 can still mean "pool cooling down",
		// which should fall through to the next region. Successful responses
		// stream without buffering, and a bounded ReadAll avoids the
		// single-Read partial-segment trap on error bodies.
		if resp.StatusCode >= 400 {
			head, _ = io.ReadAll(io.LimitReader(resp.Body, 8192))
		}
		if !accept(resp.StatusCode, head) {
			_, _ = io.Copy(io.Discard, resp.Body)
			retry(fmt.Sprintf("%s %s", http.StatusText(resp.StatusCode), retryHint(head)))
			return
		}
	}

	copyHeaders(w.Header(), resp.Header)
	w.WriteHeader(resp.StatusCode)
	if len(head) > 0 {
		if _, err := w.Write(head); err != nil {
			return
		}
	}
	flusher, _ := w.(http.Flusher)
	if len(head) > 0 && flusher != nil {
		flusher.Flush()
	}
	buf := make([]byte, 32*1024)
	for {
		n, readErr := resp.Body.Read(buf)
		if n > 0 {
			if _, writeErr := w.Write(buf[:n]); writeErr != nil {
				return
			}
			if flusher != nil {
				flusher.Flush()
			}
		}
		if readErr != nil {
			return
		}
	}
}

// retryHint extracts the gateway's error code for the log line.
func retryHint(head []byte) string {
	var probe struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	if err := json.Unmarshal(head, &probe); err == nil && probe.Error.Code != "" {
		return probe.Error.Code
	}
	return ""
}

func (s *Server) health(w http.ResponseWriter) {
	s.aliases.Reload()
	upstreamView := func(channel string) map[string]any {
		u := s.Config().Upstreams[channel]
		return map[string]any{
			"base":  u.Base,
			"key":   s.keyset().For(channel) != "",
			"child": u.Child,
		}
	}
	payload := map[string]any{
		"ok":        true,
		"opencode":  upstreamView("OC"),
		"workbuddy": upstreamView("WB"),
		"qoder":     upstreamView("QD"),
		"alias": map[string]any{
			"path":   s.aliases.Path(),
			"models": s.aliases.Count(),
		},
		"children": s.sup.States(),
		"uptime_s": int(time.Since(s.started).Seconds()),
	}
	writeJSON(w, 200, payload)
}

// routeChain walks a merged chain: every hop carries its own base, channel and
// upstream id, so one display name can span WorkBuddy, Qoder and OpenCode-Go.
func (s *Server) routeChain(w http.ResponseWriter, r *http.Request, body []byte, model string, t alias.Target, path, search string, isChat bool) {
	protocol := t.Protocol
	if protocol == "" {
		protocol = "chat"
	}
	if protocol != "chat" {
		if !isChat {
			writeJSON(w, 400, errorBody("bridged models only support chat/completions", "invalid_request_error"))
			return
		}
		s.attemptBridge(w, r, body, model, t, protocol, path, search, 0)
		return
	}
	s.attemptChain(w, r, body, model, t, path, search, 0)
}

func (s *Server) attemptChain(w http.ResponseWriter, r *http.Request, body []byte, model string, t alias.Target, path, search string, index int) {
	if index >= len(t.Chain) {
		writeJSON(w, 502, errorBody("all upstreams failed: "+chainNames(t.Chain), "proxy_error"))
		return
	}
	hop := t.Chain[index]
	key := s.keyset().For(hop.Channel)
	if key == "" {
		s.log.Warnf("通道 %s 缺少 key，跳过 %s", hop.Channel, hop.Upstream)
		s.attemptChain(w, r, body, model, t, path, search, index+1)
		return
	}
	if err := s.prepare(hop.Channel); err != nil {
		s.log.Warnf("通道 %s 的子进程未就绪: %v", hop.Channel, err)
		s.attemptChain(w, r, body, model, t, path, search, index+1)
		return
	}
	rewritten, ok := rewriteModel(body, hop.Upstream)
	if !ok {
		writeJSON(w, 400, errorBody("invalid JSON body", "invalid_request_error"))
		return
	}
	headers := s.forwardHeaders(r, body, hop.Channel, key)
	s.log.Infof("%s %s%s model=%s -> %s:%s (%d/%d)", r.Method, path, search, model, hop.Channel, hop.Upstream, index+1, len(t.Chain))
	s.doForwardWith(w, r, rewritten, hop.Base, path, search, headers, chainAccept, func(reason string) {
		s.log.Infof("[router] %s -> %s, fallback %s", hop.Upstream, reason, nextHopName(t.Chain, index))
		s.attemptChain(w, r, body, model, t, path, search, index+1)
	})
}

func (s *Server) attemptBridge(w http.ResponseWriter, r *http.Request, body []byte, model string, t alias.Target, protocol, path, search string, index int) {
	if index >= len(t.Chain) {
		writeJSON(w, 502, errorBody("all upstreams failed: "+chainNames(t.Chain), "proxy_error"))
		return
	}
	hop := t.Chain[index]
	key := s.keyset().For(hop.Channel)
	if key == "" {
		s.attemptBridge(w, r, body, model, t, protocol, path, search, index+1)
		return
	}
	if err := s.prepare(hop.Channel); err != nil {
		s.attemptBridge(w, r, body, model, t, protocol, path, search, index+1)
		return
	}
	s.log.Infof("%s %s%s model=%s -> %s:%s (%d/%d)", r.Method, path, search, model, hop.Channel, hop.Upstream, index+1, len(t.Chain))
	result := bridge.Forward(s.client, bridge.Options{
		Protocol:      protocol,
		Base:          hop.Base,
		Key:           key,
		Body:          body,
		UpstreamModel: hop.Upstream,
		DisplayModel:  model,
		Ctx:           r.Context(),
	})
	// Retry only on server-side failures; a 4xx (bad request, bad key) would
	// fail identically on every hop. The last hop's real error is passed
	// through instead of a generic "all upstreams failed".
	if (result.Status >= 500 || result.Status == 429) && index+1 < len(t.Chain) {
		s.log.Infof("[router] %s -> HTTP %d, fallback %s", hop.Upstream, result.Status, nextHopName(t.Chain, index))
		s.attemptBridge(w, r, body, model, t, protocol, path, search, index+1)
		return
	}
	writeResult(w, result)
}

// chainAccept decides whether a chain attempt should fall through to the next hop.
func chainAccept(status int, head []byte) bool {
	switch status {
	case 429, 502, 503, 504:
		return false
	case 400:
		return !bytes.Contains(head, []byte(`"model_unavailable"`))
	}
	return true
}

func chainNames(chain []alias.Hop) string {
	names := make([]string, 0, len(chain))
	for _, hop := range chain {
		names = append(names, hop.Channel+":"+hop.Upstream)
	}
	return strings.Join(names, " -> ")
}

func nextHopName(chain []alias.Hop, index int) string {
	if index+1 < len(chain) {
		return chain[index+1].Channel + ":" + chain[index+1].Upstream
	}
	return "(none)"
}

// reload re-reads zgate.json and applies the parts that can change at runtime:
// config values, upstream bases, credentials, child policies, idle thresholds
// and windows. The listen address, newly added children and a changed alias-map
// path still need a restart.
func (s *Server) reload(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, 405, errorBody("use POST", "invalid_request_error"))
		return
	}
	old := s.Config()
	next, err := config.Load(old.Path)
	if err != nil {
		writeJSON(w, 400, errorBody("配置读取失败: "+err.Error(), "configuration_error"))
		return
	}
	ks := keys.Load(next.ProviderConfig, next.WBGatewayConfig, next.QoderEnvFile)
	applied, stale, added := s.sup.ApplyConfig(next.Children)
	s.setRuntime(next, ks)
	s.aliases.Reload()
	s.log.Infof("配置已热加载: %s（生效 %v）", next.Path, applied)
	writeJSON(w, 200, map[string]any{
		"ok":      true,
		"applied": applied,
		"stale":   stale,
		"added":   added,
		"note":    "监听地址、新增子进程与 alias map 路径仍需重启 zgate；配置、上游 base 与 key 已热加载",
	})
}

// trimPrefixFold removes a prefix case-insensitively.
func trimPrefixFold(s, prefix string) string {
	if len(s) >= len(prefix) && strings.EqualFold(s[:len(prefix)], prefix) {
		return s[len(prefix):]
	}
	return s
}

// ---------------------------------------------------------------- helpers

func normalizePath(r *http.Request) (string, string) {
	path := r.URL.Path
	if strings.HasPrefix(path, "/v1") && (len(path) == 3 || path[3] == '/') {
		path = path[3:]
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	if path == "" {
		path = "/"
	}
	// RawQuery does not include the "?", while the JS router's url.search does.
	// Callers concatenate base+path+search, so keep the separator here.
	if r.URL.RawQuery != "" {
		return path, "?" + r.URL.RawQuery
	}
	return path, ""
}

func rewriteModel(body []byte, upstream string) ([]byte, bool) {
	if len(body) == 0 {
		return body, true
	}
	var obj map[string]any
	if err := json.Unmarshal(body, &obj); err != nil {
		return nil, false
	}
	obj["model"] = upstream
	out, err := json.Marshal(obj)
	if err != nil {
		return nil, false
	}
	return out, true
}

func copyHeaders(dst, src http.Header) {
	for name, values := range src {
		if hopByHop[strings.ToLower(name)] {
			continue
		}
		for _, v := range values {
			dst.Add(name, v)
		}
	}
}

func writeResult(w http.ResponseWriter, r bridge.Result) {
	ct := r.ContentType
	if ct == "" {
		ct = "application/json; charset=utf-8"
	}
	w.Header().Set("Content-Type", ct)
	if strings.HasPrefix(ct, "text/event-stream") {
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
	}
	w.Header().Set("Content-Length", itoa(len(r.Body)))
	w.WriteHeader(r.Status)
	_, _ = w.Write(r.Body)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	body, err := json.Marshal(payload)
	if err != nil {
		body = []byte(`{"error":{"message":"encode failed","type":"proxy_error"}}`)
	}
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("Content-Length", itoa(len(body)))
	w.WriteHeader(status)
	_, _ = w.Write(body)
}

func errorBody(message, kind string) map[string]any {
	return map[string]any{"error": map[string]any{"message": message, "type": kind}}
}

func itoa(n int) string { return strconv.Itoa(n) }

func isWorkBuddy(model string) bool {
	m := strings.ToLower(model)
	return strings.HasPrefix(m, "cn:") || strings.HasPrefix(m, "global:")
}

func isQoder(model string) bool {
	return strings.HasPrefix(strings.ToLower(model), "qoder:")
}

func orDash(s string) string {
	if s == "" {
		return "-"
	}
	return s
}
