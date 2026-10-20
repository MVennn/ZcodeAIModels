#!/usr/bin/env python3
r"""Probe WorkBuddy gateway models with the EXACT body ZCode will send.

ZCode's builtin `modelConfigRules.modelApiRules` inject extra thinking fields
into every `openai-chat-completions` request (resources/config/provider/
zcode-builtin.json):

  idx 2  (.*)                     -> thinking + enable_thinking + reasoning_effort + reasoning
  idx 37 (.*deepseek-v4-flash.*)  -> thinking + reasoning_effort
  idx 39 (.*deepseek-v4-pro.*)    -> thinking + reasoning_effort
  idx 63 (.*deepseek-flash.*)     -> thinking + reasoning_effort
  idx 67 (.*deepseek-v4[.-]1-flash.*) -> thinking + reasoning_effort
  idx 30 (.*kimi-k2\.7-code.*)    -> thinking
  idx 33 (.*kimi-k2\.6.*)         -> thinking
  idx 35 (.*kimi-k2\.5.*)         -> thinking
  idx 55 (.*mimo-v2\.5.*)         -> thinking
  idx 57 (.*mimo-v2\.5-pro.*)     -> thinking
  idx 59 (.*mimo-v2-flash.*)      -> thinking

The gateway forwards those fields verbatim upstream (it only rewrites
reasoning_effort for models it knows), so a model that rejects one of them
400s in ZCode while a plain curl works. This probe replays the body ZCode
would send, then retries with slimmer variants to find a working shape.

Writes a resumable JSON cache: model id -> {status, variant, http, detail}.

Status:
    ok        - HTTP 200 with the primary (ZCode-native) body
    fallback  - primary body failed, a slimmer body worked (map override needed)
    blocked   - upstream says the account type may not use this model
    unavailable - model not available upstream
    rate_limited - transient 429 / no_healthy_account
    error     - anything else

Usage:
    python workbuddy_probe_zcode.py --sleep 20
    python workbuddy_probe_zcode.py --only cn: --sleep 12
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY_BASE = os.environ.get("WB_GATEWAY_BASE", "http://127.0.0.1:7863")
GATEWAY_KEY = os.environ.get("WB_GATEWAY_KEY", "")
HERE = Path(__file__).parent
CACHE_DIR = HERE / "cache"
# 活数据（价格表 / 探测结果）统一放 cache/；可用环境变量覆盖
STATUS_FILE = Path(
    os.environ.get(
        "WB_ZCODE_PROBE_FILE",
        CACHE_DIR / "wb_zcode_probe.json",
    )
)
PRICING_FILE = Path(
    os.environ.get("WB_PRICING_FILE", CACHE_DIR / "wb_pricing.json")
)

EFFECTIVE_BODY_SCRIPT = HERE / "zcode_effective_body.js"

# Cache of model id -> ZCode's effective thinking body, computed by replaying
# the engine's own rule resolution (zcode_effective_body.js).
_EFFECTIVE: dict[str, dict] = {}


def load_effective_bodies(ids: list[str], max_tokens: int = 24) -> dict[str, dict]:
    """Ask Node for the exact body ZCode sends for each model id.

    max_tokens is passed through so that the `maxOutputTokens` scope variable in
    ZCode's map expressions resolves to *our* request's value — upstream applies
    `optionSpecs.maxOutputTokens.map` too, and that rule reads that variable.
    """
    global _EFFECTIVE
    missing = [i for i in ids if i not in _EFFECTIVE]
    if missing:
        try:
            out = subprocess.run(
                [
                    "node", str(EFFECTIVE_BODY_SCRIPT),
                    "--max-output-tokens", str(max_tokens),
                    *missing,
                ],
                capture_output=True, text=True, timeout=60, check=True,
            )
            _EFFECTIVE.update(json.loads(out.stdout))
        except Exception as e:  # node missing / script failed
            print(f"warning: cannot compute effective bodies: {e}", file=sys.stderr)
            for i in missing:
                _EFFECTIVE[i] = {"body": {}, "values": None, "level": "enabled"}
    return _EFFECTIVE


def zcode_body(model: str, max_tokens: int = 24) -> dict:
    """Build the request body ZCode would send for this model."""
    eff = load_effective_bodies([model], max_tokens).get(model, {})
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_completion_tokens": max_tokens,
        "stream": False,
    }
    for key, value in (eff.get("body") or {}).items():
        body[key] = value
    return body


def body_kind(model: str) -> str:
    """Short label for the shape ZCode uses (for logging)."""
    eff = load_effective_bodies([model]).get(model, {})
    keys = set((eff.get("body") or {}).keys())
    if "enable_thinking" in keys and "reasoning" in keys:
        return "generic"
    if "reasoning_effort" in keys:
        return "deepseek"
    if "thinking" in keys:
        return "thinking"
    return "none"


FALLBACK_ORDER = ["deepseek", "thinking", "bare"]


def build_bare(model: str) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_completion_tokens": 24,
        "stream": False,
    }


def build_body(model: str, kind: str, effort: str = "high") -> dict:
    """Slimmer bodies tried when ZCode's native body is rejected."""
    body: dict = {
        "model": model,
        "messages": [{"role": "user", "content": "ok"}],
        "max_completion_tokens": 24,
        "stream": False,
    }
    if kind == "deepseek":
        body["thinking"] = {"type": "enabled"}
        body["reasoning_effort"] = effort
    elif kind == "thinking":
        body["thinking"] = {"type": "enabled"}
    return body


def http_json(payload: dict, timeout: int = 150) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    headers = {
        "Authorization": f"Bearer {GATEWAY_KEY}",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(
        GATEWAY_BASE.rstrip("/") + "/v1/chat/completions", data=data, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw)
            except Exception:
                return resp.status, {"raw": raw[:400]}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"raw": e.read().decode("utf-8", "replace")[:400]}
    except Exception as e:
        return 0, {"exception": str(e)}


def classify(code: int, body: dict) -> tuple[str, str]:
    text = json.dumps(body, ensure_ascii=False)
    if code == 200:
        return "ok", ""
    if "not allowed for user type" in text:
        return "blocked", "not allowed for user type"
    if "service info not found" in text or "model_unavailable" in text or "not available" in text:
        return "unavailable", "model unavailable"
    if code == 429 or "no_healthy_account" in text or "rate limit" in text or "rate_limit" in text:
        return "rate_limited", text[:220]
    return "error", f"HTTP {code}: {text[:220]}"


def load_pricing() -> dict[str, dict]:
    if not PRICING_FILE.exists():
        return {}
    try:
        return {m["id"]: m for m in json.loads(PRICING_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleep", type=float, default=20.0, help="seconds between models")
    ap.add_argument("--only", default="", help="only ids containing this substring")
    ap.add_argument("--max-rate", type=float, default=None,
                    help="skip models whose effective credit rate exceeds this")
    ap.add_argument("--force", action="store_true", help="re-probe finished entries")
    ap.add_argument("--dry-run", action="store_true", help="list the plan and exit")
    args = ap.parse_args()

    pricing = load_pricing()
    if not pricing:
        print("wb_pricing.json missing - fetch pricing first", file=sys.stderr)
        return 1

    cache: dict[str, dict] = {}
    if STATUS_FILE.exists():
        try:
            cache = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    plan = []
    for mid, info in pricing.items():
        if args.only and args.only not in mid:
            continue
        rate = info.get("eff_rate")
        if args.max_rate is not None and rate is not None and rate > args.max_rate:
            continue
        plan.append(mid)

    pending = [
        m for m in plan
        if args.force or m not in cache or cache[m].get("status") not in ("ok", "fallback", "blocked", "unavailable")
    ]
    plan.sort(key=lambda m: (pricing[m].get("eff_rate") if pricing[m].get("eff_rate") is not None else 999, m))
    pending.sort(key=lambda m: (pricing[m].get("eff_rate") if pricing[m].get("eff_rate") is not None else 999, m))

    load_effective_bodies(plan)
    print(f"plan={len(plan)} cached={len(cache)} pending={len(pending)} -> {STATUS_FILE}")
    for m in plan:
        info = pricing[m]
        print(f"  {str(info.get('eff_rate')):>6}  {m:30s} body={body_kind(m):8s} "
              f"cached={cache.get(m, {}).get('status', '-')}")
    if args.dry_run:
        return 0

    for i, mid in enumerate(pending, 1):
        kind = body_kind(mid)
        code, resp = http_json(zcode_body(mid))
        st, detail = classify(code, resp)
        used = "zcode"
        if st == "error" or code == 0:
            # ZCode's native body was rejected - find a slimmer one that works.
            for alt in FALLBACK_ORDER:
                c2, r2 = http_json(build_body(mid, alt) if alt != "bare" else build_bare(mid))
                st2, det2 = classify(c2, r2)
                if st2 == "ok":
                    st, detail, used = "fallback", f"zcode body rejected; '{alt}' works", alt
                    break
                if st2 == "blocked":
                    st, detail, used = "blocked", det2, alt
                    break
        cache[mid] = {
            "status": st,
            "variant": used,
            "zcode_body": kind,
            "http": code,
            "detail": detail,
            "rate": pricing[mid].get("eff_rate"),
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        STATUS_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{i}/{len(pending)}] {mid:30s} {st:12s} body={kind:8s}->{used:8s} {detail[:70]}", flush=True)
        if i < len(pending):
            time.sleep(args.sleep)

    counts: dict[str, int] = {}
    for rec in cache.values():
        counts[rec["status"]] = counts.get(rec["status"], 0) + 1
    print("summary:", json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
