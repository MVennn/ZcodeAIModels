# 排错手册

> **一句话**：按「现象 → 排查步骤 → 原因 / 解法」组织的排查流程 ——
> 标题就是检索词，搜到标题就搜到了解法。

**机制解释在 [PITFALLS.md](PITFALLS.md)**，本篇只讲怎么查、怎么修。

**每条都标了适用范围**：

| 标记 | 含义 |
|---|---|
| **【通用】** | 换任何供应商都成立 —— ZCode 客户端侧的行为、协议与配额机制 |
| **【实例 A】** | OpenCode-Go 特有（本仓实例一） |
| **【实例 B】** | WorkBuddy2API 网关特有（本仓实例二） |

通用条目照抄就能用；实例条目只在本仓这两个示例供应商上成立，
接自己的供应商时按「机制」那一列推断。

---

<a id="model-list-not-refreshed"></a>

## 1. ZCode 里模型列表不刷新 【通用】

**现象**：脚本跑完说「已写入」，但 ZCode 的模型列表里没有新模型；
或者过一会儿模型自己消失了。

**排查**

```bash
# 1) 确认脚本真的写进去了
python -c "import json,os; p=os.path.expanduser('~/.zcode/v2/provider_config.json'); c=json.load(open(p,encoding='utf-8')); r=c['config']['providerConfigRules']; rs=r['providerRules'] if isinstance(r,dict) else r; [print(x['providerId'], x.get('providerName'), len(x.get('config',{}).get('personalModelIds',[]))) for x in rs]"

# 2) 看备份确认脚本动过文件（时间戳对得上 = 写过了）
ls -lt ~/.zcode/v2/provider_config.json*

# 3) 确认 JSON 没写坏
python -c "import json,os; json.load(open(os.path.expanduser('~/.zcode/v2/provider_config.json'),encoding='utf-8')); print('JSON OK')"

# 4) 确认模型规则也在（provider 有模型但没 model rule = 不会出现在列表里）
python -c "import json,os; c=json.load(open(os.path.expanduser('~/.zcode/v2/provider_config.json'),encoding='utf-8')); m=c['config']['modelConfigRules']; rs=m['providerModelRules'] if isinstance(m,dict) else m; print(len(rs),'条模型规则')"
```

**原因 / 解法**（全部**【通用】**）

| 原因 | 解法 |
|---|---|
| ZCode 还没热重载（约 1 秒轮询） | 等 1~2 秒；仍不刷新就**重启客户端** |
| **ZCode 的 provider 设置界面在你写完之后又保存了一次**，整份写回覆盖了 | 写配置期间**不要在界面里改**；重新跑一次脚本 |
| 只写了 `personalModelIds` 没写 `modelConfigRules.providerModelRules` | 两个都要有（脚本会一起写） |
| `providerId` 与 `providerOrder` 里不一致 | `providerOrder` 里补上该 `providerId` |
| 写到了**另一个** `provider_config.json` | 检查环境变量 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 与实际路径是否一致 |

---

<a id="model-400"></a>

## 2. 某个模型 400 【通用】

**现象**：某个模型一发就 400，报 `ModelProtocolUnsupported` / `does not support this protocol`
/ `invalid request` 之类。

**排查**

```bash
# 1) 看 ZCode 会给这个模型发什么（复刻引擎规则，算真实 body）
cd workbuddy
node zcode_effective_body.js <model-id>

# 2) 看这个模型归在哪个 provider、什么协议
python -c "import json,os; c=json.load(open(os.path.expanduser('~/.zcode/v2/provider_config.json'),encoding='utf-8')); r=c['config']['providerConfigRules']; rs=r['providerRules'] if isinstance(r,dict) else r; [print(p['providerId'], p['config']['api']['type'], m) for p in rs for m in p['config'].get('personalModelIds',[]) if m=='<model-id>']"

# 3) OpenCode-Go 侧：三协议逐个试，看哪个不是 400
#    messages 协议只认 x-api-key，其余认 Authorization: Bearer
```

**原因 / 解法**

| 原因 | 适用范围 | 解法 |
|---|---|---|
| **协议放错**（模型不在这个 provider 的协议里） | **【通用】** | 挪到正确的 provider，见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §2 |
| **ZCode 注入的思考字段上游不认** | **【通用】** | 给模型配 `optionSpecs.reasoningLevel.map = "{}"`，见 [PITFALLS.md](PITFALLS.md) §2 |
| `anthropic/messages` 用了 `Authorization: Bearer` | **【实例 A】** | 换成 `x-api-key`（OpenCode-Go 的 messages 端点只认这个头） |
| 缺 `x-opencode-session` | **【实例 A】** | ZCode 会自动带；其它客户端用 `opencode-header-proxy.js` |
| 上游要隐私授权（`trains on request data`） | **【实例 A】** | 去 OpenCode Console 的 workspace Privacy 里允许「付费且训练数据的端点」 |

> **通用做法**：400 先分清是「协议用错」还是「请求体里有上游不认的字段」。
> 前者改 provider 归属，后者改 `optionSpecs.reasoningLevel.map`。
> 供应商特有错误码只影响「是哪一类」的判断，不影响这两条解法。

---

<a id="model-503"></a>

## 3. 某个模型 503 【实例 B】

**现象**：某个 global 模型 503，报 `not allowed for user type`。

> **适用范围**：账号类型限制是 **WorkBuddy2API 网关**特有的 —— 它的账号池里
> 混了不同类型的号，类型不够格就 503。别的供应商若也按账号类型分档，症状类似。

**排查**

```bash
# 1) 看网关账号池的 realm 与类型
curl -s http://127.0.0.1:7863/status | python -m json.tool | head -60

# 2) 看被拒的模型在不在探测缓存里，状态是什么
python -c "import json; d=json.load(open('workbuddy/cache/wb_zcode_probe.json',encoding='utf-8')); [print(k,v.get('status'),v.get('detail')) for k,v in d.items() if v.get('status')!='ok']"
```

**原因 / 解法**（均为**【实例 B】**）

| 原因 | 解法 |
|---|---|
| **账号类型不允许** —— 3 个 global 号是 `personal_free_user`，多数 global 高端模型上游直接拒 | **改配置没用**。唯一路径是换非该类型的账号。见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4.7 |
| 模型被网关锁（`model_locks`） | 查 `/status` 的 `model_locks`，等解锁日期 |
| 上游真的不可用（`11102 model not available`） | 换一个，或等上游恢复 |
| 池里没有健康账号（`no_healthy_account`） | 见第 4 条（打爆账号池） |

---

<a id="probe-protocol-unsupported"></a>

## 4. 探测脚本报协议不支持 【通用】

**现象**：探针输出里大量 `ModelProtocolUnsupported`，或者脚本判定「三种协议都跑不通」。

> **适用范围**：机制是通用的 —— 上游按协议挑模型，探针逐个协议试，
> 于是「大部分模型报不支持」是**正常结果**不是故障。
> 探针的实现与脚本路径是本仓两个实例的（实例 A 的三协议探针、实例 B 的单协议探针）。

**排查**

```bash
# 1) 看探测结果原始数据
python -c "import json; d=json.load(open('opencode-go/probe/results/20261019/probe_results.json',encoding='utf-8')); [print(k, v.get('status'), (v.get('err') or '')[:80]) for k,v in d.items() if v.get('status')!=200]"

# 2) WorkBuddy 侧：看探测缓存的状态分布
python -c "import json,collections; d=json.load(open('workbuddy/cache/wb_zcode_probe.json',encoding='utf-8')); print(collections.Counter(v.get('status') for v in d.values()))"
```

**原因 / 解法**

| 原因 | 适用范围 | 解法 |
|---|---|---|
| **这不是故障** —— 探针就是在告诉你这个模型不走这个协议 | **【通用】** | 按 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §2.8 的协议表放 |
| 401（凭据 / 隐私授权） | **【通用】** | 脚本解决不了；先修凭据或 Console 权限 |
| 429 | **【通用】** | 日配额耗尽，见第 8 条 |
| `no_healthy_account` | **【实例 B】** | **探测间隔太短，把账号池打爆了** —— 用 `--sleep 20` 重跑（脚本支持断点续跑） |
| 429 / `no_healthy_account` 伴随**网关进程消失** | **【实例 B】** | 网关被打崩了，重启 `wb2api` 后再跑；**先确认 `/status` 可达** |

---

<a id="pricing-stale"></a>

## 5. 价格表过期 【通用机制 + 实例 B 的取数】

**现象**：模型清单看着对，实际花的积分比预期多；或者限时免费到期后倍率没变。

> **适用范围**：**机制通用** —— 任何供应商的目录接口都会变（涨价、促销到期、模型下架），
> 缓存下来的价格表一定会过期。**下面命令是实例 B 的**；
> 别的供应商换自己的目录接口与价格表路径即可（通用做法见
> [MAINTENANCE.md](MAINTENANCE.md) §1.1）。

**排查**

```bash
# 1) 看当前价格表里各模型的生效倍率
python -c "import json; d=json.load(open('workbuddy/cache/wb_pricing.json',encoding='utf-8')); [print('%-32s list=%-6s eff=%s' % (m['id'], m.get('list_rate'), m.get('eff_rate'))) for m in sorted(d, key=lambda x: x.get('eff_rate') if x.get('eff_rate') is not None else 999)]"

# 2) 对比网关当前返回的倍率
curl -s http://127.0.0.1:7863/panel/api/models -H "Authorization: Bearer $WB_GATEWAY_KEY" | python -m json.tool | head -40
```

**原因 / 解法**

| 原因 | 解法 |
|---|---|
| 价格表**忘了刷新** | 跑 `workbuddy/workbuddy_fetch_pricing.py`（`--dry-run` 先看差异）；别的供应商照 [MAINTENANCE.md](MAINTENANCE.md) §1.1 的通用做法用自己的取数脚本 |
| 限时免费到期（网关日志：`free tier ended, now 0.227 credits/1k`） | 重新取倍率，重排四档 |
| 网关未重启时 `/panel/api/models` 只返回 34 个 global 模型 | 重启网关再取 |

---

<a id="config-overwritten"></a>

## 6. 同步后配置被覆盖 【通用】

**现象**：脚本写完是对的，几分钟后模型或 provider 没了 / 顺序变了。

**排查**

```bash
# 1) 看备份链，确认脚本写过了、之后又被改过
ls -lt ~/.zcode/v2/provider_config.json*

# 2) 对比备份内容，看是哪一版丢了什么
python -c "
import json,os,glob
p=os.path.expanduser('~/.zcode/v2/provider_config.json')
b=sorted(glob.glob(p+'.bak-*'), key=os.path.getmtime)[-1:]
for f in [p]+b:
    c=json.load(open(f,encoding='utf-8'))
    r=c['config']['providerConfigRules']; rs=r['providerRules'] if isinstance(r,dict) else r
    print(os.path.basename(f), [(x['providerId'], len(x['config'].get('personalModelIds',[]))) for x in rs])
"
```

**原因 / 解法**

| 原因 | 适用范围 | 解法 |
|---|---|---|
| **ZCode 界面保存时整份写回** | **【通用】** | 写配置期间不要在界面里改；重新跑脚本 |
| `workbuddy_zcode_sync.py` **整条替换** `workbuddy-free/low/high/backup` 四个 provider | **【实例 B】** | 你在这四个 provider 上手工加的模型会被冲掉 —— 加完要重跑脚本，别手改配置 |
| `go_model_sync.py` 把新模型追加到**组尾**，打乱了手工排的顺序 | **【实例 A】** | 组内顺序由脚本按版本号倒序排；要固定顺序就改脚本后重跑 |
| 别的脚本 / 别的会话也在写同一份配置 | **【通用】** | 同一时间只跑一个写入者 |

> **通用做法**：同步脚本对 provider 的写入策略各不相同 ——
> 有的**整条替换**（自己管的 provider 上你手工加的模型会被冲掉），
> 有的**只追加**（组内顺序会被打乱）。写自己的同步脚本时，
> **先想清楚「整条替换」还是「只追加」**，并在报错文案里说清楚。

回退方式见 [MAINTENANCE.md](MAINTENANCE.md) §4。

---

<a id="proxy-port-in-use"></a>

## 7. 代理端口被占用 【实例 A】

**现象**：`node opencode-header-proxy.js` 起不来，报 `EADDRINUSE`。

**排查**

```bash
# Windows
netstat -ano | grep 8787
tasklist | grep <PID>

# Git Bash / 通用
lsof -i :8787
```

**原因 / 解法**

| 原因 | 解法 |
|---|---|
| 上一次没退干净，进程还在跑 | `taskkill //PID <PID> //F`（Git Bash 里 `//` 转义） |
| 端口被别的程序占了 | 换端口：`node opencode-header-proxy.js --port 8788`，客户端 Base URL 跟着改 |
| 想同时开两个实例 | 用不同 `--port` 与 `--session` |

> 顺带：客户端 Base URL 填 `http://127.0.0.1:<port>/v1` 即可，
> 代理会把 `/v1` 或 `/zen/go/v1` 两种前缀都归一到上游的 `/zen/go/v1`。
> **代理不保存也不读取 API key**，key 照旧填在客户端里。

---

<a id="free-pool-429"></a>

## 8. 某个模型突然 429

**现象**：某模型开始 429，`Retry-After` 指向次日 00:00 UTC。

**排查**

```bash
# 1) 看错误里的 Retry-After
#    （ZCode 里看报错详情，或直接 curl 网关看响应头）
curl -si -X POST http://127.0.0.1:7863/v1/chat/completions \
  -H "Authorization: Bearer $WB_GATEWAY_KEY" -H "Content-Type: application/json" \
  -d '{"model":"<model-id>","messages":[{"role":"user","content":"hi"}],"max_tokens":16}' | head -20
```

**原因 / 解法**

| 原因 | 适用范围 | 解法 |
|---|---|---|
| **免费 / 促销档日配额耗尽** | **【通用】** | **等次日再试**。不是配置问题、不是模型下线 |
| 探针把 429 当成「不可用」而排除掉了 → 模型从清单消失 | **【通用】** | 重探一次就回来 |
| 真的撞上限流 | **【通用】** | 降并发、错开时段 |

> **通用做法**：429 + `Retry-After` 落在次日 00:00 UTC = **日配额耗尽**，
> 任何供应商的免费 / 促销档都可能是这个机制。此时改配置、重探、改 provider 归属都是白费力气。

---

<a id="probe-cache-missing"></a>

## 9. 探测脚本报 `wb_pricing.json missing` 【实例 B】

**现象**：`workbuddy_probe_zcode.py` 直接退出：
`wb_pricing.json missing - fetch pricing first`。

**原因 / 解法**

| 原因 | 解法 |
|---|---|
| 文件不存在 —— `.gitignore` 排除了 `/workbuddy/cache/*.json`，**克隆后不会带过来** | 按网关面板手工重建（字段含义见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4），或用环境变量 `WB_PRICING_FILE` 指到别处 |
| 路径变了 | 检查 `WB_PRICING_FILE` / `WB_ZCODE_PROBE_FILE` 环境变量 |

---

<a id="node-missing"></a>

## 10. 探测脚本报 `cannot compute effective bodies` 【通用机制 + 实例 B 的脚本名】

**现象**：`warning: cannot compute effective bodies: ...`，探测结果全部按「最简 body」发。

> **适用范围**：机制是**通用**的 —— 算真实 body 依赖 Node.js 与 ZCode 内置规则文件，
> 拿不到就会退化成裸 body（结果不可信）。脚本名与目录依赖是实例 B 的。

**原因 / 解法**

| 原因 | 适用范围 | 解法 |
|---|---|---|
| 没装 Node.js | **【通用】** | 装 Node.js 并保证 `node` 在 PATH 里 |
| `zcode_effective_body.js` 不在 `workbuddy_probe_zcode.py` 同目录（**硬依赖**） | **【实例 B】** | 把两个文件放同一目录 |
| 找不到 ZCode 内置规则文件 | **【通用】** | 设 `ZCODE_BUILTIN` 指向 `.../ZCode/resources/config/provider/zcode-builtin.json` |
| 规则文件 JSON 坏了 | **【通用】** | 修好它；脚本会退化成发裸 body，结果**不可信**（见 [PITFALLS.md](PITFALLS.md) §2） |

---

<a id="gateway-lifecycle"></a>

## 11. 网关没跟着 ZCode 起停 【实例 B】

**现象**：打开 ZCode 后 WorkBuddy 模型连不上 `127.0.0.1:7863`；或者关了 ZCode
网关进程还在；或者开机后守护器没生效。

**排查**

```bash
# 1) 一次看全：ZCode / 网关 / 守护器
powershell -NoProfile -ExecutionPolicy Bypass -File workbuddy/zcode_gateway_watch.ps1 -Status

# 2) 看守护器日志（每次状态迁移一行；文件是 UTF-8）
python -c "import os; p=os.path.join(os.environ['LOCALAPPDATA'],'ZCodeGateway','watchdog.log'); print(open(p,encoding='utf-8').read()[-3000:])"

# 3) 看开机自启在不在
ls "$APPDATA/Microsoft/Windows/Start Menu/Programs/Startup/" | grep -i zcode
```

**原因 / 解法**（均为**【实例 B】**）

| 原因 | 解法 |
|---|---|
| 守护器没在跑（没装自启 / 被结束） | `-Install`：注册自启并立即启动 |
| `WB_GATEWAY_DIR` 指错，找不到 `wb2api.exe` | 改环境变量，或确认仓库内默认目录 `workbuddy/gateway/` 存在（它整目录被 `.gitignore` 排除，**克隆后不会自带**；重建方法见 [MAINTENANCE.md](MAINTENANCE.md) §8） |
| 网关启动后立刻退出 | 看 `%LOCALAPPDATA%\ZCodeGateway\gateway.stderr.log` |
| 关 ZCode 后网关还在 | 先等满 8 秒宽限 + 最多 30 秒在途连接排空（`-DrainTimeoutSeconds`）；仍不走在 `-Status` 里看守护器是否还活着，必要时 `stop-gateway.bat` |
| `-Status` 的 Provider 行显示「不匹配」或「key 缺失」 | ZCode 的 provider 没指向本网关：重跑 `workbuddy_zcode_sync.py --apply`，或检查 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` |
| `-Status` 显示「有 N 个进程但未识别到主进程」 | ZCode 升级可能改了命令行判据。看 `watchdog.log`；确认新版主进程命令行后更新 `Get-ZCodeMainProcess` 的过滤条件 |
| 自启快捷方式在，登录后却没起 | 目标应为 `wscript.exe "<仓库>\workbuddy\zcode_gateway_watch.vbs"`，用 `-Install` 重建 |
| 想彻底回到手动 | `-Uninstall`，之后按网关目录的 `run.bat` / `stop-gateway.bat` 控制 |

> 守护器只做两件事：**主进程**出现时拉起、主进程退出且连接排空后停止。
> ZCode 只是最小化到托盘时主进程仍在，网关也会保持运行 —— 这是预期行为。
> 生命周期设计的取舍见 [MAINTENANCE.md](MAINTENANCE.md) §8。

---

## 附：通用排查顺序

**换任何供应商都按这个顺序**（括号里是本仓两个实例的具体命令）：

1. **先确认服务活着**（实例 B：`curl http://127.0.0.1:7863/status`；
   实例 A：`curl https://opencode.ai/zen/go/v1/models`）。
2. **再看配置写没写进去**（`provider_config.json` + `.bak-*` 备份链）。
3. **再看 ZCode 真实发了什么**（`workbuddy/zcode_effective_body.js`）。
4. **最后才怀疑上游** —— 大部分「上游坏了」其实是本地配置或请求体的问题。
