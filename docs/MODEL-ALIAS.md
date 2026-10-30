# 统一模型命名与分组

> **一句话**：模型 ID 只用型号名（如 `DeepSeek-4.1-Flash`），同一型号跨渠道合并成一条
> 按价格升序的链路；**2026-10-28 起只保留三组**——主力（人工两条）、免费、
> 省钱（每厂商 1–2 个代表作），未进人工名单的模型**不收录**。

---

## 1. 为什么需要 alias map

显示名不再带渠道和积分，路由无法从名字反推上游（`DeepSeek-4.1-Flash` 对应三个渠道的
三个上游跳）。因此同步脚本同时写两份：

| 文件 | 作用 |
|---|---|
| `~/.zcode/v2/provider_config.json` | ZCode 看到的三个 provider 与显示名列表 |
| `~/.zcode/v2/model-alias-map.json` | 显示名 → `{protocol, price, chain:[{channel, upstream, base, price}], group}`；路由读它 |

`chain` 是**有序链路**：路由从第一跳开始试，遇到 429 / 502 / 503 / 504 或
`400 model_unavailable` 就换下一跳。每一跳自带 `base`，所以一条链路可以横跨
WorkBuddy（7863）、Qoder（8790）、千问（远程 Messages）和 OpenCode-Go（远程）。

**与请求无关的 4xx 也算「这跳作废」**：`Model not exist`（上游没有这个 id）、
`Arrearage` / `AllocationQuota` / `FreeTierOnly`（额度耗尽）、以及 402，都会立即换
下一跳，并把该跳放进 **30 分钟冷却**（内存态，重启清零，`/health` 的 `cooling`
是当前数量）。没有这条，几十跳的集合体每轮都要先把死跳撞一遍。
集合体（池子）的定义见 [QWEN.md](QWEN.md) §4.5；当前 `pools.json` 为空，集合体已停用。

alias map **不含凭据**；上游 key 仍由路由按渠道从 `provider_config.json` /
`gateways/upstream/workbuddy/config.json` / `providers/qoder/.env.local` 读取。

---

## 2. 显示名格式

```
<型号>
```

例：`DeepSeek-4.1-Flash`、`GLM-5.3-Flash`、`Qwen-3.8-Max`、`Claude-Haiku-5.5`。

- **不再带渠道**（原 `W/` `O/` `Q/`）**和积分**（原 `/0.03/`）。
- 版本号保留点号（`4.1` / `3.8` / `2.6` / `5.3`），`Flash` 与 `Preview` 不再缩写（`DeepSeek-4.1-Flash`、`HY4-Pre`）。
- 系列前缀保持可读：`DeepSeek`、`Qwen`、`GLM`、`MiniMax`、`Kimi`、`HY`、`MiMo`、
  `LongCat`、`Beam`、`Claude`、`GPT`、`Muse`、`Step`、`Space`。
- 变体只保留模型本身有意义的：`Flash`、`Pre`=Preview、`Pro`、`Max`、`Plus`、`Vision`。

**同名冲突的两种处理：**

| 情况 | 做法 |
|---|---|
| 同型号既有免费档又有付费档 | **先合并**：免费档并入付费条目当第一跳（见 §3）。只有协议不同无法合并时才单独成条，且**真重名**才给免费那条加 `-Free`（当前无此情况） |
| 同名但协议不同（chat / messages / responses） | 桥接那条加 `-Msg` / `-Resp`（2026-10-28 首次触发：千问桥接版） |

`deepseek-v4.1-flash` 是唯一例外：免费档**并入**付费条目并放在链路第一跳，见 §3。

---

## 3. 跨渠道合并（chain）

同一型号、同一协议的所有渠道按**价格升序**排成一条链路；同价时 GB 优先于 CN，
CN 优先于其它渠道。以 DeepSeek 为例：

```
DeepSeek-4.1-Flash
  1. WB  cn:deepseek-v4.1-flash          0.11   ← 面板现价
  2. OC  deepseek-v4.1-flash             0.11
  3. QW  deepseek-v4.1-flash             0.00   ← 一年期预付额度，钉在链尾
```

- 实际扣费看命中哪一跳；显示名不再体现价格。
- `MERGE_FREE_GB`（当前只有 `deepseek-v4.1-flash`）：免费档不单独成条，直接作为
  付费条目的第一跳。其它型号的免费档仍然单独成条（`-Free`）。
- 合并键是「型号 + 协议」，所以 chat 与 messages/responses 不会混在一条链路里。
- 生成器**幂等**：链路会写回 alias map 的 `chain`，下一次运行从 `chain` 还原全部跳，
  不会因为配置里只剩一个条目而丢掉其它渠道。

### 3.0 每跳自己的出口（`chain[].proxy`，2026-10-30 起）

`chain` 的每一跳可以带 `"proxy": "http://host:port"`，表示**这一跳走这个 HTTP 代理**，
不带就是直连。它解决的是「同一个上游、同一个域名，但有的型号只能从境外 IP 调」：
opencode 的型号共用 `opencode.ai`，规则层分不开，只有 `gpt-*` / `beam-free` /
`muse-spark-*` 拿 403 地区限制（`unsupported_country_region_territory` / `RegionError`）。

生成器给每条 OC 直连跳补一条**同上游的孪生跳**（`AIRPORT_PROXY`，默认
`http://10.0.0.1:7896` —— 路由器上的入站固定绑 🤖 AI接口 组），**排在链尾**：

```
GPT-6-Luna         1. OC gpt-6-luna 直连
                   2. OC gpt-6-luna @机场   ← 直连 403 才走它
DeepSeek-4.1-Flash 1. WB cn → 2. OC 直连 → 3. QW 直连 → 4. OC @机场
```

- zgate 把地区受限的 403 当「换出口」处理，不是「这一跳坏了」；冷却键 `hopKey`
  里含 proxy，否则直连那跳的 403 会把机场跳一起冷却掉（= 兜底被吃掉）。
- 机场跳排链尾而不是紧跟直连跳：前面还有免费的国内跳（千问尾跳）时先试它们。
- 改 `AIRPORT_PROXY` 时路由器侧必须同时有对应的 `listeners` 入站，
  否则这一跳直接连不上（见 ShellcrashRules `docs/ARCHITECTURE.md` §2.2）。

### 3.1 价格是派生量，不继承

`chain` 里存的是「有哪些跳、怎么路由」；`chain[].price` 只是上一轮的记录，
**每轮都从价格源重算**（WB 价格表 / Qoder 在线接口 / OC 静态价表），永不沿用旧值。

- 上游已下架/被封的跳：源里查不到价 → 该跳直接剔除，不靠旧价赖在清单里。
- 价格源不可用（整渠道无价）：拒绝 `--apply`，除非显式 `--force-unpriced`。
- WB 价格表超过 **48 小时**未刷新会打 WARN；`--probe-file` 的探测结果默认超过
  **72 小时**按「未知」处理（`--probe-max-age-hours` 可调，0 = 不设限）。
  过期的 `ok` 会留住已下架的模型，过期的 `blocked` 会删掉还能用的模型，两个方向都错。
- `--check`：把重算结果与现有 alias map 比对，有漂移就以退出码 1 结束，不写盘。
  建议挂进定时任务 —— `sync_report.py` 比的是「上一版产物 vs 这一版」，
  一个稳定存在的偏差在它眼里永远是「无变化」。

> 事故背景（2026-10-28）：Step-5-Pre 的「独家限免」10-25 到期后已按 x0.33 计费，
> 配置里却一直挂在免费档 0.00，就是因为链路继承了 alias map 里的旧价。
> 同轮还抓出 MiMo-2.6-Pro（0.18 应为 0.13）和一条 Qoder 源故障时吃静态回退
> 留下的 0.0 假免费条目。

---

## 4. 三组规则（2026-10-28 起）

分组**不再按价格四档自动切**，而是「人工名单 + 价格兜底」。起因：实测 4 天 74.6 亿
token 里 86% 是 `DeepSeek-4.1-Flash` 一个模型，高耗组 16 条全部零使用。

| 组（providerId） | 装什么 | 判定 |
|---|---|---|
| **主力** `opencode-go-chat` | 两条：`DeepSeek-4.1-Flash`（三跳链：WB → OC → 千问兜底）+ `Qwen-3.8-Max`（贵备份） | `MAIN_IDS`，键是 `<协议>:<上游 id>`，**不受价格上限约束** |
| **免费** `opencode-go-chat-free` | 真免费条目（当前 8 条） | 链路最低价 = 0；组内 `HY` 前缀置顶，其余按价格升序 |
| **省钱** `opencode-go-chat-fast` | **每个厂商 1–2 个最具代表性的现行产品**（当前 9 条）；前旗舰/上一代一律不收录 | 命中 `LOW_PICKS` 即进组，**不受 `LOW_MAX` 价格上限约束**（所以 MiMo-2.6-Pro 0.19 能在组里） |
| ~~高耗~~ | 已删除 | 不在两个名单里且价格 > 0.11 → **不收录** |

为什么这么切：用户的实际选择只有「DeepSeek」和「免费」。按价格四档会让
16 个永远不点的贵模型占着选择器，也让主力被榜单越塞越肿。

三条硬口径：

- **名单的键必须带协议**（`chat:cn:deepseek-v4.1-flash`）。同一型号会以 chat 与
  messages 两种形态同时存在（千问桥接版），只写型号名会把两条一起吸进主力。
- **跨协议合并是例外而非默认**：`MERGE_ACROSS_PROTOCOL` 里的型号（目前只有
  `deepseek-v4.1-flash`）把 chat 与 messages 跳并成一条链，每跳自带 `protocol`，
  路由逐跳派发。`TAIL_HOPS` 再把指定跳钉到链尾，实现「先把月度额度用完，再用
  一年期预付额度」。
- **主力豁免价格上限**：贵备份 `Qwen-3.8-Max` 现价 0.17，其余超限模型一律不收录，
  所以 `--max-price` 只对非主力生效。
- **榜单不再自动扩主力**：`arena_leaderboard.py` 仍能产候选，但
  `model_alias.py` 默认忽略，要 `--arena` 才生效。
- **顺序由人工名单决定，不按价格**：主力按 `MAIN_ORDER`、省钱按 `LOW_ORDER`
  的书写顺序排。旧实现按「厂商最低价」排序，会把便宜厂商顶到前面、把 MiMo 之类
  挤到列表末尾 —— 用户明确要求常用型号在最前，所以排序权收归名单。
- **省钱组只留各厂代表作**：每厂 1–2 个（小米是 Flash + Pro），旧代旗舰
  （如 MiMo-2.5、GLM-5.2、Qwen-3.7）不进组；不在名单里的模型直接不收录。

改名单/改顺序 = 改 `tools/model_alias.py` 的 **`MAIN_ORDER` / `LOW_ORDER`**，
然后 `python tools/model_alias.py --slot auto --apply`。`MAIN_IDS` / `LOW_PICKS`
由这两个有序列表派生，不要再单独维护（两份字面量会漂移）。
**收缩名单要跑两次**：第一次落新分组，第二次才收敛名字（`-Msg` / `-Free`
后缀取决于同型号还有没有别的形态）。

### 4.1 峰谷价（早晚不同）

`model_alias.py` 支持 `--slot auto|peak|offpeak`：

- `auto`：Qoder 按 `price_factor_peak` / `price_factor_valley` 和 `off_peak`
  窗口（22:00–08:00，Asia/Shanghai）取当前价；WorkBuddy 用价格表里的 `eff_rate`
  （由 `workbuddy_fetch_pricing.py` 在时段边界刷新）。
- OpenCode-Go：**只有 DeepSeek V4.1 Flash / V4 Pro** 有峰谷价。峰时是 UTC
  周一至周五 01:00–04:00、06:00–10:00（北京时间 09:00–12:00、14:00–18:00），
  其余时间（含夜间和周末）为谷价；其他 OC 模型是固定价。
- `peak` / `offpeak`：显式取峰价 / 谷价，适合手动预演。

**名字不再随价格变化**：峰谷切换只会改变链路顺序、最低价和分组归属
（例如 Qoder 的 DeepSeek-Flash 谷价时进免费组、峰价时并进付费链路），
不会改显示名，老会话不受影响。

自动切换的做法（北京时间）：每天 **08:00 / 22:00**，外加**工作日 09:00 / 12:00 /
14:00 / 18:00**（OC 峰谷边界）各跑一次：

```bash
python providers/workbuddy/workbuddy_fetch_pricing.py
python tools/model_alias.py --slot auto --apply
```

### 4.2 主力扩充（外部榜单，默认关闭）

2026-10-28 起**默认只用人工 `MAIN_IDS`**，榜单扩充需要显式 `--arena`。

1. **人工**：`model_alias.py` 里的 `MAIN_IDS`，按厂商/额度/协议挑，不随榜单变；
2. **榜单（opt-in）**：`tools/arena_leaderboard.py` 拉 ArenaGalleri 实时榜，按
   「分数 ≥ DeepSeek 基准 95%、积分 ≤ 0.11、非临时、≥50 局、积分 > 0」筛出候选，
   写 `~/.zcode/v2/arena-main.json`；`model_alias.py` 默认读它，任意一跳命中
   `(channel, upstream)` 就放进主力。

```bash
python tools/arena_leaderboard.py --refresh --apply   # 重拉 + 落候选 + 重写三组
python tools/arena_leaderboard.py --status            # 看当前候选
python tools/model_alias.py --no-arena --apply        # 回到纯人工主力（默认即是）
```

- 榜单口径、名字映射与 2026-10-23 的候选表见 [BENCHMARKS.md](BENCHMARKS.md) §8。
- **免费条目不进主力**（价格 = 0 留在免费组）；榜单掉出窗口的模型退回价格分组。
- 榜单每 10 分钟更新，但只有候选集合或规则变化才重写配置；分数波动不会引起 ID 抖动。
- 候选按谷价/eff/valley 判断，峰时切价不会改变主力成员。

## 5. 协议桥接

`gateways/zgate` 内置协议桥（原 `tools/protocol_bridge.js` 已退役），把 chat 请求转成：

- Anthropic Messages（`/v1/messages`，`x-api-key` + `anthropic-version`）
- OpenAI Responses（`/v1/responses`，Bearer）

上游按 **`stream: true`** 调用，桥接器边收边转成 chat SSE（2026-10-29 起）：
文本、`thinking` 推理、以及**工具调用增量**都是逐块转发，首字不再等整段生成完。

- 工具调用双向转换：`tools` / `tool_calls` / `tool_use` / `function_call`；
  流式下 `content_block_start`(tool_use) → `input_json_delta` → chat
  `tool_calls` 增量，收尾 `finish_reason` 为 `tool_calls`。
- **只有链尾跳走流式**：前面某跳失败还要能回落，已写出的半截 SSE 收不回来，
  所以非尾跳仍整段缓冲后一次写出。
- 上游在写出任何 chunk 前就报错（4xx/5xx）时，桥接器把真实错误码经 JSON
  回给客户端，不会留下一个挂起的空流。
- **空闲看门狗**：上游连上后连续 30 秒没有任何字节，桥接器主动断开并返回
  `504 upstream_timeout`（`DefaultIdle`）。没有它，静默的聚合端点会一直等到
  120 秒总超时，用户端就是「两分钟没响应」。
- **429 处理**：先就地退避 700ms 重试同一跳一次；仍 429 才短冷却 45 秒；
  桥接上游静默超时冷却 5 分钟；模型不存在 / 额度耗尽等死跳仍冷却 30 分钟。
- 链路里的桥接跳失败（5xx / 429 / 503）会自动换下一跳。

---

## 6. 生成与探测

```bash
# 0. 重拉外部榜单，更新主力候选（候选没变时不会触发重写）
python tools/arena_leaderboard.py --refresh --write

# 1. 用真实 ZCode body 探测全部模型（经 7871，按 provider 套用 optionSpecs）
python tools/model_probe.py

# 2. 生成三组 + alias map；只保留探测 ok（或曾 ok 的瞬时限流）的模型
python tools/model_alias.py --slot auto --probe-file ~/.zcode/v2/model_probe.json --apply

# 3. 漂移自检：重算结果应与刚落盘的 alias map 完全一致（退出码 0）
python tools/model_alias.py --check
```

- 只预演：去掉 `--apply`。
- 备份：`provider_config.json.bak-alias-<时间戳>`。
- 回归测试：`python -m unittest discover -s tests -v`（价格派生、死跳剔除、漂移检测、
  探测过期）。
- 旧 ID（`cn:` / `global:` / `qoder:` / 裸 OC，以及旧的 `W/0.03/…` 显示名）会进
  alias map 的 `legacy`，老会话仍可路由；改名链会自动追到最终名字。
- 旧的 `workbuddy_zcode_sync.py` / `go_model_sync.py` / `qoder_zcode_sync.py`
  现在只当**数据采集器**：它们写旧 ID，随后由 `model_alias.py` 归一化。不要
  在 `model_alias.py` 之后单独跑它们的 `--apply`，否则会临时把旧 ID 写回去
  （实测会把 `cn:*` 原始 id 混进分组的 `personalModelIds`，下一次生成的命名顺序
  也会跟着变）。

---

## 7. 已知边界

- 价格不进 ID 后，**改名只发生在型号/版本变化时**；峰谷切换只影响分组归属。
- 峰谷重写按 §4.1 的时段跑；不跑则分组停在最后一次生成的时段。
- `no_healthy_account` / `400 model_unavailable`（WorkBuddy 池冷却或模型级限流）
  会触发下一跳；没有下一跳时才报 502。
- `deepseek-v4-flash-vision-exp` 没有公布价格，暂不收录；`minimax-m2.7` 价格已公布
  （$0.30/$1.20 → 积分 0.22），2026-10-26 起收录。
- 桥接模型已改为流式（§5）；**非链尾跳**仍是整段缓冲，这是为回落安全付出的代价。
- 上游自己不流式时（实测 Qoder 渠道整段缓冲，首字 ~32s），桥接器无法改变，
  只能等上游；这类慢模型不要放进主力。
- 别名表是本地活数据，不入库；`provider_config.json` 与备份同样不入库。
- 榜单接口不可用时用本地缓存；缓存也没有就跳过扩充，人工 `MAIN_IDS` 仍生效。
- 同名不同协议的条目靠 `-Msg` / `-Resp` 区分；免费条目默认不加后缀，只有与
  付费条目**真重名且无法合并**时才加 `-Free`。

---

## 8. 相关

- 价格 / 协议来源：[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)
- 外部榜单与主力扩充口径：[BENCHMARKS.md](BENCHMARKS.md) §8
- 工具清单：[TOOLS.md](TOOLS.md)
- 日常维护：[MAINTENANCE.md](MAINTENANCE.md)
- Qoder 专用链路：[QODER.md](QODER.md)
