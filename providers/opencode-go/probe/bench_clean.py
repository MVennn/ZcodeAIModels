#!/usr/bin/env python3
"""Clean serial benchmark: 3 samples per model, TTFT + throughput."""
import json, os, statistics, time, urllib.error, urllib.request

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
FINALISTS = [
    ("beam-free", "chat"),
    ("glm-5.3-flash", "chat"),
    ("minimax-m3", "chat"),
    ("claude-haiku-5-5", "messages"),
    ("space-bunny", "chat"),
    ("qwen3.8-flash", "chat"),
    ("deepseek-v4.1-flash", "chat"),
    ("mimo-v2.5-pro", "chat"),
    ("gpt-5.6-luna", "responses"),
    ("gpt-6-luna", "responses"),
    ("hy3", "chat"),
    ("longcat-2.0", "chat"),
    ("mimo-v2.5", "chat"),
    ("mimo-v2.6-flash", "chat"),
    ("qwen3.7-plus", "messages"),
    ("longcat-2.5-preview-free", "chat"),
]

PROMPT = ("Write a Python function `merge_intervals(intervals)` that merges "
          "overlapping intervals and returns the sorted result. Include a docstring. "
          "Code only, no explanation.")

SAMPLES = 3

def stream_call(mid, proto, max_tokens=400):
    if proto == "chat":
        url = BASE + "/chat/completions"
        hdr = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
               "User-Agent": "zcode-bench/1.0", "x-opencode-session": f"sb-{mid}",
               "Accept": "text/event-stream"}
        body = {"model": mid, "messages": [{"role": "user", "content": PROMPT}],
                "max_tokens": max_tokens, "stream": True, "temperature": 0}
    elif proto == "messages":
        url = BASE + "/messages"
        hdr = {"x-api-key": _key(), "anthropic-version": "2023-06-01",
               "Content-Type": "application/json", "User-Agent": "zcode-bench/1.0",
               "x-opencode-session": f"sb-{mid}", "Accept": "text/event-stream"}
        body = {"model": mid, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": PROMPT}], "stream": True}
    else:
        url = BASE + "/responses"
        hdr = {"Authorization": f"Bearer {_key()}", "Content-Type": "application/json",
               "User-Agent": "zcode-bench/1.0", "x-opencode-session": f"sb-{mid}",
               "Accept": "text/event-stream"}
        body = {"model": mid, "input": PROMPT, "max_output_tokens": max_tokens,
                "stream": True}

    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=hdr)
    t0 = time.time()
    first = None
    text = ""
    out_tok = None
    prompt_tok = None
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload in ("[DONE]", ""):
                    continue
                try:
                    j = json.loads(payload)
                except Exception:
                    continue
                u = j.get("usage") or (j.get("message") or {}).get("usage")
                if u:
                    out_tok = u.get("completion_tokens") or u.get("output_tokens") or out_tok
                    prompt_tok = u.get("prompt_tokens") or u.get("input_tokens") or prompt_tok
                # content deltas
                frag = ""
                if j.get("choices"):
                    d = j["choices"][0].get("delta") or {}
                    frag = d.get("content") or ""
                elif j.get("type") == "content_block_delta":
                    frag = (j.get("delta") or {}).get("text") or ""
                elif j.get("type") == "response.output_text.delta":
                    frag = j.get("delta") or ""
                if frag:
                    if first is None:
                        first = time.time() - t0
                    text += frag
    except urllib.error.HTTPError as e:
        return {"err": f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:160]}"}
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"[:160]}
    total = time.time() - t0
    if first is None:
        first = total
    return {"ttft": round(first*1000), "total": round(total*1000),
            "out_tok": out_tok, "prompt_tok": prompt_tok,
            "tok_s": round((out_tok or 0)/max(total-first, 0.001), 1),
            "chars": len(text)}

results = {}
for mid, proto in FINALISTS:
    runs = []
    for i in range(SAMPLES):
        r = stream_call(mid, proto)
        runs.append(r)
        if "err" in r:
            print(f"  {mid} sample{i+1}: ERR {r['err']}", flush=True)
    ok = [r for r in runs if "err" not in r]
    if not ok:
        results[f"{mid}|{proto}"] = {"model": mid, "proto": proto, "error": runs[0]["err"]}
        print(f"{mid:28s} [{proto:8s}] ALL FAILED: {runs[0]['err']}", flush=True)
        continue
    rec = {
        "model": mid, "proto": proto, "samples": len(ok),
        "ttft_ms": round(statistics.median(r["ttft"] for r in ok)),
        "total_ms": round(statistics.median(r["total"] for r in ok)),
        "tok_s": round(statistics.median(r["tok_s"] for r in ok), 1),
        "out_tok": round(statistics.median(r["out_tok"] or 0 for r in ok)),
        "chars": round(statistics.median(r["chars"] for r in ok)),
    }
    results[f"{mid}|{proto}"] = rec
    print(f"{mid:28s} [{proto:8s}] ttft={rec['ttft_ms']:6d}ms total={rec['total_ms']:6d}ms "
          f"{rec['tok_s']:5.1f} tok/s out={rec['out_tok']:4d}tok chars={rec['chars']:5d}", flush=True)

with open("bench_clean.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("\nSaved bench_clean.json")
