#!/usr/bin/env python3
"""Validate every model configured in ZCode against its provider protocol."""
import json, time, urllib.request, urllib.error

CFG = r"<USER>\.zcode\v2\provider_config.json"
d = json.load(open(CFG, encoding="utf-8"))
cfg = d["config"]

BASE = "https://opencode.ai/zen/go/v1"
KEY = None
for p in cfg["providerConfigRules"]["providerRules"]:
    KEY = p["config"]["access"]["apiKey"]
    break

UA = "zcode-validate/1.0"

def call(model, api_type):
    headers = {"Content-Type": "application/json", "User-Agent": UA,
               "x-opencode-session": f"validate-{model}"}
    if api_type == "anthropic-messages":
        url = BASE + "/messages"
        headers.update({"x-api-key": KEY, "anthropic-version": "2023-06-01"})
        body = {"model": model, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 16}
    elif api_type == "openai-responses":
        url = BASE + "/responses"
        headers["Authorization"] = f"Bearer {KEY}"
        body = {"model": model, "input": "Say OK", "max_output_tokens": 16}
    else:
        url = BASE + "/chat/completions"
        headers["Authorization"] = f"Bearer {KEY}"
        body = {"model": model, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 16}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            j = json.loads(r.read().decode("utf-8", "replace"))
            return True, round((time.time()-t0)*1000), ""
    except urllib.error.HTTPError as e:
        return False, round((time.time()-t0)*1000), e.read().decode("utf-8", "replace")[:140]
    except Exception as e:
        return False, round((time.time()-t0)*1000), f"{type(e).__name__}: {e}"[:140]

total = ok = 0
for p in cfg["providerConfigRules"]["providerRules"]:
    api_type = p["config"]["api"]["type"]
    print(f"\n=== {p['providerId']} ({api_type}) ===")
    for m in p["config"]["personalModelIds"]:
        total += 1
        good, ms, err = call(m, api_type)
        ok += good
        print(f"  {'OK ' if good else 'FAIL'} {m:32s} {ms:6d}ms {err}")
print(f"\n{ok}/{total} passed")
