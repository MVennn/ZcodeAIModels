#!/usr/bin/env python3
"""
OpenCode Go 套餐模型自动收录同步脚本

适用范围
--------
**这是 OpenCode-Go 侧的接入器**，不是通用框架 —— 数据源（文档页结构、端点路径、
鉴权头）与分档口径都是这个供应商特有的。接别的供应商时照同样的结构另写一份：
① 换成你自己的目录接口；② 逐协议探测；③ 按你自己的计价口径分档；
④ 写进 ZCode 配置的同三个落点（见 docs/MODEL-PROVIDERS.md §1）。
**与供应商无关的部分**：ZCode 侧的写入方式、思考参数覆盖机制、探测必须用真实 body。

用途
----
每天跑一次，检测 Go 套餐是否新增模型，对符合收录标准的模型自动写进 ZCode 的
provider_config.json，并把变化写成报告。

数据源（四个，必须取并集，任何一个都不完整）
  1. https://opencode.ai/zen/go/v1/models            —— 实时的 Go 套餐模型清单（不需要鉴权）
  2. https://opencode.ai/v2/docs/console/go/         —— Go 套餐文档：模型表(含端点=协议) + 定价表(含月额度)
  3. https://opencode.ai/v2/docs/console/models      —— 全量目录：公开价、"Free" 标记、弃用日期表
  4. provider_config.json 里已配置的模型              —— 有些能用的模型不在任何清单里(如 deepseek-v4-flash-vision-exp)

收录标准（硬门槛）
  - 上游未弃用（410 ModelDeprecated / 弃用日期表）
  - 三种协议里至少一种能跑通（200），且 401 一律不收（workspace 隐私/凭据问题，脚本解决不了）
  - 输出单价 <= MAX_OUTPUT_PRICE（美元/百万 token），阈值取现有配置里最贵的 qwen3.7-plus
  - 价格未知（不在任何价格表、名字里也没有 free）的模型只报候选，不自动收录

分组规则
  chat 协议 -> 按成本档：免费 / 低耗（额度可撑输出 >= 80M）/ 高耗 / 备用
  messages  -> 对话
  responses -> 响应
  主力组是人工精选，不自动进。
  备用组是人工指定（BACKUP_MODEL_IDS），按性价比 < 1 选，不按价格自动进。

用法
  python go_model_sync.py                 # 只出报告，不改配置
  python go_model_sync.py --apply         # 写配置（先备份，原子替换）
  python go_model_sync.py --apply --probe-only
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.request

BASE = "https://opencode.ai/zen/go/v1"
GO_DOCS = "https://opencode.ai/v2/docs/console/go/"
CATALOG_DOCS = "https://opencode.ai/v2/docs/console/models"
# ZCode 客户端配置：默认按「当前用户主目录」推导，不要写死某个人的用户名。
# 换机器时用 --config 覆盖即可（本脚本不读 ZCODE_PERSONAL_PROVIDER_CONFIG_FILE）。
DEFAULT_CONFIG = os.path.join(
    os.path.expanduser("~"), ".zcode", "v2", "provider_config.json"
)
# 报告默认写进本仓的 evidence/（可用环境变量覆盖）
REPORT_DIR = os.environ.get(
    "GO_SYNC_REPORT_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "evidence"),
)
UA = "opencode-cli/1.0"

# 输出单价上限（美元 / 百万 token）。现有配置里最贵的是 qwen3.7-plus 的 $1.60。
MAX_OUTPUT_PRICE = 1.60
# 低耗档阈值：月额度 / 输出单价 >= 80M token
LOW_COST_MIN_M = 80.0

# 备用档：以 deepseek-v4.1-flash 为 100 基准、性价比 < 1 的模型。
# 依据见 docs/BENCHMARKS.md §5.4；新增模型不要自动进这里，必须人工确认。
BACKUP_PROVIDER = "opencode-go-chat-backup"
BACKUP_MODEL_IDS = {"minimax-m3"}

CHAT_PROVIDER = {
    "免费": "opencode-go-chat-free",
    "低耗": "opencode-go-chat-fast",
    "高耗": "opencode-go-chat-slow",
    "备用": BACKUP_PROVIDER,
}
MESSAGES_PROVIDER = "opencode-go-messages"
RESPONSES_PROVIDER = "opencode-go-responses"

# 协议 <-> 端点路径关键字
PROTOCOLS = ("chat/completions", "messages", "responses")


def now():
    return datetime.datetime.now()


def stamp():
    return now().strftime("%Y%m%d-%H%M%S")


def http(url, data=None, headers=None, timeout=45):
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9"}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
        return r.status, raw


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def money(cell):
    """从 '$1.40 $2.80' / '$60' / 'Free' / '-' 里取数字；Free 返回 0.0"""
    c = (cell or "").strip()
    if not c or c == "-":
        return None
    if c.lower().startswith("free"):
        return 0.0
    m = re.findall(r"\$\s*([0-9]+(?:\.[0-9]+)?)", c)
    return float(m[0]) if m else None


def cells_of(row_html):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip()
            for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S)]


def rows_of(html):
    return [cells_of(r) for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)]


# ---------------------------------------------------------------- 数据源解析

def fetch_live_models():
    st, raw = http(BASE + "/models")
    return [m["id"] for m in json.loads(raw)["data"]]


def base_name(name):
    """去掉括号后缀（(Off-Peak)/(≤ 256K tokens)/(50% off)）再归一化"""
    return norm((name or "").split("(")[0])


def endpoint_proto(url):
    for p in PROTOCOLS:
        if url.endswith(p):
            return p
    return None


def parse_go_docs():
    """返回 (protocol_hint, go_price) —— protocol_hint: id -> 协议；go_price: id -> 价格行列表"""
    st, html = http(GO_DOCS)
    protocol_hint = {}
    name_to_id = {}
    price_rows = []
    mode = "list"
    price_tables = 0
    for c in rows_of(html):
        if len(c) < 2:
            continue
        name, mid = c[0], c[1]
        # 模型表：Model | Model ID | Endpoint | AI SDK Package
        if len(c) >= 3 and "opencode.ai/inference/go" in c[2]:
            proto = endpoint_proto(c[2])
            if proto:
                protocol_hint[mid] = proto
            name_to_id.setdefault(base_name(name), mid)
            continue
        if name == "Model" and len(c) >= 6:
            price_tables += 1
            mode = "price" if price_tables == 1 else "other"  # 只取第一张 = Go $10 档
            continue
        if mode == "price" and len(c) >= 6:
            out = money(c[2])
            inp = money(c[1])
            limit = money(c[5])
            if out is None and inp is None:
                continue
            price_rows.append({"name": name, "input": inp, "output": out, "limit": limit})
    go_price = {}
    for r in price_rows:
        key = name_to_id.get(base_name(r["name"]), base_name(r["name"]))
        go_price.setdefault(key, []).append(r)
    return protocol_hint, go_price


def parse_catalog():
    """全量目录：公开价(可能为 Free)、弃用日期表"""
    st, html = http(CATALOG_DOCS)
    name_to_id = {}
    public_rows = []
    deprecated = {}
    mode = "list"
    for c in rows_of(html):
        if len(c) < 2:
            continue
        name, mid = c[0], c[1]
        if name == "Model" and c[1] == "Deprecation date":
            mode = "deprec"
            continue
        if name == "Model" and c[1] == "Model ID":
            mode = "list"
            continue
        if name == "Model" and len(c) >= 5:
            mode = "price"
            continue
        if mode == "list" and len(c) >= 3 and "opencode.ai/inference" in c[2]:
            name_to_id.setdefault(base_name(name), mid)
            continue
        if mode == "price" and len(c) >= 4:
            out = money(c[2])
            inp = money(c[1])
            if out is None and inp is None:
                continue
            public_rows.append({"name": name, "input": inp, "output": out,
                                "free": out == 0.0 and inp == 0.0})
            continue
        if mode == "deprec" and len(c) >= 2:
            when = c[1]
            try:
                d = datetime.datetime.strptime(when, "%B %d, %Y").date()
            except ValueError:
                continue
            if d <= now().date():
                key = name_to_id.get(base_name(c[0]), base_name(c[0]))
                deprecated[key] = when
    public_price = {}
    for r in public_rows:
        key = name_to_id.get(base_name(r["name"]), base_name(r["name"]))
        public_price.setdefault(key, []).append(r)
    return public_price, deprecated


def price_lookup(model_id, go_price, public_price):
    """返回价格字典；找不到返回 None"""
    for table, src in ((go_price, "go"), (public_price, "public")):
        rows = table.get(model_id) or table.get(base_name(model_id))
        if not rows:
            continue
        outs = [r["output"] for r in rows if r["output"] is not None]
        ins = [r["input"] for r in rows if r["input"] is not None]
        limits = [r.get("limit") for r in rows if r.get("limit")]
        if not outs and not ins:
            continue
        all_free = all(r.get("free") or (r.get("output") == 0.0 and r.get("input") == 0.0) for r in rows)
        return {
            "src": src,
            "input": min(ins) if ins else None,
            "out_min": min(outs) if outs else None,
            "out_max": max(outs) if outs else None,
            "limit": max(limits) if limits else None,
            "free": all_free,
        }
    return None


# ---------------------------------------------------------------- 探测

API_KEY = None  # 由 main() 从 provider_config.json 读出，probe 时带上
SESSION = "go-model-sync"


def probe_headers(protocol=None):
    """anthropic-messages 端点只认 x-api-key，chat/responses 认 Authorization: Bearer"""
    h = {"x-opencode-session": SESSION}
    if API_KEY:
        if protocol == "messages":
            h["x-api-key"] = API_KEY
        else:
            h["Authorization"] = "Bearer " + API_KEY
    return h


def probe_detail(model, protocol, thinking=True):
    """返回 (status, kind, raw)。kind: ok / protocol_unsupported / deprecated / unauthorized / error"""
    if protocol == "chat/completions":
        body = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4096}
        if thinking:
            body["thinking"] = {"type": "enabled", "budget_tokens": 1024}
    elif protocol == "messages":
        body = {"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": "hi"}]}
        if thinking:
            body["thinking"] = {"type": "enabled", "budget_tokens": 1024}
    else:
        body = {"model": model, "input": "hi", "max_output_tokens": 4096}
        if thinking:
            body["reasoning_effort"] = "medium"
    try:
        st, raw = http(BASE + "/" + protocol, data=body, headers=probe_headers(protocol))
    except urllib.error.HTTPError as e:
        st, raw = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # 超时等 -> 重试一次
        try:
            st, raw = http(BASE + "/" + protocol, data=body, headers=probe_headers(protocol))
        except urllib.error.HTTPError as e2:
            st, raw = e2.code, e2.read().decode("utf-8", "replace")
        except Exception as e2:
            return 0, "error:" + type(e2).__name__, str(e2)
    if st == 200:
        return st, "ok", raw
    low = raw.lower()
    if "modeldeprecat" in low or "has been deprecated" in low:
        return st, "deprecated", raw
    if "modelprotocolunsupported" in low or "does not support this protocol" in low:
        return st, "protocol_unsupported", raw
    if st == 401:
        return st, "unauthorized", raw
    if st == 429:
        return st, "rate_limited", raw
    return st, "error", raw


def probe(model, protocol, thinking=True):
    """返回 (status, kind)"""
    st, kind, _ = probe_detail(model, protocol, thinking)
    return st, kind


def is_workbuddy_id(model):
    """统一路由把 cn:/global: 开头的模型转给 WorkBuddy，不属于 Go 套餐。"""
    return model.startswith(("cn:", "global:"))


def upstream_message(raw):
    """从上游错误体里取一句话，放进报告。"""
    try:
        data = json.loads(raw)
        err = data.get("error")
        msg = err.get("message") if isinstance(err, dict) else err
        if msg:
            return str(msg).replace("\n", " ")[:200]
    except Exception:
        pass
    return (raw or "").strip().replace("\n", " ")[:200]


UNAVAILABLE_MARKERS = (
    "endpoint is unavailable",
    "unsupported model",
    "model is unavailable",
)


def stale_reason(model, st, kind, raw, deprecated_dates, live, hint):
    """返回该配置模型应被移除的原因；None 表示保留。调用方已排除 WorkBuddy 前缀。"""
    if model in deprecated_dates:
        return "已过官方弃用日 %s" % deprecated_dates[model]
    if kind == "deprecated":
        return "上游已弃用：HTTP %s %s" % (st, upstream_message(raw))
    if kind == "error" and st in (400, 402, 404):
        low = (raw or "").lower()
        if any(x in low for x in UNAVAILABLE_MARKERS):
            where = "仍在清单但上游不可用" if (model in live or model in hint) else "已不在任何清单"
            return "%s：HTTP %s %s" % (where, st, upstream_message(raw))
        if model not in live and model not in hint:
            return "已不在实时/文档模型清单：HTTP %s %s" % (st, upstream_message(raw))
    if kind == "protocol_unsupported" and model not in live and model not in hint:
        return "已不在实时/文档模型清单，且拒绝当前协议"
    return None


def probe_protocols(model, hint=None):
    """按协议顺序探测，返回 (protocol, needs_no_thinking) 或 (None, reason)"""
    order = list(PROTOCOLS)
    if hint:
        order.sort(key=lambda p: 0 if p == hint else 1)
    reasons = []
    for p in order:
        st, kind = probe(model, p, thinking=True)
        if kind == "ok":
            return p, False, ""
        if kind == "deprecated":
            return None, None, "deprecated"
        reasons.append("%s:%s" % (p, kind))
        if kind == "unauthorized":
            return None, None, "unauthorized"
    # 带思考参数不通、不带思考参数通的模型 -> 需要 reasoningLevel.map="{}"
    for p in order:
        st, kind = probe(model, p, thinking=False)
        if kind == "ok":
            return p, True, ""
    return None, None, "|".join(reasons)


# ---------------------------------------------------------------- 配置读写

def load_config(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def provider_rules(cfg):
    pcr = cfg["config"]["providerConfigRules"]
    return pcr["providerRules"] if isinstance(pcr, dict) else pcr


def model_rules(cfg):
    mcr = cfg["config"]["modelConfigRules"]
    if isinstance(mcr, dict):
        return mcr.setdefault("providerModelRules", [])
    return mcr


def configured_models(cfg):
    out = {}
    for r in provider_rules(cfg):
        for m in r["config"].get("personalModelIds", []):
            out[m] = r["providerId"]
    return out


def api_key(cfg):
    for r in provider_rules(cfg):
        k = r["config"].get("access", {}).get("apiKey")
        if k:
            return k
    return None


def tier_for(price, model=None):
    """按成本档分组。主力组是人工精选，不自动进。
    没有 Go 额度行（只有公开价）的模型算不出可撑输出，保守放高耗。
    BACKUP_MODEL_IDS 是人工按性价比指定的备用档，优先于价格分档。"""
    if model in BACKUP_MODEL_IDS:
        return "备用", None
    if price is None or price.get("free"):
        return "免费", None
    out = price.get("out_min")
    limit = price.get("limit")
    if out is None or out <= 0:
        return "免费", None
    if not limit:
        return "高耗", None
    durable = limit / out  # 百万 token
    if durable >= LOW_COST_MIN_M:
        return "低耗", durable
    return "高耗", durable


def tail_number(model_id):
    """取 id 里最后一段数字做版本比较用：muse-spark-1.3-contributor -> 1.3"""
    nums = re.findall(r"[0-9]+(?:\.[0-9]+)?", model_id or "")
    try:
        return float(nums[-1])
    except (IndexError, ValueError):
        return 0.0


def add_model(cfg, model, provider_id, needs_no_thinking, durable):
    for r in provider_rules(cfg):
        if r["providerId"] != provider_id:
            continue
        ids = r["config"].setdefault("personalModelIds", [])
        order = r["config"].setdefault("modelOrder", [])
        if model not in ids:
            ids.append(model)
        if model not in order:
            order.append(model)
        break
    else:
        raise RuntimeError("provider not found: " + provider_id)
    rule = {"modelId": model, "config": {"enabled": True}, "providerId": provider_id}
    if needs_no_thinking:
        rule["config"]["optionSpecs"] = {"reasoningLevel": {"map": "{}"}}
    rules = model_rules(cfg)
    for m in rules:
        if m.get("modelId") == model:
            m["providerId"] = provider_id
            break
    else:
        rules.append(rule)


def ensure_provider(cfg, provider_id, name, template_id):
    """Clone the template provider under a new id/name; idempotent."""
    rules = provider_rules(cfg)
    for r in rules:
        if r["providerId"] == provider_id:
            r["providerName"] = name
            return r
    template = next((r for r in rules if r["providerId"] == template_id), None)
    if template is None:
        raise RuntimeError("template provider not found: " + template_id)
    new = json.loads(json.dumps(template))
    new["providerId"] = provider_id
    new["providerName"] = name
    new["config"]["personalModelIds"] = []
    new["config"]["modelOrder"] = []
    rules.append(new)
    order = cfg["config"].setdefault("providerOrder", [])
    if provider_id in order:
        order.remove(provider_id)
    idx = order.index(template_id) + 1 if template_id in order else len(order)
    order.insert(idx, provider_id)
    return new


def move_model(cfg, model, target_provider_id):
    """Move a model out of every provider and into the target one."""
    for r in provider_rules(cfg):
        c = r.get("config", {})
        for key in ("personalModelIds", "modelOrder"):
            ids = c.get(key)
            if isinstance(ids, list) and model in ids:
                c[key] = [m for m in ids if m != model]
    target = next((r for r in provider_rules(cfg) if r["providerId"] == target_provider_id), None)
    if target is None:
        raise RuntimeError("provider not found: " + target_provider_id)
    for key in ("personalModelIds", "modelOrder"):
        ids = target["config"].setdefault(key, [])
        if model not in ids:
            ids.append(model)
    for m in model_rules(cfg):
        if m.get("modelId") == model:
            m["providerId"] = target_provider_id
            break


def prune_model(cfg, model):
    """从所有 provider 的模型清单和 modelConfigRules 中彻底删掉一个模型。"""
    touched = []
    for r in provider_rules(cfg):
        c = r.setdefault("config", {})
        hit = False
        for key in ("personalModelIds", "modelOrder"):
            ids = c.get(key)
            if isinstance(ids, list) and model in ids:
                c[key] = [m for m in ids if m != model]
                hit = True
        if hit:
            touched.append(r["providerId"])
    mcr = cfg["config"].get("modelConfigRules", {})
    if isinstance(mcr, dict):
        for key in ("providerModelRules", "manualProviderModelRules"):
            rules = mcr.get(key)
            if isinstance(rules, list):
                rules[:] = [r for r in rules if r.get("modelId") != model]
    elif isinstance(mcr, list):
        mcr[:] = [r for r in mcr if r.get("modelId") != model]
    return touched


def reclassify_backup(cfg):
    """Ensure the 备用 provider exists and holds BACKUP_MODEL_IDS.
    Returns the list of models actually moved."""
    present = {
        m for m in BACKUP_MODEL_IDS
        if any(m in (r.get("config", {}).get("personalModelIds") or [])
               for r in provider_rules(cfg))
    }
    if not present:
        return []
    ensure_provider(cfg, BACKUP_PROVIDER, "备用", "opencode-go-chat-slow")
    moved = []
    for model in sorted(present):
        before = next(
            (r["providerId"] for r in provider_rules(cfg)
             if model in (r.get("config", {}).get("personalModelIds") or [])),
            None,
        )
        move_model(cfg, model, BACKUP_PROVIDER)
        if before != BACKUP_PROVIDER:
            moved.append(model)
    order = cfg["config"].setdefault("providerOrder", [])
    if BACKUP_PROVIDER in order:
        order.remove(BACKUP_PROVIDER)
    idx = (order.index("opencode-go-chat-slow") + 1
           if "opencode-go-chat-slow" in order else len(order))
    order.insert(idx, BACKUP_PROVIDER)
    return moved


def write_config(cfg, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    json.load(open(tmp, encoding="utf-8"))  # 写前校验
    os.replace(tmp, path)


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写入 provider_config.json")
    ap.add_argument("--config", default=DEFAULT_CONFIG)
    ap.add_argument("--probe-only", action="store_true", help="只探测，不做分组/写入")
    ap.add_argument("--no-existing", action="store_true", help="跳过对已配置模型的重测")
    ap.add_argument("--reclassify-only", action="store_true",
                    help="只按备用档重排，不联网探测")
    args = ap.parse_args()

    lines = []
    def log(s=""):
        print(s)
        lines.append(s)

    if args.reclassify_only:
        cfg = load_config(args.config)
        moved = reclassify_backup(cfg)
        log("# OpenCode Go 备用档重排 — %s" % now().strftime("%Y-%m-%d %H:%M:%S"))
        log("模式: %s" % ("写入" if args.apply else "只读报告"))
        if moved:
            log("移动: " + ", ".join(moved))
        else:
            log("备用档无需移动")
        if args.apply and moved:
            backup = args.config + ".bak-reclassify-" + stamp()
            shutil.copy2(args.config, backup)
            write_config(cfg, args.config)
            log("已写入 %s（备份 %s）" % (args.config, os.path.basename(backup)))
        elif not args.apply:
            log("[dry-run] 未写入；加 --apply 才写")
        return

    log("# OpenCode Go 模型自动收录同步 — %s" % now().strftime("%Y-%m-%d %H:%M:%S"))
    log("模式: %s" % ("写入" if args.apply else "只读报告"))

    cfg = load_config(args.config)
    key = api_key(cfg)
    global API_KEY
    API_KEY = key
    if not key:
        log("!! 配置里没有 apiKey，探测会全部 401")

    live = fetch_live_models()
    hint, go_price = parse_go_docs()
    public_price, deprecated = parse_catalog()
    log("- 实时 /models: %d 个" % len(live))
    log("- Go 文档模型表: %d 个; 定价表: %d 个" % (len(hint), len(go_price)))
    log("- 全量目录价格: %d 个; 已过弃用日: %d 个" % (len(public_price), len(deprecated)))

    conf = configured_models(cfg)
    candidates = sorted(set(live) | set(hint.keys()))
    new_models = [m for m in candidates if m not in conf]
    log("- 已配置 %d 个; 待评估新模型 %d 个" % (len(conf), len(new_models)))

    # ---- 已配置模型体检（弃用 / 协议漂移 / 上游已下架）
    removed = []
    if not args.no_existing:
        log("\n## 已配置模型体检")
        wb_skipped = 0
        verb = "移除" if (args.apply and not args.probe_only) else "将移除"
        for m, pid in sorted(conf.items()):
            if is_workbuddy_id(m):
                wb_skipped += 1
                continue
            proto = ("responses" if "responses" in pid else
                     "messages" if "messages" in pid else "chat/completions")
            st, kind, raw = probe_detail(m, proto, thinking=False)
            why = stale_reason(m, st, kind, raw, deprecated, live, hint)
            if why:
                removed.append((m, why))
                log("  - %s %s：%s" % (verb, m, why))
            elif kind == "protocol_unsupported":
                log("  ✗ %s 现在拒绝 %s 协议，协议归属可能变了" % (m, proto))
            elif kind == "unauthorized":
                log("  ⚠ %s 返回 401（凭据/隐私授权问题）" % m)
            elif kind != "ok":
                log("  ⚠ %s 探测异常: %s (HTTP %s)" % (m, kind, st))
        if wb_skipped:
            log("  · 跳过 %d 个 cn:/global: 开头的 WorkBuddy 模型（由统一路由处理，不属于 Go 套餐）" % wb_skipped)
        if not removed:
            log("  无需移除")
        removed_ids = {m for m, _ in removed}
        new_models = [m for m in new_models if m not in removed_ids]

    # ---- 新模型评估
    log("\n## 新模型评估")
    added, skipped = [], []
    for m in new_models:
        price = price_lookup(m, go_price, public_price)
        proto_hint = hint.get(m)
        row = {"model": m, "price": price, "hint": proto_hint}
        if m in deprecated:
            skipped.append((m, "已过官方弃用日 %s" % deprecated[m]))
            continue
        if price is None:
            if "free" in m.lower():
                price = {"src": "free-name", "out_min": 0.0, "out_max": 0.0, "limit": None, "free": True}
            else:
                skipped.append((m, "价格未知（不在任何价格表），只列候选"))
                continue
        if not price.get("free") and price.get("out_max") is not None and price["out_max"] > MAX_OUTPUT_PRICE:
            skipped.append((m, "输出单价 $%.2f 超过门槛 $%.2f" % (price["out_max"], MAX_OUTPUT_PRICE)))
            continue
        proto, needs_no_thinking, reason = probe_protocols(m, proto_hint)
        if proto is None:
            skipped.append((m, "三种协议都跑不通: %s" % reason))
            continue
        row.update({"protocol": proto, "needs_no_thinking": needs_no_thinking})
        if price.get("free"):
            tier, durable = "免费", None
        else:
            tier, durable = tier_for(price, m)
        if proto == "chat/completions":
            provider_id = CHAT_PROVIDER[tier]
        elif proto == "messages":
            provider_id, tier = MESSAGES_PROVIDER, "对话"
        else:
            provider_id, tier = RESPONSES_PROVIDER, "响应"
        row.update({"tier": tier, "provider": provider_id, "durable": durable})
        added.append(row)

    log("\n### 建议收录 %d 个" % len(added))
    for r in added:
        p = r["price"]
        if p.get("free"):
            price_txt = "免费"
        elif p.get("limit"):
            price_txt = "输入 $%.3f / 输出 $%.2f~%.2f / 月额度 $%s" % (
                p.get("input") or 0, p.get("out_min") or 0, p.get("out_max") or 0, p.get("limit"))
        else:
            price_txt = "输入 $%.3f / 输出 $%.2f~%.2f / 无 Go 额度表(按公开价)" % (
                p.get("input") or 0, p.get("out_min") or 0, p.get("out_max") or 0)
        durable_txt = ("额度可撑 %.0fM" % r["durable"]) if r.get("durable") else "—"
        log("  + %-28s 协议 %-16s 组 %-4s (%s) %s %s %s" % (
            r["model"], r["protocol"], r["tier"], r["provider"], price_txt, durable_txt,
            "  [需关思考覆盖]" if r["needs_no_thinking"] else ""))
    log("\n### 不收录 %d 个" % len(skipped))
    for m, why in skipped:
        log("  - %-28s %s" % (m, why))

    # ---- 写入
    if args.apply and not args.probe_only:
        for m, _ in removed:
            touched = prune_model(cfg, m)
            if touched:
                log("  · 已从 %s 删除 %s" % (", ".join(touched), m))
        # 同一组内按版本号倒序追加，保持厂商块连续
        by_provider = {}
        for r in added:
            by_provider.setdefault(r["provider"], []).append(r)
        for pid, rows in by_provider.items():
            rows.sort(key=lambda r: tail_number(r["model"]), reverse=True)
            # responses 组现在是"响应"（协议语义），原来的"备用"标签已不准确
            if pid == RESPONSES_PROVIDER:
                for pr in provider_rules(cfg):
                    if pr["providerId"] == pid and pr.get("providerName") != "响应":
                        log("  · provider 标签 %s -> 响应（providerId 不变）" % pr.get("providerName"))
                        pr["providerName"] = "响应"
            for r in rows:
                add_model(cfg, r["model"], pid, r["needs_no_thinking"], r.get("durable"))
        moved = reclassify_backup(cfg)
        if moved:
            log("  · 备用档移动: " + ", ".join(moved))
        if added or moved or removed:
            backup = args.config + ".bak-gosync-" + stamp()
            shutil.copy2(args.config, backup)
            write_config(cfg, args.config)
            log("\n已写入 %s（备份 %s）" % (args.config, os.path.basename(backup)))
        else:
            log("\n没有需要写入的新模型或失效模型，配置未改动")
    elif args.apply:
        log("\n只探测，配置未改动")

    # ---- 报告落盘
    try:
        os.makedirs(REPORT_DIR, exist_ok=True)
        rp = os.path.join(REPORT_DIR, "go-model-sync-%s.md" % stamp())
        with open(rp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        log("报告: %s" % rp)
    except Exception as e:
        log("报告写入失败: %s" % e)


if __name__ == "__main__":
    main()
