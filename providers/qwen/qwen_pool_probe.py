#!/usr/bin/env python3
"""千问上游探测：逐个试 pools.json 里的每一跳，产出 `qwen_pool_probe.json`。

为什么需要它：千问的免费额度是「每模型 1M tokens」，用完就 403。池子里死跳越多，
路由每请求就要多撞几次超时，用户体感就是首字极慢。定时任务每天跑一遍这个脚本，
再用 `qwen_zcode_sync.py --write-pools --probe-file …` 把死跳剔掉。

用法：
    python providers/qwen/qwen_pool_probe.py
    python providers/qwen/qwen_pool_probe.py --sleep 0.5 --timeout 30
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_ENV = HERE / ".env.local"
DEFAULT_POOLS = HERE / "pools.json"
DEFAULT_OUT = HERE / "qwen_pool_probe.json"
API_PATH = "/messages"

# 与路由一致：额度耗尽/欠费/配额这几种都算「这跳废了」
FATAL_MARKERS = ("Free quota exhausted", "Arrearage", "AllocationQuota",
                 "use free tier only", "Model not exist")


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def pool_hops(pools_path: Path) -> list[str]:
    """池子里的全部上游 id，去重保序。"""
    payload = json.loads(pools_path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    hops: list[str] = []
    for pool in payload.get("pools") or []:
        for model_id in pool.get("hops") or []:
            if model_id not in seen:
                seen.add(model_id)
                hops.append(model_id)
    return hops


def probe(base: str, key: str, model_id: str, timeout: float) -> dict:
    body = json.dumps({
        "model": model_id,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "1"}],
    }).encode()
    request = urllib.request.Request(
        base.rstrip("/") + API_PATH,
        data=body,
        method="POST",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    stamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(256)
        return {"status": "ok", "checked_at": stamp}
    except urllib.error.HTTPError as exc:
        raw = exc.read(400).decode("utf-8", "replace")
        fatal = any(marker in raw for marker in FATAL_MARKERS)
        return {
            "status": "unavailable",
            # quota 类错误短时间内不会恢复，标出来方便人工判断
            "fatal": fatal,
            "http": exc.code,
            "detail": raw[:160],
            "checked_at": stamp,
        }
    except Exception as exc:  # noqa: BLE001 - 网络层什么都可能抛
        return {"status": "unavailable", "fatal": False,
                "detail": str(exc)[:160], "checked_at": stamp}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", default=str(DEFAULT_ENV), help="读 QWEN_API_KEY 的 .env.local")
    parser.add_argument("--pools", default=str(DEFAULT_POOLS), help="pools.json（提供待测 id）")
    parser.add_argument("--output", default=str(DEFAULT_OUT), help="探测结果输出路径")
    parser.add_argument("--base", help="覆盖上游 base（默认取 QWEN_BASE 或 .env.local）")
    parser.add_argument("--sleep", type=float, default=0.3, help="每次请求之间的间隔秒数")
    parser.add_argument("--timeout", type=float, default=20, help="单次请求超时秒数")
    args = parser.parse_args()

    env = read_env(Path(args.env).expanduser())
    key = env.get("QWEN_API_KEY")
    if not key:
        print(f"ERROR: QWEN_API_KEY 不在 {args.env}", file=sys.stderr)
        return 2
    base = args.base or env.get("QWEN_BASE") or "https://maas.qianwenaiapi.com/apps/anthropic"

    pools_path = Path(args.pools).expanduser()
    if not pools_path.exists():
        print(f"ERROR: 找不到 {pools_path}（先跑 --write-pools）", file=sys.stderr)
        return 2
    hops = pool_hops(pools_path)
    if not hops:
        print(f"ERROR: {pools_path} 里没有跳", file=sys.stderr)
        return 2

    print(f"探测 {len(hops)} 个上游（{base}）")
    results: dict[str, dict] = {}
    for index, model_id in enumerate(hops, 1):
        result = probe(base, key, model_id, args.timeout)
        results[model_id] = result
        mark = "ok" if result["status"] == "ok" else ("dead" if result.get("fatal") else "fail")
        print(f"  [{index:2}/{len(hops)}] {mark:4} {model_id}"
              + ("" if result["status"] == "ok" else f"  {result.get('detail', '')[:60]}"))
        if index < len(hops):
            time.sleep(max(args.sleep, 0))

    alive = sum(1 for r in results.values() if r["status"] == "ok")
    print(f"\n存活 {alive}/{len(results)}")
    out = Path(args.output).expanduser()
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {out}")
    print("下一步：python providers/qwen/qwen_zcode_sync.py --write-pools "
          f"--probe-file {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
