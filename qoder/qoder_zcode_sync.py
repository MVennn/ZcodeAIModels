#!/usr/bin/env python3
"""Sync Qoder models from qoder2api-hub into ZCode's existing chat tiers.

Default (merge mode)
--------------------
Qoder models are merged into the same five chat providers the WorkBuddy sync
already uses, with a `qoder:` prefix on every model id:

    price_factor == 0        -> opencode-go-chat-free
    0 < price_factor <= 0.2  -> opencode-go-chat-fast
    price_factor > 0.2       -> opencode-go-chat-slow

The prefix is required because Qoder and WorkBuddy/OpenCode share names such as
`GLM-5.3-Flash`, `MiniMax-M3.1-Flash` and `GLM-5.3`. `tools/unified-router.js`
routes `qoder:` models to the hub on 127.0.0.1:8790 and strips the prefix before
forwarding. The old standalone `qoder` provider is removed in merge mode, so the
ZCode provider list stays at seven entries.

`--separate` restores the previous behaviour: one standalone `qoder` provider
with bare model ids. Switching modes cleans both shapes first, so it is safe to
run repeatedly.

The hub must be running. Credentials never go to stdout and never enter the
repository: the API key comes from `--api-key`, `$QD_API_KEY`, or the local
`qoder/.env.local` (gitignored), and the ZCode config write is backed up first.

Usage
-----
    python qoder/qoder_zcode_sync.py                 # dry run (merge)
    python qoder/qoder_zcode_sync.py --apply          # backup + write (merge)
    python qoder/qoder_zcode_sync.py --separate --apply
    python qoder/qoder_zcode_sync.py --probe-file qoder/qoder_probe.json --apply
    python qoder/qoder_zcode_sync.py --max-price 1.4  # widen the default 0.8 cap
    python qoder/qoder_zcode_sync.py --max-price 0    # no price cap

Notes
-----
* ZCode hot-reloads provider_config.json (~1s polling); no restart is needed.
* Probe results are a separate concern: `qoder_probe_zcode.py` tests the exact
  body ZCode sends and writes `qoder_probe.json`. `--probe-file` keeps only
  models that answered 200; a model that has answered before is kept through a
  transient queue/timeout (`ever_ok`).
* In merge mode the API key lives only in `qoder/.env.local` / `$QD_API_KEY`,
  because the router reads it from there. The separate provider embeds it in
  `provider_config.json`; both paths are local and gitignored.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_BASE = os.environ.get("QD_GATEWAY_BASE", "http://127.0.0.1:8790/v1")
DEFAULT_PROVIDER_ID = "qoder"
DEFAULT_PROVIDER_NAME = "Qoder"
DEFAULT_GROUP = "standard-personal"
DEFAULT_MAX_PRICE = 0.8
DEFAULT_ORDER_AFTER = "opencode-go-chat-free"
PREFIX = "qoder:"
# Merge targets by Qoder's own relative price. The WorkBuddy tiers use a credit
# multiplier, so the two scales are not comparable; these thresholds only split
# Qoder's free / cheap-flash / rest bands.
MERGE_TARGETS = {
    "free": "opencode-go-chat-free",
    "low": "opencode-go-chat-fast",
    "high": "opencode-go-chat-slow",
}
LOW_MAX = 0.2
# Qoder's routing aliases resolve to another model and have no own price.
# `auto` comes from the embedded catalog; `fast` appears in the live catalog
# for trial/Pro accounts. Keep this list conservative: a real model added
# upstream must not be dropped by a substring match.
ROUTING_ALIASES = {"auto", "fast", "default", "primary", "deep", "balanced", "enhance"}


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return out


def resolve_api_key(explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    if os.environ.get("QD_API_KEY"):
        return os.environ["QD_API_KEY"].strip()
    env = read_env_file(HERE / ".env.local")
    key = (env.get("QD_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "缺少 Qoder API key：设置 QD_API_KEY、qoder/.env.local，或传 --api-key"
        )
    return key


def config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ZCODE_PERSONAL_PROVIDER_CONFIG_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "provider_config.json"


def fetch_models(base: str, key: str, timeout: int = 20) -> list[dict]:
    url = base.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"GET {url} -> HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise SystemExit(
            f"无法连接 qoder2api-hub（{url}）：{exc}\n"
            "先运行 qoder/gateway/start-qoder-proxy.bat，确认 8790 已就绪。"
        ) from exc
    data = payload.get("data")
    if not isinstance(data, list):
        raise SystemExit(f"{url} 返回的不是 OpenAI 模型清单：{str(payload)[:300]}")
    return data


def model_price(model: dict) -> float | None:
    value = model.get("price_factor")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def select_models(models: list[dict], max_price: float) -> tuple[list[dict], list[str]]:
    picked: list[dict] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for model in models:
        model_id = str(model.get("id") or model.get("name") or "").strip()
        if not model_id or model_id.lower() in seen:
            continue
        # Auto/Fast are routing aliases: they point at another model and have
        # no own price. Same exclusion as cn:auto / global:auto in WorkBuddy.
        upstream_key = str(model.get("upstream_key") or "").strip().lower()
        if model_id.lower() in ROUTING_ALIASES or upstream_key in ROUTING_ALIASES:
            skipped.append(f"{model_id} (routing alias)")
            continue
        if model.get("enabled") is False:
            skipped.append(f"{model_id} (disabled upstream)")
            continue
        price = model_price(model)
        if max_price > 0 and price is not None and price > max_price:
            skipped.append(f"{model_id} (price {price:g} > {max_price:g})")
            continue
        seen.add(model_id.lower())
        picked.append(model)
    # Free first, then by relative price; unknown price goes last. Name is the
    # stable tie-breaker so repeated runs produce the same order.
    picked.sort(
        key=lambda m: (
            model_price(m) is None,
            model_price(m) if model_price(m) is not None else 0.0,
            str(m.get("id") or "").lower(),
        )
    )
    return picked, skipped


def provider_rules(cfg: dict) -> list[dict]:
    rules = cfg["config"]["providerConfigRules"]
    if isinstance(rules, list):
        return rules
    return rules.setdefault("providerRules", [])


def model_rules(cfg: dict) -> list[dict]:
    rules = cfg["config"].setdefault("modelConfigRules", {})
    return rules.setdefault("providerModelRules", [])


def remove_merged_models(cfg: dict) -> int:
    """Remove every `qoder:` model from every provider and model rule."""
    removed = 0
    prefix = PREFIX.lower()
    for rule in provider_rules(cfg):
        config = rule.setdefault("config", {})
        for key in ("personalModelIds", "modelOrder"):
            ids = config.get(key) or []
            kept = [item for item in ids if not str(item).lower().startswith(prefix)]
            removed += len(ids) - len(kept)
            config[key] = kept
    entries = model_rules(cfg)
    before = len(entries)
    entries[:] = [
        entry for entry in entries
        if not str(entry.get("modelId") or "").lower().startswith(prefix)
    ]
    return removed + (before - len(entries))


def remove_separate_provider(cfg: dict) -> None:
    """Remove the old standalone `qoder` provider and its bare model rules."""
    rules = provider_rules(cfg)
    rules[:] = [rule for rule in rules if rule.get("providerId") != DEFAULT_PROVIDER_ID]
    order = cfg["config"].setdefault("providerOrder", [])
    order[:] = [provider for provider in order if provider != DEFAULT_PROVIDER_ID]
    entries = model_rules(cfg)
    entries[:] = [
        entry for entry in entries
        if entry.get("providerId") != DEFAULT_PROVIDER_ID
    ]


def provider_rule(models: list[dict], key: str, base: str, provider_id: str,
                  provider_name: str, group: str) -> dict:
    ids = [str(m.get("id") or "").strip() for m in models]
    return {
        "providerId": provider_id,
        "providerName": provider_name,
        "config": {
            "group": group,
            "access": {"type": "api-key", "apiKey": key},
            "api": {"type": "openai-chat-completions", "baseUrl": base.rstrip("/")},
            "personalModelIds": ids,
            "modelOrder": ids,
        },
    }


def upsert_provider(cfg: dict, rule: dict, order_after: str) -> str:
    rules = provider_rules(cfg)
    provider_id = rule["providerId"]
    for index, existing in enumerate(rules):
        if existing.get("providerId") == provider_id:
            rules[index] = rule
            action = "updated"
            break
    else:
        rules.append(rule)
        action = "added"

    order = cfg["config"].setdefault("providerOrder", [])
    if provider_id not in order:
        if order_after and order_after in order:
            order.insert(order.index(order_after) + 1, provider_id)
        else:
            order.append(provider_id)
    return action


def upsert_model_rules(cfg: dict, models: list[dict], provider_id: str) -> int:
    entries = model_rules(cfg)
    entries[:] = [entry for entry in entries if entry.get("providerId") != provider_id]
    for model in models:
        entries.append({
            "modelId": str(model.get("id") or "").strip(),
            "config": {"enabled": True},
            "providerId": provider_id,
        })
    return len(models)


def tier_of(price: float | None) -> str | None:
    if price is None:
        return None
    if price <= 0:
        return "free"
    if price <= LOW_MAX:
        return "low"
    return "high"


def merge_models(cfg: dict, models: list[dict]) -> tuple[list[tuple[str, str, str, float]], list[str]]:
    """Merge Qoder models into the existing chat tiers with the qoder: prefix."""
    remove_merged_models(cfg)
    remove_separate_provider(cfg)
    by_id = {rule.get("providerId"): rule for rule in provider_rules(cfg)}
    for target_id in MERGE_TARGETS.values():
        if target_id not in by_id:
            raise SystemExit(f"provider 不存在：{target_id}（先跑 Go/WorkBuddy 同步建立五个 chat 组）")

    entries = model_rules(cfg)
    added: list[tuple[str, str, str, float]] = []
    skipped: list[str] = []
    for model in models:
        model_id = str(model.get("id") or "").strip()
        price = model_price(model)
        tier = tier_of(price)
        if tier is None:
            skipped.append(f"{model_id} (no price_factor)")
            continue
        target_id = MERGE_TARGETS[tier]
        prefixed = PREFIX + model_id
        config = by_id[target_id].setdefault("config", {})
        for key in ("personalModelIds", "modelOrder"):
            ids = config.setdefault(key, [])
            if prefixed not in ids:
                ids.append(prefixed)
        entries.append({
            "modelId": prefixed,
            "config": {"enabled": True},
            "providerId": target_id,
        })
        added.append((tier, target_id, model_id, price))
    return added, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="写入 provider_config.json（默认只预演）")
    parser.add_argument("--base-url", default=DEFAULT_BASE, help=f"qoder2api-hub 的 /v1 地址（默认 {DEFAULT_BASE}）")
    parser.add_argument("--api-key", help="Qoder API key；缺省读 QD_API_KEY 或 qoder/.env.local")
    parser.add_argument("--config", help="provider_config.json 路径")
    parser.add_argument("--separate", action="store_true",
                        help="不合并，写独立的 qoder provider（旧模式）")
    parser.add_argument("--provider-id", default=DEFAULT_PROVIDER_ID)
    parser.add_argument("--provider-name", default=DEFAULT_PROVIDER_NAME)
    parser.add_argument("--group", default=DEFAULT_GROUP)
    parser.add_argument("--max-price", type=float, default=DEFAULT_MAX_PRICE,
                        help=f"price_factor 上限（默认 {DEFAULT_MAX_PRICE}；0 = 不设上限）")
    parser.add_argument("--order-after", default=DEFAULT_ORDER_AFTER,
                        help=f"separate 模式插入位置（默认 {DEFAULT_ORDER_AFTER}）")
    parser.add_argument("--probe-file",
                        help="qoder_probe_zcode.py 的结果；只保留 status=ok 的模型")
    args = parser.parse_args()

    key = resolve_api_key(args.api_key)
    path = config_path(args.config)
    if not path.exists():
        raise SystemExit(f"找不到 ZCode 配置：{path}")

    models, skipped = select_models(fetch_models(args.base_url, key), args.max_price)
    transient_kept: list[str] = []
    if args.probe_file:
        probe_path = Path(args.probe_file).expanduser()
        if not probe_path.exists():
            raise SystemExit(f"找不到探测结果：{probe_path}")
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        kept: list[dict] = []
        transient = {"queued", "timeout", "rate_limited"}
        for model in models:
            model_id = str(model.get("id") or "").strip()
            entry = probe.get(model_id) or {}
            status = entry.get("status")
            if status == "ok":
                kept.append(model)
            elif status in transient and entry.get("ever_ok"):
                # A model that has answered 200 before is not dead just
                # because the upstream queue is busy right now. Keep it; the
                # next probe will confirm. A never-ok model (e.g. the heavily
                # queued free Qwen3.8-Flash) still has to earn its first 200.
                kept.append(model)
                transient_kept.append(f"{model_id} (probe {status}, previously ok)")
            else:
                skipped.append(f"{model_id} (probe {status or 'not probed'})")
        models = kept
    if not models:
        raise SystemExit("Qoder 清单里没有可写入的模型")

    cfg = json.loads(path.read_text(encoding="utf-8"))
    if args.separate:
        merged_removed = remove_merged_models(cfg)
        rule = provider_rule(models, key, args.base_url, args.provider_id, args.provider_name, args.group)
        action = upsert_provider(cfg, rule, args.order_after)
        rule_count = upsert_model_rules(cfg, models, args.provider_id)
        print(f"Qoder provider: {args.provider_id} ({args.provider_name}) -> {args.base_url}")
        print(f"模型 {len(models)} 个（{action}，{rule_count} 条 model rule）：")
        for model in models:
            price = model_price(model)
            price_text = "free" if price == 0 else ("?" if price is None else f"x{price:g}")
            efforts = model.get("reasoning_efforts") or []
            effort_text = "/".join(str(x) for x in efforts) if efforts else "-"
            print(f"  {str(model.get('id')):<22} {price_text:<8} efforts={effort_text}")
        if merged_removed:
            print(f"已从五个 chat 组清掉 {merged_removed} 条旧的 qoder: 条目")
        print(f"providerOrder: {cfg['config'].get('providerOrder')}")
        backup_name = "provider_config.json.bak-qoder-" + time.strftime("%Y%m%d-%H%M%S")
    else:
        added, merge_skipped = merge_models(cfg, models)
        skipped.extend(merge_skipped)
        print("合并模式：Qoder 模型并入现有 chat 组（前缀 qoder:）")
        for tier, target_id, model_id, price in added:
            price_text = "free" if price == 0 else f"x{price:g}"
            print(f"  {PREFIX + model_id:<28} -> {target_id:<24} {price_text}")
        print("目标组：")
        for tier, target_id in MERGE_TARGETS.items():
            rule = next((r for r in provider_rules(cfg) if r.get("providerId") == target_id), None)
            ids = (rule or {}).get("config", {}).get("personalModelIds") or []
            print(f"  {target_id:<24} {len(ids)} 个模型（其中 qoder: {sum(1 for x in ids if str(x).startswith(PREFIX))}）")
        print(f"providerOrder: {cfg['config'].get('providerOrder')}")
        backup_name = "provider_config.json.bak-qoder-merge-" + time.strftime("%Y%m%d-%H%M%S")

    if skipped:
        print("跳过：")
        for item in skipped:
            print(f"  {item}")
    if transient_kept:
        print("保留（瞬时限流/排队，曾探测 ok）：")
        for item in transient_kept:
            print(f"  {item}")

    if not args.apply:
        print("dry run；加 --apply 写入（会先备份 provider_config.json）")
        return 0

    backup = path.with_name(backup_name)
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp-qoder")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print(f"已写入 {path}（备份：{backup.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
