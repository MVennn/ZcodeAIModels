#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取 WorkBuddy2API 网关的模型价格表，写入 cache/wb_pricing.json。

适用范围
--------
**这是 WorkBuddy 侧的接入器**，不是通用框架 —— 它认的是 WorkBuddy2API 网关的
目录接口与字段。接别的供应商时**照这个结构再写一份**：

1. 换成你自己的目录接口地址（`fetch_models()` 里那一行）；
2. 把上游条目归一化成**同一套字段**（下面那张表）—— 归一化之后，
   分档脚本（`workbuddy_zcode_sync.py`）就不用改；
3. 保留「写前备份 + 打印变动摘要」这两条约定。

为什么需要这个脚本
------------------
`wb_pricing.json` 是 `workbuddy_zcode_sync.py` 的**唯一价格输入**：
分档（免代 / 低代 / 高代）完全依赖它里面的 `eff_rate`。
在它出现之前，这张表只能手工维护 —— 改一次套餐就得手改一次 JSON，
这是本仓最实质的工程缺口。本脚本把它变成一条命令。

数据源
------
`GET {WB_GATEWAY_BASE}/panel/api/models` → `{"models": [ ... ]}`

每个模型会被**归一化**成下面这组字段（与 `workbuddy_zcode_sync.py` 的消费方式一致）：

| 字段 | 含义 | 上游来源（按优先级尝试） |
|---|---|---|
| `id` | 模型标识 | `id` / `name` / `model` / `model_id` |
| `credits` | 标价原文 | `credits` |
| `promo` | 促销价原文 | `promo_credits` / `promo` |
| `list_rate` | 标价倍率（float） | 从 `credits` 里抽数字 |
| `eff_rate` | 实际倍率（float） | 从 `promo` 抽数字；没有就等于 `list_rate` |
| `promo_label` | 促销标签 | `promo_label` |
| `ctx` | 上下文窗口 | `context_length` / `max_allowed_size` |
| `out` | 最大输出 | `max_output_tokens` / `max_output` |
| `tool` | 是否支持工具调用 | `supports_tool_call` / `tool_call` |
| `img` | 是否支持图片输入 | `supports_images` / `supports_image` / `image` |
| `efforts` | 支持的推理档位 | `efforts` / `supported_efforts` |
| `default_effort` | 默认推理档位 | `default_effort` |
| `can_disable` | 是否可关闭思考 | `can_disable_thinking` / `can_disable` |
| `only_reasoning` | 是否仅推理模型 | `only_reasoning` |

用法
----
    # 默认：写 cache/wb_pricing.json（先备份旧的）
    python workbuddy_fetch_pricing.py

    # 只看会变成什么样，不落盘
    python workbuddy_fetch_pricing.py --dry-run

    # 指定输出位置
    python workbuddy_fetch_pricing.py --output cache/wb_pricing.json

    # 确认是真实的大规模下架，跳过“列表骤降”保护
    python workbuddy_fetch_pricing.py --force

环境变量
--------
| 变量 | 默认 | 说明 |
|---|---|---|
| `WB_GATEWAY_BASE` | `http://127.0.0.1:7863` | 网关地址 |
| `WB_GATEWAY_KEY` | 空 | 网关 api_key（本地面板通常不需要） |
| `WB_PRICING_FILE` | `cache/wb_pricing.json` | 输出路径 |

退出码：0 成功 / 1 失败。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
CACHE_DIR = HERE / "cache"

GATEWAY_BASE = os.environ.get("WB_GATEWAY_BASE", "http://127.0.0.1:7863")
GATEWAY_KEY = os.environ.get("WB_GATEWAY_KEY", "")
DEFAULT_OUTPUT = Path(
    os.environ.get("WB_PRICING_FILE", CACHE_DIR / "wb_pricing.json")
)

# 从 "x0.29" / "0.29 credits" 这类串里抽第一个数字
_NUM = re.compile(r"(\d+(?:\.\d+)?)")


def _first(model: dict, *keys, default=None):
    """按顺序取第一个存在且非空的键。"""
    for k in keys:
        v = model.get(k)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, dict)) and not v:
            continue
        return v
    return default


def _as_float(raw) -> float | None:
    if raw is None:
        return None
    m = _NUM.search(str(raw))
    return float(m.group()) if m else None


def _as_int(raw) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _as_bool(raw) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        return raw.strip().lower() in ("1", "true", "yes", "y", "on")
    return False


# 免费模型按 `-f` 后缀命名；纯路由别名没有自己的价格（解析到下层模型）。
FREE_SUFFIX = "-f"
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


def normalize(model: dict) -> dict | None:
    """把上游的一个模型条目归一化成价格表的一行。"""
    mid = _first(model, "id", "name", "model", "model_id")
    if not mid:
        return None
    mid = str(mid)

    credits = _first(model, "credits", default="")
    promo = _first(model, "promo_credits", "promo", default="")
    list_rate = _as_float(credits)
    eff_rate = _as_float(promo)
    if eff_rate is None:
        eff_rate = list_rate

    # 网关没公布价格时保留 None（下游 rate_of 会返回 None 并跳过该模型），
    # 不能归零 —— 归零会让付费模型被分到"免费"档。只有显式免费的
    # `-f` 模型和纯路由别名才补 0.0。
    if list_rate is None and not (mid.endswith(FREE_SUFFIX) or mid in ALIAS_IDS):
        list_rate = None
        eff_rate = None
    else:
        if list_rate is None:
            list_rate = 0.0
        if eff_rate is None:
            eff_rate = list_rate

    efforts = _first(model, "efforts", "supported_efforts", default=[])
    if isinstance(efforts, str):
        efforts = [e.strip() for e in efforts.split(",") if e.strip()]

    ctx = _as_int(_first(model, "context_length", "max_allowed_size", default=0))
    out = _as_int(_first(model, "max_output_tokens", "max_output", default=0))
    if ctx > 0 and out > ctx:
        out = ctx

    return {
        "id": mid,
        "credits": str(credits),
        "promo": str(promo),
        "list_rate": list_rate,
        "eff_rate": eff_rate,
        "promo_label": str(_first(model, "promo_label", default="") or ""),
        "ctx": ctx,
        "out": out,
        "tool": _as_bool(_first(model, "supports_tool_call", "tool_call", default=False)),
        "img": _as_bool(_first(model, "supports_images", "supports_image", "image", default=False)),
        "efforts": efforts if isinstance(efforts, list) else [],
        "default_effort": str(_first(model, "default_effort", default="") or ""),
        "can_disable": _as_bool(_first(model, "can_disable_thinking", "can_disable", default=False)),
        "only_reasoning": _as_bool(_first(model, "only_reasoning", default=False)),
    }


def fetch_models(base: str, key: str, timeout: int = 25) -> list[dict]:
    url = base.rstrip("/") + "/panel/api/models"
    req = urllib.request.Request(url)
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"连不上 WorkBuddy2API 网关 {base}（{e.reason}）。\n"
            f"  先确认 WorkBuddy2API 面板在跑，或用 WB_GATEWAY_BASE 指定别的地址。\n"
            f"  （本脚本是 WorkBuddy 侧的接入器；接别的供应商请照同样的结构另写一份，"
            f"换掉取数接口与字段映射即可。）"
        ) from e
    if not isinstance(payload, dict):
        raise RuntimeError(
            "WorkBuddy2API 面板返回的不是预期结构（应为 {\"models\": [...]}）"
        )
    models = payload.get("models") or []
    if not models:
        raise RuntimeError("WorkBuddy2API 面板返回了空的模型列表")
    return models


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取 WorkBuddy 网关价格表")
    ap.add_argument("--base", default=GATEWAY_BASE, help="网关地址（默认 %(default)s）")
    ap.add_argument("--api-key", default=GATEWAY_KEY, help="网关 api_key（默认取 WB_GATEWAY_KEY）")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出路径（默认 %(default)s）")
    ap.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    ap.add_argument("--force", action="store_true", help="列表骤降时仍然写入（确认是真实下架）")
    ap.add_argument("--timeout", type=int, default=25, help="请求超时秒数（默认 %(default)s）")
    args = ap.parse_args()

    print(f"→ 拉取 {args.base}/panel/api/models")
    try:
        raw = fetch_models(args.base, args.api_key, args.timeout)
    except RuntimeError as e:
        print(f"!! {e}", file=sys.stderr)
        return 1

    rows = []
    skipped = 0
    for m in raw:
        row = normalize(m)
        if row is None:
            skipped += 1
            continue
        rows.append(row)
    rows.sort(key=lambda r: r["id"])

    priced = [r for r in rows if isinstance(r["eff_rate"], (int, float)) and r["eff_rate"] > 0]
    print(f"   上游 {len(raw)} 条 → 归一化 {len(rows)} 条（跳过无 id 的 {skipped} 条）")
    print(f"   有价格的 {len(priced)} 条")

    # 变动摘要：与旧文件逐条对比
    out = Path(args.output)
    old: dict[str, dict] = {}
    if out.exists():
        try:
            old = {m["id"]: m for m in json.loads(out.read_text(encoding="utf-8"))}
        except Exception:
            old = {}
    new = {r["id"]: r for r in rows}
    changed = [k for k in new if k in old and old[k].get("eff_rate") != new[k].get("eff_rate")]
    added = [k for k in new if k not in old]
    removed = [k for k in old if k not in new]
    if changed:
        print("   倍率变化：")
        for k in changed:
            print(f"     {k}: {old[k].get('eff_rate')} → {new[k].get('eff_rate')}")
    if added:
        print(f"   新增 {len(added)} 个：{', '.join(added[:8])}{' …' if len(added) > 8 else ''}")
    if removed:
        print(f"   下架 {len(removed)} 个：{', '.join(removed[:8])}{' …' if len(removed) > 8 else ''}")

    # 安全阀：网关偶尔会返回残缺列表（例如只剩 global 池）。数量骤降时不覆盖
    # 旧表，否则下游同步会把正常模型当成“已下架”从配置里删掉。
    if old and len(rows) < len(old) * 0.7:
        pct = 100 - len(rows) * 100 // len(old)
        print(
            f"!! 上游返回 {len(rows)} 条，旧表 {len(old)} 条，减少 {pct}%；疑似网关临时残缺。",
            file=sys.stderr,
        )
        if removed:
            print(f"   被判定为下架的 {len(removed)} 个：{', '.join(removed)}", file=sys.stderr)
        if not args.force and not args.dry_run:
            print("   未写入；确认是真实下架后加 --force 重跑。", file=sys.stderr)
            return 2

    if args.dry_run:
        print("（--dry-run，未写文件）")
        print(json.dumps(rows[:3], ensure_ascii=False, indent=2))
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        bak = out.with_suffix(out.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(out, bak)
        print(f"   旧文件已备份到 {bak.name}")
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 已写入 {out}（{len(rows)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
