#!/usr/bin/env python3
"""Determine which protocol each OpenCode Go model speaks."""
import json, os, time, urllib.error, urllib.request

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

MODELS = [
    "grok-4.6","grok-4.7","gpt-5.6-luna","gpt-6-luna","claude-haiku-5-5",
    "minimax-m2.7","muse-spark-1.2-contributor","muse-spark-1.3-contributor",
    "gemini-4-argon-contributor","omen-alpha","deepseek-v4.1-flash",
    "kimi-k3","qwen3.8-max","step-5-preview","hy4-preview",
]

def post(path, body, headers, timeout=45):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
                                 headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, raw, round((time.time()-t0)*1000)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:400], round((time.time()-t0)*1000)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", round((time.time()-t0)*1000)

def try_chat(mid):
    return post("/chat/completions", {
        "model": mid, "messages": [{"role": "user", "content": "Say OK"}],
        "max_tokens": 16, "stream": False,
    }, {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
        "User-Agent": "zcode-probe/1.0", "x-opencode-session": f"p-{mid}"})

def try_messages(mid):
    return post("/messages", {
        "model": mid, "max_tokens": 16,
        "messages": [{"role": "user", "content": "Say OK"}],
    }, {"x-api-key": _key(), "anthropic-version": "2023-06-01",
        "Content-Type": "application/json", "User-Agent": "zcode-probe/1.0",
        "x-opencode-session": f"p-{mid}"})

def try_responses(mid):
    return post("/responses", {
        "model": mid, "input": "Say OK", "max_output_tokens": 16,
    }, {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
        "User-Agent": "zcode-probe/1.0", "x-opencode-session": f"p-{mid}"})

def summarize(raw):
    try:
        j = json.loads(raw)
    except Exception:
        return raw[:150]
    if "error" in j and j["error"]:
        e = j["error"]
        return "ERR:" + str(e.get("type") or e.get("message"))[:120]
    # openai shape
    if j.get("choices"):
        c = j["choices"][0]
        txt = (c.get("message") or {}).get("content") or (c.get("message") or {}).get("reasoning") or ""
        return f"OK text={str(txt)[:40]!r} usage={j.get('usage')}"
    # anthropic shape
    if j.get("content"):
        txt = "".join(b.get("text","") for b in j["content"] if isinstance(b, dict))
        return f"OK text={txt[:40]!r} usage={j.get('usage')}"
    if j.get("output"):
        return f"OK output_keys={list(j.keys())[:6]} usage={j.get('usage')}"
    return "OK raw=" + raw[:120]

for mid in MODELS:
    line = [mid]
    for name, fn in (("chat", try_chat), ("messages", try_messages), ("responses", try_responses)):
        st, raw, ms = fn(mid)
        s = summarize(raw)
        line.append(f"{name}:{st}/{ms}ms {s}")
    print(" | ".join(line), flush=True)
