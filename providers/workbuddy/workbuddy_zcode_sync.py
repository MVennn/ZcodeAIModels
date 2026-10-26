#!/usr/bin/env python3
"""Sync WorkBuddy2API gateway models into ZCode as tiered personal providers.

Scope
-----
**This is the WorkBuddy2API adapter, not a generic framework.**  The tiering
below is driven by the gateway's credit multiplier, which is WorkBuddy-specific.
To onboard a different provider, write a sibling script with the same shape:
read your own normalized pricing table, apply your own tier thresholds, and
write the same three places of `provider_config.json` (see docs/MODEL-PROVIDERS.md
§1).  The ZCode-side write path itself is provider-neutral.

The gateway bills by a credit multiplier ("倍率"): smaller = cheaper. Models are
split into four providers. The first three are rate tiers; the fourth is a
value tier for models whose benchmark score per price is below the deepseek
anchor (see BACKUP_MODEL_IDS and docs/BENCHMARKS.md §5.4). The anchor price is
the daily driver `cn:deepseek-v4.1-flash` at x0.11; anything above x0.30
(~2.7x) is treated as too expensive and excluded ("贵不加"). Inside every
provider the list is ordered CN-first, then grouped by vendor (company),
cheapest-first within each vendor; the pinned model goes first:

    workbuddy-free   "免代"   rate == 0        (限时免费 / Free now / 独家限免)
    workbuddy-low    "低代"   0 < rate <= 0.16 (主力价位，只收这一档)
    workbuddy-high   "高代"   0.16 < rate <= --max-rate (default 0.30)
    workbuddy-backup "备用"   性价比 < 1（以 deepseek-v4.1-flash 为 100 基准）

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
    python workbuddy_zcode_sync.py --reorder-only --apply
                                                   # only fix model/provider order

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
    "backup": "workbuddy-backup",
}
PROVIDER_NAMES = {
    "free": "免代",
    "low": "低代",
    "high": "高代",
    "backup": "备用",
}
# Tier boundaries on the effective credit multiplier. Anchor = the pin
# cn:deepseek-v4.1-flash at x0.11; users only accept that price band, so
# 低代 caps at ~1.5x the anchor, 高代 absorbs the 1.5x-2.7x leftovers, and
# anything beyond the ceiling is excluded instead of collected.
FREE_MAX = 0.0
LOW_MAX = 0.16
DEFAULT_MAX_RATE = 0.30

# Value tier: benchmark score per price below the deepseek anchor.
# See docs/BENCHMARKS.md §5.4; new models must be added by hand.
BACKUP_MODEL_IDS = {"cn:deepseek-v4-flash", "cn:minimax-m3"}

# User-facing order inside each tier provider:
#   1. pinned models first (the daily driver)
#   2. cn:* before global:*
#   3. inside a region, group by vendor in VENDOR_ORDER
#   4. inside a vendor, cheapest rate first, then id
PINNED_MODEL_IDS = ("deepseek-v4.1-flash", "cn:deepseek-v4.1-flash")
VENDOR_ORDER = (
    "deepseek",   # 深度求索
    "zhipu",      # 智谱 GLM
    "minimax",    # MiniMax
    "kimi",       # 月之暗面
    "mimo",       # 小米 MiMo
    "hunyuan",    # 腾讯混元
    "stepfun",    # 阶跃星辰
    "other",      # 匿名 / 未标注厂商
)
# Reverse-proxy providers: 低代 first (it holds the pinned daily driver), then
# 免代, 高代, and 备用 last.  ZCode renders personal providers in providerOrder.
TIER_DISPLAY_ORDER = ("low", "free", "high", "backup")

# Unified mode (default): merge WorkBuddy models into the OpenCode chat tier
# providers instead of creating separate workbuddy-* providers. The merged
# providers point at tools/unified-router.js, which routes cn:/global: models
# to the gateway and everything else to OpenCode-Go.
MAIN_MODEL_IDS = {"cn:deepseek-v4.1-flash", "global:deepseek-v4.1-flash-sg"}
UNIFIED_TARGETS = {
    "main": "opencode-go-chat",
    "free": "opencode-go-chat-free",
    "low": "opencode-go-chat-fast",
    "high": "opencode-go-chat-slow",
    # 四组制：备用档并入高耗，不再单独建 opencode-go-chat-backup。
    "backup": "opencode-go-chat-slow",
}
ROUTER_BASE = os.environ.get("UNIFIED_ROUTER_BASE", "http://127.0.0.1:7871/v1")
UNIFIED_ORDER = (
    "opencode-go-chat",
    "opencode-go-chat-free",
    "opencode-go-chat-fast",
    "opencode-go-chat-slow",
)

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
    """Effective credit multiplier.

    Trust the normalized `eff_rate` / `list_rate` floats that
    `workbuddy_fetch_pricing.py` already extracted into `wb_pricing.json`
    (the sync's sole price input, per the module docstring). Fall back to
    re-parsing the raw `credits` / `promo_credits` strings only when those
    normalized fields are absent. This is what lets the free `-f` models
    (e.g. `cn:hy4-preview-f`, whose gateway `credits` is an empty string but
    whose normalized `eff_rate` is 0.0) be classified into the free tier
    instead of being dropped as "no published rate". Truly unpriced models
    (empty raw strings *and* no normalized rate) still return None; the probe
    gate then drops unavailable ones before tiering.
    """
    for key in ("eff_rate", "list_rate"):
        v = model.get(key)
        if isinstance(v, (int, float)):
            return float(v)
    for key in ("promo_credits", "credits"):
        raw = str(model.get(key) or "").strip()
        if not raw:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)", raw)
        if m:
            return float(m.group())
    return None


def vendor_of(model_id: str) -> str:
    """Group id by model company. The gateway's own `vendor` field is a
    one-letter pool code (e/f/i/j) that does not match the model brand
    (e.g. cn:glm-5.3-flash is vendor "f", cn:glm-5.3 is "e"), so classify by
    the model name instead."""
    name = model_id.split(":", 1)[-1].lower()
    if name.startswith("deepseek"):
        return "deepseek"
    if name.startswith("glm"):
        return "zhipu"
    if name.startswith("minimax"):
        return "minimax"
    if name.startswith("kimi"):
        return "kimi"
    if name.startswith("mimo"):
        return "mimo"
    if name.startswith("hy"):
        return "hunyuan"
    if name.startswith("step"):
        return "stepfun"
    return "other"


def model_sort_key(rec: dict) -> tuple:
    """Order used for both personalModelIds and modelOrder."""
    mid = str(rec["id"])
    rate = rec.get("_rate")
    return (
        0 if mid in PINNED_MODEL_IDS else 1,
        0 if mid.startswith("cn:") else 1,
        VENDOR_ORDER.index(vendor_of(mid)),
        rate if isinstance(rate, (int, float)) else 999.0,
        mid,
    )


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


def tier_of(rate: float | None, model_id: str | None = None) -> str | None:
    if model_id in BACKUP_MODEL_IDS:
        return "backup"
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


def reorder_provider_order(root: dict, active_ids: set[str]) -> None:
    """Keep the reverse-proxy providers contiguous, in display order.

    ZCode renders personal providers in `providerOrder` sequence, so this is
    what decides whether 低代 (holding the pinned daily driver) shows up first.
    """
    order = root.setdefault("providerOrder", [])
    wb_ids = [PROVIDER_IDS[t] for t in TIER_DISPLAY_ORDER]
    present = [pid for pid in wb_ids if pid in active_ids]
    insert_at = min((order.index(pid) for pid in wb_ids if pid in order),
                    default=len(order))
    order[:] = [pid for pid in order if pid not in PROVIDER_IDS.values()]
    order[insert_at:insert_at] = present


def write_config(config: dict) -> Path:
    backup = CONFIG_FILE.with_name(
        CONFIG_FILE.name + ".bak-wbproxy-" + time.strftime("%Y%m%d-%H%M%S")
    )
    shutil.copy2(CONFIG_FILE, backup)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp-wbproxy")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)
    return backup


def provider_rules_of(config: dict) -> list[dict]:
    root = config.setdefault("config", {})
    pcr = root.setdefault("providerConfigRules", {})
    return pcr.setdefault("providerRules", [])


def model_rules_of(config: dict) -> list[dict]:
    root = config.setdefault("config", {})
    mcr = root.setdefault("modelConfigRules", {})
    return mcr.setdefault("providerModelRules", [])


def ensure_provider(config: dict, tier: str, template_tier: str = "high") -> dict:
    """Clone the template tier provider under a new id/name; idempotent."""
    pid = PROVIDER_IDS[tier]
    rules = provider_rules_of(config)
    for r in rules:
        if r.get("providerId") == pid:
            r["providerName"] = PROVIDER_NAMES[tier]
            return r
    template_id = PROVIDER_IDS[template_tier]
    template = next((r for r in rules if r.get("providerId") == template_id), None)
    if template is None:
        raise RuntimeError("template provider not found: " + template_id)
    new = json.loads(json.dumps(template))
    new["providerId"] = pid
    new["providerName"] = PROVIDER_NAMES[tier]
    new["config"]["personalModelIds"] = []
    new["config"]["modelOrder"] = []
    rules.append(new)
    return new


def move_model(config: dict, model_id: str, target_pid: str) -> None:
    """Move a model out of every provider and into the target one."""
    for r in provider_rules_of(config):
        c = r.get("config", {})
        for key in ("personalModelIds", "modelOrder"):
            ids = c.get(key)
            if isinstance(ids, list) and model_id in ids:
                c[key] = [m for m in ids if m != model_id]
    target = next((r for r in provider_rules_of(config) if r.get("providerId") == target_pid), None)
    if target is None:
        raise RuntimeError("provider not found: " + target_pid)
    for key in ("personalModelIds", "modelOrder"):
        ids = target["config"].setdefault(key, [])
        if model_id not in ids:
            ids.append(model_id)
    for m in model_rules_of(config):
        if m.get("modelId") == model_id:
            m["providerId"] = target_pid
            break


def reclassify_backup(config: dict) -> list[str]:
    """Ensure workbuddy-backup exists and holds BACKUP_MODEL_IDS.
    Returns the list of models actually moved."""
    present = {
        mid for mid in BACKUP_MODEL_IDS
        if any(mid in (r.get("config", {}).get("personalModelIds") or [])
               for r in provider_rules_of(config))
    }
    if not present:
        return []
    ensure_provider(config, "backup", "high")
    moved: list[str] = []
    for mid in sorted(present):
        before = next(
            (r["providerId"] for r in provider_rules_of(config)
             if mid in (r.get("config", {}).get("personalModelIds") or [])),
            None,
        )
        move_model(config, mid, PROVIDER_IDS["backup"])
        if before != PROVIDER_IDS["backup"]:
            moved.append(mid)
    active = {r.get("providerId") for r in provider_rules_of(config)}
    reorder_provider_order(config["config"], active)
    return moved


def apply_unified(
    config: dict,
    tiers: dict[str, list[dict]],
    probe: dict[str, dict],
    live_ids: set[str],
    pricing_ids: set[str],
) -> tuple[int, list[str], list[str]]:
    """Merge WorkBuddy tiers into the OpenCode chat providers.

    The merged providers point at tools/unified-router.js, which routes
    cn:/global: models back to the WorkBuddy gateway and everything else to
    OpenCode-Go. Returns (entries merged, stale ids removed, uncertain ids
    kept). A stale id is either still in the live list but excluded (rate cap,
    blocked, ...) or absent from a complete live list. When the live list is
    shorter than the pricing snapshot, missing ids are only reported, because
    that usually means the gateway returned a partial list.
    """
    root = config.setdefault("config", {})
    provider_rules = provider_rules_of(config)
    by_id = {r.get("providerId"): r for r in provider_rules}
    model_rules = model_rules_of(config)
    existing = {(r.get("providerId"), r.get("modelId")): r for r in model_rules}
    rates = {
        str(rec["id"]): rec.get("_rate")
        for recs in tiers.values()
        for rec in recs
    }

    # Remove every WorkBuddy model from every target provider first, so a
    # re-run can move a model between tiers without leaving a duplicate.
    # Prefixed models no longer selected are dropped for good, unless the live
    # model list looks partial (then they are kept and reported).
    live_ids = {str(x) for x in live_ids}
    pricing_ids = {str(x) for x in pricing_ids}
    live_complete = bool(pricing_ids) and live_ids >= pricing_ids
    all_wb = {str(rec["id"]) for recs in tiers.values() for rec in recs}
    stale: set[str] = set()
    uncertain: set[str] = set()
    for target_pid in dict.fromkeys(UNIFIED_TARGETS.values()):
        target = by_id.get(target_pid)
        if target is None:
            continue
        ids = []
        for mid in (target["config"].get("personalModelIds") or []):
            mid_s = str(mid)
            if mid_s in all_wb:
                continue
            if mid_s.startswith(("cn:", "global:")):
                if mid_s in live_ids or live_complete:
                    stale.add(mid_s)
                else:
                    uncertain.add(mid_s)
                    ids.append(mid)  # 列表残缺，先原样保留
                continue
            ids.append(mid)
        target["config"]["personalModelIds"] = ids
        target["config"]["modelOrder"] = ids

    added = 0
    for tier, target_pid in UNIFIED_TARGETS.items():
        target = by_id.get(target_pid)
        if target is None:
            raise RuntimeError("target provider not found: " + target_pid)
        ids = list(target["config"].get("personalModelIds") or [])
        for rec in tiers[tier]:
            mid = str(rec["id"])
            if mid not in ids:
                ids.append(mid)
            rule = build_model_rule(target_pid, rec, probe.get(mid))
            old = existing.get((target_pid, mid))
            if old and isinstance(old.get("config"), dict):
                rule["config"] = deep_merge(old["config"], rule["config"])
                rule["config"]["enabled"] = True
            model_rules[:] = [r for r in model_rules if r.get("modelId") != mid]
            model_rules.append(rule)
            existing[(target_pid, mid)] = rule
            added += 1
        ids.sort(key=lambda mid: model_sort_key({"id": mid, "_rate": rates.get(mid)}))
        target["config"]["personalModelIds"] = ids
        target["config"]["modelOrder"] = ids
        target["config"].setdefault("api", {})["baseUrl"] = ROUTER_BASE

    provider_rules[:] = [
        r for r in provider_rules
        if not str(r.get("providerId", "")).startswith("workbuddy-")
    ]
    model_rules[:] = [
        r for r in model_rules
        if not str(r.get("providerId", "")).startswith("workbuddy-")
    ]
    if stale:
        targets = set(UNIFIED_TARGETS.values())
        model_rules[:] = [
            r for r in model_rules
            if not (r.get("modelId") in stale and r.get("providerId") in targets)
        ]
    order = root.setdefault("providerOrder", [])
    order[:] = [pid for pid in order if not str(pid).startswith("workbuddy-")]
    for pid in UNIFIED_ORDER:
        if pid not in order:
            order.append(pid)
    return added, sorted(stale), sorted(uncertain)


def reclassify_unified_backup(config: dict) -> list[str]:
    """Move BACKUP_MODEL_IDS into the merged OpenCode backup provider."""
    target_pid = UNIFIED_TARGETS["backup"]
    target = next(
        (r for r in provider_rules_of(config) if r.get("providerId") == target_pid),
        None,
    )
    if target is None:
        raise RuntimeError("target provider not found: " + target_pid)
    moved: list[str] = []
    for mid in sorted(BACKUP_MODEL_IDS):
        before = next(
            (r["providerId"] for r in provider_rules_of(config)
             if mid in (r.get("config", {}).get("personalModelIds") or [])),
            None,
        )
        if before is None:
            continue
        move_model(config, mid, target_pid)
        if before != target_pid:
            moved.append(mid)
    target["config"].setdefault("api", {})["baseUrl"] = ROUTER_BASE
    return moved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write config (default dry run)")
    ap.add_argument("--reorder-only", action="store_true",
                    help="reorder existing workbuddy providers/models only; "
                         "do not change membership or tiers")
    ap.add_argument("--reclassify-only", action="store_true",
                    help="only move BACKUP_MODEL_IDS into the backup target; "
                         "no gateway fetch")
    ap.add_argument("--separate", action="store_true",
                    help="keep the old four workbuddy-* providers instead of "
                         "merging into the OpenCode chat tiers")
    ap.add_argument("--api-key", default=GATEWAY_KEY, help="gateway api_key")
    ap.add_argument("--max-rate", type=float, default=DEFAULT_MAX_RATE,
                    help="highest credit multiplier to include, anything above "
                         "is dropped (default 0.30)")
    ap.add_argument("--include-aliases", action="store_true",
                    help="also include routing aliases (auto/primary/deep/fast/balanced/enhance)")
    ap.add_argument("--include-blocked", action="store_true",
                    help="keep models the probe marked blocked/unavailable")
    ap.add_argument("--pricing-file", default=str(PRICING_FILE))
    ap.add_argument("--probe-file", default=str(PROBE_FILE))
    args = ap.parse_args()

    if args.reclassify_only:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        moved = reclassify_backup(config) if args.separate else reclassify_unified_backup(config)
        print(f"config      : {CONFIG_FILE}")
        print("mode        : reclassify only (%s)" % ("separate" if args.separate else "unified"))
        print("moved       : " + (", ".join(moved) if moved else "(none)"))
        if not args.apply:
            print("[dry-run] no changes written; pass --apply to write")
            return 0
        if not moved:
            print("nothing to do")
            return 0
        backup = write_config(config)
        print(f"backup      : {backup.name}")
        print(f"written     : {CONFIG_FILE}")
        return 0

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

    # ---- reorder-only mode ------------------------------------------------
    if args.reorder_only:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not args.separate:
            print(f"config      : {CONFIG_FILE}")
            print("mode        : reorder only (unified)")
            print("unified mode: merged lists are rebuilt by --apply; "
                  "no workbuddy-* providers to reorder")
            return 0
        root = config.setdefault("config", {})
        provider_rules = root.setdefault("providerConfigRules", {}).setdefault("providerRules", [])
        rates = {str(r["id"]): r.get("_rate") for r in merged}
        active: set[str] = set()
        print(f"config      : {CONFIG_FILE}")
        print("mode        : reorder only (membership unchanged)")
        print()
        for provider in provider_rules:
            pid = provider.get("providerId")
            if pid not in PROVIDER_IDS.values():
                continue
            cfg = provider.setdefault("config", {})
            ids = list(cfg.get("personalModelIds") or [])
            ordered = sorted(ids, key=lambda mid: model_sort_key(
                {"id": mid, "_rate": rates.get(mid)}))
            cfg["personalModelIds"] = ordered
            cfg["modelOrder"] = ordered
            active.add(pid)
            name = provider.get("providerName") or pid
            print(f"== {name} ({pid}) - {len(ordered)} models ==")
            for mid in ordered:
                rate = rates.get(mid)
                shown = f"x{rate:<5.2f}" if isinstance(rate, (int, float)) else "  -   "
                print(f"  {shown} {mid}")
            print()
        reorder_provider_order(root, active)
        print("providerOrder:", ", ".join(
            pid for pid in root.get("providerOrder", []) if pid in PROVIDER_IDS.values()))
        if not args.apply:
            print("[dry-run] no changes written; pass --apply to write")
            return 0
        backup = write_config(config)
        print(f"backup      : {backup.name}")
        print(f"written     : {CONFIG_FILE}")
        return 0

    excluded: list[tuple[str, str]] = []
    tiers: dict[str, list[dict]] = {"free": [], "low": [], "high": [], "backup": []}

    for rec in sorted(merged, key=model_sort_key):
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
            # rate_limited / queued / timeout / error are transient: dropping
            # the model here removes it from the config until a later probe
            # happens to succeed, while a never-probed model is kept — two
            # contradictory policies. Keep it this round and say so.
            if pstat in ("rate_limited", "queued", "timeout", "error"):
                print(f"  note: {mid} 本次探测 {pstat}（瞬态，保留）", file=sys.stderr)
            elif pstat is None:
                print(f"  note: {mid} 无探测记录（保留，等待下一轮探测）", file=sys.stderr)
        tier = tier_of(rate, mid)
        if tier is None:
            excluded.append((mid, "unclassified"))
            continue
        tiers[tier].append(rec)

    total = sum(len(v) for v in tiers.values())
    if total == 0:
        print("no models selected", file=sys.stderr)
        return 1

    # ---- unified mode (default) -------------------------------------------
    if not args.separate:
        config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        unified_tiers: dict[str, list[dict]] = {
            "main": [], "low": [], "free": [], "high": [], "backup": []
        }
        for tier in ("low", "free", "high", "backup"):
            for rec in tiers[tier]:
                target = "main" if str(rec["id"]) in MAIN_MODEL_IDS else tier
                unified_tiers[target].append(rec)
        added, stale, uncertain = apply_unified(
            config, unified_tiers, probe, set(by_id), set(pricing)
        )
        print(f"config      : {CONFIG_FILE}")
        print("mode        : unified (WorkBuddy -> OpenCode chat tiers)")
        print(f"router base : {ROUTER_BASE}")
        print(f"selected    : {total} models")
        print(f"merged      : {added} model entries")
        for tier in ("main", "low", "free", "high", "backup"):
            print(f"  {tier:6} -> {UNIFIED_TARGETS[tier]}: {len(unified_tiers[tier])}")
        print(f"excluded    : {len(excluded)}")
        if stale:
            print(f"removed     : {len(stale)} stale WorkBuddy models (no longer selected upstream)")
            for mid in stale:
                print(f"  - {mid}")
        if uncertain:
            print(f"kept        : {len(uncertain)} models missing from a partial live list (kept, re-check next run)")
            for mid in uncertain:
                print(f"  ? {mid}")
        if not args.apply:
            print("[dry-run] no changes written; pass --apply to write")
            return 0
        backup = write_config(config)
        print(f"backup      : {backup.name}")
        print(f"written     : {CONFIG_FILE}")
        return 0

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
    for tier in TIER_DISPLAY_ORDER:
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

    reorder_provider_order(root, {r.get("providerId") for r in new_provider_rules})

    # ---- report -----------------------------------------------------------
    print(f"config      : {CONFIG_FILE}")
    print(f"baseUrl     : {GATEWAY_BASE.rstrip('/')}/v1")
    print(f"max rate    : <= {args.max_rate}")
    print(f"selected    : {total} models")
    print(f"excluded    : {len(excluded)}")
    for mid, why in excluded:
        print(f"  - {mid:38s} {why}")
    print()
    for tier in TIER_DISPLAY_ORDER:
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

    backup = write_config(config)
    print(f"backup      : {backup.name}")
    print(f"written     : {CONFIG_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
