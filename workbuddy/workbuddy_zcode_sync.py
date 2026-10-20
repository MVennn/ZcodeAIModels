#!/usr/bin/env python3
"""Sync WorkBuddy2API gateway models into ZCode as tiered personal providers.

The gateway bills by a credit multiplier ("倍率"): smaller = cheaper. Models are
split into three providers by that multiplier, each ordered cheapest-first:

    workbuddy-free   "免代"   rate == 0        (限时免费 / Free now / 独家限免)
    workbuddy-low    "低代"   0 < rate <= 0.30
    workbuddy-high   "高代"   rate > 0.30 and <= --max-rate (default 0.80)

The ceiling keeps every listed model priced in the same ballpark as
deepseek-v4.1-flash (x0.11 list / x0.00 global promo) instead of the x1.3-x6.7
premium tier.

Data sources
    pricing : GET /panel/api/models   (list rate `credits`, effective `promo_credits`)
    probe   : workbuddy_probe_zcode.py cache (availability with ZCode's real body)

Usage
    python workbuddy_zcode_sync.py                 # dry run (default)
    python workbuddy_zcode_sync.py --apply         # backup + write config
    python workbuddy_zcode_sync.py --max-rate 1.2  # widen the ceiling

Notes
    * ZCode hot-reloads provider_config.json (~1s polling), so no restart is
      normally required. Avoid editing provider settings in the UI while this
      script writes.
    * Routing aliases (auto / primary / deep / fast / balanced / enhance) are
      excluded: they resolve to another model and have no own price.
    * Models the probe marked blocked (upstream: "not allowed for user type")
      are excluded - that account type cannot use them at all.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent

PROVIDER_IDS = {
    "free": "workbuddy-free",
    "low": "workbuddy-low",
    "high": "workbuddy-high",
}
PROVIDER_NAMES = {
    "free": "免代",
    "low": "低代",
    "high": "高代",
}
# Tier boundaries on the effective credit multiplier.
FREE_MAX = 0.0
LOW_MAX = 0.30
DEFAULT_MAX_RATE = 0.80

GROUP = "standard-personal"
GATEWAY_BASE = os.environ.get("WB_GATEWAY_BASE", "http://127.0.0.1:7863")
GATEWAY_KEY = os.environ.get("WB_GATEWAY_KEY", "")
CONFIG_FILE = Path(
    os.environ.get(
        "ZCODE_PERSONAL_PROVIDER_CONFIG_FILE",
        Path.home() / ".zcode" / "v2" / "provider_config.json",
    )
)
CACHE_DIR = HERE / "cache"
# 活数据（价格表 / 探测结果）统一放 cache/；可用环境变量覆盖
PRICING_FILE = Path(os.environ.get("WB_PRICING_FILE", CACHE_DIR / "wb_pricing.json"))
PROBE_FILE = Path(os.environ.get("WB_ZCODE_PROBE_FILE", CACHE_DIR / "wb_zcode_probe.json"))

# Pure routing aliases: no own price, resolve to another model underneath.
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


def rate_of(model: dict) -> float | None:
    """Effective credit multiplier; None when the upstream quotes no price."""
    for key in ("promo_credits", "credits"):
        raw = str(model.get(key) or "").strip()
        if not raw:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)", raw)
        if m:
            return float(m.group())
    return None


def fetch_models(base: str, key: str) -> list[dict]:
    req = urllib.request.Request(base.rstrip("/") + "/panel/api/models")
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=25) as resp:
        payload = json.load(resp)
    models = payload.get("models") or []
    if not models:
        raise RuntimeError("gateway returned an empty model list")
    return models


def load_pricing_file() -> dict[str, dict]:
    if not PRICING_FILE.exists():
        return {}
    try:
        return {m["id"]: m for m in json.loads(PRICING_FILE.read_text(encoding="utf-8"))}
    except Exception:
        return {}


def load_probe() -> dict[str, dict]:
    if not PROBE_FILE.exists():
        return {}
    try:
        return json.loads(PROBE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def tier_of(rate: float | None) -> str | None:
    if rate is None:
        return None
    if rate <= FREE_MAX:
        return "free"
    if rate <= LOW_MAX:
        return "low"
    return "high"


def deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base (override wins), recursively for dicts."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def build_model_rule(provider_id: str, model: dict, probe_rec: dict | None) -> dict:
    cfg: dict = {"enabled": True}
    ctx = int(model.get("context_length") or model.get("max_allowed_size") or 0)
    out = int(model.get("max_output_tokens") or 0)
    if ctx > 0 and out > ctx:
        out = ctx
    props: dict = {}
    if ctx > 0:
        props["contextWindow"] = ctx
    if model.get("supports_tool_call") is not None:
        props["supportsToolCall"] = bool(model["supports_tool_call"])
    if model.get("supports_images") is not None:
        props["inputFormat"] = {"supportsImage": bool(model["supports_images"])}
    if props:
        cfg["properties"] = props
    if out > 0:
        cfg["optionSpecs"] = {"maxOutputTokens": {"max": out}}

    # The probe found that ZCode's native body (thinking + reasoning_effort +
    # enable_thinking + reasoning) is rejected by this model; a slimmer body
    # works. Override reasoningLevel.map so ZCode stops sending the rejected
    # fields.
    if probe_rec and probe_rec.get("status") == "fallback":
        variant = probe_rec.get("variant")
        if variant == "deepseek":
            cfg.setdefault("optionSpecs", {})["reasoningLevel"] = {
                "map": '{"thinking":{"type":"enabled"},"reasoning_effort":reasoningLevel}'
            }
        elif variant == "thinking":
            cfg.setdefault("optionSpecs", {})["reasoningLevel"] = {
                "map": '{"thinking":{"type":"enabled"}}'
            }
        elif variant == "bare":
            cfg.setdefault("optionSpecs", {})["reasoningLevel"] = {"map": "{}"}
    return {"providerId": provider_id, "modelId": str(model["id"]), "config": cfg}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write config (default dry run)")
    ap.add_argument("--api-key", default=GATEWAY_KEY, help="gateway api_key")
    ap.add_argument("--max-rate", type=float, default=DEFAULT_MAX_RATE,
                    help="highest credit multiplier to include (default 0.80)")
    ap.add_argument("--include-aliases", action="store_true",
                    help="also include routing aliases (auto/primary/deep/fast/balanced/enhance)")
    ap.add_argument("--include-blocked", action="store_true",
                    help="keep models the probe marked blocked/unavailable")
    ap.add_argument("--pricing-file", default=str(PRICING_FILE))
    ap.add_argument("--probe-file", default=str(PROBE_FILE))
    args = ap.parse_args()

    pricing = load_pricing_file()
    probe = load_probe()

    models = fetch_models(GATEWAY_BASE, args.api_key)
    by_id = {str(m["id"]): m for m in models}

    # Prefer the pricing cache (it carries effective/promo fields); fall back to
    # the live payload for ids the cache lacks.
    merged: list[dict] = []
    for mid, m in by_id.items():
        rec = dict(pricing.get(mid) or {})
        rec.update({k: v for k, v in m.items() if v not in (None, "", [], {})})
        rec["id"] = mid
        rec["_rate"] = rate_of(rec)
        merged.append(rec)

    excluded: list[tuple[str, str]] = []
    tiers: dict[str, list[dict]] = {"free": [], "low": [], "high": []}

    for rec in sorted(merged, key=lambda r: (r["_rate"] if r["_rate"] is not None else 999, r["id"])):
        mid = str(rec["id"])
        rate = rec["_rate"]
        if mid in ALIAS_IDS and not args.include_aliases:
            excluded.append((mid, "routing alias"))
            continue
        if rate is None:
            excluded.append((mid, "no published rate"))
            continue
        if rate > args.max_rate:
            excluded.append((mid, f"rate {rate} > {args.max_rate}"))
            continue
        pstat = (probe.get(mid) or {}).get("status")
        if not args.include_blocked:
            if pstat in ("blocked", "unavailable"):
                excluded.append((mid, pstat))
                continue
            if pstat in ("error", "rate_limited"):
                excluded.append((mid, pstat or "unprobed"))
                continue
        tier = tier_of(rate)
        if tier is None:
            excluded.append((mid, "unclassified"))
            continue
        tiers[tier].append(rec)

    total = sum(len(v) for v in tiers.values())
    if total == 0:
        print("no models selected", file=sys.stderr)
        return 1

    # ---- build config -----------------------------------------------------
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    root = config.setdefault("config", {})
    provider_rules = root.setdefault("providerConfigRules", {}).setdefault("providerRules", [])
    model_rules_root = root.setdefault("modelConfigRules", {})
    model_rules = model_rules_root.setdefault("providerModelRules", [])
    model_rules_root.setdefault("manualProviderModelRules", [])

    existing = {
        (r.get("providerId"), r.get("modelId")): r
        for r in model_rules
        if r.get("providerId") in PROVIDER_IDS.values()
    }

    new_provider_rules = []
    new_model_rules = []
    for tier in ("free", "low", "high"):
        entries = tiers[tier]
        if not entries:
            continue
        pid = PROVIDER_IDS[tier]
        ids = [str(e["id"]) for e in entries]
        provider = {
            "providerId": pid,
            "providerName": PROVIDER_NAMES[tier],
            "config": {
                "group": GROUP,
                "access": {"type": "api-key", "apiKey": args.api_key},
                "api": {
                    "type": "openai-chat-completions",
                    "baseUrl": GATEWAY_BASE.rstrip("/") + "/v1",
                },
                "personalModelIds": ids,
                "modelOrder": ids,
            },
        }
        new_provider_rules.append(provider)
        for rec in entries:
            rule = build_model_rule(pid, rec, probe.get(str(rec["id"])))
            old = existing.get((pid, rule["modelId"]))
            if old and isinstance(old.get("config"), dict):
                rule["config"] = deep_merge(old["config"], rule["config"])
                rule["config"]["enabled"] = True
            new_model_rules.append(rule)

    provider_rules[:] = [
        p for p in provider_rules if p.get("providerId") not in PROVIDER_IDS.values()
    ] + new_provider_rules
    model_rules[:] = [
        r for r in model_rules if r.get("providerId") not in PROVIDER_IDS.values()
    ] + new_model_rules

    order = root.setdefault("providerOrder", [])
    for tier in ("free", "low", "high"):
        pid = PROVIDER_IDS[tier]
        if pid not in order:
            order.append(pid)

    # ---- report -----------------------------------------------------------
    print(f"config      : {CONFIG_FILE}")
    print(f"baseUrl     : {GATEWAY_BASE.rstrip('/')}/v1")
    print(f"max rate    : <= {args.max_rate}")
    print(f"selected    : {total} models")
    print(f"excluded    : {len(excluded)}")
    for mid, why in excluded:
        print(f"  - {mid:38s} {why}")
    print()
    for tier in ("free", "low", "high"):
        entries = tiers[tier]
        if not entries:
            continue
        print(f"== {PROVIDER_NAMES[tier]} ({PROVIDER_IDS[tier]}) - {len(entries)} models ==")
        for rec in entries:
            mid = str(rec["id"])
            pstat = (probe.get(mid) or {}).get("status", "-")
            variant = (probe.get(mid) or {}).get("variant", "")
            flag = "" if pstat == "ok" else f"  [{pstat}/{variant}]"
            print(f"  x{rec['_rate']:<5.2f} {mid:38s}{flag}")
        print()

    if not args.apply:
        print("[dry-run] no changes written; pass --apply to write")
        return 0

    backup = CONFIG_FILE.with_name(
        CONFIG_FILE.name + ".bak-wbproxy-" + time.strftime("%Y%m%d-%H%M%S")
    )
    shutil.copy2(CONFIG_FILE, backup)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp-wbproxy")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    print(f"backup      : {backup.name}")
    print(f"written     : {CONFIG_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
