#!/usr/bin/env python3
"""Probe which WorkBuddy2API gateway models the current account pool can use.

Writes a resumable JSON cache mapping model id -> {status, http, detail, checked_at}.
Statuses:
    ok           - HTTP 200
    blocked      - explicit "not allowed for user type" from upstream
    unavailable  - explicit "service info not found" / model_unavailable
    rate_limited - 429 / no_healthy_account; retried on the next run
    error        - other failure (kept for inspection; retried next run)

Usage:
    python workbuddy_probe_models.py                 # probe all, 12s apart
    python workbuddy_probe_models.py --sleep 15
    python workbuddy_probe_models.py --only cn:
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY_BASE = os.environ.get("WB_GATEWAY_BASE", "http://127.0.0.1:7863")
GATEWAY_KEY = os.environ.get("WB_GATEWAY_KEY", "")
STATUS_FILE = Path(
    os.environ.get(
        "WB_MODEL_STATUS_FILE",
        Path(__file__).with_name("wb_model_status.json"),
    )
)
ALIAS_IDS = {
    "cn:auto",
    "global:auto-chat",
    "global:default-model",
    "global:primary-model",
    "global:deep-model",
    "global:fast-model",
    "global:balanced-model",
    "global:enhance-1.0",
}
TERMINAL = {"ok", "blocked", "unavailable"}


def http_json(url: str, payload: dict | None = None, timeout: int = 120) -> tuple[int, dict]:
    data = None
    headers = {"Authorization": f"Bearer {GATEWAY_KEY}", "Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = {"raw": e.read().decode("utf-8", "replace")[:500]}
        return e.code, body
    except Exception as e:  # network error / timeout
        return 0, {"exception": str(e)}


def classify(code: int, body: dict) -> tuple[str, str]:
    err = body.get("error") if isinstance(body, dict) else None
    text = json.dumps(err or body, ensure_ascii=False)
    if code == 200:
        return "ok", ""
    if "not allowed for user type" in text:
        return "blocked", "not allowed for user type"
    if "service info not found" in text or "model_unavailable" in text:
        return "unavailable", "model unavailable"
    if code == 429 or "no_healthy_account" in text or "rate limit" in text:
        return "rate_limited", text[:200]
    return "error", f"HTTP {code}: {text[:200]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sleep", type=float, default=12.0, help="seconds between requests")
    parser.add_argument("--only", default="", help="only ids containing this substring")
    parser.add_argument("--force", action="store_true", help="re-probe terminal results too")
    args = parser.parse_args()

    status, payload = http_json(GATEWAY_BASE.rstrip("/") + "/panel/api/models", timeout=20)
    if status != 200:
        print(f"failed to fetch model list: HTTP {status} {payload}", file=sys.stderr)
        return 1
    models = [m for m in payload.get("models", []) if str(m.get("id")) not in ALIAS_IDS]
    if args.only:
        models = [m for m in models if args.only in str(m.get("id"))]

    cache: dict[str, dict] = {}
    if STATUS_FILE.exists():
        try:
            cache = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    pending = []
    for m in models:
        mid = str(m["id"])
        old = cache.get(mid)
        if args.force or not old or old.get("status") not in TERMINAL:
            pending.append(mid)

    print(f"models={len(models)} cached={len(cache)} pending={len(pending)} -> {STATUS_FILE}")
    for i, mid in enumerate(pending, 1):
        code, body = http_json(
            GATEWAY_BASE.rstrip("/") + "/v1/chat/completions",
            {
                "model": mid,
                "messages": [{"role": "user", "content": "ok"}],
                "max_tokens": 24,
                "stream": False,
            },
        )
        st, detail = classify(code, body)
        cache[mid] = {
            "status": st,
            "http": code,
            "detail": detail,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        STATUS_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{i}/{len(pending)}] {mid:38s} {st:12s} http={code} {detail[:80]}")
        if i < len(pending):
            time.sleep(args.sleep)

    counts: dict[str, int] = {}
    for rec in cache.values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    print("summary:", json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
