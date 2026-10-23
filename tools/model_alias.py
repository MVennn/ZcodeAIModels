#!/usr/bin/env python3
"""Rebuild ZCode's model list as four credit-based groups with stable aliases.

The display id is:

    <CHANNEL>/<CREDITS>/<MODEL>

    W/0.03/DeepSeek-41-Fs   WorkBuddy global, deepseek-v4.1-flash-sg
    O/0.11/DeepSeek-41-Fs   OpenCode-Go, deepseek-v4.1-flash
    O/0.09/Qwen-38-Fs       OpenCode-Go, qwen3.8-flash
    Q/0.00/DeepSeek-4-Fs    Qoder CN, DeepSeek-Flash (off-peak)

Channel letters are W (WorkBuddy), O (OpenCode-Go), Q (Qoder). Model names
drop the `V` and version dots (`DeepSeek-V4.1-FS` -> `DeepSeek-41-Fs`).

The four providers are 主力 / 免费 / 低耗 / 高耗. 备用 is dissolved into
高耗 by price. `tools/unified-router.js` reads the generated alias map and
forwards each display id to its original upstream model, so the display name
never has to be parseable.

Credit conversion
-----------------
WorkBuddy `eff_rate` is the base. OpenCode-Go is anchored on
deepseek-v4.1-flash ($0.15 in / $0.60 out = 0.11 credits, 1:1 blend).
Qoder `price_factor` is multiplied by 0.86, the median ratio of same-name
models against WorkBuddy (GLM-5.3 0.862, GLM-5.3-Flash 0.80,
MiniMax-M3.1-Flash 0.80, Kimi-K2.8 0.963, DeepSeek-V4-Pro 1.02).

This script is the final writer. The existing Go / WorkBuddy / Qoder syncs may
still run first to refresh pricing and probe caches; run this script after them
so their old ids are normalized away. It is idempotent and backs up first.

`~/.zcode/v2/arena-main.json` (written by `tools/arena_leaderboard.py`) can
extend 主力 with models that score near the DeepSeek baseline at a similar
price. Pass `--no-arena` to ignore it.

Usage
-----
    python tools/model_alias.py                  # dry run, prints the full table
    python tools/model_alias.py --apply          # backup + write config + alias map
    python tools/model_alias.py --max-price 2.0  # widen the high tier (0 = no cap)
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
WB_PRICING = REPO / "workbuddy" / "cache" / "wb_pricing.json"
QD_ENV = REPO / "qoder" / ".env.local"
DEFAULT_ARENA = Path.home() / ".zcode" / "v2" / "arena-main.json"

PROVIDER_MAIN = "opencode-go-chat"
PROVIDER_FREE = "opencode-go-chat-free"
PROVIDER_LOW = "opencode-go-chat-fast"
PROVIDER_HIGH = "opencode-go-chat-slow"
PROVIDER_IDS = [PROVIDER_MAIN, PROVIDER_FREE, PROVIDER_LOW, PROVIDER_HIGH]
PROVIDER_NAMES = {
    PROVIDER_MAIN: "主力",
    PROVIDER_FREE: "免费",
    PROVIDER_LOW: "低耗",
    PROVIDER_HIGH: "高耗",
}
REMOVE_PROVIDERS = {
    "opencode-go-chat-backup",
    "opencode-go-messages",
    "opencode-go-responses",
    "qoder",
}
ROUTER_BASE = "http://127.0.0.1:7871/v1"
WB_BASE = "http://127.0.0.1:7863/v1"
QD_BASE = "http://127.0.0.1:8790/v1"
OC_BASE = "https://opencode.ai/zen/go/v1"

# Hand-picked core. `~/.zcode/v2/arena-main.json` can add more (see
# tools/arena_leaderboard.py); `--no-arena` restores this list only.
MAIN_IDS = {
    "cn:deepseek-v4.1-flash",
    "global:deepseek-v4.1-flash-sg",
    "deepseek-v4.1-flash",
    "mimo-v2.6-pro",
    # 2026-10-23: benchmark #4 (372.95) at 0.09 credits, vs DeepSeek V4.1
    # Flash #11 (342.40) at 0.11; higher intelligence and cheaper.
    "qwen3.8-flash",
}
FREE_MAX = 0.0
LOW_MAX = 0.16
QD_FACTOR = 0.86

# OpenCode-Go prices from docs/MODEL-PROVIDERS.md §2, converted with the
# deepseek-v4.1-flash anchor (1 credit = $3.409/M, 1:1 input/output blend).
OC_PRICES = {
    # DeepSeek V4.1 Flash / V4 Pro are the only OpenCode-Go models with
    # time-based pricing (peak UTC Mon-Fri 01:00-04:00 and 06:00-10:00).
    "deepseek-v4.1-flash": {"off": 0.11, "peak": 0.22},
    "deepseek-v4-pro": {"off": 0.39, "peak": 0.77},
    "deepseek-v4-flash-vision-exp": None,
    "mimo-v2.6-pro": {"flat": 0.19},
    "mimo-v2.5-pro": {"flat": 0.19},
    "glm-5.3-flash": {"flat": 0.10},
    "mimo-v2.6-flash": {"flat": 0.06},
    "mimo-v2.5": {"flat": 0.06},
    "hy3": {"flat": 0.11},
    "longcat-2.0": {"flat": 0.22},
    "minimax-m3": {"flat": 0.22},
    "minimax-m3.1-flash": {"flat": 0.11},
    "beam-free": {"flat": 0.00},
    "claude-haiku-5-5": {"flat": 0.09},
    "qwen3.8-flash": {"flat": 0.09},
    "qwen3.7-plus": {"flat": 0.29},
    "minimax-m2.7": None,
    "gpt-6-luna": {"flat": 0.09},
    "gpt-5.6-luna": {"flat": 0.21},
    "muse-spark-1.3-contributor": {"flat": 0.04},
    "muse-spark-1.2-contributor": {"flat": 0.04},
}
# Qoder fallback if the hub is not reachable; live /v1/models wins.
QD_PRICES = {
    "DeepSeek-Flash": 0.0,
    "GLM-5.3-Flash": 0.1,
    "MiniMax-M3.1-Flash": 0.1,
    "DeepSeek-V4-Pro": 0.5,
    "Qwen3.8-Max": 0.5,
    "GLM-5.3": 0.8,
    "Kimi-K2.8-Preview": 0.8,
}

ABBR = {
    "deepseek-v4.1-flash": "DeepSeek-41-Fs",
    "deepseek-v4.1-flash-sg": "DeepSeek-41-Fs",
    "deepseek-v4-flash": "DeepSeek-4-Fs",
    "deepseek-v4-flash-vision-exp": "DeepSeek-4-Fs-Vision",
    "deepseek-v4-pro": "DeepSeek-4-Pro",
    "deepseek-flash": "DeepSeek-4-Fs",
    "qwen3.8-max": "Qwen-38-Max",
    "qwen3.8-flash": "Qwen-38-Fs",
    "qwen3.7-max": "Qwen-37-Max",
    "qwen3.7-plus": "Qwen-37-Plus",
    "qwen3.7-flash": "Qwen-37-Fs",
    "glm-5.3": "GLM-53",
    "glm-5.3-flash": "GLM-53-Fs",
    "glm-5.2": "GLM-52",
    "minimax-m3.1-flash": "MiniMax-M31-Fs",
    "minimax-m3": "MiniMax-M3",
    "minimax-m2.7": "MiniMax-M27",
    "kimi-k2.8-preview": "Kimi-K28-Preview",
    "kimi-k3": "Kimi-K3",
    "kimi-k2.6": "Kimi-K26",
    "kimi-k2.5": "Kimi-K25",
    "hy3": "HY3",
    "hy3-x": "HY3-X",
    "hy4-preview": "HY4-Preview",
    "hy4-preview-f": "HY4-Preview",
    "step-5-preview": "Step-5-Preview",
    "space-bunny": "Space-Bunny",
    "mimo-v2.6-pro": "MiMo-26-Pro",
    "mimo-v2.6-flash": "MiMo-26-Fs",
    "mimo-v2.5": "MiMo-25",
    "mimo-v2.5-pro": "MiMo-25-Pro",
    "longcat-2.0": "LongCat-20",
    "longcat-2.5-preview-free": "LongCat-25-Preview",
    "beam-free": "Beam",
    "claude-haiku-5-5": "Claude-Haiku-55",
    "gpt-6-luna": "GPT-6-Luna",
    "gpt-5.6-luna": "GPT-56-Luna",
    "muse-spark-1.3-contributor": "Muse-Spark13",
    "muse-spark-1.2-contributor": "Muse-Spark12",
}
CHANNEL_LETTER = {"WB": "W", "OC": "O", "QD": "Q"}
VENDOR_ORDER = ("DSP", "QW", "GLM", "MM", "KIMI", "HY", "MIMO", "LONG", "BEAM",
                "CL", "GPT", "MUSE", "STEP", "SPB", "OTHER")


def config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ZCODE_PERSONAL_PROVIDER_CONFIG_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "provider_config.json"


def alias_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("UNIFIED_MODEL_MAP")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "model-alias-map.json"


def arena_main_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ARENA_MAIN_FILE")
    if env:
        return Path(env).expanduser()
    return DEFAULT_ARENA


def load_arena_targets(path: Path) -> dict[tuple[str, str], dict]:
    """Read `arena-main.json` into {(channel, upstream): candidate}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        print(f"warning: 读不了榜单候选 {path}（{exc}），本次不扩充主力", file=sys.stderr)
        return {}
    targets: dict[tuple[str, str], dict] = {}
    for entry in data.get("candidates") or []:
        channel = str(entry.get("channel") or "")
        upstream = str(entry.get("upstream") or "")
        if channel and upstream:
            targets[(channel, upstream)] = entry
    return targets


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                out[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return out


def provider_rules(cfg: dict) -> list[dict]:
    rules = cfg["config"]["providerConfigRules"]
    if isinstance(rules, list):
        return rules
    return rules.setdefault("providerRules", [])


def model_rules(cfg: dict) -> list[dict]:
    return cfg["config"].setdefault("modelConfigRules", {}).setdefault("providerModelRules", [])


def wb_prices() -> dict[str, dict]:
    try:
        rows = json.loads(WB_PRICING.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for row in rows:
        model = str(row.get("id") or "")
        if not model:
            continue
        try:
            list_rate = float(row.get("list_rate") if row.get("list_rate") is not None else row.get("eff_rate"))
            eff_rate = float(row.get("eff_rate") if row.get("eff_rate") is not None else list_rate)
        except (TypeError, ValueError):
            continue
        out[model] = {
            "list": list_rate,
            "eff": eff_rate,
            "promo": str(row.get("promo") or ""),
            "label": str(row.get("promo_label") or ""),
        }
    return out


def qd_prices() -> dict[str, dict]:
    env = read_env(QD_ENV)
    key = os.environ.get("QD_API_KEY") or env.get("QD_API_KEY") or ""
    if key:
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8790/v1/models",
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            out = {}
            for model in payload.get("data") or []:
                name = str(model.get("id") or "")
                price = model.get("price_factor")
                if not name or price is None:
                    continue
                out[name] = {
                    "price": float(price),
                    "peak": float(model.get("price_factor_peak") if model.get("price_factor_peak") is not None else price),
                    "valley": float(model.get("price_factor_valley") if model.get("price_factor_valley") is not None else price),
                    "off_peak": model.get("off_peak") or {},
                }
            if out:
                return out
        except Exception:
            pass
    return {
        name: {"price": price, "peak": price, "valley": price, "off_peak": {}}
        for name, price in QD_PRICES.items()
    }


def in_off_peak(record: dict) -> bool:
    off = record.get("off_peak") or {}
    start = str(off.get("window_start") or "22:00")
    end = str(off.get("window_end") or "08:00")
    now = datetime.now(timezone(timedelta(hours=8)))
    hm = now.strftime("%H:%M")
    if start <= end:
        return start <= hm < end
    return hm >= start or hm < end


def in_oc_peak() -> bool:
    """OpenCode-Go peak: UTC Mon-Fri 01:00-04:00 and 06:00-10:00."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return (60 <= minutes < 240) or (360 <= minutes < 600)


def price_of(channel: str, upstream: str, wb: dict[str, dict],
             qd: dict[str, dict], slot: str) -> float | None:
    if channel == "WB":
        record = wb.get(upstream)
        if not record:
            return None
        if slot == "peak":
            return record["list"] if record["list"] > 0 else record["eff"]
        if slot == "offpeak":
            label = record.get("label", "").lower()
            time_based = any(key in label for key in ("夜间", "错峰", "night", "off-peak", "off peak"))
            if time_based and record["eff"] < record["list"]:
                return record["eff"]
        return record["eff"]
    if channel == "QD":
        record = qd.get(upstream)
        if not record:
            return None
        if slot == "peak":
            factor = record["peak"]
        elif slot == "offpeak":
            factor = record["valley"]
        else:
            factor = record["valley"] if in_off_peak(record) else record["peak"]
        return factor * QD_FACTOR
    record = OC_PRICES.get(upstream)
    if record is None:
        return None
    if "flat" in record:
        return float(record["flat"])
    if slot == "peak":
        return float(record.get("peak", record.get("off")))
    if slot == "offpeak":
        return float(record.get("off", record.get("peak")))
    return float(record["peak"] if in_oc_peak() else record["off"])


def abbreviate(model: str) -> str:
    key = model.lower()
    if key in ABBR:
        return ABBR[key]
    text = re.sub(r"(?<=\d)\.(?=\d)", "", model)
    text = re.sub(r"^[Vv](?=\d)", "", text)
    text = re.sub(r"(?i)flash\b", "Fs", text)
    text = re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-")
    return text or "MODEL"


def group_of(item: dict, price: float, max_price: float,
             arena_targets: dict[tuple[str, str], dict] | None = None) -> str | None:
    if item["original"] in MAIN_IDS:
        return "main"
    if arena_targets and (item["channel"], item["upstream"]) in arena_targets:
        return "main"
    if max_price > 0 and price > max_price:
        return None
    if price <= FREE_MAX:
        return "free"
    if price <= LOW_MAX:
        return "low"
    return "high"


VENDOR_PREFIXES = (
    ("DeepSeek", "DSP"), ("Qwen", "QW"), ("GLM", "GLM"), ("MiniMax", "MM"),
    ("Kimi", "KIMI"), ("HY", "HY"), ("MiMo", "MIMO"), ("LongCat", "LONG"),
    ("Beam", "BEAM"), ("Claude", "CL"), ("GPT", "GPT"), ("Muse", "MUSE"),
    ("Step", "STEP"), ("Space", "SPB"),
)


def vendor_of(abbr: str) -> str:
    for prefix, vendor in VENDOR_PREFIXES:
        if abbr.startswith(prefix):
            return vendor
    return "OTHER"


def vendor_rank(abbr: str) -> int:
    return VENDOR_ORDER.index(vendor_of(abbr))


def classify(model: str, protocol: str, alias_models: dict, legacy: dict) -> dict | None:
    """Map any config model id (old or already-renamed) to its inventory fields."""
    if model in alias_models:
        entry = alias_models[model]
        channel = str(entry.get("channel") or "")
        upstream = str(entry.get("upstream") or "")
        base_model = str(entry.get("base_model") or (
            upstream.split(":", 1)[1] if channel == "WB" and ":" in upstream else upstream
        ))
        region = str(entry.get("region") or (
            "CN" if channel == "WB" and upstream.startswith("cn:") else
            "GB" if channel == "WB" else "CN" if channel == "QD" else ""
        ))
        return {
            "raw": model,
            "original": str(entry.get("original") or model),
            "channel": channel,
            "region": region,
            "upstream": upstream,
            "base_model": base_model,
            "protocol": str(entry.get("protocol") or protocol),
            "fallbacks": list(entry.get("fallbacks") or []),
            "legacy_ids": list(entry.get("legacy_ids") or [entry.get("original") or model, upstream]),
        }
    if model in legacy and legacy[model] in alias_models:
        result = classify(legacy[model], protocol, alias_models, {})
        if result is None:
            return None
        result = dict(result)
        result["raw"] = model
        legacy_ids = result.get("legacy_ids") or []
        if model not in legacy_ids:
            legacy_ids = [model] + legacy_ids
        result["legacy_ids"] = legacy_ids
        return result
    if model.startswith(("cn:", "global:")):
        return {
            "raw": model,
            "original": model,
            "channel": "WB",
            "region": "CN" if model.startswith("cn:") else "GB",
            "upstream": model,
            "base_model": model.split(":", 1)[1],
            "protocol": protocol,
            "fallbacks": [],
            "legacy_ids": [model],
        }
    if model.startswith("qoder:"):
        upstream = model[len("qoder:"):]
        return {
            "raw": model,
            "original": model,
            "channel": "QD",
            "region": "CN",
            "upstream": upstream,
            "base_model": upstream,
            "protocol": protocol,
            "fallbacks": [],
            "legacy_ids": [model],
        }
    if model.startswith(("WB:", "OC:", "QD:")):
        # A renamed id that is not in the alias map: refuse to guess.
        return None
    return {
        "raw": model,
        "original": model,
        "channel": "OC",
        "region": "",
        "upstream": model,
        "base_model": model,
        "protocol": protocol,
        "fallbacks": [],
        "legacy_ids": [model],
    }


def inventory(cfg: dict, alias_models: dict, legacy: dict) -> list[dict]:
    """Collect unique models from the current provider config."""
    seen: dict[tuple[str, str, str], dict] = {}
    for rule in provider_rules(cfg):
        provider_id = str(rule.get("providerId") or "")
        config = rule.get("config") or {}
        api = config.get("api") or {}
        api_type = str(api.get("type") or "openai-chat-completions")
        protocol = {
            "openai-chat-completions": "chat",
            "anthropic-messages": "messages",
            "openai-responses": "responses",
        }.get(api_type, "chat")
        for raw in config.get("personalModelIds") or []:
            model = str(raw).strip()
            if not model:
                continue
            item = classify(model, protocol, alias_models, legacy)
            if item is None:
                continue
            item["provider_id"] = provider_id
            key = (item["channel"], item["upstream"], item["protocol"])
            if key in seen:
                previous = seen[key]
                for field in ("fallbacks", "legacy_ids"):
                    values = previous.setdefault(field, [])
                    for value in item.get(field) or []:
                        if value not in values:
                            values.append(value)
                continue
            seen[key] = item
    return list(seen.values())


def raw_models(cfg: dict, alias_models: dict, legacy: dict) -> list[dict]:
    out: list[dict] = []
    for rule in provider_rules(cfg):
        config = rule.get("config") or {}
        api = config.get("api") or {}
        api_type = str(api.get("type") or "openai-chat-completions")
        protocol = {
            "openai-chat-completions": "chat",
            "anthropic-messages": "messages",
            "openai-responses": "responses",
        }.get(api_type, "chat")
        for raw in config.get("personalModelIds") or []:
            model = str(raw).strip()
            if not model:
                continue
            item = classify(model, protocol, alias_models, legacy)
            if item is not None:
                out.append(item)
    return out


def merge_inventory(items: list[dict], wb: dict, qd: dict, slot: str) -> list[dict]:
    """Merge WorkBuddy CN/GB variants under one WB channel.

    GB is the primary; every GB price tier keeps its own entry (so a free GB
    promo stays free), and the CN variants become fallbacks. Same-price CN/GB
    pairs collapse into one entry. The displayed price is the GB (primary)
    price; when GB is unavailable the router retries CN.
    """
    merged: list[dict] = []
    wb_groups: dict[str, list[dict]] = {}
    for item in items:
        if item["channel"] == "WB":
            # `-sg` is a region variant, not a different model: keep the free
            # GB and SG GB tiers in the same merge group so both get the CN
            # fallback.
            base_key = re.sub(r"-sg$", "", item["base_model"])
            wb_groups.setdefault(base_key, []).append(item)
            continue
        item = dict(item)
        item["price"] = price_of(item["channel"], item["upstream"], wb, qd, slot)
        item["region"] = ""
        item["fallbacks"] = list(item.get("fallbacks") or [])
        item["legacy_ids"] = list(item.get("legacy_ids") or [item["original"], item["upstream"]])
        merged.append(item)

    for base_model, group in wb_groups.items():
        priced = []
        for item in group:
            item = dict(item)
            item["price"] = price_of("WB", item["upstream"], wb, qd, slot)
            priced.append(item)
        gb = [item for item in priced
              if item["upstream"].startswith("global:") and item["price"] is not None]
        cn = [item for item in priced if item["upstream"].startswith("cn:")]
        existing_fallbacks: list[str] = []
        existing_legacy: list[str] = []
        for item in priced:
            for fb in item.get("fallbacks") or []:
                if fb not in existing_fallbacks:
                    existing_fallbacks.append(fb)
            for lid in item.get("legacy_ids") or []:
                if lid not in existing_legacy:
                    existing_legacy.append(lid)

        if gb:
            by_price: dict[float, list[dict]] = {}
            for item in gb:
                by_price.setdefault(round(float(item["price"]), 2), []).append(item)
            owner_price = max(by_price)
            cn_upstreams: list[str] = []
            for item in cn:
                if item["upstream"] not in cn_upstreams:
                    cn_upstreams.append(item["upstream"])
            for fb in existing_fallbacks:
                if fb not in cn_upstreams:
                    cn_upstreams.append(fb)
            cn_legacy: list[str] = []
            for item in cn:
                for lid in item.get("legacy_ids") or [item["original"], item["upstream"]]:
                    if lid not in cn_legacy:
                        cn_legacy.append(lid)
            gb_legacy_all = set()
            for rows in by_price.values():
                for item in rows:
                    gb_legacy_all.update(item.get("legacy_ids") or [item["original"], item["upstream"]])
            for price, rows in by_price.items():
                primary = sorted(rows, key=lambda row: row["upstream"])[0]
                legacy_ids: list[str] = []
                for item in rows:
                    for lid in item.get("legacy_ids") or [item["original"], item["upstream"]]:
                        if lid not in legacy_ids:
                            legacy_ids.append(lid)
                if price == owner_price:
                    for lid in cn_legacy + [x for x in existing_legacy if x not in gb_legacy_all]:
                        if lid not in legacy_ids:
                            legacy_ids.append(lid)
                entry = dict(primary)
                entry.update({
                    "region": "",
                    "price": price,
                    "fallbacks": cn_upstreams,
                    "legacy_ids": legacy_ids,
                })
                merged.append(entry)
        else:
            for item in cn:
                if item["price"] is None:
                    continue
                entry = dict(item)
                entry.update({
                    "region": "",
                    "fallbacks": list(item.get("fallbacks") or []),
                    "legacy_ids": list(item.get("legacy_ids") or [item["original"], item["upstream"]]),
                })
                merged.append(entry)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="写入 provider_config.json 与 alias map")
    parser.add_argument("--config", help="provider_config.json 路径")
    parser.add_argument("--alias-map", help="alias map 路径")
    parser.add_argument("--max-price", type=float, default=0.0,
                        help="高耗组的价格上限（默认 0 = 不设上限）")
    parser.add_argument("--slot", choices=("auto", "peak", "offpeak"), default="auto",
                        help="取价时段：auto 按当前时间、peak 峰价、offpeak 谷价")
    parser.add_argument("--probe-file",
                        help="model_probe.py 的结果；只保留 ok（或曾 ok 的瞬时限流）")
    parser.add_argument("--arena-main",
                        help=f"榜单候选文件（默认 {DEFAULT_ARENA}）")
    parser.add_argument("--no-arena", action="store_true",
                        help="忽略榜单候选，主力只用人工 MAIN_IDS")
    args = parser.parse_args()

    path = config_path(args.config)
    if not path.exists():
        raise SystemExit(f"找不到 ZCode 配置：{path}")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    alias_file = alias_path(args.alias_map)
    existing = {}
    if alias_file.exists():
        try:
            existing = json.loads(alias_file.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    existing_models = existing.get("models") or {}
    legacy = dict(existing.get("legacy") or {})
    wb, qd = wb_prices(), qd_prices()
    items = inventory(cfg, existing_models, legacy)
    items = merge_inventory(items, wb, qd, args.slot)
    raw = raw_models(cfg, existing_models, legacy)
    arena_file = arena_main_path(args.arena_main)
    arena_targets = {} if args.no_arena else load_arena_targets(arena_file)

    # Copy the original model rule (optionSpecs / properties) before removing
    # the old rules. A renamed id no longer matches ZCode's builtin patterns,
    # so models that need an empty thinking map must carry it explicitly.
    old_rules = {}
    for entry in model_rules(cfg):
        old_rules.setdefault(str(entry.get("modelId")), entry.get("config") or {})

    grouped: dict[str, list[dict]] = {key: [] for key in ("main", "free", "low", "high")}
    skipped: list[str] = []
    used: set[str] = set()
    for item in items:
        price = item.get("price")
        if price is None:
            skipped.append(f"{item['original']} (no price)")
            continue
        group = group_of(item, price, args.max_price, arena_targets)
        if group is None:
            skipped.append(f"{item['original']} (price {price:g} > {args.max_price:g})")
            continue
        if item["original"] in MAIN_IDS:
            main_reason = "manual"
        elif (item["channel"], item["upstream"]) in arena_targets:
            main_reason = "arena"
        else:
            main_reason = ""
        abbr = abbreviate(item["base_model"])
        channel = CHANNEL_LETTER.get(item["channel"], item["channel"])
        new_id = f"{channel}/{price:.2f}/{abbr}"
        if new_id in used:
            suffix = 2
            while f"{new_id}-{suffix}" in used:
                suffix += 1
            new_id = f"{new_id}-{suffix}"
        used.add(new_id)
        item = dict(item)
        item.update({"price": price, "group": group, "new_id": new_id, "abbr": abbr,
                     "main_reason": main_reason,
                     "fallbacks": list(item.get("fallbacks") or []),
                     "legacy_ids": list(item.get("legacy_ids") or [item["original"], item["upstream"]])})
        grouped[group].append(item)

    for group, rows in grouped.items():
        rows.sort(key=lambda r: (
            0 if r["channel"] == "WB" else 1 if r["channel"] == "OC" else 2,
            0 if vendor_of(r["abbr"]) == "DSP" else 1,
            0 if r["region"] in ("", "CN") else 1,
            vendor_rank(r["abbr"]),
            r["price"],
            r["new_id"],
        ))

    transient_kept: list[str] = []
    if args.probe_file:
        probe_path = Path(args.probe_file).expanduser()
        if not probe_path.exists():
            raise SystemExit(f"找不到探测结果：{probe_path}")
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        transient = {"queued", "timeout", "rate_limited"}
        reverse_legacy: dict[str, list[str]] = {}
        for old_id, new_id in legacy.items():
            reverse_legacy.setdefault(new_id, []).append(old_id)
        for group, rows in grouped.items():
            kept = []
            for row in rows:
                candidates = [row["new_id"], row.get("raw"), row["original"]]
                candidates += reverse_legacy.get(row["new_id"], [])
                entry = next((probe[c] for c in candidates if c in probe), {})
                status = entry.get("status")
                if status == "ok" or (status in transient and entry.get("ever_ok")):
                    kept.append(row)
                elif not entry and row["new_id"] in existing_models:
                    # Renamed since the last probe: the model was already in
                    # the working config, so keep it until the next probe.
                    kept.append(row)
                    transient_kept.append(f"{row['new_id']} (no probe entry, kept: existing model)")
                else:
                    skipped.append(f"{row['new_id']} (probe {status or 'not probed'})")
            grouped[group] = kept

    print("分组 / 新 ID / 原模型 / 协议 / 积分")
    for group in ("main", "free", "low", "high"):
        print(f"\n## {PROVIDER_NAMES[{'main':PROVIDER_MAIN,'free':PROVIDER_FREE,'low':PROVIDER_LOW,'high':PROVIDER_HIGH}[group]]} ({len(grouped[group])})")
        for item in grouped[group]:
            print(f"  {item['new_id']:<34} {item['original']:<34} {item['protocol']:<10} {item['price']:.2f}")
    arena_rows = [row for row in grouped["main"] if row.get("main_reason") == "arena"]
    if arena_rows:
        print(f"\n## 主力扩充来源（{arena_file.name}）")
        for row in arena_rows:
            entry = arena_targets[(row["channel"], row["upstream"])]
            ratio = float(entry.get("ratio") or 0) * 100
            print(f"  {row['new_id']:<34} 分数 {entry.get('score')}（基准 {ratio:.1f}%）"
                  f" #{entry.get('rank')}  {entry.get('model')}")
    if skipped:
        print("\n跳过：")
        for line in skipped:
            print(f"  {line}")
    if transient_kept:
        print("\n保留（无探测记录，但已在上一版配置里）：")
        for line in transient_kept:
            print(f"  {line}")

    if not args.apply:
        print("\ndry run；加 --apply 写入 provider_config.json 与 alias map")
        return 0

    new_id_by_key = {
        (item["channel"], item["upstream"], item["protocol"]): item["new_id"]
        for rows in grouped.values() for item in rows
    }
    for item in raw:
        key = (item["channel"], item["upstream"], item["protocol"])
        if key in new_id_by_key:
            legacy[item["raw"]] = new_id_by_key[key]
            legacy[item["original"]] = new_id_by_key[key]

    # Build the new config.
    template = next((r for r in provider_rules(cfg) if r.get("providerId") == PROVIDER_MAIN), None)
    if template is None:
        raise SystemExit(f"缺少模板 provider：{PROVIDER_MAIN}")
    access = copy.deepcopy((template.get("config") or {}).get("access") or {})
    group_name = (template.get("config") or {}).get("group") or "standard-personal"
    new_providers = []
    new_model_rules = []
    alias_models = {}
    for group, provider_id in (("main", PROVIDER_MAIN), ("free", PROVIDER_FREE),
                               ("low", PROVIDER_LOW), ("high", PROVIDER_HIGH)):
        rows = grouped[group]
        ids = [row["new_id"] for row in rows]
        new_providers.append({
            "providerId": provider_id,
            "providerName": PROVIDER_NAMES[provider_id],
            "config": {
                "group": group_name,
                "access": copy.deepcopy(access),
                "api": {"type": "openai-chat-completions", "baseUrl": ROUTER_BASE},
                "personalModelIds": ids,
                "modelOrder": ids,
            },
        })
        for row in rows:
            original_config = (
                old_rules.get(str(row.get("raw")))
                or old_rules.get(row["original"])
                or old_rules.get(row["upstream"])
                or {}
            )
            config = copy.deepcopy(original_config) if original_config else {}
            config["enabled"] = True
            if row["protocol"] != "chat":
                option_specs = config.setdefault("optionSpecs", {})
                reasoning = option_specs.setdefault("reasoningLevel", {})
                reasoning["map"] = "{}"
            new_model_rules.append({
                "modelId": row["new_id"],
                "config": config,
                "providerId": provider_id,
            })
            base = WB_BASE if row["channel"] == "WB" else QD_BASE if row["channel"] == "QD" else OC_BASE
            alias_models[row["new_id"]] = {
                "channel": row["channel"],
                "region": row["region"],
                "upstream": row["upstream"],
                "base_model": row["base_model"],
                "base": base,
                "protocol": row["protocol"],
                "original": row["original"],
                "price": row["price"],
                "group": PROVIDER_NAMES[provider_id],
                "fallbacks": list(row.get("fallbacks") or []),
                "legacy_ids": list(row.get("legacy_ids") or [row["original"], row["upstream"]]),
            }
            if row.get("main_reason"):
                alias_models[row["new_id"]]["main_reason"] = row["main_reason"]
            for legacy_id in row.get("legacy_ids") or [row["original"], row["upstream"]]:
                legacy[legacy_id] = row["new_id"]

    valid_ids = set(alias_models)
    legacy = {key: value for key, value in legacy.items() if value in valid_ids}

    cfg["config"]["providerConfigRules"]["providerRules"] = new_providers
    cfg["config"]["providerOrder"] = PROVIDER_IDS
    cfg["config"]["modelConfigRules"]["providerModelRules"] = new_model_rules
    cfg["config"]["modelConfigRules"]["manualProviderModelRules"] = []

    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + f"{time.time_ns() % 1_000_000:06d}"
    backup = path.with_name(path.name + ".bak-alias-" + stamp)
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp-alias")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)

    alias_file = alias_path(args.alias_map)
    alias_file.parent.mkdir(parents=True, exist_ok=True)
    alias_tmp = alias_file.with_name(alias_file.name + ".tmp")
    alias_tmp.write_text(json.dumps({
        "version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "slot": args.slot,
        "models": alias_models,
        "legacy": legacy,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(alias_tmp, alias_file)
    print(f"\n已写入 {path}（备份：{backup.name}）")
    print(f"已写入 {alias_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
