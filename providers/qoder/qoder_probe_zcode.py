#!/usr/bin/env python3
"""Probe Qoder models with the exact body ZCode will send.

Default mode probes through the unified router (127.0.0.1:7871) with the
`qoder:` prefix, i.e. the same path ZCode uses after the merge. The catalog is
always read from qoder2api-hub (127.0.0.1:8790) so the candidate list includes
models that are currently not in the ZCode config (e.g. the queued free
Qwen3.8-Flash can be retried and re-added).

    ok            HTTP 200 with the ZCode-native body
    fallback      native body failed, a slimmer body worked (needs a map rule)
    queued        upstream 10605 / isQueued (transient; retry later)
    rate_limited  429 / upstream rate limit
    blocked       account type / plan may not use this model
    unavailable   404 / model unavailable
    timeout       no answer inside --timeout
    error         anything else

Every record carries `ever_ok`: true once the model has answered 200 at least
once. `qoder_zcode_sync.py --probe-file` keeps a previously working model
through a transient queue/timeout, while a model that has never answered is
not added.

Usage
-----
    python qoder/qoder_probe_zcode.py                  # via router, prefixed
    python qoder/qoder_probe_zcode.py --direct         # via hub, bare ids
    python qoder/qoder_probe_zcode.py --only Qwen3.8-Flash --timeout 180
    python qoder/qoder_probe_zcode.py --sleep 3

The API key comes from `--api-key`, `$QD_API_KEY`, or `qoder/.env.local`; it is
never printed. Probes are charged like normal requests (the free models are
`billable:false`), so keep `--max-tokens` small.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from qoder_zcode_sync import (
    DEFAULT_MAX_PRICE,
    fetch_models,
    resolve_api_key,
    select_models,
)

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_HUB = "http://127.0.0.1:8790/v1"
DEFAULT_PROBE = HERE / "qoder_probe.json"
DEFAULT_PREFIX = "qoder:"
EFFECTIVE_BODY = REPO / "workbuddy" / "zcode_effective_body.js"


def catalog_ids(catalog_base: str, key: str, max_price: float) -> list[str]:
    picked, _ = select_models(fetch_models(catalog_base, key), max_price)
    return [str(model.get("id") or "").strip() for model in picked if str(model.get("id") or "").strip()]


def effective_body(model: str, base: str, max_tokens: int) -> dict:
    try:
        out = subprocess.run(
            [
                "node", str(EFFECTIVE_BODY),
                "--api-type", "openai-chat-completions",
                "--base-url", base,
                "--max-output-tokens", str(max_tokens),
                model,
            ],
            capture_output=True, text=True, timeout=60, check=True,
        )
        parsed = json.loads(out.stdout)
        return (parsed.get(model) or {}).get("body") or {}
    except Exception as exc:
        print(f"warning: effective body failed for {model}: {exc}", file=sys.stderr)
        return {
            "thinking": {"type": "enabled"},
            "enable_thinking": True,
            "reasoning_effort": "high",
            "reasoning": {"effort": "high"},
        }


def build_body(request_model: str, extra: dict, max_tokens: int) -> dict:
    body = {
        "model": request_model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "ok"},
        ],
        "max_completion_tokens": max_tokens,
        "stream": False,
    }
    for key, value in extra.items():
        body[key] = value
    return body


def post(base: str, key: str, body: dict, timeout: int) -> tuple[int | None, str, str]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), ""
    except Exception as exc:
        return None, "", str(exc)


def classify(http: int | None, detail: str, error: str) -> str:
    text = (detail + " " + error).lower()
    if http is None:
        return "timeout" if "timed out" in text or "timeout" in text else "error"
    if http == 200:
        return "ok"
    if "10605" in text or "isqueued" in text or ("queue" in text and http in (403, 502)):
        return "queued"
    if http == 429 or "rate limit" in text:
        return "rate_limited"
    if http == 404 or "not found" in text or "unavailable" in text:
        return "unavailable"
    if http == 403 or "not allowed" in text or "permission" in text or "user type" in text:
        return "blocked"
    return "error"


def probe_one(base: str, key: str, model: str, prefix: str, max_tokens: int,
              timeout: int) -> dict:
    request_model = prefix + model
    native = effective_body(request_model, base, max_tokens)
    variants = [("native", native)]
    if native:
        variants.append(("thinking", {"thinking": {"type": "enabled"}}))
        variants.append(("bare", {}))
    last_http, last_detail, last_error = None, "", ""
    for variant, extra in variants:
        body = build_body(request_model, extra, max_tokens)
        started = time.time()
        http, detail, error = post(base, key, body, timeout)
        elapsed = round(time.time() - started, 1)
        last_http, last_detail, last_error = http, detail, error
        if http == 200:
            status = "ok" if variant == "native" else "fallback"
            return {
                "status": status,
                "variant": variant,
                "http": http,
                "ms": int(elapsed * 1000),
                "detail": detail[:300],
                "body_keys": sorted(native.keys()),
                "request_model": request_model,
            }
        # A queue/plan gate is not something a different body shape fixes.
        if classify(http, detail, error) in ("queued", "rate_limited", "blocked", "unavailable"):
            break
        # A client-side timeout means the gateway is still waiting upstream;
        # slimmer bodies only make the same wait longer.
        if http is None:
            break
    status = classify(last_http, last_detail, last_error)
    return {
        "status": status,
        "variant": "native",
        "http": last_http,
        "detail": (last_detail or last_error)[:300],
        "body_keys": sorted(native.keys()),
        "request_model": request_model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:7871/v1",
                        help="探测入口：默认统一路由 7871；--direct 时改为 catalog 地址")
    parser.add_argument("--catalog-base", default=DEFAULT_HUB,
                        help=f"模型清单地址（默认 {DEFAULT_HUB}）")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX,
                        help=f"请求模型前缀（默认 {DEFAULT_PREFIX}）")
    parser.add_argument("--direct", action="store_true",
                        help="直连 qoder2api-hub（8790，裸模型名），不经统一路由")
    parser.add_argument("--max-price", type=float, default=DEFAULT_MAX_PRICE,
                        help=f"候选模型的 price_factor 上限（默认 {DEFAULT_MAX_PRICE}）")
    parser.add_argument("--api-key")
    parser.add_argument("--out", default=str(DEFAULT_PROBE))
    parser.add_argument("--max-tokens", type=int, default=24)
    parser.add_argument("--timeout", type=int, default=75)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--only", help="只探测这些模型（逗号分隔，裸模型名；可不在当前配置里）")
    args = parser.parse_args()

    key = resolve_api_key(args.api_key)
    base = args.catalog_base if args.direct else args.base_url
    prefix = "" if args.direct else args.prefix

    models = catalog_ids(args.catalog_base, key, args.max_price)
    if args.only:
        models = [part.strip() for part in args.only.split(",") if part.strip()]
    if not models:
        raise SystemExit("没有要探测的模型")

    out_path = Path(args.out)
    results: dict[str, dict] = {}
    if out_path.exists():
        try:
            results = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            results = {}

    print(f"probe: {base} prefix={prefix or '(none)'} catalog={args.catalog_base}")
    for index, model in enumerate(models):
        print(f"[{index + 1}/{len(models)}] {model} ...", flush=True)
        result = probe_one(base, key, model, prefix, args.max_tokens, args.timeout)
        previous = results.get(model) or {}
        result["ever_ok"] = (
            bool(previous.get("ever_ok"))
            or previous.get("status") == "ok"
            or result.get("status") == "ok"
        )
        if result.get("status") == "ok":
            result["ok_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        elif previous.get("ok_at"):
            result["ok_at"] = previous["ok_at"]
        results[model] = result
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {result['status']:<12} http={result['http']} {result.get('detail','')[:120]}", flush=True)
        if index + 1 < len(models) and args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\n结果写入 {out_path}")
    for model in models:
        result = results.get(model, {})
        print(f"  {model:<22} {result.get('status','?'):<12} http={result.get('http')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
