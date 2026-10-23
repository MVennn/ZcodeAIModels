"""Smoke test for the live zgate endpoint.

Picks one cheap model per channel (and one bridged model per protocol) from the
live alias map, so the test keeps working after model reclassification.

    python gateways/zgate/smoke_test.py
    ZGATE_BASE=http://127.0.0.1:7871/v1 python gateways/zgate/smoke_test.py
    UNIFIED_MODEL_MAP=/path/to/model-alias-map.json python gateways/zgate/smoke_test.py

Costs a few tokens per run; keep max_tokens small.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("ZGATE_BASE", "http://127.0.0.1:7871/v1")
MAP_PATH = os.environ.get(
    "UNIFIED_MODEL_MAP",
    str(Path.home() / ".zcode" / "v2" / "model-alias-map.json"),
)


def load_cases():
    """Return [(label, model, stream)] built from the alias map."""
    try:
        data = json.loads(Path(MAP_PATH).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"读不到 alias map: {MAP_PATH} ({exc})")
    models = data.get("models") or {}
    if not models:
        raise SystemExit(f"alias map 里没有 models: {MAP_PATH}")

    cases = []
    for channel, label in (("OC", "OC chat"), ("WB", "WB chat"), ("QD", "QD chat")):
        rows = [
            (name, target)
            for name, target in models.items()
            if target.get("channel") == channel and (target.get("protocol") or "chat") == "chat"
        ]
        if not rows:
            continue
        # Try the cheapest few: a cooling model must not fail the whole smoke.
        rows.sort(key=lambda row: row[1].get("price") or 0)
        cases.append((label, [name for name, _ in rows[:3]], False))

    for protocol, label in (("messages", "bridged messages"), ("responses", "bridged responses")):
        rows = [
            (name, target)
            for name, target in models.items()
            if (target.get("protocol") or "chat") == protocol
        ]
        if not rows:
            continue
        rows.sort(key=lambda row: row[1].get("price") or 0)
        cases.append((label, [name for name, _ in rows[:2]], False))

    stream_source = next((c for c in cases if c[0] == "OC chat"), None) or (cases[0] if cases else None)
    if stream_source:
        cases.append(("stream", stream_source[1][:1], True))
    return cases


def post(model, stream):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "max_tokens": 16,
        "stream": stream,
    }
    req = urllib.request.Request(
        BASE + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), ""


def check(stream, ctype, text):
    if stream:
        if not ctype.startswith("text/event-stream"):
            return f"content-type 不是 SSE: {ctype}"
        if not text.rstrip().endswith("[DONE]"):
            return "SSE 没有以 data: [DONE] 收尾"
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return f"响应不是 JSON: {text[:120]}"
    if obj.get("object") != "chat.completion":
        return f"object 不是 chat.completion: {obj.get('object')}"
    choices = obj.get("choices") or []
    if not choices or "message" not in choices[0]:
        return "choices/message 缺失"
    return None


def main():
    cases = load_cases()
    failures = 0
    for label, candidates, stream in cases:
        if isinstance(candidates, str):
            candidates = [candidates]
        problem = None
        for model in candidates:
            status, text, ctype = post(model, stream)
            problem = None if status == 200 else f"HTTP {status}: {text[:160]}"
            if problem is None:
                problem = check(stream, ctype, text)
            if problem is None:
                print(f"[PASS] {label} ({model})")
                break
            print(f"[skip] {label} ({model}): {problem}")
        else:
            failures += 1
            print(f"[FAIL] {label}: 候选都不可用")
    print(f"\n{len(cases) - failures}/{len(cases)} 通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
