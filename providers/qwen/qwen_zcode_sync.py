#!/usr/bin/env python3
"""Warm-start ZCode with the Qwen platform's free-quota models.

What this does
--------------
The 千问 AI 平台 (platform.qianwenai.com, gateway maas.qianwenaiapi.com) hands out
a per-model free quota (1M tokens each) but exposes **only** the Anthropic
Messages protocol and **no** `/v1/models` listing. This script therefore:

1. reads a catalog snapshot (`cache/freetier_<date>.txt`, produced from the
   console's 权益 page) or optionally fetches `/api/models`;
2. collapses dated snapshots onto one canonical id per family;
3. picks a curated subset (`DEFAULT_MODELS`) or every chat-capable family
   (`--all-chat`);
4. writes them into the existing 免费 tier as `qwen:<id>`, which
   `tools/model_alias.py` then normalizes into `<型号>-Msg` display names.

Why the `qwen:` prefix
----------------------
The platform speaks `anthropic-messages`, so `gateways/zgate` bridges these
models (chat in, Messages out). The prefix lets the router resolve the channel
before the alias map is regenerated, exactly like the `qoder:` prefix.

Why so few models by default
----------------------------
506 free entries collapse to 209 chat-capable models / 118 families. Putting
them all into one ZCode group is unusable in the picker, and each one costs a
non-streaming bridge round-trip. The default list is the flagships plus one
model per vendor; use `--all-chat` only for a deliberate quota burn.

Usage
-----
    python providers/qwen/qwen_zcode_sync.py                    # dry run
    python providers/qwen/qwen_zcode_sync.py --apply            # backup + write
    python providers/qwen/qwen_zcode_sync.py --all-chat         # every family
    python providers/qwen/qwen_zcode_sync.py --only qwen3.8-max,glm-5.3
    python providers/qwen/qwen_zcode_sync.py --probe-file ~/.zcode/v2/model_probe.json --apply
    python providers/qwen/qwen_zcode_sync.py --fetch            # try /api/models first

Credentials never reach stdout or the repository: the key is read from
`$QWEN_API_KEY` or `providers/qwen/.env.local` (gitignored).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CATALOG = HERE / "cache" / "freetier_20261028.txt"
DEFAULT_BASE = os.environ.get("QWEN_BASE", "https://maas.qianwenaiapi.com/apps/anthropic")
DEFAULT_MODELS_API = "https://maas.qianwenaiapi.com/api/models"
PREFIX = "qwen:"
TARGET_PROVIDER = "opencode-go-chat-free"

# Flagships + one representative per vendor. Each entry is a canonical id from
# the console's free-tier page; dated snapshots collapse onto these.
DEFAULT_MODELS = [
    # 唯一保留的单型号：它是主力 `DeepSeek-4.1-Flash` 三跳链的尾跳（¥300 预付额度）。
    # 其余千问模型一律只作为池子的跳出现 —— 单跳条目额度一旦烧完就是硬 403，
    # 没有下一跳可退，用户看到的就是「auth failed」。池子至少有 9~21 跳可退。
    "deepseek-v4.1-flash",
]

# Non-chat families that happen to carry a token quota (embedding / rerank /
# ASR / TTS / OCR / omni / realtime ...). Kept out of every selection.
NON_CHAT = re.compile(
    r"embedding|rerank|asr|tts|ocr|captioner|intent|-mt-|mt-image|livetranslate|"
    r"voice|audio|omni|realtime|image|video|^wan|wanx|wordart|sambert|cosyvoice|"
    r"sensevoice|paraformer|gummy|fun-music|fun-asr|animate|aitryon|liveportrait|"
    r"videoretalk|^emo|emoji|z-image|happyhorse|avatar|style-transform|"
    r"out-painting|sketch|repaint|background-generation|xiaomi|character|"
    r"opennlu|gui-plus|qwen-long",
    re.I,
)


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
    if os.environ.get("QWEN_API_KEY"):
        return os.environ["QWEN_API_KEY"].strip()
    key = (read_env_file(HERE / ".env.local").get("QWEN_API_KEY") or "").strip()
    if not key:
        raise SystemExit("缺少千问 API key：设置 QWEN_API_KEY，或写进 providers/qwen/.env.local")
    return key


def config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ZCODE_PERSONAL_PROVIDER_CONFIG_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "provider_config.json"


def family_of(model_id: str) -> str:
    """Collapse a dated / latest / preview snapshot onto its family key."""
    key = model_id.lower()
    key = re.sub(r"-(latest|preview|exp)$", "", key)
    key = re.sub(r"-\d{4}-\d{2}-\d{2}$", "", key)
    key = re.sub(r"-\d{4}$", "", key)
    return key


def read_catalog(path: Path) -> dict[str, list[str]]:
    """Parse `family <= id,id,...` lines written from the console snapshot."""
    families: dict[str, list[str]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return families
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "<=" not in line:
            continue
        family, ids = line.split("<=", 1)
        ids = [item.strip() for item in ids.split(",") if item.strip()]
        if ids:
            families[family.strip().lower()] = ids
    return families


def fetch_catalog(key: str, timeout: int = 20) -> dict[str, list[str]]:
    """Best effort: the console's /api/models endpoint is undocumented and flaky.

    It answers `{"output":{"total":N,"page_no":..,"page_size":..,"models":[...]}}`
    for a Bearer workspace key, but returns 404 on some edge nodes. Treat a
    failure as "no catalog" and let the caller fall back to the snapshot.
    """
    families: dict[str, list[str]] = {}
    url = DEFAULT_MODELS_API
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"WARN: {url} 不可用（{exc}），改用本地快照", file=sys.stderr)
        return families
    rows = ((payload.get("output") or {}).get("models")) or []
    for row in rows:
        model_id = str(row.get("model") or row.get("id") or "").strip()
        if model_id:
            families.setdefault(family_of(model_id), []).append(model_id)
    if rows:
        print(f"目录来源：{url}（{len(rows)} 条，page_size="
              f"{(payload.get('output') or {}).get('page_size')}）")
    return families


def canonical(family: str, ids: list[str]) -> str:
    """Prefer the undated id; otherwise the lexicographically last snapshot."""
    for candidate in ids:
        if candidate.lower() == family:
            return candidate
    return sorted(ids)[-1]


# 集合体已停用（2026-10-29）：千问每模型只有 1M 免费 tokens，用户每天 18.6 亿的用量
# 意味着一个模型 30 秒就烧完。全部 114 个模型加起来也只值约 1.5 小时，而维持池子需要
# 每天探测 + 重建，还要处理单跳额度耗尽后的硬 403。收益远低于维护成本，故清空。
# 需要恢复时把 POOL_SPECS 加回来并跑 --write-pools --probe-file。
POOL_SPECS: list[tuple[str, str, str]] = []
VENDOR_ORDER = ("qwen", "deepseek", "glm", "kimi", "minimax", "qwq", "qvq", "other")


def vendor_of(model_id: str) -> str:
    m = model_id.lower()
    if m.startswith("qwen"): return "qwen"
    if m.startswith("qwq"): return "qwq"
    if m.startswith("qvq"): return "qvq"
    if m.startswith("deepseek"): return "deepseek"
    if m.startswith("glm"): return "glm"
    if m.startswith("kimi") or m.startswith("moonshot"): return "kimi"
    if m.startswith("minimax"): return "minimax"
    return "other"


def series_version(model_id: str) -> float:
    """取 id 里第一个版本号（`qwen3.8-max` → 3.8，`qwen3-235b-a22b` → 3.0）。"""
    found = re.search(r"(\d+(?:\.\d+)?)", model_id.lower())
    try:
        return float(found.group(1)) if found else 0.0
    except ValueError:
        return 0.0


# 三方模型的名字里没有 max / plus / flash 这类档位词，按世代手工归位。
THIRD_PARTY_TIER = {
    "glm-5.3": 3.0, "glm-5.2": 2.8, "glm-5.1": 2.6, "glm-5": 2.5,
    "kimi-k3": 3.0, "kimi-k2.7-code": 2.6, "kimi-k2.6": 2.2,
    "kimi-k2.5": 2.0, "kimi-k2-thinking": 1.8,
    "moonshot-kimi-k2-instruct": 2.0,
    "minimax-m2.5": 2.8, "minimax-m2.1": 1.5,
    "deepseek-v4-pro": 2.8, "deepseek-v4.1-flash": 1.2, "deepseek-v4-flash": 1.0,
    "deepseek-v3.2": 1.6, "deepseek-v3.1": 1.4, "deepseek-v3": 1.2,
    "deepseek-r1": 2.0,
    "qvq-max": 3.0, "qvq-plus": 2.0, "qwq-plus": 2.0, "qwq-32b": 2.0,
}


def tier_of(model_id: str) -> float:
    """档位启发式：max/pro > coder/plus > flash/turbo > air/lite > 其余。"""
    m = model_id.lower()
    if m in THIRD_PARTY_TIER:
        return THIRD_PARTY_TIER[m]
    if m.startswith("deepseek-r1-distill"):
        return 1.0
    if re.search(r"(^|-)max($|-)", m) or "a95b" in m or "a17b" in m or "-2.4t" in m:
        return 3.0
    if m.endswith("-pro") or "-pro-" in m or "-v4-pro" in m:
        return 2.8
    if "coder" in m:
        return 2.5
    if "plus" in m:
        return 2.0
    if "flash" in m or "turbo" in m:
        return 1.0
    if "air" in m or "lite" in m:
        return 0.8
    if "thinking" in m:
        return 1.5
    return 1.2


def select(families: dict[str, list[str]], only: list[str] | None,
           all_chat: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """Return [(id, family)] plus the skip reasons."""
    picked: list[tuple[str, str]] = []
    skipped: list[str] = []

    if only:
        index = {candidate.lower(): (candidate, fam) for fam, ids in families.items()
                 for candidate in ids}
        for wanted in only:
            hit = index.get(wanted.lower())
            if hit is None:
                skipped.append(f"{wanted} (不在目录里)")
                continue
            picked.append(hit)
        return picked, skipped

    if all_chat:
        for fam in sorted(families):
            if NON_CHAT.search(fam):
                skipped.append(f"{fam} (非对话模型)")
                continue
            picked.append((canonical(fam, families[fam]), fam))
        return picked, skipped

    index = {candidate.lower(): (candidate, fam) for fam, ids in families.items()
             for candidate in ids}
    for wanted in DEFAULT_MODELS:
        hit = index.get(wanted.lower())
        if hit is None:
            # Not in this snapshot: still seed it, the probe decides.
            picked.append((wanted, wanted))
            continue
        picked.append(hit)
    return picked, skipped


def interleave(rows: list[tuple[float, float, str, str]]) -> list[str]:
    """按厂商轮转排：同厂商的连续型号不挨着，一家挂了下一跳就换公司。"""
    buckets: dict[str, list[str]] = {}
    for _tier, _version, vendor, model_id in rows:
        buckets.setdefault(vendor, []).append(model_id)
    order = [v for v in VENDOR_ORDER if v in buckets] + \
            sorted(v for v in buckets if v not in VENDOR_ORDER)
    out: list[str] = []
    while any(buckets[v] for v in order):
        for vendor in order:
            if buckets[vendor]:
                out.append(buckets[vendor].pop(0))
    return out


def is_open_weight(model_id: str) -> bool:
    """带参数量后缀（235b / 480b / a22b / 2.4t-a95b）的是开源权重版，排在托管旗舰之后。"""
    m = model_id.lower()
    return bool(re.search(r"\d+(\.\d+)?[bt](?=-|$)", m)) or bool(re.search(r"a\d+b", m))


def build_pools(families: dict[str, list[str]]) -> dict:
    """把 118 个家族编成 3 个集合体：旗舰 / 代码 / 快速。

    分池只做三件事：`coder` 进代码池；非开源权重且档位 ≥2.8 进旗舰池；
    其余按档位降序进快速池。池内再按「档位 → 版本 → 名字长度」排序，
    最后用厂商轮转打散，保证相邻两跳不是同一家。
    """
    if not POOL_SPECS:
        return {"version": 1, "source": "providers/qwen/cache/freetier_*.txt",
                "note": "集合体已停用（2026-10-29，见 POOL_SPECS 注释）", "pools": []}
    buckets: dict[str, list[tuple[float, float, int, str, str]]] = {p[2]: [] for p in POOL_SPECS}
    for family in families:
        if NON_CHAT.search(family):
            continue
        model_id = canonical(family, families[family])
        tier = tier_of(model_id)
        if "coder" in model_id.lower() or "-code" in model_id.lower():
            pool = "max"
        elif tier >= 2.8 and not is_open_weight(model_id):
            pool = "max"
        else:
            pool = "fast"
        buckets[pool].append((tier, series_version(model_id), len(model_id),
                              vendor_of(model_id), model_id))
    pools = []
    for name, label, key in POOL_SPECS:
        ranked = sorted(buckets[key], key=lambda r: (-r[0], -r[1], r[2],
                                                     VENDOR_ORDER.index(r[3]) if r[3] in VENDOR_ORDER else 99,
                                                     r[4]))
        hops = interleave([(t, v, vendor, mid) for t, v, _n, vendor, mid in ranked])
        pools.append({"name": name, "label": label, "hops": hops})
    return {"version": 1, "source": "providers/qwen/cache/freetier_*.txt",
            "note": "按档位+厂商编成的集合体；路由从第一跳开始逐个烧，失败即换下一跳",
            "pools": pools}


def provider_rules(cfg: dict) -> list[dict]:
    rules = cfg["config"]["providerConfigRules"]
    if isinstance(rules, list):
        return rules
    return rules.setdefault("providerRules", [])


def model_rules(cfg: dict) -> list[dict]:
    return cfg["config"].setdefault("modelConfigRules", {}).setdefault("providerModelRules", [])


def remove_prefixed(cfg: dict) -> int:
    """清掉上一轮的播种痕迹。

    `qwen:` 前缀的种子和已归一化的显示名都要清：归一化之后配置里只剩显示名，
    只认前缀会让每次 --apply 都在旧显示名旁边再叠一份新种子。
    """
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
    entries[:] = [entry for entry in entries
                  if not str(entry.get("modelId") or "").lower().startswith(prefix)]
    return removed + (before - len(entries))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="写入 provider_config.json（默认只预演）")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG),
                        help=f"目录快照（默认 {DEFAULT_CATALOG.name}）")
    parser.add_argument("--fetch", action="store_true",
                        help="先试 /api/models（接口不稳定，失败自动回落快照）")
    parser.add_argument("--all-chat", action="store_true",
                        help="收录全部对话家族（118 个，慎用）")
    parser.add_argument("--only", help="只收这些 id（逗号分隔，精确匹配）")
    parser.add_argument("--config", help="provider_config.json 路径")
    parser.add_argument("--api-key", help="千问 API key（缺省读 QWEN_API_KEY / .env.local）")
    parser.add_argument("--probe-file",
                        help="tools/model_probe.py 的结果；只保留 ok（或曾 ok 的瞬时限流）")
    parser.add_argument("--write-pools", action="store_true",
                        help="从目录生成 pools.json（3 个集合体的跳序），不做其它事")
    args = parser.parse_args()

    families = {}
    if args.fetch:
        families = fetch_catalog(resolve_api_key(args.api_key))
    if not families:
        families = read_catalog(Path(args.catalog).expanduser())
    if not families:
        raise SystemExit(
            f"目录为空：{args.catalog}\n"
            "从 platform.qianwenai.com 的「权益」页导出一份 `family <= id,id` 快照，"
            "或用 --fetch 试 /api/models。"
        )

    if args.write_pools:
        plan = build_pools(families)
        # 池子也过探测筛：死跳会让路由逐个撞超时，用户体感就是首字极慢
        if args.probe_file:
            probe_path = Path(args.probe_file).expanduser()
            if probe_path.exists():
                probe = json.loads(probe_path.read_text(encoding="utf-8"))
                for pool in plan["pools"]:
                    before = len(pool["hops"])
                    pool["hops"] = [h for h in pool["hops"]
                                    if (probe.get(h) or {}).get("status") == "ok"
                                    or ((probe.get(h) or {}).get("status")
                                        in {"queued", "timeout", "rate_limited"}
                                        and (probe.get(h) or {}).get("ever_ok"))]
                    if len(pool["hops"]) < before:
                        print(f"  {pool['name']}: 探测筛掉 {before - len(pool['hops'])} 死跳"
                              f"（{before} → {len(pool['hops'])}）")
        out = HERE / "pools.json"
        out.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已写入 {out}")
        for pool in plan["pools"]:
            print(f"  {pool['name']:<14} {pool['label']}  {len(pool['hops'])} 跳")
            print("    " + " -> ".join(pool["hops"][:8]) + (" …" if len(pool["hops"]) > 8 else ""))
        print("下一步：python tools/model_alias.py --slot auto --apply")
        return 0

    only = [part.strip() for part in (args.only or "").split(",") if part.strip()]
    picked, skipped = select(families, only or None, args.all_chat)

    if args.probe_file:
        probe_path = Path(args.probe_file).expanduser()
        if not probe_path.exists():
            raise SystemExit(f"找不到探测结果：{probe_path}")
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        transient = {"queued", "timeout", "rate_limited"}
        kept = []
        for model_id, family in picked:
            entry = (probe.get(model_id) or probe.get(PREFIX + model_id)
                     or probe.get(family) or {})
            status = entry.get("status")
            if status == "ok" or (status in transient and entry.get("ever_ok")):
                kept.append((model_id, family))
            else:
                skipped.append(f"{model_id} (probe {status or 'not probed'})")
        picked = kept

    path = config_path(args.config)
    if not path.exists():
        raise SystemExit(f"找不到 ZCode 配置：{path}")
    cfg = json.loads(path.read_text(encoding="utf-8"))

    target = next((r for r in provider_rules(cfg) if r.get("providerId") == TARGET_PROVIDER), None)
    if target is None:
        raise SystemExit(f"provider 不存在：{TARGET_PROVIDER}（先跑一次 tools/model_alias.py --apply）")

    removed = remove_prefixed(cfg)
    entries = model_rules(cfg)
    config = target.setdefault("config", {})
    for key in ("personalModelIds", "modelOrder"):
        ids = config.setdefault(key, [])
        for model_id, _family in picked:
            prefixed = PREFIX + model_id
            if prefixed not in ids:
                ids.append(prefixed)
    for model_id, _family in picked:
        entries.append({
            "modelId": PREFIX + model_id,
            "config": {"enabled": True},
            "providerId": TARGET_PROVIDER,
        })

    print(f"千问：{len(picked)} 个模型 -> {TARGET_PROVIDER}（前缀 {PREFIX}）")
    for model_id, family in picked:
        note = "" if family == model_id.lower() else f"  (family {family})"
        print(f"  {PREFIX + model_id:<30}{note}")
    if removed:
        print(f"清掉旧的 {PREFIX} 条目：{removed}")
    if skipped:
        print("跳过：")
        for item in skipped:
            print(f"  {item}")

    if not args.apply:
        print("dry run；加 --apply 写入（会先备份 provider_config.json）")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + ".bak-qwen-" + stamp)
    shutil.copy2(path, backup)
    tmp = path.with_name(path.name + ".tmp-qwen")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print(f"已写入 {path}（备份：{backup.name}）")
    print("下一步：python tools/model_alias.py --slot auto --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
