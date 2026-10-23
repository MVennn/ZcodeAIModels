// Package bridge translates OpenAI Chat Completions into Anthropic Messages or
// OpenAI Responses and back. It is a faithful port of tools/protocol_bridge.js.
//
// Upstream calls are non-streaming; the chat SSE ZCode expects is synthesised
// here. That keeps the translation small and deterministic (no delta
// accumulation across chunk boundaries). The trade-off is that bridged models
// deliver their text in one chunk instead of token-by-token.
package bridge

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// DefaultTimeout bounds one upstream bridge call. The JS bridge used 120s; a
// bridge call is a single non-streaming round trip, so a hard ceiling is safe
// and stops a hung upstream from pinning the request forever.
const DefaultTimeout = 120 * time.Second

// Options describes one bridged call.
type Options struct {
	Protocol      string // messages | responses
	Base          string
	Key           string
	Body          []byte
	UpstreamModel string
	DisplayModel  string
	Timeout       time.Duration
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
		payload = chatToAnthropic(opts.Body, opts.UpstreamModel)
		headers = map[string]string{
			"content-type":       "application/json",
			"user-agent":         "opencode-cli/1.0",
			"x-opencode-session": "unified-bridge",
			"x-api-key":          opts.Key,
			"anthropic-version":  "2023-06-01",
		}
		url = strings.TrimRight(opts.Base, "/") + "/messages"
	case "responses":
		payload = chatToResponses(opts.Body, opts.UpstreamModel)
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
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	status, raw := postJSON(ctx, client, url, headers, payload)
	if status < 200 || status >= 300 {
		msg := upstreamMessage(raw, status)
		return jsonResult(502, errorBody("bridge upstream error: "+msg, "upstream_error"))
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
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
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

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
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

func chatToAnthropic(body []byte, model string) map[string]any {
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
	if maxTokens == 0 {
		maxTokens = 4096
	}
	payload := map[string]any{
		"model":      model,
		"max_tokens": maxTokens,
		"messages":   messages,
		"stream":     false,
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
			payload["stop_sequences"] = arr
		} else {
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

func chatToResponses(body []byte, model string) map[string]any {
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
	payload := map[string]any{"model": model, "input": input, "stream": false}
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
