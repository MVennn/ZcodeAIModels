#!/usr/bin/env python3
"""Throughput + tool-calling benchmark for OpenCode Go candidate models."""
import json, os, queue, threading, time, urllib.error, urllib.request

# OpenCode-Go API key 不写在源码里：从环境变量读取（见 docs/SECRETS.md）
KEY = os.environ.get("OPENCODE_GO_KEY", "").strip()

def _key():
    """取 OpenCode-Go API key；未提供时立刻报错，避免发出注定 401 的请求。"""
    k = os.environ.get("OPENCODE_GO_KEY", "").strip()
    if not k:
        raise RuntimeError(
            "缺少环境变量 OPENCODE_GO_KEY（OpenCode-Go API key，见 docs/SECRETS.md）"
        )
    return k

BASE = "https://opencode.ai/zen/go/v1"

# (model, protocol)
CANDIDATES = [
    ("deepseek-v4.1-flash", "chat"),
    ("deepseek-v4.1-flash", "messages"),
    ("glm-5.3-flash", "chat"),
    ("mimo-v2.6-flash", "chat"),
    ("mimo-v2.6-pro", "chat"),
    ("mimo-v2.5", "chat"),
    ("mimo-v2.5-pro", "chat"),
    ("hy3", "chat"),
    ("qwen3.8-flash", "chat"),
    ("qwen3.8-flash", "messages"),
    ("space-bunny", "chat"),
    ("gpt-6-luna", "responses"),
    ("gpt-5.6-luna", "responses"),
    ("claude-haiku-5-5", "messages"),
    ("minimax-m3", "chat"),
    ("minimax-m2.7", "messages"),
    ("longcat-2.0", "chat"),
    ("longcat-2.5-preview-free", "chat"),
    ("beam-free", "chat"),
    ("qwen3.7-plus", "chat"),
    ("kimi-k2.7-code", "chat"),
    ("deepseek-v4-pro", "chat"),
    ("glm-5.1", "chat"),
    ("omen-alpha", "chat"),
    ("qwen3.6-plus", "chat"),
    ("qwen3.7-max", "chat"),
    ("glm-5.2", "chat"),
    ("glm-5.3", "chat"),
]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from disk",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "file path"}},
            "required": ["path"],
        },
    },
}]

def req_chat(mid, msgs, max_tokens, tools=None, stream=False):
    body = {"model": mid, "messages": msgs, "max_tokens": max_tokens, "stream": stream}
    if tools: body["tools"] = tools
    r = urllib.request.Request(BASE + "/chat/completions", data=json.dumps(body).encode(),
        method="POST", headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
        "User-Agent": "zcode-bench/1.0", "x-opencode-session": f"b-{mid}"})
    return r

def req_messages(mid, msgs, max_tokens, tools=None):
    body = {"model": mid, "messages": msgs, "max_tokens": max_tokens}
    if tools:
        body["tools"] = [{"name": "read_file", "description": "Read a file from disk",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                             "required": ["path"]}}]
    r = urllib.request.Request(BASE + "/messages", data=json.dumps(body).encode(),
        method="POST", headers={"x-api-key": _key(), "anthropic-version": "2023-06-01",
        "Content-Type": "application/json", "User-Agent": "zcode-bench/1.0",
        "x-opencode-session": f"b-{mid}"})
    return r

def req_responses(mid, text, max_tokens, tools=None):
    body = {"model": mid, "input": text, "max_output_tokens": max_tokens}
    if tools:
        body["tools"] = [{"type": "function", "name": "read_file",
            "description": "Read a file from disk",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                           "required": ["path"]}}]
    r = urllib.request.Request(BASE + "/responses", data=json.dumps(body).encode(),
        method="POST", headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
        "User-Agent": "zcode-bench/1.0", "x-opencode-session": f"b-{mid}"})
    return r

def call(mid, proto, msgs_or_text, max_tokens, tools=None):
    if proto == "chat": r = req_chat(mid, msgs_or_text, max_tokens, tools)
    elif proto == "messages": r = req_messages(mid, msgs_or_text, max_tokens, tools)
    else: r = req_responses(mid, msgs_or_text, max_tokens, tools)
    t0 = time.time()
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:
            j = json.loads(resp.read().decode("utf-8", "replace"))
            return {"ok": True, "ms": round((time.time()-t0)*1000), "j": j}
    except urllib.error.HTTPError as e:
        return {"ok": False, "ms": round((time.time()-t0)*1000),
                "err": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:
        return {"ok": False, "ms": round((time.time()-t0)*1000), "err": f"{type(e).__name__}: {e}"[:200]}

def bench_tool(mid, proto):
    prompt = "Read the file /etc/hosts using the read_file tool. Do not explain, just call the tool."
    if proto == "chat":
        msgs = [{"role": "user", "content": prompt}]
    elif proto == "messages":
        msgs = [{"role": "user", "content": prompt}]
    else:
        msgs = prompt
    r = call(mid, proto, msgs, 256, TOOLS)
    if not r["ok"]: return {"tool": None, "ms": r["ms"], "err": r["err"]}
    j = r["j"]
    tool = None
    if proto == "chat":
        tc = (j.get("choices") or [{}])[0].get("message", {}).get("tool_calls")
        tool = bool(tc)
    elif proto == "messages":
        tool = any(b.get("type") == "tool_use" for b in j.get("content", []) if isinstance(b, dict))
    else:
        tool = any((o.get("type") in ("function_call", "tool_call")) for o in j.get("output", []) if isinstance(o, dict))
    return {"tool": tool, "ms": r["ms"], "usage": j.get("usage")}

def bench_speed(mid, proto):
    prompt = "Count from 1 to 60, space separated, numbers only."
    if proto == "chat": msgs = [{"role": "user", "content": prompt}]
    elif proto == "messages": msgs = [{"role": "user", "content": prompt}]
    else: msgs = prompt
    r = call(mid, proto, msgs, 512)
    if not r["ok"]: return {"ms": r["ms"], "err": r["err"]}
    j = r["j"]
    u = j.get("usage") or {}
    if proto == "chat":
        out = u.get("completion_tokens") or 0
        txt = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    elif proto == "messages":
        out = u.get("output_tokens") or 0
        txt = "".join(b.get("text","") for b in j.get("content", []) if isinstance(b, dict))
    else:
        out = u.get("output_tokens") or 0
        txt = ""
        for o in j.get("output", []):
            for c in (o.get("content") or []):
                if isinstance(c, dict) and c.get("text"): txt += c["text"]
    secs = max(r["ms"] / 1000.0, 0.001)
    return {"ms": r["ms"], "out_tok": out, "tok_s": round(out / secs, 1),
            "chars": len(txt), "usage": u}

results = {}
lock = threading.Lock()

def worker(q):
    while True:
        try: item = q.get_nowait()
        except queue.Empty: return
        mid, proto = item
        t = bench_tool(mid, proto)
        s = bench_speed(mid, proto)
        rec = {"model": mid, "proto": proto, "tool": t, "speed": s}
        with lock:
            results[f"{mid}|{proto}"] = rec
            ts = f"tool={t.get('tool')}" if t.get("tool") is not None else f"toolERR={t.get('err','')[:70]}"
            ss = f"{s.get('tok_s')}tok/s {s.get('out_tok')}tok {s.get('ms')}ms" if "tok_s" in s else f"speedERR={s.get('err','')[:70]}"
            print(f"{mid:28s} {proto:9s} {ts:14s} | {ss}", flush=True)
        q.task_done()

q = queue.Queue()
for c in CANDIDATES: q.put(c)
ths = [threading.Thread(target=worker, args=(q,)) for _ in range(5)]
for th in ths: th.start()
for th in ths: th.join()

with open("bench_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nSaved bench_results.json")
