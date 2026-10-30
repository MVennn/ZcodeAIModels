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
	// 冷却表：一跳被判「这跳现在没用」（模型不存在 / 额度耗尽 / 欠费）后就跳过它一段时间。
	// 集合体的链路有几十跳，不记住这些死跳，每个请求都要先把它们撞一遍。
	coolMu sync.Mutex
	cool   map[string]time.Time
}

// hopCooldown 是死跳的默认冷却时长；与额度窗口同一量级的短周期，够跨过一轮使用。
const hopCooldown = 30 * time.Minute

// rateLimitCooldown 是 429 的冷却时长。比死跳短得多：429 多半是瞬时 QPS 限制，
// 但每次都去撞它会让每个请求白付一次往返（实测 WorkBuddy 一跳今天被限流 182 次，
// 而 OC 只有 16 次），所以退避重试仍失败后先把它摘出一小段时间。
const rateLimitCooldown = 45 * time.Second

// rateLimitBackoff 是收到 429 后的就地退避：先睡一小会儿重试同一跳，
// 限流窗口通常不到 1 秒，这样多数突发根本不会让你看到失败。
const rateLimitBackoff = 700 * time.Millisecond

// transportRetryDelay 是「传输层失败」后重试同一跳前的等待。
// 这类失败（EOF / TLS 握手超时 / 连接被重置）说明请求多半没被上游受理，
// 换一次同一条腿往往就过了；等待只是给链路一个喘息窗口。
const transportRetryDelay = 300 * time.Millisecond

// timeoutCooldown 是桥接上游「连上但不说话」超时后的冷却时长。
// 实测 Conatus 会静默到总超时，不冷却就会每个请求都再等一次。
const timeoutCooldown = 5 * time.Minute

// New wires the server. client is shared with the bridge.
func New(cfg *config.Config, ks keys.Set, am *alias.Map, sup *supervisor.Supervisor, client *http.Client, log *logx.Logger) *Server {
	return &Server{cfg: cfg, keys: ks, aliases: am, sup: sup, client: client, log: log,
		started: time.Now(), cool: map[string]time.Time{}}
}

// hopKey 是冷却表的主键。出口也算进去：同一条链里「直连」和「经机场」是同一个
// upstream 的两跳，共用一个 key 会让直连那跳被地区受限的 403 冷却掉，
// 紧接着的机场跳就被当成「冷却中，跳过」—— 恰好把兜底吃掉。
func hopKey(hop alias.Hop) string { return hop.Channel + "|" + hop.Upstream + "|" + hop.Proxy }

func (s *Server) cooling(hop alias.Hop) bool {
	s.coolMu.Lock()
	defer s.coolMu.Unlock()
	until, ok := s.cool[hopKey(hop)]
	if !ok {
		return false
	}
	if time.Now().After(until) {
		delete(s.cool, hopKey(hop))
		return false
	}
	return true
}

func (s *Server) markCooling(hop alias.Hop) {
	s.markCoolingFor(hop, hopCooldown)
}

// markCoolingFor 按指定时长冷却一跳（429 用 45s，僵死上游用 5min，死跳用 30min）。
func (s *Server) markCoolingFor(hop alias.Hop, d time.Duration) {
	s.coolMu.Lock()
	s.cool[hopKey(hop)] = time.Now().Add(d)
	s.coolMu.Unlock()
}

// retryBridgeOn429 在桥接跳收到 429 时先就地退避重试一次。
// 只在还没向客户端写过任何 chunk 时重试（写过了就不能重放，会把 SSE 弄乱）。
func (s *Server) retryBridgeOn429(r *http.Request, hop alias.Hop, cw *bridgeChunkWriter, opts bridge.Options, result bridge.Result) bridge.Result {
	if result.Status != 429 || cw.written {
		return result
	}
	s.log.Infof("[router] %s 429，退避 %v 后重试同一跳", hopKey(hop), rateLimitBackoff)
	select {
	case <-time.After(rateLimitBackoff):
	case <-r.Context().Done():
		return result
	}
	return bridge.Forward(s.client, opts)
}

// coolBridgeFailure 给桥接失败分级冷却：429 短暂摘掉，上游静默超时（504）摘得久一些。
func (s *Server) coolBridgeFailure(hop alias.Hop, result bridge.Result) {
	switch result.Status {
	case 429:
		s.markCoolingFor(hop, rateLimitCooldown)
	case 504:
		s.log.Infof("[router] %s 上游静默超时，冷却 %v", hopKey(hop), timeoutCooldown)
		s.markCoolingFor(hop, timeoutCooldown)
	}
}

func (s *Server) coolingCount() int {
	s.coolMu.Lock()
	defer s.coolMu.Unlock()
	n := 0
	now := time.Now()
	for key, until := range s.cool {
		if now.After(until) {
			delete(s.cool, key)
			continue
		}
		n++
	}
	return n
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
	if !isChat && (isQoder(model) || isWorkBuddy(model) || isQwen(model) || isQiniu(model)) {
		writeJSON(w, 400, errorBody("WorkBuddy/Qoder/Qwen models only support chat/completions", "invalid_request_error"))
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
		streaming := wantsStream(body)
		cw := newBridgeChunkWriter(w)
		result := bridge.Forward(s.client, bridge.Options{
			Protocol:      protocol,
			Base:          t.Base,
			Key:           key,
			Body:          body,
			UpstreamModel: t.Upstream,
			DisplayModel:  model,
			Ctx:           r.Context(),
			Stream:        streaming,
			OnChunk:       cw.write,
		})
		finishBridge(w, cw, result)
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
	case isChat && isQwen(model):
		// 千问平台只认 Anthropic Messages；裸 `qwen:` id 还没进 alias map 时
		// （播种后、归一化前）也要能落到正确上游，而不是被当成 OpenCode 模型。
		channel, label, key = "QW", "qwen", ks.QW
		base = cfg.Upstreams["QW"].Base
		if key == "" {
			writeJSON(w, 502, errorBody("Qwen key not configured", "configuration_error"))
			return
		}
		s.log.Infof("%s %s%s model=%s -> QW:messages", r.Method, path, search, model)
		streaming := wantsStream(body)
		cw := newBridgeChunkWriter(w)
		result := bridge.Forward(s.client, bridge.Options{
			Protocol:      "messages",
			Base:          base,
			Key:           key,
			Body:          body,
			UpstreamModel: trimPrefixFold(model, "qwen:"),
			DisplayModel:  model,
			Ctx:           r.Context(),
			Stream:        streaming,
			OnChunk:       cw.write,
		})
		finishBridge(w, cw, result)
		return
	case isChat && isQiniu(model):
		// 七牛云 AI 网关：同样只认 Anthropic Messages，裸 `qn:` id 还没进 alias map
		// 时（播种后、归一化前）也要能落到正确上游。
		channel, label, key = "QN", "qiniu", ks.QN
		base = cfg.Upstreams["QN"].Base
		if key == "" {
			writeJSON(w, 502, errorBody("Qiniu key not configured", "configuration_error"))
			return
		}
		s.log.Infof("%s %s%s model=%s -> QN:messages", r.Method, path, search, model)
		streaming := wantsStream(body)
		cw := newBridgeChunkWriter(w)
		result := bridge.Forward(s.client, bridge.Options{
			Protocol:      "messages",
			Base:          base,
			Key:           key,
			Body:          body,
			UpstreamModel: trimPrefixFold(model, "qn:"),
			DisplayModel:  model,
			Ctx:           r.Context(),
			Stream:        streaming,
			OnChunk:       cw.write,
		})
		finishBridge(w, cw, result)
		return
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
	case "WB", "QD", "QW":
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
	s.doForwardWith(w, r, body, base, path, search, headers, nil, nil, nil)
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
	s.doForwardWith(w, r, rewritten, base, path, search, headers, chainAccept, retry, nil)
}

func (s *Server) doForwardWith(w http.ResponseWriter, r *http.Request, body []byte, base, path, search string, headers http.Header,
	accept func(status int, head []byte) bool, retry func(reason string), onThrottled func()) {

	target := strings.TrimRight(base, "/") + path + search
	// 429 就地退避重试一次：限流窗口通常很短，先等一小会儿再试同一跳，
	// 比立刻回落/直接失败更划算。重试仍 429 时再交给 onThrottled 冷却。
	// txRetry 单独计数：传输层失败的重试不能消耗 429 的退避预算，反之亦然。
	txRetry := 0
	for attempt := 0; ; attempt++ {
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
			// 传输层失败（EOF / TLS 握手超时 / 连接被重置）说明请求大概率没被上游
			// 受理过，重试同一条腿通常就能过 —— 先重试本跳一次，再谈回落。
			// 2026-10-31 实测：机场某节点对 opencode.ai 的大包短暂黑洞，5 KB 以上的
			// POST 全部 5s 超时，而 GET 健康检查一直 200（url-test 看不出来）。
			if txRetry == 0 {
				txRetry++
				s.log.Infof("[router] %s 传输层失败（%v），%v 后重试同一跳", base, err, transportRetryDelay)
				select {
				case <-time.After(transportRetryDelay):
				case <-r.Context().Done():
					return
				}
				continue
			}
			if retry != nil {
				retry(err.Error())
				return
			}
			writeJSON(w, 502, errorBody("unified-router upstream error: "+err.Error(), "proxy_error"))
			return
		}

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
				resp.Body.Close()
				if resp.StatusCode == 429 {
					if attempt == 0 {
						s.log.Infof("[router] 429 退避 %v 后重试同一跳", rateLimitBackoff)
						select {
						case <-time.After(rateLimitBackoff):
						case <-r.Context().Done():
							return
						}
						continue
					}
					if onThrottled != nil {
						onThrottled()
					}
				}
				retry(fmt.Sprintf("%s %s", http.StatusText(resp.StatusCode), retryHint(head)))
				return
			}
		}

		defer resp.Body.Close()
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
		"qwen":      upstreamView("QW"),
		"qiniu":     upstreamView("QN"),
		"alias": map[string]any{
			"path":   s.aliases.Path(),
			"models": s.aliases.Count(),
		},
		"children": s.sup.States(),
		"cooling":  s.coolingCount(),
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
	if protocol != "chat" && !isChat {
		writeJSON(w, 400, errorBody("bridged models only support chat/completions", "invalid_request_error"))
		return
	}
	// 每跳按自己的协议派发（chat 直转 / messages·responses 过桥），
	// 所以一条链里可以既有原生 chat 跳也有桥接跳。
	s.attemptChain(w, r, body, model, t, path, search, 0)
}

func (s *Server) attemptChain(w http.ResponseWriter, r *http.Request, body []byte, model string, t alias.Target, path, search string, index int) {
	if index >= len(t.Chain) {
		writeJSON(w, 502, errorBody("all upstreams failed: "+chainNames(t.Chain), "proxy_error"))
		return
	}
	hop := t.Chain[index]
	// 这一跳的出口交给 context（EgressRouter 按它挑 Transport），
	// 往下传的 r 也带着它，回落到下一跳时会被下一跳覆盖。
	r = r.WithContext(WithProxy(r.Context(), hop.Proxy))
	if s.cooling(hop) {
		s.log.Infof("[router] %s 冷却中，跳过", hopKey(hop))
		s.attemptChain(w, r, body, model, t, path, search, index+1)
		return
	}
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
	proto := hop.Protocol
	if proto == "" {
		proto = t.Protocol
	}
	if proto == "" {
		proto = "chat"
	}
	if proto != "chat" {
		// 这一跳是桥接上游（千问）。链里可以混协议：前面几跳原生 chat，
		// 尾巴这一跳走 Messages 桥，失败照样换下一跳。
		s.log.Infof("%s %s%s model=%s -> %s:%s [%s] (%d/%d)", r.Method, path, search,
			model, hop.Channel, hop.Upstream, proto, index+1, len(t.Chain))
		// 只有「链尾跳」才走流式：一旦前面某跳失败才能安全回落；非尾跳若先写了半截 SSE
		// 就没法再换下一跳了（整段缓冲后一次性写出，与旧版一致）。
		streaming := wantsStream(body) && index == len(t.Chain)-1
		cw := newBridgeChunkWriter(w)
		opts := bridge.Options{
			Protocol:      proto,
			Base:          hop.Base,
			Key:           key,
			Body:          body,
			UpstreamModel: hop.Upstream,
			DisplayModel:  model,
			Ctx:           r.Context(),
			Stream:        streaming,
			OnChunk:       cw.write,
		}
		result := bridge.Forward(s.client, opts)
		// 传输层失败且还没写出任何 chunk：重试同一跳一次（理由见 transportFailed）。
		if !cw.written && transportFailed(result) {
			s.log.Infof("[router] %s 传输层失败，%v 后重试同一跳", hopKey(hop), transportRetryDelay)
			select {
			case <-time.After(transportRetryDelay):
			case <-r.Context().Done():
				return
			}
			result = bridge.Forward(s.client, opts)
		}
		result = s.retryBridgeOn429(r, hop, cw, opts, result)
		if hopFatal(result.Status, result.Body) {
			s.markCooling(hop)
			if index+1 < len(t.Chain) {
				s.attemptChain(w, r, body, model, t, path, search, index+1)
				return
			}
		}
		s.coolBridgeFailure(hop, result)
		// 地区受限按失败处理：桥接路径不走 chainAccept，必须单独判，
		// 否则 gpt-6-luna 这类 responses 模型会拿 403 直接返回给客户端。
		if (result.Status >= 500 || result.Status == 429 || regionBlocked(result.Status, result.Body)) && index+1 < len(t.Chain) {
			s.log.Infof("[router] %s -> HTTP %d, fallback %s", hop.Upstream, result.Status, nextHopName(t.Chain, index))
			s.attemptChain(w, r, body, model, t, path, search, index+1)
			return
		}
		finishBridge(w, cw, result)
		return
	}
	rewritten, ok := rewriteModel(body, hop.Upstream)
	if !ok {
		writeJSON(w, 400, errorBody("invalid JSON body", "invalid_request_error"))
		return
	}
	headers := s.forwardHeaders(r, body, hop.Channel, key)
	s.log.Infof("%s %s%s model=%s -> %s:%s (%d/%d)", r.Method, path, search, model, hop.Channel, hop.Upstream, index+1, len(t.Chain))
	accept := func(status int, head []byte) bool {
		if hopFatal(status, head) {
			s.markCooling(hop)
			return false
		}
		return chainAccept(status, head)
	}
	s.doForwardWith(w, r, rewritten, hop.Base, path, search, headers, accept, func(reason string) {
		s.log.Infof("[router] %s -> %s, fallback %s", hop.Upstream, reason, nextHopName(t.Chain, index))
		s.attemptChain(w, r, body, model, t, path, search, index+1)
	}, func() {
		s.log.Infof("[router] %s 退避后仍 429，冷却 %v", hopKey(hop), rateLimitCooldown)
		s.markCoolingFor(hop, rateLimitCooldown)
	})
}

func (s *Server) attemptBridge(w http.ResponseWriter, r *http.Request, body []byte, model string, t alias.Target, protocol, path, search string, index int) {
	if index >= len(t.Chain) {
		writeJSON(w, 502, errorBody("all upstreams failed: "+chainNames(t.Chain), "proxy_error"))
		return
	}
	hop := t.Chain[index]
	r = r.WithContext(WithProxy(r.Context(), hop.Proxy))
	if s.cooling(hop) {
		s.log.Infof("[router] %s 冷却中，跳过", hopKey(hop))
		s.attemptBridge(w, r, body, model, t, protocol, path, search, index+1)
		return
	}
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
	// 只有「链尾跳」才走流式：前面某跳失败时需要安全回落，不能先写半截 SSE。
	streaming := wantsStream(body) && index == len(t.Chain)-1
	cw := newBridgeChunkWriter(w)
	opts := bridge.Options{
		Protocol:      protocol,
		Base:          hop.Base,
		Key:           key,
		Body:          body,
		UpstreamModel: hop.Upstream,
		DisplayModel:  model,
		Ctx:           r.Context(),
		Stream:        streaming,
		OnChunk:       cw.write,
	}
	result := bridge.Forward(s.client, opts)
	// 传输层失败且还没写出任何 chunk：重试同一跳一次（理由见 transportFailed）。
	if !cw.written && transportFailed(result) {
		s.log.Infof("[router] %s 传输层失败，%v 后重试同一跳", hopKey(hop), transportRetryDelay)
		select {
		case <-time.After(transportRetryDelay):
		case <-r.Context().Done():
			return
		}
		result = bridge.Forward(s.client, opts)
	}
	result = s.retryBridgeOn429(r, hop, cw, opts, result)
	// Retry only on server-side failures; a 4xx (bad request, bad key) would
	// fail identically on every hop. The last hop's real error is passed
	// through instead of a generic "all upstreams failed".
	// 模型不存在 / 额度耗尽 / 欠费与请求无关：这一跳作废，冷却它并换下一跳。
	if hopFatal(result.Status, result.Body) {
		s.markCooling(hop)
		if index+1 < len(t.Chain) {
			s.log.Infof("[router] %s -> %s, fallback %s", hop.Upstream,
				strings.TrimSpace(string(result.Body))[:min(len(result.Body), 120)], nextHopName(t.Chain, index))
			s.attemptBridge(w, r, body, model, t, protocol, path, search, index+1)
			return
		}
	}
	s.coolBridgeFailure(hop, result)
	if (result.Status >= 500 || result.Status == 429 || regionBlocked(result.Status, result.Body)) && index+1 < len(t.Chain) {
		s.log.Infof("[router] %s -> HTTP %d, fallback %s", hop.Upstream, result.Status, nextHopName(t.Chain, index))
		s.attemptBridge(w, r, body, model, t, protocol, path, search, index+1)
		return
	}
	if streaming {
		return
	}
	writeResult(w, result)
}

// hopFatal 标记「这一跳现在就是不能用」的响应：模型 id 不存在、免费额度耗尽、欠费。
// 这类 4xx 与请求本身无关，换下一跳大概率能成，所以要回落并把该跳冷却一段时间。
func hopFatal(status int, head []byte) bool {
	switch status {
	case 400, 402, 403:
	default:
		return false
	}
	for _, marker := range [][]byte{
		[]byte("model_unavailable"), []byte("Model not exist"),
		[]byte("Arrearage"), []byte("AllocationQuota"), []byte("FreeTierOnly"),
		[]byte("insufficient_quota"), []byte("quota exhausted"),
		// 千问：`403 AccessDenied` + 这句表示免费额度用完且「用完即停」开着
		[]byte("Free quota exhausted"), []byte("use free tier only"),
	} {
		if bytes.Contains(head, marker) {
			return true
		}
	}
	return false
}

// transportFailed 判断桥接结果是不是「请求根本没被上游受理」的传输层失败。
// 桥接把 client.Do 的错误包成 502 + 原始错误文本，只能按文本认。
// 只有这种情况重试同一跳才安全：上游已经读过请求再断开的，重试会重复计费。
func transportFailed(result bridge.Result) bool {
	if result.Status < 500 {
		return false
	}
	body := string(result.Body)
	for _, marker := range []string{
		"EOF", "TLS handshake timeout", "connection reset", "i/o timeout",
		"broken pipe", "server closed idle connection", "connection refused",
	} {
		if strings.Contains(body, marker) {
			return true
		}
	}
	return false
}

// regionBlocked 判断这一跳是不是「地区受限」：不是跳坏了，是这条出口进不去。
// opencode 转发上游时原样带回（2026-10-30 实测里两种写法都出现过）：
//   chat 端点  {"type":"error","error":{"type":"RegionError",...}}
//   responses {"error":{"code":"unsupported_country_region_territory",...}}
// 桥接路径（messages / responses）不走 chainAccept，必须单独问这个，
// 否则 403 会原样返回给客户端，链上的机场跳永远轮不到。
func regionBlocked(status int, head []byte) bool {
	if status != 403 && status != 400 {
		return false
	}
	for _, marker := range [][]byte{
		[]byte("unsupported_country_region_territory"),
		[]byte("RegionError"),
		[]byte("not available in your country"),
		[]byte("region, or territory not supported"),
	} {
		if bytes.Contains(head, marker) {
			return true
		}
	}
	return false
}

// chainAccept decides whether a chain attempt should fall through to the next hop.
func chainAccept(status int, head []byte) bool {
	switch status {
	case 429, 502, 503, 504:
		return false
	case 403, 400:
		if regionBlocked(status, head) {
			return false
		}
		if status == 400 {
			return !bytes.Contains(head, []byte(`"model_unavailable"`))
		}
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
	ks := keys.Load(next.ProviderConfig, next.WBGatewayConfig, next.QoderEnvFile, next.QwenEnvFile, next.QiniuEnvFile)
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

// wantsStream 返回客户端（ZCode）是否请求了 SSE 流式输出。桥接模型上游也按流式请求，
// 让首字即时到达；非流式时桥接器退化为「整段合成一个 chunk」。
func wantsStream(body []byte) bool {
	var probe struct {
		Stream bool `json:"stream"`
	}
	if err := json.Unmarshal(body, &probe); err != nil {
		return false
	}
	return probe.Stream
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

// bridgeChunkWriter 把桥接流式响应的每个 chat SSE chunk 直接写给客户端并 flush，
// 让首字随上游 delta 即时到达（不再等整段生成完）。首次写入时落 SSE 头。
type bridgeChunkWriter struct {
	w       http.ResponseWriter
	flusher http.Flusher
	once    bool
	written bool
}

func (b *bridgeChunkWriter) write(chunk []byte) error {
	if !b.once {
		b.w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
		b.w.Header().Set("Cache-Control", "no-cache")
		b.w.Header().Set("Connection", "keep-alive")
		b.w.WriteHeader(200)
		b.once = true
	}
	if _, err := b.w.Write(chunk); err != nil {
		return err
	}
	b.written = true
	if b.flusher != nil {
		b.flusher.Flush()
	}
	return nil
}

func newBridgeChunkWriter(w http.ResponseWriter) *bridgeChunkWriter {
	f, _ := w.(http.Flusher)
	return &bridgeChunkWriter{w: w, flusher: f}
}

// finishBridge 收口桥接响应：流式且已写出过 chunk 时，SSE 已结束，无需再写；
// 流式但尚未写出任何 chunk（上游直接返回错误）时，仍要把真实错误码经 writeResult 透出，
// 否则客户端会一直挂起。非流式则一律走 writeResult（与旧行为一致）。
func finishBridge(w http.ResponseWriter, cw *bridgeChunkWriter, result bridge.Result) {
	if cw.written {
		return
	}
	writeResult(w, result)
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

func isQwen(model string) bool {
	return strings.HasPrefix(strings.ToLower(model), "qwen:")
}

func isQiniu(model string) bool {
	return strings.HasPrefix(strings.ToLower(model), "qn:")
}

func orDash(s string) string {
	if s == "" {
		return "-"
	}
	return s
}
