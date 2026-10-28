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

The three providers are 主力 / 免费 / 省钱. Anything above 0.11 that is not in
MAIN_IDS or LOW_PICKS is dropped instead of getting its own group. `gateways/zgate` reads the generated alias map and
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
price. The leaderboard is opt-in now: pass `--arena` to allow it.

Usage
-----
    python tools/model_alias.py                  # dry run, prints the full table
    python tools/model_alias.py --apply          # backup + write config + alias map
    python tools/model_alias.py --max-price 2.0  # widen the high tier (0 = no cap)
    python tools/model_alias.py --check          # drift check only; exit 1 on drift

Prices are derived, never inherited: every run recomputes each hop's price from
the current source (WB pricing cache / Qoder live / OC price table). The alias
map stores identity only (what the model is called and which upstreams it maps
to); a hop whose upstream no longer prices is dropped. `--check` compares the
recomputed result against the existing alias map so a frozen price shows up as
drift instead of silently staying in the config.
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
WB_PRICING = REPO / "providers" / "workbuddy" / "cache" / "wb_pricing.json"
QD_ENV = REPO / "providers" / "qoder" / ".env.local"
# 千问的集合体（旗舰/代码/快速）：每条是一串上游 id，路由按顺序逐个烧。
POOLS_FILE = REPO / "providers" / "qwen" / "pools.json"
DEFAULT_ARENA = Path.home() / ".zcode" / "v2" / "arena-main.json"

PROVIDER_MAIN = "opencode-go-chat"
PROVIDER_FREE = "opencode-go-chat-free"
PROVIDER_LOW = "opencode-go-chat-fast"
PROVIDER_IDS = [PROVIDER_MAIN, PROVIDER_FREE, PROVIDER_LOW]
PROVIDER_NAMES = {
    PROVIDER_MAIN: "主力",
    PROVIDER_FREE: "免费",
    PROVIDER_LOW: "省钱",
}
GROUPS = ("main", "free", "low")
ROUTER_BASE = "http://127.0.0.1:7871/v1"
WB_BASE = "http://127.0.0.1:7863/v1"
QD_BASE = "http://127.0.0.1:8790/v1"
OC_BASE = "https://opencode.ai/zen/go/v1"
QW_BASE = "https://maas.qianwenaiapi.com/apps/anthropic/v1"
# 千问渠道是**预付额度**：先用掉「每模型 1M tokens」的试用池（2026-12-15 到期），
# 之后走 ¥300 学生额度（一年有效，到期作废，用不完也不退）。
# 预付额度的边际单价就是 0，所以整段窗口内按 0 记账；额度真烧光时上游返回配额错误，
# 路由的 hopFatal + 冷却会把这跳摘掉，不需要有人回来改配置。
QW_CREDIT_UNTIL = "2027-10-28"

# 七牛云 `qiniu/conatus-free` 是限时免费（到 2026-11-30）。过期后 price_of 返回 None，
# 这一跳自动消失 —— 和限免到期同一条机制，不需要人工回来删配置。
QN_FREE_UNTIL = "2026-11-30"

# Hand-picked core. `~/.zcode/v2/arena-main.json` can add more (see
# tools/arena_leaderboard.py); `--no-arena` restores this list only.
# 键一律 `<协议>:<上游 id>`：同一型号会以 chat / messages 两种形态出现
# （千问桥接版是 messages），只写型号名会把两条一起吸进主力。
# 主力顺序：组内按此顺序排（DeepSeek 置顶，Qwen 贵备份次之，千问尾跳最后）。
# 组内排序的权威来源；MAIN_IDS 由它派生，避免"按厂商最低价排序把便宜厂商顶到前面"。
MAIN_ORDER = [
    # 日常主力：唯一的付费心智负担
    "chat:cn:deepseek-v4.1-flash",
    "chat:deepseek-v4.1-flash",
    # 贵备份：AA 榜上唯一高于 DeepSeek 基准的模型（2026-10-28 1122 vs 1093，
    # #44 vs #56），只在 DeepSeek 两跳同时不可用时手动切。
    "chat:Qwen3.8-Max",
    # 免费 DeepSeek（千问渠道，messages 协议）：¥300 预付额度先烧这一条。
    # 它由 MERGE_ACROSS_PROTOCOL 并进上一条的链尾（同一显示名、按跳派发协议），
    # 这里仍列出是为了让排序与「链路覆盖」自解释。
    "messages:deepseek-v4.1-flash",
]
MAIN_IDS = set(MAIN_ORDER)
# 省钱组：每个厂商留 1–2 个特色型号（用户 2026-10-28 口径：前旗舰/旧版本全砍，
# 只留"最能代表这家、日常会用"的）。命中这里才进组，未命中的模型直接不收录 ——
# 组里不会出现用不上的模型。
# ⚠️ 这是**严格有序白名单**：组内顺序由 LOW_ORDER 决定（不是按厂商最低价，
# 否则便宜厂商会顶到前面把列表打乱）；命中这里即进组，不受 LOW_MAX 价格上限约束，
# 所以小米 MiMo-2.6-Pro（0.19）也能留在省钱组当厂商旗舰。
# 省钱组排列顺序（唯一权威来源）：总价档无关，按"厂商代表型号"排。
# 价格随价格源走，不写死。LOW_PICKS 由它派生，避免两份名单各自维护而漂移。
# 各行尾注释说明「为什么这家留这个型号」：
LOW_ORDER = [
    "messages:qwen3.8-flash",        # Qwen：中文 / 长输出（AA 基准附近）
    "chat:cn:glm-5.3-flash",         # 智谱：工具调用稳（AA 993）
    "chat:cn:minimax-m3.1-flash",    # MiniMax：1M 上下文
    "chat:mimo-v2.6-flash",          # 小米：每积分最耐用（AA 1087）
    "chat:mimo-v2.6-pro",            # 小米：旗舰（0.19，厂商代表型号）
    "chat:cn:hy3-x",                 # 腾讯：最便宜（0.05）
    "messages:claude-haiku-5-5",     # Anthropic：子代理 / 小改动（AA 1026）
    "responses:gpt-6-luna",          # OpenAI：responses 协议（AA 992）
    "chat:cn:space-bunny",           # Space：AA 1074，性价比最高之一
]
LOW_PICKS = set(LOW_ORDER)

# Base models whose free GB tier is folded into the paid entry instead of being
# listed separately: the paid entry tries the free upstream first, then the paid
# one, then CN. Display name keeps the paid price.
MERGE_FREE_GB = {"deepseek-v4.1-flash"}
# 同一型号允许 chat 与 messages 跳并进同一条链（路由按每跳自己的协议派发）。
MERGE_ACROSS_PROTOCOL = {"deepseek-v4.1-flash"}
# 这些跳排到链尾，不看价格：千问的额度是一年期预付，按「OC 先用完再用它」的
# 顺序来花，所以它必须排在付费跳之后，只有当付费全挂时才轮到。
TAIL_HOPS = {("QW", "deepseek-v4.1-flash")}
FREE_MAX = 0.0
LOW_MAX = 0.11
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
    # 2026-10-28 实测：上游 usage 自带 cost=0 / list_cost=0，按免费档收录。
    "iceman-contributor-free": {"flat": 0.00},
    "claude-haiku-5-5": {"flat": 0.09},
    "qwen3.8-flash": {"flat": 0.09},
    "qwen3.7-plus": {"flat": 0.29},
    "minimax-m2.7": {"flat": 0.22},
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
    # 七牛云网关的 id 形如 `qiniu/conatus-free`：去掉 `qiniu/` 前缀，Conatus 自成系列。
    "qiniu/conatus-free": "Conatus",
    "moonshotai/kimi-k3-free": "Kimi-K3",
    "deepseek-v4.1-flash": "DeepSeek-4.1-Flash",
    "deepseek-v4.1-flash-sg": "DeepSeek-4.1-Flash",
    "deepseek-v4-flash": "DeepSeek-4-Flash",
    "deepseek-v4-flash-vision-exp": "DeepSeek-4-Flash-Vision",
    "deepseek-v4-pro": "DeepSeek-4-Pro",
    "deepseek-v3-2-volc": "DeepSeek-3.2-Volc",
    "deepseek-flash": "DeepSeek-4-Flash",
    "qwen3.8-max": "Qwen-3.8-Max",
    "qwen3.8-flash": "Qwen-3.8-Flash",
    "qwen3.7-max": "Qwen-3.7-Max",
    "qwen3.7-plus": "Qwen-3.7-Plus",
    "qwen3.7-flash": "Qwen-3.7-Flash",
    "qwen-max": "Qwen-Max",
    "qwen3-coder-plus": "Qwen-3-Coder-Plus",
    "qwen3-coder-flash": "Qwen-3-Coder-Flash",
    "qwen-plus": "Qwen-Plus",
    "qwen-flash": "Qwen-Flash",
    "qwen3-vl-plus": "Qwen-3-VL-Plus",
    "qwq-plus": "QwQ-Plus",
    "glm-5.3": "GLM-5.3",
    "glm-5.3-flash": "GLM-5.3-Flash",
    "glm-5.2": "GLM-5.2",
    "glm-4.6": "GLM-4.6",
    "glm-4.6v": "GLM-4.6V",
    "minimax-m3.1-flash": "MiniMax-M3.1-Flash",
    "minimax-m3": "MiniMax-M3",
    "minimax-m2.7": "MiniMax-M2.7",
    "minimax-m2.5": "MiniMax-M2.5",
    "kimi-k2.8-preview": "Kimi-K2.8-Pre",
    "kimi-k3": "Kimi-K3",
    "kimi-k2.6": "Kimi-K2.6",
    "kimi-k2.5": "Kimi-K2.5",
    "hy3": "HY3",
    "hy3-x": "HY3-X",
    "hy4-preview": "HY4-Pre",
    "hy4-preview-f": "HY4-Pre",
    "hy4-preview-ctrl": "HY4-Pre",
    "hy4-preview-exp": "HY4-Pre",
    "hy4-preview-x": "HY4-Pre",
    "hy3-b": "HY3",
    "hy3-c": "HY3",
    "fast-model": "HY-Fast",
    "step-5-preview": "Step-5-Pre",
    "space-bunny": "Space-Bunny",
    "mimo-v2.6-pro": "MiMo-2.6-Pro",
    "mimo-v2.6-flash": "MiMo-2.6-Flash",
    "mimo-v2.5": "MiMo-2.5",
    "mimo-v2.5-pro": "MiMo-2.5-Pro",
    "longcat-2.0": "LongCat-2.0",
    "longcat-2.5-preview-free": "LongCat-2.5-Pre",
    "beam-free": "Beam",
    "iceman-contributor-free": "Iceman",
    "claude-haiku-5-5": "Claude-Haiku-5.5",
    "gpt-6-luna": "GPT-6-Luna",
    "gpt-5.6-luna": "GPT-5.6-Luna",
    "muse-spark-1.3-contributor": "Muse-Spark1.3",
    "muse-spark-1.2-contributor": "Muse-Spark1.2",
}
VENDOR_ORDER = ("DSP", "QW", "GLM", "MM", "KIMI", "HY", "MIMO", "LONG", "BEAM",
                "CL", "GPT", "MUSE", "STEP", "SPB", "CONATUS", "OTHER")


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


_PRICE_WARNED: set[str] = set()
# 缺价统计：整渠道无价时 --apply 会把该渠道的模型整批从配置里剔除。
_UNPRICED: dict[str, int] = {}
_CHANNEL_ITEMS: dict[str, int] = {}


def _warn_price_once(channel: str, detail: str) -> None:
    """价格源不可用必须留痕：静默返回空表会把整个渠道的模型从配置里剔除。"""
    if channel in _PRICE_WARNED:
        return
    _PRICE_WARNED.add(channel)
    print(f"WARN: {channel} 价格源不可用（{detail}），该渠道模型将无法定价", file=sys.stderr)


def _warn_stale_cache(path: Path, label: str, refresh_hint: str,
                      max_age_hours: float = 48.0) -> None:
    """价格表是活数据：过期了还照用，分档就会停在旧价上（限免到期尤其如此）。"""
    try:
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return
    if age_hours <= max_age_hours:
        return
    print(
        f"WARN: {label} 已 {age_hours:.0f} 小时未刷新（> {max_age_hours:.0f}h），"
        f"分档可能已过期；先跑 {refresh_hint}",
        file=sys.stderr,
    )


def _fresh_probe(probe: dict, max_age_hours: float) -> tuple[dict, list[str]]:
    """丢掉过期的探测结论。

    过期的 ok 会留住已经下架的模型，过期的 blocked/unavailable 会删掉还能用的
    模型 —— 两个方向都错，所以过期条目一律按「未知」处理（未知不删除）。
    """
    if max_age_hours <= 0:
        return probe, []
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    fresh: dict = {}
    stale: list[str] = []
    for model_id, record in probe.items():
        raw = str((record or {}).get("checked_at") or "")
        try:
            checked = datetime.fromisoformat(raw)
        except ValueError:
            stale.append(model_id)
            continue
        if checked.tzinfo is not None:
            checked = checked.astimezone().replace(tzinfo=None)
        if checked >= cutoff:
            fresh[model_id] = record
        else:
            stale.append(model_id)
    return fresh, stale


def wb_prices() -> dict[str, dict]:
    try:
        rows = json.loads(WB_PRICING.read_text(encoding="utf-8"))
    except Exception as exc:
        _warn_price_once("WB", f"{WB_PRICING}: {exc}")
        return {}
    _warn_stale_cache(WB_PRICING, "WB 价格表", "providers/workbuddy/workbuddy_fetch_pricing.py")
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
        except Exception as exc:
            _warn_price_once("QD", f"127.0.0.1:8790: {exc}")
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


def qw_credit_active() -> bool:
    return datetime.now().strftime("%Y-%m-%d") <= QW_CREDIT_UNTIL


def price_of(channel: str, upstream: str, wb: dict[str, dict],
             qd: dict[str, dict], slot: str) -> float | None:
    if channel == "QW":
        return 0.0 if qw_credit_active() else None
    if channel == "QN":
        # 七牛限免只覆盖带 -free 后缀的模型（2026-11-30 前）。渠道级一律返 0
        # 会把将来播种的付费模型也误标成免费，所以必须按上游 id 判定。
        if not str(upstream).endswith("-free"):
            return None
        return 0.0 if datetime.now().strftime("%Y-%m-%d") <= QN_FREE_UNTIL else None
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
    # 厂商前缀（`qiniu/` `moonshotai/`）与 `-free` / `-f` 标记都不进显示名：
    # 「免费」由分组表达，只有同型号同时存在免费与付费档时才加 `-Free`。
    text = re.sub(r"^[a-z0-9_-]+/", "", model, flags=re.IGNORECASE)
    text = re.sub(r"(?i)[-_]free$", "", text)
    text = re.sub(r"^[Vv](?=\d)", "", text)
    text = re.sub(r"(?i)flash\b", "Fs", text)
    text = re.sub(r"(?i)preview\b", "Pre", text)
    text = re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-")
    return text or "MODEL"


VENDOR_PREFIXES = (
    ("DeepSeek", "DSP"), ("Qwen", "QW"), ("QwQ", "QW"), ("GLM", "GLM"), ("MiniMax", "MM"),
    ("Kimi", "KIMI"), ("HY", "HY"), ("MiMo", "MIMO"), ("LongCat", "LONG"),
    ("Beam", "BEAM"), ("Claude", "CL"), ("GPT", "GPT"), ("Muse", "MUSE"),
    ("Step", "STEP"), ("Space", "SPB"), ("Conatus", "CONATUS"),
)


def vendor_of(abbr: str) -> str:
    for prefix, vendor in VENDOR_PREFIXES:
        if abbr.startswith(prefix):
            return vendor
    return "OTHER"


def vendor_rank(abbr: str) -> int:
    return VENDOR_ORDER.index(vendor_of(abbr))


_PROTOCOL_HINTS: dict | None = None


def protocol_hints() -> dict:
    """go 同步写下的新模型协议提示（chat/messages/responses），供 classify 兜底。"""
    global _PROTOCOL_HINTS
    if _PROTOCOL_HINTS is None:
        path = (Path(__file__).resolve().parent.parent
                / "providers" / "opencode-go" / "cache" / "go_protocols.json")
        try:
            _PROTOCOL_HINTS = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _PROTOCOL_HINTS = {}
    return _PROTOCOL_HINTS


PREFIXES = ("qwen:", "qoder:", "cn:", "global:")


def _bare(model_id: str) -> str:
    """去掉渠道前缀后的裸 id，用于比较 legacy 映射是否还指得对。"""
    text = str(model_id)
    for prefix in PREFIXES:
        if text.lower().startswith(prefix):
            return text[len(prefix):].lower()
    return text.lower()


def classify(model: str, protocol: str, alias_models: dict, legacy: dict) -> dict | None:
    """Map any config model id (old or already-renamed) to its inventory fields."""
    if model in alias_models:
        entry = alias_models[model]
        # 集合体只由 pools.json 生成：不能让它进 inventory 被 expand_hops 按跳拆开，
        # 否则每一跳都会变成一条独立模型，下一轮再翻倍。
        if entry.get("kind") == "pool":
            return None
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
            "chain": list(entry.get("chain") or []),
            "legacy_ids": list(entry.get("legacy_ids") or [entry.get("original") or model, upstream]),
        }
    legacy_target = legacy.get(model)
    if legacy_target in alias_models and ":" in model:
        # 带渠道前缀的 key 必须真能对上目标条目的某一跳：否则这是上一轮
        # 改名/展开留下的陈旧映射，会把这个 id 静默指到完全无关的模型上。
        target = alias_models[legacy_target]
        hops = target.get("chain") or [target]
        upstreams = {_bare(h.get("upstream") or "") for h in hops}
        if _bare(model) not in upstreams:
            legacy_target = None
    if legacy_target in alias_models:
        result = classify(legacy_target, protocol, alias_models, {})
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
    if model.startswith("qwen:"):
        upstream = model[len("qwen:"):]
        return {
            "raw": model,
            "original": model,
            "channel": "QW",
            "region": "CN",
            "upstream": upstream,
            "base_model": upstream,
            # 千问平台只提供 Anthropic Messages 端点：协议必须钉成 messages，
            # 否则 zgate 会按 chat 直转，上游直接 404。
            "protocol": "messages",
            "fallbacks": [],
            "legacy_ids": [model],
        }
    if model.startswith("qn:"):
        upstream = model[len("qn:"):]
        return {
            "raw": model,
            "original": model,
            "channel": "QN",
            "region": "CN",
            "upstream": upstream,
            "base_model": upstream,
            # 七牛云 AI 网关同样只有 Anthropic Messages 端点。
            "protocol": "messages",
            "fallbacks": [],
            "legacy_ids": [model],
        }
    if model.startswith(("WB:", "OC:", "QD:")):
        # A renamed id that is not in the alias map: refuse to guess.
        return None
    # 4 组制：messages / responses 模型也进成本档，协议由 go 同步写的提示缓存兜底，
    # 写进 alias map 后 zgate 才能按 protocol 桥接。
    hint = protocol_hints().get(model)
    if hint:
        protocol = hint
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
            for hop in expand_hops(item):
                key = (hop["channel"], hop["upstream"], hop["protocol"])
                if key in seen:
                    previous = seen[key]
                    values = previous.setdefault("legacy_ids", [])
                    for value in hop.get("legacy_ids") or []:
                        if value not in values:
                            values.append(value)
                    continue
                seen[key] = hop
    return list(seen.values())


# 千问平台只有 Anthropic Messages 端点，任何 QW 跳的协议都必须是 messages。
# 这是渠道属性，不依赖 alias map 里存了什么（上一版存错时会被这里纠正）。
CHANNEL_PROTOCOL = {"QW": "messages"}


def expand_hops(item: dict) -> list[dict]:
    """One item per upstream: v2 chain, v1 fallbacks, or the item itself."""
    chain = item.get("chain") or []
    if chain:
        out = []
        for hop in chain:
            sub = dict(item)
            sub.update({
                "channel": hop.get("channel") or item["channel"],
                "upstream": hop.get("upstream") or item["upstream"],
                "base_model": hop.get("base_model") or item["base_model"],
                "original": hop.get("original") or hop.get("upstream") or item["upstream"],
                # 每跳保留自己的协议：跨协议合并的条目（主力的 DeepSeek 链）
                # 条目级是 chat，尾跳是 messages，覆盖成条目级会让路由按 chat
                # 直转 messages 上游，直接 404。
                "protocol": CHANNEL_PROTOCOL.get(
                    hop.get("channel") or item["channel"],
                    hop.get("protocol") or item["protocol"],
                ),
                # 价格一律由 price_of() 从当轮价格源重算：继承上一版 alias map
                # 里的 price 会把上游改价/限免到期永久冻结在旧值上
                # （2026-10-28 Step-5-Pre 限免结束仍显示 0.00 即此因）。
                "price": None,
                "fallbacks": [],
            })
            out.append(sub)
        return out
    out = [dict(item)]
    for fallback in item.get("fallbacks") or []:
        if fallback == item["upstream"]:
            continue
        sub = dict(item)
        sub.update({
            "upstream": fallback,
            "base_model": re.sub(r"^(cn|global):", "", fallback),
            "original": fallback,
            "price": None,
            "fallbacks": [],
        })
        out.append(sub)
    return out


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


QN_BASE = "https://api.qnaigc.com/v1"
CHANNEL_BASE = {"WB": WB_BASE, "QD": QD_BASE, "OC": OC_BASE, "QW": QW_BASE, "QN": QN_BASE}


def base_of(channel: str) -> str:
    return CHANNEL_BASE.get(channel, OC_BASE)


def family_entries(items: list[dict], wb: dict, qd: dict, slot: str) -> list[dict]:
    """Collapse one entry per (model, protocol), merging channels by price.

    The display name is just the model name (no channel, no price). Hops are
    ordered cheapest-first across channels, and each hop carries its own base so
    the router can switch upstreams without a shared host.

    A free tier stays a separate entry (suffixed -F) when the same model also has
    a paid tier, except for MERGE_FREE_GB families where the free hop is folded
    into the paid entry and tried first.
    """
    families: dict[tuple[str, str], dict[str, dict]] = {}
    for item in items:
        _CHANNEL_ITEMS[item["channel"]] = _CHANNEL_ITEMS.get(item["channel"], 0) + 1
        price = item.get("price")
        if price is None:
            price = price_of(item["channel"], item["upstream"], wb, qd, slot)
        if price is None:
            _UNPRICED[item["channel"]] = _UNPRICED.get(item["channel"], 0) + 1
            continue
        hop = dict(item)
        hop["price"] = round(float(price), 2)
        abbr = abbreviate(item["base_model"])
        if str(item["base_model"]).lower() in MERGE_ACROSS_PROTOCOL:
            key = (abbr, "merged")
        else:
            key = (abbr, item["protocol"])
        families.setdefault(key, {})[(item["channel"], item["upstream"])] = hop

    entries: list[dict] = []
    # 同一型号若同时存在 chat 与桥接协议（messages / responses），原型名必须留给
    # chat 那条：否则桥接条目会先占名，聊天条目被挤成 `-2`，老会话里选中的
    # `GLM-5.3` 会悄悄指到另一个渠道上去。
    abbr_protocols: dict[str, set[str]] = {}
    for (abbr, protocol) in families:
        abbr_protocols.setdefault(abbr, set()).add(protocol)
    for (abbr, protocol), hop_map in families.items():
        hops = sorted(hop_map.values(), key=lambda h: (h["price"], h["upstream"]))
        if not hops:
            continue
        free = [h for h in hops if h["price"] <= 0]
        paid = [h for h in hops if h["price"] > 0]
        base_model = hops[0]["base_model"]
        family_key = re.sub(r"(-sg|-f)$", "", base_model.lower())

        if family_key in MERGE_FREE_GB or not (free and paid):
            groups = [hops]
        else:
            groups = [paid, free]

        for group in groups:
            group = sorted(group, key=lambda h: (
                1 if (h["channel"], h["upstream"]) in TAIL_HOPS else 0,
                h["price"],
                0 if h["upstream"].startswith("global:") else 1 if h["upstream"].startswith("cn:") else 2,
                0 if h["channel"] == "WB" else 1 if h["channel"] == "QD" else 2,
                h["upstream"],
            ))
            is_free_entry = all(h["price"] <= 0 for h in group)
            base_name = abbr
            if protocol != "chat" and "chat" in abbr_protocols.get(abbr, ()):
                base_name = abbr + ("-Msg" if protocol == "messages" else "-Resp")
            name = base_name + ("-Free" if is_free_entry and len(groups) > 1 else "")
            chain = [{
                "upstream": h["upstream"],
                "base": base_of(h["channel"]),
                "channel": h["channel"],
                "protocol": h["protocol"],
                "price": h["price"],
                "original": h["original"],
                "base_model": h["base_model"],
            } for h in group]
            legacy_ids: list[str] = []
            for h in group:
                for lid in h.get("legacy_ids") or [h["original"], h["upstream"]]:
                    if lid not in legacy_ids:
                        legacy_ids.append(lid)
            entry = dict(group[0])
            entry.update({
                "name": name,
                "abbr": abbr,
                "protocol": "chat" if protocol == "merged" else protocol,
                "channel": chain[0]["channel"],
                "upstream": chain[0]["upstream"],
                "base": chain[0]["base"],
                "base_model": base_model,
                "price": chain[0]["price"],
                "chain": chain,
                "fallbacks": [c["upstream"] for c in chain[1:]],
                "legacy_ids": legacy_ids,
                "is_free_entry": is_free_entry,
            })
            entries.append(entry)
    return entries


def load_pools(path: Path) -> list[dict]:
    """集合体定义：每个池子是一条按顺序试的长链路。文件不存在就跳过。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception as exc:
        print(f"warning: 读不了集合体定义 {path}（{exc}），本次不生成池子", file=sys.stderr)
        return []
    return [pool for pool in (data.get("pools") or []) if pool.get("name") and pool.get("hops")]


def pool_entries(pools: list[dict], slot: str) -> list[dict]:
    """把池子变成合成条目：一条显示名，chain 是整串上游。

    池内每一跳都是千问渠道（QW），价格取 `price_of`；试用窗口外整池无价 -> 不生成。
    """
    entries: list[dict] = []
    for pool in pools:
        hops: list[dict] = []
        for upstream in pool["hops"]:
            price = price_of("QW", upstream, {}, {}, slot)
            if price is None:
                continue
            hops.append({
                "upstream": upstream,
                "base": QW_BASE,
                "channel": "QW",
                "price": round(float(price), 2),
                "original": "qwen:" + upstream,
                "base_model": upstream,
            })
        if not hops:
            continue
        entries.append({
            "name": str(pool["name"]),
            "abbr": str(pool["name"]),
            "protocol": "messages",
            "channel": "QW",
            "upstream": hops[0]["upstream"],
            "original": hops[0]["original"],
            "base": QW_BASE,
            "base_model": hops[0]["base_model"],
            "price": hops[0]["price"],
            "chain": hops,
            "fallbacks": [hop["upstream"] for hop in hops[1:]],
            "legacy_ids": [str(pool["name"])],
            "is_free_entry": all(hop["price"] <= 0 for hop in hops),
            "is_pool": True,
            "label": str(pool.get("label") or ""),
        })
    return entries


def _picked(entry: dict, hop: dict, wanted: set[str]) -> bool:
    """按 `<协议>:<上游>` 命中：协议是必需的，同型号的 chat / 桥接版名字一样。"""
    protocol = str(entry.get("protocol") or "chat")
    for value in (hop.get("upstream"), hop.get("base_model")):
        if value and f"{protocol}:{value}" in wanted:
            return True
    return False


def entry_group(entry: dict, arena_targets: dict[tuple[str, str], dict]) -> tuple[str, str]:
    """Return (group, reason) for a merged entry. `drop` = 不收录。"""
    # 集合体是「一整串上游」的人造条目：它的跳会包含很多被单型号名单点名的 id，
    # 按跳匹配会把它误吸进主力（91 跳的快速池命中 deepseek-v4.1-flash 的桥接版）。
    # 池子只按价格归组 —— 0 积分就是免费。
    if entry.get("is_pool"):
        return ("free", "") if entry["price"] <= 0 else ("drop", "")
    for hop in entry["chain"]:
        if _picked(entry, hop, MAIN_IDS):
            return "main", "manual"
    for hop in entry["chain"]:
        if (hop["channel"], hop["upstream"]) in arena_targets:
            return "main", "arena"
    price = entry["price"]
    if price <= 0:
        return "free", ""
    if any(_picked(entry, hop, LOW_PICKS) for hop in entry["chain"]):
        # 严格白名单命中即进省钱组，不受 LOW_MAX 价格上限约束
        # （小米 MiMo-2.6-Pro 0.19 也借此留在组里当厂商旗舰）。
        return "low", ""
    return "drop", ""


# "high"（高耗）已不产出，但保留标签：迁移期的旧 alias map 里还有这一组，
# 漂移检测要能读得懂它，才不会在收缩当天报 KeyError。
_GROUP_LABELS = {"main": "主力", "free": "免费", "low": "省钱", "drop": "不收录", "high": "高耗"}


def _hop_label(hop: dict) -> str:
    return f"{hop.get('channel')}:{hop.get('upstream')}@{hop.get('price')}"


def _entry_signature(entry: dict) -> dict:
    chain = entry.get("chain") or []
    hops = [_hop_label(h) for h in chain] if chain else [_hop_label(entry)]
    return {
        "group": str(entry.get("group") or ""),
        "price": round(float(entry.get("price") or 0.0), 2),
        "chain": hops,
    }


def proposed_signature(grouped: dict[str, list[dict]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for group, rows in grouped.items():
        for row in rows:
            entry = dict(row)
            entry["group"] = _GROUP_LABELS[group]
            out[row["new_id"]] = _entry_signature(entry)
    return out


def drift_report(grouped: dict[str, list[dict]], existing_models: dict) -> dict[str, list]:
    """重算结果与现有 alias map 的差异。

    `sync_report.py` 比的是「上一版 alias map」和「这一版」——两边都来自同一份
    缓存时，一个稳定存在的偏差永远不会显示成变化。这里比的是「现有产物」和
    「按当前价格源重算的结果」，是唯一能抓到价格冻结这类 bug 的检查。
    """
    proposed = proposed_signature(grouped)
    current = {name: _entry_signature(entry) for name, entry in (existing_models or {}).items()}
    added = sorted(set(proposed) - set(current))
    removed = sorted(set(current) - set(proposed))
    group_changed, price_changed, chain_changed = [], [], []
    for name in sorted(set(proposed) & set(current)):
        old, new = current[name], proposed[name]
        if old["group"] != new["group"]:
            group_changed.append((name, old["group"], new["group"]))
        if old["price"] != new["price"]:
            price_changed.append((name, old["price"], new["price"]))
        if old["chain"] != new["chain"]:
            chain_changed.append((name, old["chain"], new["chain"]))
    return {
        "added": added,
        "removed": removed,
        "group_changed": group_changed,
        "price_changed": price_changed,
        "chain_changed": chain_changed,
    }


def print_drift(drift: dict[str, list]) -> None:
    total = sum(len(v) for v in drift.values())
    if total == 0:
        print("\n无漂移：现有 alias map 与按当前价格源重算的结果一致")
        return
    print(f"\n发现漂移 {total} 处（现有 alias map vs 当前价格源重算）：")
    if drift["added"]:
        print("  新增：", ", ".join(drift["added"]))
    if drift["removed"]:
        print("  消失：", ", ".join(drift["removed"]))
    for name, old, new in drift["price_changed"]:
        print(f"  价格：{name}  {old:g} -> {new:g}")
    for name, old, new in drift["group_changed"]:
        print(f"  分组：{name}  {old or '-'} -> {new}")
    for name, old, new in drift["chain_changed"]:
        print(f"  链路：{name}")
        print(f"    旧：{' -> '.join(old)}")
        print(f"    新：{' -> '.join(new)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="写入 provider_config.json 与 alias map")
    parser.add_argument("--check", action="store_true",
                        help="只做漂移检测：把重算结果与现有 alias map 比对，有差异退出码 1，不写盘")
    parser.add_argument("--probe-max-age-hours", type=float, default=72.0,
                        help="探测结果超过该小时数视为未知（默认 72；0 = 不设限）")
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
    parser.add_argument("--arena", action="store_true",
                        help="允许榜单自动扩主力（默认关闭：它会把主力越塞越肿）")
    parser.add_argument("--no-arena", action="store_true",
                        help="兼容旧参数：榜单本来就是默认关闭的")
    parser.add_argument("--pools",
                        help=f"集合体定义（默认 {POOLS_FILE.name}；一条显示名对应一串上游）")
    parser.add_argument("--no-pools", action="store_true",
                        help="忽略集合体定义，只生成单型号条目")
    parser.add_argument("--force-unpriced", action="store_true",
                        help="允许在某个渠道全部无价时仍然 --apply（默认拒绝，避免整批剔除）")
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
    entries = family_entries(items, wb, qd, args.slot)
    pool_file = Path(args.pools).expanduser() if args.pools else POOLS_FILE
    pool_rows = [] if args.no_pools else pool_entries(load_pools(pool_file), args.slot)
    entries.extend(pool_rows)
    raw = raw_models(cfg, existing_models, legacy)
    arena_file = arena_main_path(args.arena_main)
    arena_targets = load_arena_targets(arena_file) if (args.arena and not args.no_arena) else {}

    # Copy the original model rule (optionSpecs / properties) before removing
    # the old rules. A renamed id no longer matches ZCode's builtin patterns,
    # so models that need an empty thinking map must carry it explicitly.
    old_rules = {}
    for entry in model_rules(cfg):
        old_rules.setdefault(str(entry.get("modelId")), entry.get("config") or {})

    grouped: dict[str, list[dict]] = {key: [] for key in GROUPS}
    skipped: list[str] = []
    used: set[str] = set()
    # 上一版的名字按 (渠道, 上游, 协议) 记下来：同一个 hop 继续用旧名，
    # 否则配置里混进原始 id 时同名模型的命名会按出现顺序翻转，
    # 用户会话里选的 "MiniMax-M2.7" 会悄悄换到另一个上去游。
    prev_names: dict[tuple[str, str, str], str] = {}
    for prev_name, prev_entry in existing_models.items():
        for hop in prev_entry.get("chain") or [prev_entry]:
            key = (
                str(hop.get("channel") or prev_entry.get("channel") or ""),
                str(hop.get("upstream") or prev_entry.get("upstream") or ""),
                str(prev_entry.get("protocol") or ""),
            )
            prev_names.setdefault(key, prev_name)
    for entry in entries:
        group, main_reason = entry_group(entry, arena_targets)
        if group == "drop":
            skipped.append(f"{entry['name']} (price {entry['price']:g}，未在主力/省钱名单)")
            continue
        if args.max_price > 0 and entry["price"] > args.max_price and group != "main":
            skipped.append(f"{entry['name']} (price {entry['price']:g} > {args.max_price:g})")
            continue
        new_id = entry["name"]
        for hop in entry["chain"]:
            prev = prev_names.get((hop["channel"], hop["upstream"], entry["protocol"]))
            if not prev or prev in used:
                continue
            # 只继承「同名去冲突」后缀（-Msg / -Resp / -2）；-Free 是状态后缀，
            # 跟着价格走，不能从上一版继承。
            if prev == entry["name"] or re.fullmatch(
                re.escape(entry["name"]) + r"-\d+(?:-\d+)?", prev
            ):
                new_id = prev
                break
        if new_id in used:
            # Same name, different protocol (e.g. a bridged variant).
            suffix = "-Msg" if entry["protocol"] == "messages" else "-Resp" if entry["protocol"] == "responses" else "-2"
            candidate = entry["abbr"] + suffix
            counter = 2
            while candidate in used:
                candidate = f"{entry['abbr']}{suffix}-{counter}"
                counter += 1
            new_id = candidate
        used.add(new_id)
        entry = dict(entry)
        entry.update({"group": group, "new_id": new_id, "main_reason": main_reason})
        grouped[group].append(entry)

    # 组内顺序由人工白名单决定，不按"厂商最低价"排 —— 否则便宜厂商会顶到前面
    # 把列表打乱（HY 0.05 / MiMo 0.06 会抢在 DeepSeek 之前，正是用户看到 mimo
    # 排到最后的反例：那时 raw id 没归并进厂商块）。主力按 MAIN_ORDER、省钱按
    # LOW_ORDER；不在名单里的模型（理论上不会进组）排末尾。
    def _pick_rank(row: dict, order: list[str]) -> int:
        """条目命中的名单序号；没命中的排末尾。组内顺序由人工名单决定。"""
        for hop in row["chain"]:
            for j, name in enumerate(order):
                if f"{row.get('protocol')}:{hop.get('upstream')}" == name or \
                   f"{row.get('protocol')}:{hop.get('base_model')}" == name:
                    return j
        return len(order)

    for group, rows in grouped.items():
        if group == "main":
            rows.sort(key=lambda r: (_pick_rank(r, MAIN_ORDER), r["new_id"]))
        elif group == "low":
            rows.sort(key=lambda r: (_pick_rank(r, LOW_ORDER), r["price"], r["new_id"]))
        else:
            # 免费组：常用优先（HY3 > HY4 > 其它），再按价格
            rows.sort(key=lambda r: (0 if r["new_id"].startswith("HY") else 1, r["price"], r["new_id"]))

    transient_kept: list[str] = []
    if args.probe_file:
        probe_path = Path(args.probe_file).expanduser()
        if not probe_path.exists():
            raise SystemExit(f"找不到探测结果：{probe_path}")
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        probe, stale_probe = _fresh_probe(probe, args.probe_max_age_hours)
        if stale_probe:
            print(
                f"WARN: {len(stale_probe)} 条探测结果超过 "
                f"{args.probe_max_age_hours:g} 小时，按「未知」处理"
                f"（不会据此删除模型）：{', '.join(sorted(stale_probe)[:5])}"
                + (" …" if len(stale_probe) > 5 else ""),
                file=sys.stderr,
            )
        transient = {"queued", "timeout", "rate_limited"}
        reverse_legacy: dict[str, list[str]] = {}
        for old_id, new_id in legacy.items():
            reverse_legacy.setdefault(new_id, []).append(old_id)
        for group, rows in grouped.items():
            kept = []
            for row in rows:
                candidates = [row["new_id"], row.get("raw")]
                for hop in row["chain"]:
                    candidates += [hop["upstream"], hop["original"]]
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
    for group in GROUPS:
        print(f"\n## {PROVIDER_NAMES[{'main':PROVIDER_MAIN,'free':PROVIDER_FREE,'low':PROVIDER_LOW}[group]]} ({len(grouped[group])})")
        for item in grouped[group]:
            print(f"  {item['new_id']:<34} {item['original']:<34} {item['protocol']:<10} {item['price']:.2f}")
    if pool_rows:
        print("## 集合体（%s）" % pool_file.name)
        for pool in pool_rows:
            head = " -> ".join(hop["upstream"] for hop in pool["chain"][:3])
            print(f"  {pool['name']:<16} {len(pool['chain'])} 跳  {head} …")
    arena_rows = [row for row in grouped["main"] if row.get("main_reason") == "arena"]
    if arena_rows:
        print(f"\n## 主力扩充来源（{arena_file.name}）")
        for row in arena_rows:
            hop = next((h for h in row["chain"]
                        if (h["channel"], h["upstream"]) in arena_targets), None)
            if hop is None:
                continue
            entry = arena_targets[(hop["channel"], hop["upstream"])]
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

    if _UNPRICED:
        detail = "、".join(f"{ch} {n} 个" for ch, n in sorted(_UNPRICED.items()))
        print(f"\nWARN: 因缺价未收录：{detail}（价格源不可用时先修复再 --apply）", file=sys.stderr)
    dead = [ch for ch, n in _CHANNEL_ITEMS.items() if n and _UNPRICED.get(ch, 0) == n]
    if dead and args.apply and not args.force_unpriced:
        print(
            f"ERROR: 渠道 {'、'.join(dead)} 的全部模型都没有价格，拒绝写入 —— "
            "这会把该渠道的模型整批从配置里剔除。修好价格源后重跑，或加 --force-unpriced。",
            file=sys.stderr,
        )
        return 1

    if args.check:
        drift = drift_report(grouped, existing_models)
        print_drift(drift)
        return 1 if any(drift.values()) else 0

    if not args.apply:
        print("\ndry run；加 --apply 写入 provider_config.json 与 alias map")
        return 0

    new_id_by_key = {}
    for rows in grouped.values():
        for item in rows:
            for hop in item["chain"]:
                new_id_by_key[(hop["channel"], hop["upstream"], item["protocol"])] = item["new_id"]
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
                               ("low", PROVIDER_LOW)):
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
            base = base_of(row["channel"])
            alias_models[row["new_id"]] = {
                "channel": row["channel"],
                "region": "",
                "upstream": row["upstream"],
                "base_model": row["base_model"],
                "base": base,
                "protocol": row["protocol"],
                "original": row["original"],
                "price": row["price"],
                "group": PROVIDER_NAMES[provider_id],
                "fallbacks": list(row.get("fallbacks") or []),
                "chain": list(row.get("chain") or []),
                "legacy_ids": list(row.get("legacy_ids") or [row["original"], row["upstream"]]),
            }
            if row.get("is_pool"):
                alias_models[row["new_id"]]["kind"] = "pool"
                alias_models[row["new_id"]]["label"] = row.get("label") or ""
            if row.get("main_reason"):
                alias_models[row["new_id"]]["main_reason"] = row["main_reason"]
            for legacy_id in row.get("legacy_ids") or [row["original"], row["upstream"]]:
                legacy[legacy_id] = row["new_id"]

    valid_ids = set(alias_models)
    # Follow rename chains (W/0.00/X -> W/0.03/X -> ...) so an id that has been
    # renamed twice still resolves to a live model instead of being dropped.
    resolved_legacy: dict[str, str] = {}
    for key, value in legacy.items():
        target = value
        seen: set[str] = set()
        while target not in valid_ids and target in legacy and target not in seen:
            seen.add(target)
            target = legacy[target]
        if target in valid_ids:
            resolved_legacy[key] = target
    legacy = resolved_legacy

    # 读取路径兼容 list/dict 两种形态（见 provider_rules），写入也必须归一化，
    # 否则 list 形态会在这里抛 TypeError，整轮 --apply 白跑。
    pcr = cfg["config"]["providerConfigRules"]
    if isinstance(pcr, list):
        pcr[:] = new_providers
    else:
        pcr["providerRules"] = new_providers
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
