#!/usr/bin/env python3
"""Pull the ArenaGalleri leaderboard and propose 主力 candidates.

The gallery at <https://gallery.arenaofbias.icu/#/leaderboard> is an SPA; its
data comes from:

    https://api.arenaofbias.icu/api/leaderboard

The response has ~240 `rows` (one per model x effort), `updatedAt` and
`refreshIntervalSeconds` (600). This script:

1. pulls the leaderboard (network, or the local cache when the API is down);
2. keeps the best non-provisional row per model with at least `--min-games`;
3. uses `deepseek-v4.1-flash` as the baseline;
4. walks the models in `model-alias-map.json` and keeps the entries whose score
   is within `--min-ratio` of the baseline and whose entry price is at most
   `--max-price` credits (0-credit models stay in 免费 unless `--allow-free`);
5. writes `~/.zcode/v2/arena-main.json` for `model_alias.py` to consume.

Price basis for selection is the *cheapest slot* (WorkBuddy `eff_rate`, Qoder
valley, OpenCode off-peak), so group membership does not wobble between peak
and off-peak. The display price still follows `model_alias.py --slot auto`.

Usage
-----
    python tools/arena_leaderboard.py                  # fetch once, print table
    python tools/arena_leaderboard.py --refresh        # force a network pull
    python tools/arena_leaderboard.py --refresh --write
    python tools/arena_leaderboard.py --refresh --apply  # also rewrite config
    python tools/arena_leaderboard.py --status           # show saved candidates

A model that drops out of the window on a later refresh falls back to its price
group, so 主力 stays honest instead of only ever growing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import model_alias as alias  # noqa: E402

LEADERBOARD_URL = "https://api.arenaofbias.icu/api/leaderboard"
GALLERY_URL = "https://gallery.arenaofbias.icu/#/leaderboard"
DEFAULT_CACHE = Path.home() / ".zcode" / "v2" / "arena-leaderboard.json"
DEFAULT_OUT = Path.home() / ".zcode" / "v2" / "arena-main.json"
DEFAULT_PROBE = Path.home() / ".zcode" / "v2" / "model_probe.json"

# Model names that differ only by vendor/region suffixes. Keys and values are
# already `canonical()` output (lowercase alphanumerics only).
CANONICAL_ALIASES = {
    "hy4previewf": "hy4preview",             # WorkBuddy free tier of HY4-Preview
    "deepseekv41flashsg": "deepseekv41flash",  # SG region variant
}


def canonical(name: str | None) -> str:
    """Fold a model name to a comparison key.

    `claude-haiku-5-5` and `claude-haiku-5.5` both become `claudehaiku55`,
    `muse-spark-1.3-contributor` becomes `musespark13`. Suffixes that denote a
    *different* model (`-next`, `-1017`, `-max`) are intentionally kept.
    """
    text = str(name or "").strip().lower()
    text = re.sub(r"-contributor$", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return CANONICAL_ALIASES.get(text, text)


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def fetch_leaderboard(cache: Path, refresh: bool, timeout: int) -> tuple[dict, str]:
    cached = read_json(cache) if cache.exists() else None
    if cached and not refresh:
        return cached, "cache"
    try:
        request = urllib.request.Request(
            LEADERBOARD_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": "ZCodeAIModels-arena/1.0",
            },
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload.get("rows"), list) or not payload["rows"]:
            raise ValueError("响应里没有 rows")
        payload["_fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_json(cache, payload)
        return payload, "network"
    except Exception as exc:
        if cached:
            print(f"warning: 榜单拉取失败（{exc}），用缓存 {cache}", file=sys.stderr)
            return cached, "stale-cache"
        raise SystemExit(f"榜单拉取失败，且没有缓存：{exc}")


def best_rows(rows: list[dict], min_games: int, allow_provisional: bool) -> dict[str, dict]:
    """Best row per model, ignoring provisional/short samples by default."""
    best: dict[str, dict] = {}
    for row in rows:
        name = row.get("model") or row.get("modelName")
        key = canonical(name)
        score = row.get("score")
        if not key or score is None:
            continue
        if row.get("provisional") and not allow_provisional:
            continue
        if int(row.get("games") or 0) < min_games:
            continue
        if key not in best or float(score) > float(best[key]["score"]):
            best[key] = row
    return best


def make_pricer() -> Callable[[dict], float | None]:
    wb = alias.wb_prices()
    qd = alias.qd_prices()

    def price(entry: dict) -> float | None:
        # Off-peak/valley/eff is the stable entry price. Peak rewrites then
        # never change main membership.
        return alias.price_of(str(entry.get("channel") or ""),
                              str(entry.get("upstream") or ""),
                              wb, qd, "offpeak")

    return price


def load_models(path: Path) -> dict[str, dict]:
    data = read_json(path)
    if not data:
        raise SystemExit(f"读不到 alias map：{path}（先跑 model_alias.py）")
    return data.get("models") or {}


def candidates(models: dict[str, dict], best: dict[str, dict], baseline: dict,
               max_price: float, min_ratio: float, price_of,
               allow_free: bool = False) -> tuple[list[dict], list[dict]]:
    base_score = float(baseline["score"])
    picked: list[dict] = []
    near: list[dict] = []
    for display, entry in models.items():
        key = canonical(entry.get("base_model") or entry.get("upstream"))
        row = best.get(key)
        if row is None:
            continue
        price = price_of(entry)
        if price is None:
            continue
        if price <= 0 and not allow_free:
            # 0 积分模型留在免费组，否则免费组会被主力抽空。
            continue
        ratio = float(row["score"]) / base_score
        item = {
            "display": display,
            "channel": str(entry.get("channel") or ""),
            "upstream": str(entry.get("upstream") or ""),
            "base_model": str(entry.get("base_model") or entry.get("upstream") or ""),
            "price": round(float(price), 4),
            "score": row.get("score"),
            "ratio": round(ratio, 4),
            "rank": row.get("rank"),
            "model": row.get("model") or row.get("modelName"),
            "effort": row.get("effort") or "",
            "games": row.get("games"),
            "provisional": bool(row.get("provisional")),
        }
        if ratio >= min_ratio and price <= max_price:
            picked.append(item)
        elif ratio >= min_ratio - 0.05 and price <= max_price * 1.5:
            item["miss"] = "价格超限" if ratio >= min_ratio else "分数偏低"
            near.append(item)
    picked.sort(key=lambda row: (-float(row["ratio"]), float(row["price"]), row["display"]))
    near.sort(key=lambda row: (-float(row["ratio"]), float(row["price"])))
    return picked, near


def same_candidates(left: list[dict], right: list[dict]) -> bool:
    def keys(rows):
        return {(row["channel"], row["upstream"]) for row in rows}
    return keys(left) == keys(right)


def print_table(payload: dict, source: str, candidates: list[dict], near: list[dict],
                baseline: dict, args: argparse.Namespace) -> None:
    rows = payload.get("rows") or []
    totals = payload.get("totals") or {}
    print(f"榜单：{GALLERY_URL}")
    print(f"  来源 {source}  更新 {payload.get('updatedAt')}  "
          f"{len(rows)} 行 / {totals.get('tasks', '?')} 题  "
          f"刷新间隔 {payload.get('refreshIntervalSeconds', '?')} 秒")
    print(f"基准：{baseline.get('model')} #{baseline.get('rank')} "
          f"{baseline.get('score')}（{baseline.get('effort') or '-'}，{baseline.get('games')} 局）")
    print(f"窗口：分数 ≥ {args.min_ratio:.0%} 基准、积分 ≤ {args.max_price:g}"
          f"（按谷价/eff 判）、非临时名次、≥{args.min_games} 局"
          + ("" if args.allow_free else "、不含 0 积分"))

    print(f"\n主力扩充（{len(candidates)}）：")
    for row in candidates:
        print(f"  {row['display']:<34} {row['score']:>6.0f} "
              f"({row['ratio'] * 100:5.1f}%)  #{str(row['rank']):<3} "
              f"{row['model']} [{row['effort'] or '-'}]  {row['games']} 局  "
              f"up={row['upstream']}")
    if near:
        print("\n接近但未入选：")
        for row in near[:8]:
            print(f"  {row['display']:<34} {row['score']:>6.0f} "
                  f"({row['ratio'] * 100:5.1f}%)  积分 {row['price']:g}  {row['miss']}")


def status(out: Path) -> int:
    data = read_json(out)
    if not data:
        print(f"没有候选文件：{out}")
        return 1
    print(f"候选文件：{out}")
    print(f"  检查时间 {data.get('checked_at')}  榜单更新 {data.get('leaderboard_updated_at')}")
    base = data.get("baseline") or {}
    print(f"  基准 {base.get('model')} #{base.get('rank')} {base.get('score')}")
    rows = data.get("candidates") or []
    print(f"  候选 {len(rows)}：")
    for row in rows:
        print(f"    {row['display']:<34} {row.get('score')} "
              f"({float(row.get('ratio') or 0) * 100:.1f}%)  up={row.get('upstream')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true",
                        help="联网重拉；不带时优先用缓存")
    parser.add_argument("--force", action="store_true",
                        help="榜单 updatedAt 未变也重算/写盘")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--alias-map", help="model-alias-map.json 路径")
    parser.add_argument("--baseline", default="deepseek-v4.1-flash")
    parser.add_argument("--max-price", type=float, default=0.11,
                        help="主力价格上限（积分，按谷价/eff 判）")
    parser.add_argument("--min-ratio", type=float, default=0.95,
                        help="相对基准分数的下限（0.95 = 95%%）")
    parser.add_argument("--min-games", type=int, default=50,
                        help="入榜样本下限（局数）")
    parser.add_argument("--allow-provisional", action="store_true",
                        help="允许临时名次参与比较（默认排除）")
    parser.add_argument("--allow-free", action="store_true",
                        help="允许 0 积分模型进主力（默认留在免费组）")
    parser.add_argument("--write", action="store_true", help="写候选文件")
    parser.add_argument("--apply", action="store_true",
                        help="写候选文件并调用 model_alias.py 重写配置")
    parser.add_argument("--slot", choices=("auto", "peak", "offpeak"), default="auto",
                        help="传给 model_alias.py 的时段")
    parser.add_argument("--probe-file", default=str(DEFAULT_PROBE))
    parser.add_argument("--top", type=int, default=0, help="额外打印榜单前 N 行")
    parser.add_argument("--status", action="store_true", help="只看已保存的候选")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    out = Path(args.out).expanduser()
    if args.status:
        return status(out)

    cache = Path(args.cache).expanduser()
    payload, source = fetch_leaderboard(cache, args.refresh, args.timeout)
    rows = payload.get("rows") or []

    if args.top > 0:
        ranked = sorted((row for row in rows if row.get("score") is not None),
                        key=lambda row: row.get("rank") or 10**9)
        print(f"榜单前 {args.top}：")
        for row in ranked[:args.top]:
            print(f"  #{str(row.get('rank')):<3} {str(row.get('model') or row.get('modelName')):<32} "
                  f"{str(row.get('effort') or '-'):<9} {row.get('score')}  "
                  f"{'临时' if row.get('provisional') else '正式'}")
        print()

    best = best_rows(rows, args.min_games, args.allow_provisional)
    base_key = canonical(args.baseline)
    baseline = best.get(base_key)
    if baseline is None:
        raise SystemExit(
            f"基准 {args.baseline} 在榜单上找不到（≥{args.min_games} 局、非临时）；"
            "换 --baseline 或降低 --min-games")

    alias_file = alias.alias_path(args.alias_map)
    models = load_models(alias_file)
    price_of = make_pricer()
    picked, near = candidates(models, best, baseline, args.max_price, args.min_ratio,
                              price_of, args.allow_free)
    print_table(payload, source, picked, near, baseline, args)

    existing = read_json(out) or {}
    rule = {
        "min_ratio": args.min_ratio,
        "max_price": args.max_price,
        "min_games": args.min_games,
        "allow_provisional": bool(args.allow_provisional),
        "allow_free": bool(args.allow_free),
        "price_basis": "offpeak",
    }
    # updatedAt moves every ~10 minutes; only a membership or rule change is
    # worth rewriting provider_config.json.
    unchanged = (
        not args.force
        and same_candidates(existing.get("candidates") or [], picked)
        and existing.get("rule") == rule
    )
    if unchanged:
        print(f"\n榜单已刷新（{payload.get('updatedAt')}），主力候选未变：{out}")
        if args.apply:
            print("跳过 model_alias.py（加 --force 可强制重写）")
        return 0

    document = {
        "version": 1,
        "source": LEADERBOARD_URL,
        "gallery": GALLERY_URL,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "leaderboard_updated_at": payload.get("updatedAt"),
        "refresh_interval_seconds": payload.get("refreshIntervalSeconds"),
        "baseline": {
            "model": baseline.get("model") or baseline.get("modelName"),
            "score": baseline.get("score"),
            "rank": baseline.get("rank"),
            "effort": baseline.get("effort") or "",
            "games": baseline.get("games"),
        },
        "rule": rule,
        "candidates": picked,
    }

    if not (args.write or args.apply):
        print("\ndry run；加 --write 落候选文件，或 --apply 同时重写配置")
        return 0

    write_json(out, document)
    print(f"\n已写入 {out}")

    if args.apply:
        command = [sys.executable, str(HERE / "model_alias.py"),
                   "--slot", args.slot,
                   "--arena-main", str(out),
                   "--apply"]
        probe = Path(args.probe_file).expanduser()
        if probe.exists():
            command += ["--probe-file", str(probe)]
        else:
            print(f"warning: 没有探测结果 {probe}，本次不按探测过滤", file=sys.stderr)
        print("运行：" + " ".join(command))
        subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
