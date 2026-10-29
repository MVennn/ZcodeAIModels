// Package bridge translates OpenAI Chat Completions into Anthropic Messages or
// OpenAI Responses and back. It is a faithful port of tools/protocol_bridge.js.
//
// Upstream calls are non-streaming; the chat SSE ZCode expects is synthesised
// here. That keeps the translation small and deterministic (no delta
// accumulation across chunk boundaries). The trade-off is that bridged models
// deliver their text in one chunk instead of token-by-token.
package bridge

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"
)

// maxUpstreamTokens 是桥接上游接受的 max_tokens 上限（Anthropic Messages 约定）。
const maxUpstreamTokens = 65536

// DefaultTimeout bounds one upstream bridge call. The JS bridge used 120s; a
// bridge call is a single non-streaming round trip, so a hard ceiling is safe
// and stops a hung upstream from pinning the request forever.
const DefaultTimeout = 120 * time.Second

// DefaultIdle 是流式桥接的「空闲上限」：上游连上后若连续这么久一个字节都没发，
// 就主动断开并返回 504，而不是干等到 DefaultTimeout。
//
// 为什么需要它：七牛的 Conatus 是聚合端点，实测会接受连接后完全静默，
// 唯一的兜底是 120 秒总超时 —— 用户端表现为「2 分钟没响应」。
// 桥接模型的正常首字实测在 0.5–1.8s，30 秒有十几倍余量；
// 只有真正僵死的上游才会触发。
const DefaultIdle = 30 * time.Second

// Options describes one bridged call.
type Options struct {
	Protocol      string // messages | responses
	Base          string
	Key           string
	Body          []byte
	UpstreamModel string
	DisplayModel  string
	Timeout       time.Duration
	// Ctx is the inbound request context; cancellation stops the upstream
	// call instead of pinning a connection after the client has gone away.
	Ctx context.Context
	// Stream 为 true 时，上行（客户端）请求了 SSE 流式；桥接器把上游的流式响应
	// 逐 delta 转成 chat SSE 经 OnChunk 推给客户端，首字不再等到整段生成完才出现。
	// OnChunk 为空（非流式调用方）时退化为原行为：整段合成一个 chunk（与旧版一致）。
	Stream   bool
	OnChunk func([]byte) error
	// Idle 是流式路径的空闲上限（0 = DefaultIdle）。上游连续这么久没有任何字节
	// 到达就断开并返回 504，把「上游僵死」变成可判定的错误。
	Idle time.Duration
}

// Result is what the router writes back.
type Result struct {
	Status      int
	ContentType string
	Body        []byte
}

// Forward performs the upstream call and returns the chat-format response.
func Forward(client *http.Client, opts Options) Result {
	var payload any
	var headers map[string]string
	var url string
	switch opts.Protocol {
	case "messages":
		payload = chatToAnthropic(opts.Body, opts.UpstreamModel, opts.Stream)
		headers = map[string]string{
			"content-type":       "application/json",
			"user-agent":         "opencode-cli/1.0",
			"x-opencode-session": "unified-bridge",
			"x-api-key":          opts.Key,
			"anthropic-version":  "2023-06-01",
		}
		url = strings.TrimRight(opts.Base, "/") + "/messages"
	case "responses":
		payload = chatToResponses(opts.Body, opts.UpstreamModel, opts.Stream)
		headers = map[string]string{
			"content-type":       "application/json",
			"user-agent":         "opencode-cli/1.0",
			"x-opencode-session": "unified-bridge",
			"authorization":      "Bearer " + opts.Key,
		}
		url = strings.TrimRight(opts.Base, "/") + "/responses"
	default:
		return jsonResult(500, errorBody("unknown bridge protocol: "+opts.Protocol, "proxy_error"))
	}

	timeout := opts.Timeout
	if timeout <= 0 {
		timeout = DefaultTimeout
	}
	parent := opts.Ctx
	if parent == nil {
		parent = context.Background()
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()

	// 流式上行：把上游的流式响应逐 delta 经 OnChunk 推给客户端，首字不再等整段。
	// 与旧版的区别：上游也按 stream=true 请求，桥接器边收边发，而不是收完再合成一个 chunk。
	if opts.Stream && opts.OnChunk != nil {
		return forwardStream(ctx, client, opts, url, headers, payload)
	}

	status, raw := postJSON(ctx, client, url, headers, payload)
	if status < 200 || status >= 300 {
		msg := upstreamMessage(raw, status)
		// Keep the upstream status: a 4xx is a client/credential problem that
		// must not be retried across every hop, and callers need the real code.
		return jsonResult(status, errorBody("bridge upstream error: "+msg, "upstream_error"))
	}
	var data map[string]any
	if err := json.Unmarshal(raw, &data); err != nil {
		return jsonResult(502, errorBody("bridge upstream returned non-JSON: "+truncate(string(raw), 300), "upstream_error"))
	}
	var chat map[string]any
	if opts.Protocol == "messages" {
		chat = anthropicToChat(data, opts.DisplayModel)
	} else {
		chat = responsesToChat(data, opts.DisplayModel)
	}
	streaming := false
	var probe struct {
		Stream bool `json:"stream"`
	}
	if err := json.Unmarshal(opts.Body, &probe); err == nil {
		streaming = probe.Stream
	}
	if streaming {
		return Result{Status: 200, ContentType: "text/event-stream; charset=utf-8", Body: sseOf(chat)}
	}
	return jsonResult(200, chat)
}

func postJSON(ctx context.Context, client *http.Client, url string, headers map[string]string, payload any) (int, []byte) {
	body, err := json.Marshal(payload)
	if err != nil {
		return 502, []byte(err.Error())
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return 502, []byte(err.Error())
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		return 502, []byte(err.Error())
	}
	defer resp.Body.Close()
	// 非流式同样要防「连上但不说话」：否则 Conatus 这类僵死上游会干等满总超时。
	ir := newIdleReader(resp.Body, DefaultIdle)
	defer ir.stop()
	raw, err := io.ReadAll(ir)
	if err != nil {
		if ir.timedOut() {
			return 504, []byte("upstream silent for " + DefaultIdle.String())
		}
		return 502, []byte(err.Error())
	}
	return resp.StatusCode, raw
}

func upstreamMessage(raw []byte, status int) string {
	var obj map[string]any
	if err := json.Unmarshal(raw, &obj); err == nil {
		if e, ok := obj["error"].(map[string]any); ok {
			if m, ok := e["message"].(string); ok && m != "" {
				return m
			}
		}
		if m, ok := obj["message"].(string); ok && m != "" {
			return m
		}
	}
	if text := strings.TrimSpace(string(raw)); text != "" {
		return truncate(text, 500)
	}
	return fmt.Sprintf("upstream HTTP %d", status)
}

// forwardStream 把上游的流式响应逐 delta 转成 chat SSE 经 OnChunk 推给客户端。
// 上游按 stream=true 请求；收到第一个 content delta 即转发，首字不再等整段生成完。
// 上游返回 4xx/5xx（或连接错误）时退回标准 Result，让路由按原逻辑回落 / 报真实状态码。
func forwardStream(ctx context.Context, client *http.Client, opts Options, url string, headers map[string]string, payload any) Result {
	body, err := json.Marshal(payload)
	if err != nil {
		return jsonResult(502, errorBody("bridge request build failed: "+err.Error(), "proxy_error"))
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return jsonResult(502, errorBody("bridge request build failed: "+err.Error(), "proxy_error"))
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	// 关键：声明接受 SSE，让上游按事件流返回（Anthropic / OpenAI responses 都认）。
	req.Header.Set("Accept", "text/event-stream")
	resp, err := client.Do(req)
	if err != nil {
		return jsonResult(502, errorBody("bridge upstream error: "+err.Error(), "upstream_error"))
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		raw, _ := io.ReadAll(resp.Body)
		msg := upstreamMessage(raw, resp.StatusCode)
		return jsonResult(resp.StatusCode, errorBody("bridge upstream error: "+msg, "upstream_error"))
	}

	// 空闲看门狗：上游连上后一直不发字节时，主动断开，让 Read 返回错误。
	idle := opts.Idle
	if idle <= 0 {
		idle = DefaultIdle
	}
	ir := newIdleReader(resp.Body, idle)
	defer ir.stop()

	writeChunk := func(delta map[string]any, finish any) error {
		chunk := map[string]any{
			"id":      "chatcmpl-" + longID(),
			"object":  "chat.completion.chunk",
			"created": time.Now().Unix(),
			"model":   opts.DisplayModel,
			"choices": []any{map[string]any{"index": 0, "delta": delta, "finish_reason": finish}},
		}
		line, _ := json.Marshal(chunk)
		out := append([]byte("data: "), line...)
		out = append(out, '\n', '\n')
		return opts.OnChunk(out)
	}

	// 首块 role 延迟到「真有数据要发」时才写：否则上游僵死时我们已经落了 SSE 头，
	// 既回不了真实错误码、也没法让路由回落。emitted 记录是否已经动过客户端。
	emitted := false
	emit := func(delta map[string]any, finish any) error {
		if !emitted {
			emitted = true
			if err := writeChunk(map[string]any{"role": "assistant"}, nil); err != nil {
				return err
			}
		}
		return writeChunk(delta, finish)
	}

	var sawTool bool
	var streamErr error
	if opts.Protocol == "responses" {
		sawTool, streamErr = streamResponses(ir, emit)
	} else {
		sawTool, streamErr = streamAnthropic(ir, emit)
	}
	if streamErr != nil {
		if !emitted {
			// 一个字节都没转出去：干净地返回错误码，路由可以正常回落/报错。
			if ir.timedOut() {
				return jsonResult(504, errorBody(
					fmt.Sprintf("bridge upstream silent for %s: %s", idle, opts.UpstreamModel),
					"upstream_timeout"))
			}
			return jsonResult(502, errorBody("bridge upstream error: "+streamErr.Error(), "upstream_error"))
		}
		// 已经流出去一部分：只能在流里报错并收尾（SSE 头已发，改不了状态码）。
		_ = emit(map[string]any{"content": "\n[bridge stream error: " + streamErr.Error() + "]"}, "stop")
		_ = opts.OnChunk([]byte("data: [DONE]\n\n"))
		return Result{Status: 200}
	}
	// 收尾：空 delta + finish_reason，再发 [DONE]。有工具调用时必须是 tool_calls，
	// 否则客户端会把这一轮当成「已说完、没有动作」而不是去执行工具。
	finish := "stop"
	if sawTool {
		finish = "tool_calls"
	}
	if err := emit(map[string]any{}, finish); err != nil {
		return Result{Status: 200}
	}
	_ = opts.OnChunk([]byte("data: [DONE]\n\n"))
	return Result{Status: 200}
}

// idleReader 在连续 idle 时长没有任何字节到达时关闭底层连接。
// 用于把「上游接受了连接但永远不说话」变成一次可判定的读错误。
type idleReader struct {
	r      io.Reader
	rc     io.ReadCloser
	d      time.Duration
	timer  *time.Timer
	mu     sync.Mutex
	tripped bool
}

func newIdleReader(rc io.ReadCloser, d time.Duration) *idleReader {
	ir := &idleReader{r: rc, rc: rc, d: d}
	ir.timer = time.AfterFunc(d, func() {
		ir.mu.Lock()
		ir.tripped = true
		ir.mu.Unlock()
		_ = rc.Close()
	})
	return ir
}

func (ir *idleReader) Read(p []byte) (int, error) {
	n, err := ir.r.Read(p)
	if n > 0 {
		ir.timer.Reset(ir.d)
	}
	return n, err
}

func (ir *idleReader) stop() { ir.timer.Stop() }

func (ir *idleReader) timedOut() bool {
	ir.mu.Lock()
	defer ir.mu.Unlock()
	return ir.tripped
}

// streamAnthropic 解析 Anthropic Messages 的 SSE 流，把 text/thinking/tool_use
// 三种增量都翻译成 chat SSE。返回本轮是否出现过工具调用（决定 finish_reason）。
func streamAnthropic(r io.Reader, emit func(map[string]any, any) error) (bool, error) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	var ev string
	sawTool := false
	toolIndex := -1
	// Anthropic 的 content block index -> chat tool_calls 的连续序号
	toolOf := map[int]int{}
	for sc.Scan() {
		line := sc.Text()
		if line == "" {
			// 一个 event 以空行结束；data 多行时这里只取最后一段，够用（单行 JSON）。
			ev = ""
			continue
		}
		if strings.HasPrefix(line, "event:") {
			ev = strings.TrimSpace(line[len("event:"):])
			continue
		}
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(line[len("data:"):])
		if data == "[DONE]" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(data), &obj); err != nil {
			continue
		}
		kind, _ := obj["type"].(string)
		if kind == "" {
			kind = ev
		}
		switch kind {
		case "content_block_start":
			block, _ := obj["content_block"].(map[string]any)
			if block == nil {
				continue
			}
			if bt, _ := block["type"].(string); bt == "tool_use" {
				toolIndex++
				toolOf[toInt(obj["index"])] = toolIndex
				sawTool = true
				id, _ := block["id"].(string)
				if id == "" {
					id = "call_" + shortID()
				}
				name, _ := block["name"].(string)
				if name == "" {
					name = "tool"
				}
				if err := emit(map[string]any{"tool_calls": []any{map[string]any{
					"index":    toolIndex,
					"id":       id,
					"type":     "function",
					"function": map[string]any{"name": name, "arguments": ""},
				}}}, nil); err != nil {
					return sawTool, err
				}
			}
		case "content_block_delta":
			delta, _ := obj["delta"].(map[string]any)
			if delta == nil {
				continue
			}
			switch delta["type"] {
			case "text_delta":
				if t, _ := delta["text"].(string); t != "" {
					if err := emit(map[string]any{"content": t}, nil); err != nil {
						return sawTool, err
					}
				}
			case "thinking_delta":
				if t, _ := delta["thinking"].(string); t != "" {
					if err := emit(map[string]any{"reasoning_content": t}, nil); err != nil {
						return sawTool, err
					}
				}
			case "input_json_delta":
				partial, _ := delta["partial_json"].(string)
				if partial == "" {
					continue
				}
				idx, ok := toolOf[toInt(obj["index"])]
				if !ok {
					continue
				}
				if err := emit(map[string]any{"tool_calls": []any{map[string]any{
					"index":    idx,
					"function": map[string]any{"arguments": partial},
				}}}, nil); err != nil {
					return sawTool, err
				}
			}
		}
	}
	return sawTool, sc.Err()
}

// streamResponses 解析 OpenAI Responses 的 SSE 流：正文增量 + function_call 增量
// 都翻译成 chat SSE。返回本轮是否出现过工具调用（决定 finish_reason）。
func streamResponses(r io.Reader, emit func(map[string]any, any) error) (bool, error) {
	sc := bufio.NewScanner(r)
	sc.Buffer(make([]byte, 1024*1024), 8*1024*1024)
	sawTool := false
	toolIndex := -1
	// item id / call_id -> chat tool_calls 的连续序号
	toolOf := map[string]int{}
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "data:") {
			continue
		}
		data := strings.TrimSpace(line[len("data:"):])
		if data == "[DONE]" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(data), &obj); err != nil {
			continue
		}
		switch typ, _ := obj["type"].(string); typ {
		case "response.output_text.delta":
			if delta, _ := obj["delta"].(string); delta != "" {
				if err := emit(map[string]any{"content": delta}, nil); err != nil {
					return sawTool, err
				}
			}
		case "response.output_item.added":
			item, _ := obj["item"].(map[string]any)
			if item == nil {
				continue
			}
			if it, _ := item["type"].(string); it != "function_call" {
				continue
			}
			toolIndex++
			id, _ := item["call_id"].(string)
			if id == "" {
				id, _ = item["id"].(string)
			}
			if id == "" {
				id = "call_" + shortID()
			}
			name, _ := item["name"].(string)
			if name == "" {
				name = "tool"
			}
			if key, _ := item["id"].(string); key != "" {
				toolOf[key] = toolIndex
			}
			if key, _ := item["call_id"].(string); key != "" {
				toolOf[key] = toolIndex
			}
			sawTool = true
			if err := emit(map[string]any{"tool_calls": []any{map[string]any{
				"index":    toolIndex,
				"id":       id,
				"type":     "function",
				"function": map[string]any{"name": name, "arguments": ""},
			}}}, nil); err != nil {
				return sawTool, err
			}
		case "response.function_call_arguments.delta":
			partial, _ := obj["delta"].(string)
			if partial == "" {
				continue
			}
			idx, ok := toolOf[toString(obj["item_id"])]
			if !ok {
				continue
			}
			if err := emit(map[string]any{"tool_calls": []any{map[string]any{
				"index":    idx,
				"function": map[string]any{"arguments": partial},
			}}}, nil); err != nil {
				return sawTool, err
			}
		}
	}
	return sawTool, sc.Err()
}

func toString(v any) string {
	s, _ := v.(string)
	return s
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	// Count characters, not bytes: cutting a multi-byte rune in half produces
	// invalid UTF-8 in the error text returned to the client.
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n])
}

func jsonResult(status int, payload any) Result {
	body, _ := json.Marshal(payload)
	return Result{Status: status, ContentType: "application/json; charset=utf-8", Body: body}
}

func errorBody(message, kind string) map[string]any {
	return map[string]any{"error": map[string]any{"message": message, "type": kind}}
}

// sseOf renders the chat SSE ZCode expects from a non-streaming chat response.
func sseOf(chat map[string]any) []byte {
	var buf bytes.Buffer
	id, _ := chat["id"].(string)
	model, _ := chat["model"].(string)
	created := chat["created"]
	base := map[string]any{"id": id, "object": "chat.completion.chunk", "created": created, "model": model}

	send := func(delta map[string]any, finish any) {
		chunk := map[string]any{
			"id":      base["id"],
			"object":  base["object"],
			"created": base["created"],
			"model":   base["model"],
			"choices": []any{map[string]any{"index": 0, "delta": delta, "finish_reason": finish}},
		}
		line, _ := json.Marshal(chunk)
		buf.WriteString("data: ")
		buf.Write(line)
		buf.WriteString("\n\n")
	}

	send(map[string]any{"role": "assistant"}, nil)
	choices, _ := chat["choices"].([]any)
	var message map[string]any
	var finish any
	if len(choices) > 0 {
		if c, ok := choices[0].(map[string]any); ok {
			message, _ = c["message"].(map[string]any)
			finish = c["finish_reason"]
		}
	}
	if message != nil {
		if v, ok := message["reasoning_content"]; ok && v != "" {
			send(map[string]any{"reasoning_content": v}, nil)
		}
		if v, ok := message["content"]; ok && v != "" {
			send(map[string]any{"content": v}, nil)
		}
		if calls, ok := message["tool_calls"].([]any); ok {
			for i, call := range calls {
				entry := map[string]any{"index": float64(i)}
				if m, ok := call.(map[string]any); ok {
					for k, v := range m {
						entry[k] = v
					}
				}
				send(map[string]any{"tool_calls": []any{entry}}, nil)
			}
		}
	}
	send(map[string]any{}, finish)
	buf.WriteString("data: [DONE]\n\n")
	return buf.Bytes()
}

// ---------------------------------------------------------------- request side

func textOf(content any) string {
	switch v := content.(type) {
	case string:
		return v
	case []any:
		var b strings.Builder
		for _, part := range v {
			switch p := part.(type) {
			case string:
				b.WriteString(p)
			case map[string]any:
				if s, ok := p["text"].(string); ok {
					b.WriteString(s)
				} else if s, ok := p["content"].(string); ok {
					b.WriteString(s)
				}
			}
		}
		return b.String()
	}
	return ""
}

func safeJSON(v any) any {
	switch x := v.(type) {
	case nil:
		return map[string]any{}
	case string:
		var out any
		if err := json.Unmarshal([]byte(x), &out); err == nil {
			return out
		}
		return map[string]any{"value": x}
	case map[string]any:
		return x
	default:
		return map[string]any{"value": x}
	}
}

func messagesOf(body []byte) []any {
	var probe struct {
		Messages []any `json:"messages"`
	}
	_ = json.Unmarshal(body, &probe)
	return probe.Messages
}

func toolsOf(body []byte) []any {
	var probe struct {
		Tools []any `json:"tools"`
	}
	_ = json.Unmarshal(body, &probe)
	return probe.Tools
}

func rawMap(body []byte) map[string]any {
	var out map[string]any
	_ = json.Unmarshal(body, &out)
	return out
}

func toInt(v any) int {
	switch x := v.(type) {
	case float64:
		return int(x)
	case int:
		return x
	}
	return 0
}

func toolFunction(tool any) map[string]any {
	if m, ok := tool.(map[string]any); ok {
		if fn, ok := m["function"].(map[string]any); ok {
			return fn
		}
	}
	return map[string]any{}
}

func chatToAnthropic(body []byte, model string, stream bool) map[string]any {
	systemParts := []string{}
	messages := []any{}
	for _, raw := range messagesOf(body) {
		msg, _ := raw.(map[string]any)
		if msg == nil {
			continue
		}
		role, _ := msg["role"].(string)
		switch role {
		case "system":
			systemParts = append(systemParts, textOf(msg["content"]))
		case "tool":
			id, _ := msg["tool_call_id"].(string)
			messages = append(messages, map[string]any{
				"role": "user",
				"content": []any{map[string]any{
					"type":        "tool_result",
					"tool_use_id": id,
					"content":     textOf(msg["content"]),
				}},
			})
		case "assistant":
			blocks := []any{}
			if text := textOf(msg["content"]); text != "" {
				blocks = append(blocks, map[string]any{"type": "text", "text": text})
			}
			if calls, ok := msg["tool_calls"].([]any); ok {
				for _, c := range calls {
					call, _ := c.(map[string]any)
					if call == nil {
						continue
					}
					id, _ := call["id"].(string)
					if id == "" {
						id = "call_" + shortID()
					}
					fn, _ := call["function"].(map[string]any)
					name, _ := fn["name"].(string)
					if name == "" {
						name = "tool"
					}
					blocks = append(blocks, map[string]any{
						"type":  "tool_use",
						"id":    id,
						"name":  name,
						"input": safeJSON(fn["arguments"]),
					})
				}
			}
			if len(blocks) == 0 {
				blocks = append(blocks, map[string]any{"type": "text", "text": ""})
			}
			messages = append(messages, map[string]any{"role": "assistant", "content": blocks})
		default:
			messages = append(messages, map[string]any{
				"role":    "user",
				"content": []any{map[string]any{"type": "text", "text": textOf(msg["content"])}},
			})
		}
	}
	if len(messages) == 0 {
		messages = append(messages, map[string]any{
			"role":    "user",
			"content": []any{map[string]any{"type": "text", "text": ""}},
		})
	}

	tools := []any{}
	for _, t := range toolsOf(body) {
		fn := toolFunction(t)
		name, _ := fn["name"].(string)
		if name == "" {
			name = "tool"
		}
		desc, _ := fn["description"].(string)
		params, ok := fn["parameters"].(map[string]any)
		if !ok {
			params = map[string]any{"type": "object", "properties": map[string]any{}}
		}
		tools = append(tools, map[string]any{
			"name":         name,
			"description":  desc,
			"input_schema": params,
		})
	}

	src := rawMap(body)
	maxTokens := toInt(src["max_completion_tokens"])
	if maxTokens == 0 {
		maxTokens = toInt(src["max_tokens"])
	}
	if maxTokens <= 0 {
		maxTokens = 4096
	}
	// 上游对区间有硬校验（千问：`Range of max_tokens should be [1, 65536]`）。
	// ZCode 会按客户端设置发 128000 这类值，不夹住就是硬 400，整条链都过不去。
	if maxTokens > maxUpstreamTokens {
		maxTokens = maxUpstreamTokens
	}
	payload := map[string]any{
		"model":      model,
		"max_tokens": maxTokens,
		"messages":   messages,
		"stream":     stream,
	}
	if filtered := nonEmpty(systemParts); len(filtered) > 0 {
		payload["system"] = strings.Join(filtered, "\n\n")
	}
	if len(tools) > 0 {
		payload["tools"] = tools
	}
	optionalNumber(payload, src, "temperature", "temperature")
	optionalNumber(payload, src, "top_p", "top_p")
	if stop, ok := src["stop"]; ok && stop != nil {
		if arr, ok := stop.([]any); ok {
			if len(arr) > 0 {
				payload["stop_sequences"] = arr
			}
		} else if s, isStr := stop.(string); !isStr || s != "" {
			// The JS version skipped every falsy value; an empty string would
			// become [""] here and can be rejected upstream.
			payload["stop_sequences"] = []any{stop}
		}
	}
	switch tc := src["tool_choice"].(type) {
	case string:
		if tc == "auto" {
			payload["tool_choice"] = map[string]any{"type": "auto"}
		} else if tc == "none" {
			payload["tool_choice"] = map[string]any{"type": "none"}
		}
	case map[string]any:
		if fn, ok := tc["function"].(map[string]any); ok {
			name, _ := fn["name"].(string)
			payload["tool_choice"] = map[string]any{"type": "tool", "name": name}
		}
	}
	return payload
}

func chatToResponses(body []byte, model string, stream bool) map[string]any {
	systemParts := []string{}
	input := []any{}
	for _, raw := range messagesOf(body) {
		msg, _ := raw.(map[string]any)
		if msg == nil {
			continue
		}
		role, _ := msg["role"].(string)
		switch role {
		case "system":
			systemParts = append(systemParts, textOf(msg["content"]))
		case "tool":
			id, _ := msg["tool_call_id"].(string)
			input = append(input, map[string]any{
				"type":    "function_call_output",
				"call_id": id,
				"output":  textOf(msg["content"]),
			})
		case "assistant":
			if text := textOf(msg["content"]); text != "" {
				input = append(input, map[string]any{"role": "assistant", "content": text})
			}
			if calls, ok := msg["tool_calls"].([]any); ok {
				for _, c := range calls {
					call, _ := c.(map[string]any)
					if call == nil {
						continue
					}
					id, _ := call["id"].(string)
					if id == "" {
						id = "call_" + shortID()
					}
					fn, _ := call["function"].(map[string]any)
					name, _ := fn["name"].(string)
					args, _ := fn["arguments"].(string)
					if name == "" {
						name = "tool"
					}
					if args == "" {
						args = "{}"
					}
					input = append(input, map[string]any{
						"type":      "function_call",
						"call_id":   id,
						"name":      name,
						"arguments": args,
					})
				}
			}
		default:
			input = append(input, map[string]any{"role": "user", "content": textOf(msg["content"])})
		}
	}

	tools := []any{}
	for _, t := range toolsOf(body) {
		fn := toolFunction(t)
		name, _ := fn["name"].(string)
		if name == "" {
			name = "tool"
		}
		desc, _ := fn["description"].(string)
		params, ok := fn["parameters"].(map[string]any)
		if !ok {
			params = map[string]any{"type": "object", "properties": map[string]any{}}
		}
		tools = append(tools, map[string]any{
			"type":        "function",
			"name":        name,
			"description": desc,
			"parameters":  params,
		})
	}

	src := rawMap(body)
	payload := map[string]any{"model": model, "input": input, "stream": stream}
	if filtered := nonEmpty(systemParts); len(filtered) > 0 {
		payload["instructions"] = strings.Join(filtered, "\n\n")
	}
	if len(tools) > 0 {
		payload["tools"] = tools
	}
	max := toInt(src["max_completion_tokens"])
	if max == 0 {
		max = toInt(src["max_tokens"])
	}
	if max > 0 {
		payload["max_output_tokens"] = max
	}
	optionalNumber(payload, src, "temperature", "temperature")
	optionalNumber(payload, src, "top_p", "top_p")
	switch tc := src["tool_choice"].(type) {
	case string:
		if tc == "auto" || tc == "none" {
			payload["tool_choice"] = tc
		}
	case map[string]any:
		if fn, ok := tc["function"].(map[string]any); ok {
			name, _ := fn["name"].(string)
			payload["tool_choice"] = map[string]any{"type": "function", "name": name}
		}
	}
	return payload
}

// --------------------------------------------------------------- response side

func anthropicToChat(data map[string]any, model string) map[string]any {
	texts := []string{}
	reasoning := []string{}
	toolCalls := []any{}
	blocks, _ := data["content"].([]any)
	for _, raw := range blocks {
		block, _ := raw.(map[string]any)
		if block == nil {
			continue
		}
		kind, _ := block["type"].(string)
		switch kind {
		case "text":
			s, _ := block["text"].(string)
			texts = append(texts, s)
		case "thinking":
			s, _ := block["thinking"].(string)
			reasoning = append(reasoning, s)
		case "tool_use":
			id, _ := block["id"].(string)
			if id == "" {
				id = "call_" + shortID()
			}
			name, _ := block["name"].(string)
			if name == "" {
				name = "tool"
			}
			input, _ := json.Marshal(safeJSON(block["input"]))
			toolCalls = append(toolCalls, map[string]any{
				"id":   id,
				"type": "function",
				"function": map[string]any{
					"name":      name,
					"arguments": string(input),
				},
			})
		}
	}
	message := map[string]any{"role": "assistant", "content": strings.Join(texts, "")}
	if len(reasoning) > 0 {
		message["reasoning_content"] = strings.Join(reasoning, "")
	}
	if len(toolCalls) > 0 {
		message["tool_calls"] = toolCalls
	}
	stopReason, _ := data["stop_reason"].(string)
	finish := "stop"
	switch {
	case len(toolCalls) > 0:
		finish = "tool_calls"
	case stopReason == "max_tokens":
		finish = "length"
	case stopReason == "tool_use":
		finish = "tool_calls"
	}
	return chatEnvelope(model, message, finish, usageOf(data))
}

func responsesToChat(data map[string]any, model string) map[string]any {
	texts := []string{}
	reasoning := []string{}
	toolCalls := []any{}
	output, _ := data["output"].([]any)
	for _, raw := range output {
		item, _ := raw.(map[string]any)
		if item == nil {
			continue
		}
		kind, _ := item["type"].(string)
		switch kind {
		case "message":
			parts, _ := item["content"].([]any)
			for _, p := range parts {
				part, _ := p.(map[string]any)
				if part == nil {
					continue
				}
				if t, _ := part["type"].(string); t == "output_text" || t == "text" {
					s, _ := part["text"].(string)
					texts = append(texts, s)
				}
			}
		case "function_call":
			id, _ := item["call_id"].(string)
			if id == "" {
				id, _ = item["id"].(string)
			}
			if id == "" {
				id = "call_" + shortID()
			}
			name, _ := item["name"].(string)
			if name == "" {
				name = "tool"
			}
			args, _ := item["arguments"].(string)
			if args == "" {
				args = "{}"
			}
			toolCalls = append(toolCalls, map[string]any{
				"id":       id,
				"type":     "function",
				"function": map[string]any{"name": name, "arguments": args},
			})
		case "reasoning":
			summary, _ := item["summary"].([]any)
			for _, s := range summary {
				part, _ := s.(map[string]any)
				if part == nil {
					continue
				}
				if t, _ := part["text"].(string); t != "" {
					reasoning = append(reasoning, t)
				}
			}
		}
	}
	if len(texts) == 0 {
		if s, ok := data["output_text"].(string); ok {
			texts = append(texts, s)
		}
	}
	message := map[string]any{"role": "assistant", "content": strings.Join(texts, "")}
	if len(reasoning) > 0 {
		message["reasoning_content"] = strings.Join(reasoning, "")
	}
	if len(toolCalls) > 0 {
		message["tool_calls"] = toolCalls
	}
	finish := "stop"
	if len(toolCalls) > 0 {
		finish = "tool_calls"
	} else if status, _ := data["status"].(string); status == "incomplete" {
		finish = "length"
	}
	return chatEnvelope(model, message, finish, usageOf(data))
}

func chatEnvelope(model string, message map[string]any, finish string, usage map[string]any) map[string]any {
	out := map[string]any{
		"id":      "chatcmpl-" + longID(),
		"object":  "chat.completion",
		"created": time.Now().Unix(),
		"model":   model,
		"choices": []any{map[string]any{
			"index":         0,
			"message":       message,
			"finish_reason": finish,
		}},
	}
	if usage != nil {
		out["usage"] = usage
	}
	return out
}

func usageOf(data map[string]any) map[string]any {
	usage, ok := data["usage"].(map[string]any)
	if !ok {
		return nil
	}
	in := toInt(usage["input_tokens"])
	out := toInt(usage["output_tokens"])
	return map[string]any{
		"prompt_tokens":     in,
		"completion_tokens": out,
		"total_tokens":      in + out,
	}
}

func optionalNumber(dst, src map[string]any, from, to string) {
	if v, ok := src[from]; ok && v != nil {
		dst[to] = v
	}
}

func nonEmpty(in []string) []string {
	out := make([]string, 0, len(in))
	for _, s := range in {
		if s != "" {
			out = append(out, s)
		}
	}
	return out
}
