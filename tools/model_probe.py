#!/usr/bin/env python3
"""Probe the unified four-group model list with the exact body ZCode sends.

Every model is sent through the unified router (127.0.0.1:7871) using its
display id (`WB:...` / `OC:...` / `QD:...`). The effective body is computed by
`providers/workbuddy/zcode_effective_body.js` with the model's provider id, so
provider-specific `optionSpecs.reasoningLevel.map` overrides (e.g. the empty
map for minimax-m3 / beam-free / bridged models) are applied.

Status vocabulary (same as the Qoder probe):

    ok / fallback / queued / rate_limited / blocked / unavailable / timeout / error

`ever_ok` is preserved across runs. `tools/model_alias.py --probe-file` keeps a
previously working model through a transient queue/timeout and removes a model
that has never answered.

Usage
-----
    python tools/model_probe.py
    python tools/model_probe.py --only "OC:MM3:X0.22" --timeout 120
    python tools/model_probe.py --group 高耗 --sleep 2
    python tools/model_alias.py --probe-file ~/.zcode/v2/model_probe.json --apply
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
EFFECTIVE = REPO / "providers" / "workbuddy" / "zcode_effective_body.js"
DEFAULT_OUT = Path.home() / ".zcode" / "v2" / "model_probe.json"
ALIAS = Path.home() / ".zcode" / "v2" / "model-alias-map.json"
PROVIDERS = ("opencode-go-chat", "opencode-go-chat-free",
             "opencode-go-chat-fast", "opencode-go-chat-slow")


def config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ZCODE_PERSONAL_PROVIDER_CONFIG_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "provider_config.json"


def provider_rules(cfg: dict) -> list[dict]:
    rules = cfg["config"]["providerConfigRules"]
    return rules if isinstance(rules, list) else rules.get("providerRules", [])


def load_alias() -> dict:
    try:
        return json.loads(ALIAS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def models_of(cfg: dict, group: str | None, alias: dict) -> list[tuple[str, str, str]]:
    """Return (display id, provider id, original id); probe results key on original."""
    models = alias.get("models") or {}
    legacy = alias.get("legacy") or {}
    out: list[tuple[str, str, str]] = []
    for rule in provider_rules(cfg):
        provider_id = str(rule.get("providerId") or "")
        if provider_id not in PROVIDERS:
            continue
        name = str(rule.get("providerName") or "")
        if group and group not in (provider_id, name):
            continue
        for model in (rule.get("config") or {}).get("personalModelIds") or []:
            display = str(model)
            entry = models.get(display) or models.get(legacy.get(display, ""), {})
            original = str((entry or {}).get("original") or display)
            out.append((display, provider_id, original))
    return out


def effective_body(model: str, provider_id: str, max_tokens: int) -> dict:
    try:
        result = subprocess.run(
            [
                "node", str(EFFECTIVE),
                "--provider-id", provider_id,
                "--api-type", "openai-chat-completions",
                "--base-url", "http://127.0.0.1:7871/v1",
                "--max-output-tokens", str(max_tokens),
                model,
            ],
            capture_output=True, text=True, timeout=60, check=True,
        )
        parsed = json.loads(result.stdout)
        return (parsed.get(model) or {}).get("body") or {}
    except Exception as exc:
        print(f"warning: effective body failed for {model}: {exc}", file=sys.stderr)
        return {}


def build_body(model: str, extra: dict, max_tokens: int) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "ok"},
        ],
        "max_completion_tokens": max_tokens,
        "stream": False,
    }
    body.update(extra)
    return body


def post(model: str, body: dict, timeout: int) -> tuple[int | None, str, str]:
    request = urllib.request.Request(
        "http://127.0.0.1:7871/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
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
    if "no_healthy_account" in text or "no healthy account" in text:
        # WorkBuddy pool-level cooldown: the model is fine, every account is
        # temporarily cooled. Treat it like a rate limit, not a dead model.
        return "rate_limited"
    if http == 429 or "rate limit" in text or "6004" in text:
        return "rate_limited"
    if http == 404 or "not found" in text or "unavailable" in text:
        return "unavailable"
    if http == 403 or "not allowed" in text or "permission" in text or "user type" in text:
        return "blocked"
    return "error"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--group", help="只探测某组（provider id 或显示名：主力/免费/低耗/高耗）")
    parser.add_argument("--only", help="只探测这些模型（逗号分隔，精确匹配）")
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=75)
    parser.add_argument("--sleep", type=float, default=1.5)
    args = parser.parse_args()

    cfg = json.loads(config_path(args.config).read_text(encoding="utf-8"))
    models = models_of(cfg, args.group, load_alias())
    if args.only:
        wanted = {part.strip() for part in args.only.split(",") if part.strip()}
        models = [item for item in models if item[0] in wanted or item[2] in wanted]
    if not models:
        raise SystemExit("没有要探测的模型")

    out_path = Path(args.out).expanduser()
    results: dict[str, dict] = {}
    if out_path.exists():
        try:
            results = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            results = {}

    for index, (model, provider_id, original) in enumerate(models):
        print(f"[{index + 1}/{len(models)}] {model} ({provider_id}) ...", flush=True)
        extra = effective_body(model, provider_id, args.max_tokens)
        started = time.time()
        http, detail, error = post(model, build_body(model, extra, args.max_tokens), args.timeout)
        status = classify(http, detail, error)
        key = original or model
        previous = results.get(key) or {}
        results[key] = {
            "display": model,
            "status": status,
            "http": http,
            "ms": int((time.time() - started) * 1000),
            "detail": (detail or error)[:300],
            "provider": provider_id,
            "body_keys": sorted(extra.keys()),
            "ever_ok": bool(previous.get("ever_ok")) or previous.get("status") == "ok" or status == "ok",
            "ok_at": time.strftime("%Y-%m-%d %H:%M:%S") if status == "ok" else previous.get("ok_at"),
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {status:<12} http={http} {results[key]['detail'][:120]}", flush=True)
        if index + 1 < len(models) and args.sleep > 0:
            time.sleep(args.sleep)

    print(f"\n结果写入 {out_path}")
    for model, provider_id, original in models:
        item = results.get(original or model, {})
        print(f"  {model:<38} {item.get('status','?'):<12} http={item.get('http')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
