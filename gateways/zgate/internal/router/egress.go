package router

import (
	"context"
	"net/http"
	"net/url"
	"sync"
)

// 每跳出口（hop.proxy）的实现。
//
// 为什么放在 context 里而不是加参数：bridge.Forward 和 doForwardWith 本来就把
// 入站请求的 context 交给上游请求，所以挂一个值就够了，签名一行都不用动；
// 代价是「谁设的代理」不可见 —— 所以每处设置都紧挨着取 hop 的那一行。
//
// 两个出口：context 上没有值时走直连（模板 Transport 的 Proxy=nil），
// 有值时按 "http://host:port" 建一个带代理的 Transport 并缓存。

type proxyCtxKey struct{}

// WithProxy 把这一跳的出口代理挂到 context 上；空字符串表示直连（不挂）。
func WithProxy(ctx context.Context, proxy string) context.Context {
	if proxy == "" {
		return ctx
	}
	return context.WithValue(ctx, proxyCtxKey{}, proxy)
}

// ProxyOf 取 context 上挂的出口代理，没挂就是直连。
func ProxyOf(ctx context.Context) string {
	if ctx == nil {
		return ""
	}
	if v, ok := ctx.Value(proxyCtxKey{}).(string); ok {
		return v
	}
	return ""
}

// EgressRouter 按 context 上的代理挑 *http.Transport，并按代理串缓存。
// 它实现 http.RoundTripper，直接塞给 http.Client.Transport。
type EgressRouter struct {
	base  *http.Transport
	mu    sync.Mutex
	cache map[string]*http.Transport
}

// NewEgressRouter 用一个模板 Transport 建路由；模板本身按直连配置（Proxy=nil），
// 带代理的实例由 Clone 派生，连接池因此互不干扰。
func NewEgressRouter(base *http.Transport) *EgressRouter {
	return &EgressRouter{base: base, cache: map[string]*http.Transport{}}
}

func (e *EgressRouter) transport(proxy string) *http.Transport {
	e.mu.Lock()
	defer e.mu.Unlock()
	if t, ok := e.cache[proxy]; ok {
		return t
	}
	t := e.base.Clone()
	if proxy == "" {
		t.Proxy = nil
	} else if u, err := url.Parse(proxy); err == nil {
		t.Proxy = http.ProxyURL(u)
	}
	e.cache[proxy] = t
	return t
}

func (e *EgressRouter) RoundTrip(req *http.Request) (*http.Response, error) {
	return e.transport(ProxyOf(req.Context())).RoundTrip(req)
}
