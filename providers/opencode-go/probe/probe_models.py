#!/usr/bin/env python3
"""Minimal-token connectivity + latency probe for OpenCode Go models."""
import json, os, queue, sys, threading, time
import urllib.request, urllib.error

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
    "deepseek-v4.1-flash","deepseek-v4-pro","glm-5.1","glm-5.2","glm-5.3",
    "grok-4.6","grok-4.7","muse-spark-1.2-contributor","muse-spark-1.3-contributor",
    "glm-5.3-flash","omen-alpha","gpt-5.6-luna","gpt-6-luna","claude-haiku-5-5",
    "hy3","hy4-preview","kimi-k2.6","kimi-k2.7-code","kimi-k3","mimo-v2.5",
    "mimo-v2.6-flash","mimo-v2.5-pro","mimo-v2.6-pro","minimax-m2.5","minimax-m2.7",
    "gemini-4-argon-contributor","minimax-m3","space-bunny","longcat-2.0",
    "longcat-2.5-preview-free","step-5-preview","beam-free","qwen3.6-plus",
    "qwen3.7-max","qwen3.8-max","qwen3.8-flash","qwen3.7-plus",
]

def probe(mid, timeout=60):
    body = {
        "model": mid,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 32,
        "stream": True,
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions", data=data, method="POST",
        headers={
            "Authorization": f"Bearer {_key()}",
            "Content-Type": "application/json",
            "User-Agent": "zcode-probe/1.0",
            "x-opencode-session": f"probe-{mid}",
            "Accept": "text/event-stream",
        },
    )
    t0 = time.time()
    first = None
    chunks = 0
    text = ""
    usage = None
    err = None
    status = None
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            for raw in r:
                if first is None:
                    first = time.time() - t0
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    j = json.loads(payload)
                except Exception:
                    continue
                chunks += 1
                if j.get("usage"):
                    usage = j["usage"]
                for ch in j.get("choices", []):
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        text += d["content"]
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            err = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            err = str(e)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    total = time.time() - t0
    return {
        "model": mid, "status": status, "first_ms": round(first*1000) if first else None,
        "total_ms": round(total*1000), "chunks": chunks,
        "text": text[:60], "usage": usage, "err": err,
    }

results = {}
lock = threading.Lock()
def worker(q):
    while True:
        try:
            mid = q.get_nowait()
        except queue.Empty:
            return
        r = probe(mid)
        with lock:
            results[mid] = r
            print(f"{mid:32s} status={r['status']} first={r['first_ms']}ms total={r['total_ms']}ms "
                  f"tok={r['usage']} text={r['text']!r}" + (f" ERR={r['err']}" if r['err'] else ""), flush=True)
        q.task_done()

q = queue.Queue()
for m in MODELS:
    q.put(m)
threads = [threading.Thread(target=worker, args=(q,)) for _ in range(6)]
for t in threads: t.start()
for t in threads: t.join()

with open(sys.argv[1] if len(sys.argv) > 1 else "probe_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nSaved.")
