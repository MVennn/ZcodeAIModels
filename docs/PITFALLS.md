# 踩坑总汇

> **一句话**：这里解释**为什么**会出这些故障 —— 每一条都对应一次真实的排查，
> 机制讲清楚，步骤去 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。
>
> **读法**：标 **【通用】** 的坑换任何供应商都成立（ZCode 客户端侧的行为）；
> 标 **【实例 A】/【实例 B】** 的是本仓两个示例供应商特有的上游行为。

| 标记 | 适用范围 |
|---|---|
| **【通用】** | ZCode 客户端侧 —— 换任何供应商都成立 |
| **【实例 A】** | OpenCode-Go 特有 |
| **【实例 B】** | WorkBuddy2API 网关特有 |

---

## 1. 协议放错 → 400 `ModelProtocolUnsupported` 【通用】

**现象**：模型在某个 provider 下请求直接 400，报错里带 `ModelProtocolUnsupported`
或 `does not support this protocol`。

**机制**：OpenCode-Go 的模型分三种协议，**每个模型只认自己那一种**：

| 协议 | 端点 |
|---|---|
| `openai-chat-completions` | `/zen/go/v1/chat/completions` |
| `anthropic-messages` | `/zen/go/v1/messages` |
| `openai-responses` | `/zen/go/v1/responses` |

ZCode 的 provider 由 `api.type` 决定端点。**把模型塞进错误协议的 provider，
上游直接拒。** 这是本仓最大的一个坑 —— 一次探测实测里 34 个模型有 8 个在 chat 协议下
返回 `ModelProtocolUnsupported`（`grok-4.6`、`grok-4.7`、`gpt-6-luna`、`gpt-5.6-luna`、
`claude-haiku-5-5`、`minimax-m2.7`、`muse-spark-1.2/1.3-contributor`、
`gemini-4-argon-contributor`）。

**同族错误**：鉴权头也**分协议** —— `chat/completions` 与 `responses` 认
`Authorization: Bearer <key>`，`anthropic/messages` **只认** `x-api-key: <key>`。
用 Bearer 打 messages 会 401 `Go requires a credential`。

**解法**：按协议分 provider（本仓的「主力 / 免费 / 低耗 / 高耗 / 对话 / 响应」就是
这么分的），模型清单见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §2。

---

## 2. ZCode 内置通用规则无条件发思考字段 → 400 【通用】

**现象**：`curl` 手搓同样的模型能通，**在 ZCode 里一发就 400**。

**机制**：ZCode 的内置规则 `modelConfigRules.modelApiRules` 里，第 3 条是
`openai-chat-completions` 的通用规则 `.*`，它的 `reasoningLevel.map` 表达式会
**无条件**注入四个字段：

```json
{
  "thinking": { "type": "enabled" },
  "enable_thinking": true,
  "reasoning_effort": "high",
  "reasoning": { "effort": "high" }
}
```

它**不检查模型是否支持**。上游不认其中任何一个字段就 400。

WorkBuddy 网关更糟一层：它的出站逻辑**只**重写 `reasoning_effort`（按模型
`supportedEfforts` 降级），**ZCode 发的 `thinking` / `enable_thinking` / `reasoning`
字段网关不删，原样透传给上游** → 上游不认就 400。

**解法**：

1. **探测必须用 ZCode 真实请求体**，不能拿裸 body 试 ——
   `providers/workbuddy/workbuddy_probe_zcode.py` 就是干这个的（先算真实 body，失败再退
   slim variant）。
2. 给模型配 `optionSpecs.reasoningLevel.map = "{}"` —— **发空 map 覆盖掉通用规则**，
   一个思考字段都不发。当前配了 5 个：
   `beam-free`、`minimax-m3.1-flash-free`、`minimax-m3`、
   `muse-spark-1.3-contributor`、`muse-spark-1.2-contributor`。
3. 需要「显式关掉」而不是「不发」时，用 `{"thinking":{"type":"disabled"}}`。

**「curl 能通但 ZCode 400」的根因永远是这一条**，不是配置写错、不是模型下线。

---

## 3. `modelMatch` 是全匹配正则，不是子串匹配 【通用】

**机制**：ZCode 匹配规则用的正则是 `^(?:pattern)$`（大小写不敏感）。
所以：

- 写 `deepseek` **不会**匹配 `deepseek-v4.1-flash`；
- 想匹配前缀必须自己写 `.*deepseek.*`；
- 内置规则里 `.*deepseek-v4[.-]1-flash.*` 同时覆盖 `deepseek-v4.1-flash` 和
  `deepseek-v4-1-flash`（`[.-]` 兼容两种分隔符）。

**推论**：`cn:deepseek-v4.1-flash` 这种带前缀的 modelId，**内制的
`.*deepseek-v4[.-]1-flash.*` 也能匹配上**（因为是 `.*` 包裹的模式）——
但如果你自己写规则只写 `deepseek-v4.1-flash`，就**匹配不到** `cn:deepseek-v4.1-flash`。

**解法**：写规则一律用 `.*` 头尾包；改完用 `providers/workbuddy/zcode_effective_body.js`
验证命中的是哪一条。

---

## 4. 规则按序叠加，后者胜 【通用】

**机制**：ZCode 的 `ModelConfigRules.resolve()` **按规则列表顺序**遍历，
把每条命中规则的 config **覆盖**到累加器上 —— **后面的规则覆盖前面的**。

所以「通用规则在前、专属规则在后」这个布局是**必需的**：通用规则无条件注入思考字段，
专属规则（`.*deepseek-v4[.-]1-flash.*` 等）排在后面才能把它盖掉。

`optionSpecs.reasoningLevel.map` 也是同一个语义：**最后一条命中的规则**的 map 生效。

**坑点**：

- 往 `modelApiRules` 里**中间**插一条通用规则，会把后面所有专属规则的覆盖打乱；
- 自定义规则如果不排到通用规则**之后**，就会被通用规则盖回去；
- `apiTypeMatch` 不同的规则**不互相覆盖**（`anthropic-messages` 的规则不影响
  `openai-chat-completions` 的请求）。

**解法**：改规则后必须重算真实 body 验证，别凭记忆。

---

## 5. 探测必须用 ZCode 真实 body，且间隔 ≥ 20 秒 【通用机制 + 实例 B 的间隔值】

**现象（其一）**：探测结果全是 200，但 ZCode 里实际用不了（→ 见 §2）。

**现象（其二）**：探测跑到一半，接口开始返回 `no_healthy_account` / 429，
甚至**网关进程直接消失**。

**机制**：WorkBuddy 网关的账号池只有 4 个号（global 只有 3 个），
网关有**熔断与冷却**：一个号被快速打满就进冷却，池子里就没号可用了。
实测**4 秒间隔会把 global 全部打进 `no_healthy_account` 冷却**（首次探测即如此）。
必须 **≥ 20 秒间隔**。

同一现象在路由器那条线上也出现过：10 个子代理同时密集探测 → 负载冲到 2.6 → 看门狗复位；
批量审计**必须限速、串行化**。

**解法**：

- 探测间隔 ≥ 20 秒（`--sleep 20`）；
- 探测前先确认网关活着：`curl http://127.0.0.1:7863/status`；
- 探测脚本**支持断点续跑**（缓存写盘），中断后重跑不会重来一遍。

---

## 6. 免费池日配额耗尽 → 429（**不是配置问题，也不是模型下线**） 【通用】

**现象**：某个模型突然开始 429，错误里的 `Retry-After` 指向**次日 00:00 UTC**。

**机制**：免费 / 促销档模型有**日配额**，用完就是 429，冷却到次日零点。
这跟模型是否被弃用、配置是否写错**完全无关**。

**关键判断**：看到 `Retry-After` 落在次日 00:00 UTC，就知道是**日配额耗尽**，
**等次日再试**。此时去改配置、去重探、去改 provider 归属都是白费力气。

**另一个容易误判的点**：探针把 429 归类成 `rate_limited`，脚本会把它当成
「模型不可用」而排除掉 —— 于是模型从清单里**消失**了，看起来像「模型被下架」，
其实只是**当天用完了**。重探一次就回来了。

---

## 7. `modelProtocolUnsupported` 样本与协议归属 【实例 A 的样本】

**现象**：批量探测里大量 400，全是 `ModelProtocolUnsupported`。

**这不是故障，是这台机器的正常结果** —— 它说明**协议探测在正常工作**，
只是那个模型不归 chat 协议管。协议归属表见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §2.8。

**但要注意两种 400 的区别**：

| 报错 | 含义 | 处理 |
|---|---|---|
| `ModelProtocolUnsupported` | 这个模型不走这个协议 | 换协议，别记成故障 |
| `trains on request data` / 隐私设置拦截 | workspace 没开「付费且训练数据的端点」 | 去 Console 开权限，脚本解决不了 |
| `401` | 凭据或权限问题 | 脚本解决不了，不收录 |

---

## 8. ZCode 配置会被界面覆盖 【通用】

**现象**：脚本写完配置、ZCode 也热重载了，但过了几分钟配置又变回原样。

**机制**：ZCode 的 provider 设置界面保存时**整份写回** `provider_config.json`，
把脚本刚写的部分覆盖掉。脚本写完那一刻是对的，几分钟后就回退了。

**解法**：**写配置期间不要在 ZCode 界面里同时改**。要改界面就先改完再跑脚本。

---

## 9. 明文凭据会随仓库一起走 【通用】

**现象（未来）**：仓库上传到公开 GitHub，**API key 一起公开了**。

**现状**：`providers/opencode-go/probe/` 下的 `probe_models.py`、`probe_protocols.py`、
`bench_models.py`、`bench_clean.py`、`thinking-off-probe.js` **已改为从 `OPENCODE_GO_KEY` 环境变量读取**；
`provider_config.json` 的 `.bak-*` 备份里也有 key。

**解法**：

- 脚本从**环境变量**读凭据（`WB_GATEWAY_KEY` / `WB_GATEWAY_BASE` /
  `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` / `ZCODE_BUILTIN` / `OPENCODE_SESSION`），
  规则见 [AGENTS.md](../AGENTS.md) §2；
- `.gitignore` 已排除 `*.key`、`*_key*`、`*.env`、`*.bak-*`；
- **上传前逐个 `grep` 一遍**，别靠 `.gitignore` 兜底。

---

## 10. 硬编码路径在拆仓后失效 【通用】

**现象**：脚本跑完了，但产物没落在预期位置。

**机制**：脚本里写死了某个绝对路径（尤其是**写死某个人的主目录**），
换台机器就失效 —— 报告落到旧目录、配置读的是不存在的路径。

**历史实例**：`providers/opencode-go/ops/go_model_sync.py` 的 `REPORT_DIR` 原先指着拆仓前的旧仓库目录，
报告会落到旧仓库去；ZCode 配置路径原先写死成某个开发者的主目录路径。
**拆仓时已修**：报告目录改为按脚本位置推导的本仓 `evidence/`（保留 `GO_SYNC_REPORT_DIR` 覆盖口）；
配置路径默认值改为按**当前用户主目录**推导（仍可用 `--config` 覆盖）。

**解法**：保持"路径由脚本自身位置推导 / 按当前用户主目录推导"这条约定 ——

- 新增脚本时用 `os.path.dirname(os.path.abspath(__file__))` 推导仓内路径；
- 涉及用户主目录的路径用 `os.path.expanduser("~")`，**不要写死用户名**；
- 提供环境变量或命令行参数覆盖口。

---

## 11. `wb_pricing.json` 的生成脚本（已补上，但别再手工维护） 【实例 B】

**现象**：想重探 WorkBuddy，脚本直接退出：
`wb_pricing.json missing - fetch pricing first`。

**机制**：价格表（模型倍率 / 上下文 / 输出上限 / effort 档位）是分档的**唯一输入**，
而它过去**只能手工维护** —— 全仓没有任何脚本能生成它。

**为什么重要**：限时免费会到期、倍率会调整，**价格表过期 = 分档过期 =
清单里的模型实际比标称的贵**。

**解法（已落地）**：`workbuddy_fetch_pricing.py` —— `GET /panel/api/models` → 归一化 →
写 `cache/wb_pricing.json`（写前自动备份），并打印**倍率变化 / 新增 / 下架**的摘要。

```bash
cd workbuddy
python workbuddy_fetch_pricing.py            # 写入
python workbuddy_fetch_pricing.py --dry-run  # 只看差异
```

字段含义见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4；
刷表频率与注意事项见 [MAINTENANCE.md](MAINTENANCE.md) §1.3；
**通用做法**（换供应商照这个做）见 [MAINTENANCE.md](MAINTENANCE.md) §1.1。

---

## 12. 一个 provider 只能一个 `baseUrl` → 跨上游必须路由 【通用】

**现象**：想把 WorkBuddy 模型和 OpenCode-Go 模型放进同一个 provider，结果要么 404 / 401，
要么只有一边能用。

**机制**：ZCode 的 `providerConfigRules[].config.api.baseUrl` 是 **provider 级**的；
模型级 `modelConfigRules` 只有 `enabled` / `properties` / `optionSpecs`，**没有** `baseUrl`。
一个 provider 下的所有模型共用同一个上游地址和 key，不能按模型换上游。

**解法**：本仓用 `gateways/zgate` 做本地入口 —— 四个 chat provider 指向
`http://127.0.0.1:7871/v1`，路由按 model 前缀把 `cn:` / `global:` 转到 WorkBuddy 网关，
其余转到 OpenCode-Go。代价是多一个常驻进程；它随 ZCode 起停（见
[MAINTENANCE.md](MAINTENANCE.md) §8）。**不要把路由端口暴露到公网**，也不要把两个
上游的 key 混进同一个 provider。

## 13. 凭据扫描的占位符不能整行放行

**现象**：`tools/check-secrets.py` 对「示例与真值同一行」完全失明。

**根因**：`PLACEHOLDER` 命中后整行 `continue`；行内出现 `example.com` / `<...>` /
`YOUR-` 时，同一行的真 `oc_sk_` / `sk-` token 不会被报。

**解法**：只豁免匹配片段本身（`m.group(0)`），示例 URL 仍按预期放行。

## 14. `gateways/upstream/workbuddy/` 是上游独立 clone，改动只在本地

**现象**：在网关里修了日志脱敏、示例配置、启动告警，`git status` 却什么都不显示，
CHANGELOG 里写的条目在远端仓里找不到对应代码。

**机制**：主仓 `.gitignore` 用 `/gateways/upstream/workbuddy/` **整目录**排除 —— 里面是
`auths/` 账号凭据、`config.json`（api_key）、`data/` 运行时状态与 `wb2api.exe`。
更新方式是 `git -C gateways/upstream/workbuddy pull --ff-only`，不是本仓管理。

**怎么避**：改网关代码前先确认它在不在 `git ls-files` 里；本地改动单独记账，
不要写进本仓 CHANGELOG（那里只记随仓分发的内容）。二进制重建后留 `.bak` 再替换。

## 15. 首次启动的日志与示例配置都不能带凭据

**现象**：网关首次启动时把自动生成的 `api_key` 明文打进 stdout；守护器把 stdout
落到 `logs/gateway.stdout.log`，等于凭据明文落盘。示例配置里的 `api_key` 是
`test_key`，而 README 的部署步骤要求 `cp` 这份文件。

**解法**：启动日志只提示「已写入该文件」，不打印值；示例配置用 `CHANGE_ME` 这类
一眼就知道要改的占位符；`api_key` 为空或仍是占位符、且监听地址不是回环时打 WARN。

**下次怎么避**：任何「首次运行自动生成凭据」的路径，都当成凭据泄露面审一遍 ——
日志、示例文件、错误信息、面板回显四个地方都要看。

## 16. 显示名不是上游模型 id，旧 sync 不能直接拿去探测

**现象**：`model_alias.py` 把配置里的模型重命名成 `DeepSeek-4.1-Fs` 这类
显示名后，`go_model_sync.py` 的「跑不通即清」会把显示名当上游模型 id 发给
`opencode.ai/zen/go/v1`。上游 404 → 判定「已不在任何清单」→ 下一次 `--apply` 全部
prune。它同时也认不出这些模型已经配置过，会把整个 Go 目录当新模型重评估一遍。

**机制**：显示名只对统一路由有意义（7871 读 alias map 还原上游名），上游网关没有
这个名字。任何「拿配置里的模型 id 直接打上游」的脚本，在重命名之后都会失效。

**解法**：体检前先读 `~/.zcode/v2/model-alias-map.json`，把显示名还原成
`upstream` 再探测；`channel` 是 `WB` / `QD` 的直接跳过（非 Go 套餐）。
`go_model_sync.py` 的 `display_alias()` + `probe_targets()` 就是这么做的。

**下次怎么避**：凡是消费 `personalModelIds` 并直接请求上游的脚本，先问一句
「这个 id 是显示名还是上游 id」；显示名一律经 alias map 还原，删除时仍用显示名
（配置里存的是它）。

## 17. 从 JS 移植时，`url.search` 自带 `?`，Go 的 `RawQuery` 不带

- **现象**：任何带查询参数的请求都 404/400，日志里路径和 query 粘在一起
  （`POST /chat/completionsstream=1`）。
- **根因**：JS 的 `url.search` 返回 `?a=b`，Go 的 `u.RawQuery` 只返回 `a=b`；
  移植时直接 `base + path + search`，少了一个分隔符。
- **解法**：拼接 query 时显式补 `?`（或在 `normalizePath` 里统一返回带 `?` 的串），
  并补一条「上游确实收到 query」的端到端测试 —— 只测 path 的用例发现不了。
- **验证**：`go test ./internal/router -run TestQueryString`。

## 18. 用 `dirname` 层数推仓库根，脚本一搬家就落错目录

- **现象**：同步报告跑到 `providers/evidence/`，与已入库的 `evidence/` 分家，
  下一次大扫除才发现。
- **根因**：`os.path.dirname(...)` 叠了三层，脚本在 `providers/opencode-go/ops/`
  下时只到 `providers/`；脚本从 `scripts/` 搬过来后层数没跟着改。
- **解法**：路径按「相对仓库根的固定层级」写，并在注释里标明层级；或者用
  `git rev-parse --show-toplevel` / 显式配置项。改目录结构时全局搜 `dirname(`。
- **验证**：跑一次 `--dry-run`，确认报告路径在 `evidence/` 下。

## 19. 价格源静默失败会把整个渠道的模型从配置里剔除

- **现象**：某次同步后某渠道的模型全没了，日志里只有「收录 N 个」，没有告警。
- **根因**：价格缓存读不到时函数返回空表，下游把「没有价格」当成「不可用」直接
  `continue`；`--apply` 随后重写配置，等于整批删除。
- **解法**：价格源不可用必须 stderr 告警；整渠道 100% 无价时拒绝写入
  （提供显式 `--force-unpriced` 绕过），并把「因缺价未收录 N 个」打进摘要。
- **验证**：临时改名价格缓存跑一次 `--apply`，确认退出码非零且配置未变。

## 20. 裸 `go build` 会把无窗 zgate 覆盖成控制台程序 【通用】

- **现象**：开机自启时弹出一个 cmd 控制台窗口，标题是快捷方式名
  （「ZcodeAIModels zgate」）；关掉那个窗口等于杀掉网关，模型全挂。
  有时窗口是「可见的」而不是最小化 —— 快捷方式里 `WindowStyle = 7`
  只对**有窗口**的程序生效，对控制台子系统程序不等于隐藏。
- **根因**：Windows PE 头里的 `Subsystem` 字段决定程序启动时要不要分配控制台。
  - `2` = `WINDOWS_GUI` → 无窗（设计要求）
  - `3` = `CONSOLE` → 一启动就分配一个真控制台窗口
  `-H windowsgui` 是**链接期** flag，只在那一次编译里生效。事后从源码看不出来，
  只能读产物的 PE 头。
- **回退是怎么发生的**：`go build` 在**单包**模式下会把可执行文件写到当前目录，
  所以在 `gateways/zgate/` 里跑一次裸 `go build .`，就把之前用
  `-ldflags "-H windowsgui"` 编好的无窗版**原地覆盖**成控制台版。
  （`go build ./...` 是多包模式，Go 只编译不落盘，**不会**覆盖 —— 实测确认。）
  产物在 `.gitignore` 里（`/gateways/zgate/*.exe`），所以 `git checkout` 救不回来。
- **为什么难发现**：覆盖发生在**编译期**，弹窗发生在**下次开机**，
  中间隔着一次重启；日志、git 历史、进程列表都看不出因果。
- **解法**：编译入口收口到 `gateways/zgate/build.py`（带 flag + 强制校验 PE 子系统）；
  检查用 `go vet ./...`，别在 `gateways/zgate/` 里裸跑 `go build`。
- **验证**：`python gateways/zgate/build.py --check` 打印
  `Subsystem = 2 → WINDOWS_GUI（无窗）`；`--cross-check` 会在临时目录交叉编译一份
  windows/amd64 再校验，CI 用这条（Linux 上也能真跑起来）。

## 21. 上游握手超时留 15s，会把一次失败拖成长尾 【通用】

- **现象**：机器人调用 `opencode.ai` 偶发 502，单次回复 22–32s；zgate 日志里
  `Post "https://opencode.ai/zen/go/v1/chat/completions": net/http: TLS handshake timeout`。
- **根因**：本机到 `opencode.ai` 走 fake-IP 透明代理，链路握手会抖（同一节点实测成功
  0.32s，坏窗口 0.6–7.7s，再往上就不返回了）。transport 的 `TLSHandshakeTimeout`
  是 15s，且 `http.Client` 没有整体 `Timeout` —— 一次坏叫要等满 15s 才回落，
  叠上 WorkBuddy 免费池的 429/503 再排队，回复就拖到 20 秒以上。
- **解法**：`TLSHandshakeTimeout` 收到 8s。**不要**顺手给 `http.Client` 设 `Timeout`：
  它覆盖整个响应体，流式（SSE）会被从中间截断，非流式的长推理也会被误杀。
- **验证**：`grep TLSHandshakeTimeout gateways/zgate/main.go` 应为 8s；
  坏窗口内单次失败的上限约为 8s，而不是 15s。

## 22. 派生数据落盘又回读 → 上游改价永久不生效 【通用】

- **现象**：上游限免到期/调价后，ZCode 里的积分和分组纹丝不动，同步报告也一直写
  「分组变化 0、链路变化 0」。2026-10-28 的 Step-5-Pre 就是这样：面板已是 x0.33、
  真实调用也在扣积分，配置里仍挂在「免费 @0.00」。
- **根因**：两层叠加。`expand_hops()` 把 alias map 里 `chain[].price` 原样带回，
  `family_entries()` 又优先用 `item["price"]`，`price_of()` 只在它是 `None` 时才跑；
  而 alias map 本身就是上一轮的输出。**输出成了下一轮的输入，一次写入等于永久冻结**。
- **为什么难发现**：`sync_report.py` 比的是「上一版产物 vs 这一版」，两边都来自同一份
  缓存时，稳定存在的偏差永远是「无变化」——报告越正常，越说明不了问题。
- **解法**：派生量（价格、分组、链路顺序）每轮从源重算，alias map 只存推不出来的
  身份信息；源里没有的 hop 直接剔除。另加 `--check`（重算 vs 现有 alias map，
  有漂移退出码 1）挂进定时任务。探测结论同理：超过 TTL 的 `ok` / `blocked` 一律
  按「未知」处理——过期的 ok 会留住死模型，过期的 blocked 会删掉活模型。
- **验证**：`python tools/model_alias.py --check` 退出码 0（幂等）；
  `python -m unittest discover -s tests -v` 里
  `test_chain_price_is_not_inherited` / `test_dead_hop_is_dropped` 通过。

## 23. 错误路径读异常属性，异常的字段契约必须先兜住 【通用】

- **现象**：上游排队（`10605` / `isQueued`）重试耗尽后，客户端什么也没收到；
  `qoder-proxy.err.log` 里是一条 `AttributeError: 'RateLimited' object has no
  attribute 'status'` 的线程 traceback，但 `/ping` 一直 200、进程也没退。
  同一时刻非流式请求拿到的是 502，而不是 429 + Retry-After。
- **根因**：两套异常并存。`UpstreamStatus` 有 `.status` / `.detail`，而排队转换
  `_as_rate_limited_for_queue()` 产出的是 `RateLimited`（只有 `.detail` / `.wait`）。
  流式 pump 的错误收尾统一写 `record_error(model, exc.status, ...)`，这个属性一缺，
  异常在 `do_POST` 里二次抛出 —— `BaseHTTPRequestHandler` 只打印 traceback，
  **不再发任何响应**。非流式路径则因为没有 `except RateLimited` 分支，掉进通用
  `except Exception` → 502，客户端看到的是「上游故障」而不是「请退避」。
- **为什么难发现**：崩在请求线程里，主线程与 `/ping` 不受影响；日志前一行还是
  HTTP 200（SSE 响应头已发），看不出请求其实没结束。
- **解法**：异常类自己承担错误路径的字段契约（`RateLimited.status = 429`、
  `retry_after` 与 `wait` 同源）；所有会进入错误收尾的聚合路径显式
  `except RateLimited` → `_rate_limited()`。**不要**在错误处理里用
  `getattr(exc, "status", 502)` 掩盖缺字段：状态码会被悄悄改成 502。
- **验证**：`python tests/_test_issue71_queue_error_paths.py` 全绿；
  排队场景实测返回 `HTTP 429` 且日志不再出现 traceback。

---

## 24. 控制台「有额度」不等于 API「能调用」；桥接基址必须带 `/v1` 【通用】

- **现象**：千问控制台「权益」页列着 506 条免费额度，但把清单直接播种进配置后，
  一部分模型请求回来 `400 InvalidParameter: Model not exist.`；换成别的写法又是
  `404 InvalidParameter: Not support`。
- **根因**两个，互不相关：
  1. 额度页是**商业化目录**，与 API 网关的可用集合不是同一份。
     `qwen3-max` / `qwen3-coder-plus` / `qwq-plus` 有额度但网关没有这些 id
     （`qwen-max` 才有）；`Model not exist.` 是唯一的判据。
  2. `zgate` 的协议桥把地址拼成 `TrimRight(base,"/") + "/messages"`，
     **不会**自己补 `/v1`。基址写成 `.../apps/anthropic` 就打到
     `/apps/anthropic/messages`，上游回 `Not support`（它的 404 不区分「路径不认识」
     与「模型不认识」，只看 `message` 字段）。
- **为什么难发现**：两种错误都是 4xx + 一句短语，`model_probe` 一律归类成
  `error`，看起来像「模型坏了」；而 `Not support` 其实是地址错，改价格/改模型都没用。
- **解法**：
  - 目录一律**先探测再收录**，不要信控制台列表（漏斗最后一层就是真实体探测）；
  - 配 `QW` 这类桥接上游时，基址写全 `…/v1`（`QWEN_BASE` 也一样）；
  - 看到 `Not support` 先查 base，看到 `Model not exist.` 才查 id。
- **验证**：`curl /health` 里 `qwen.base` 以 `/v1` 结尾；14 个收录模型
  `tools/model_probe.py` 全部 `ok`（2026-10-28）。

---

## 25. 桥接条目会抢走原型名，把聊天条目挤成 `-2` 【通用】

- **现象**：接入千问后，`GLM-5.3` / `Qwen-3.8-Max` / `DeepSeek-4-Pro` 的显示名还在，
  但指向从「Qoder 聊天」变成了「千问桥接」；原来的聊天条目改名成 `GLM-5.3-2`。
  老会话里选中的 `GLM-5.3` 于是静默换了渠道。
- **根因**：命名去重按**条目录入顺序**先到先得，而「免费组」在「高耗组」之前生成，
  桥接（messages）条目先拿到原型名，规则里「桥接那条加 `-Msg`」根本没被用上。
- **解法**：命名时先看**同一 abbr 存在哪些协议**——只要同时有 chat 与桥接，
  原型名永久留给 chat，桥接那条按协议加 `-Msg` / `-Resp`。这条与
  [MODEL-ALIAS.md](MODEL-ALIAS.md) §2 的规则一致，且与生成顺序无关。
- **验证**：`ListModels` 里 `GLM-5.3`(高耗/QD chat) 与 `GLM-5.3-Msg`(免费/QW)
  并存；`tools/model_alias.py --check` 零漂移；四组内无重复 id。

---

## 26. 合成条目过关时会被 inventory 按跳拆开，下一轮翻倍 【通用】

- **现象**：三个集合体（一条显示名派生 91 跳）写进配置后，下一轮
  `model_alias.py --apply` 里千问的模型条数从 17 跳到 117：每个跳都成了一条
  独立显示名（`qwen3-max`、`qwen-turbo`…），再下一轮还会继续膨胀。
- **根因**：`inventory()` 对配置里的每个 id 调 `expand_hops()`，而
  `expand_hops` 的语义是「把一条链展开成每一跳」，于是集合体被拆成了 91 个
  `(channel, upstream, protocol)` 单项；每项 base_model 不同 → `abbr` 不同 →
  各自成一个 family → 各自写回配置。名字还都是裸 id，因为 `ABBR` 里没有它们。
- **为什么难发现**：第一轮输出看起来完全正常（3 个池子 + 14 个单型号），
  膨胀发生在**下一轮**；`--check` 也不会报，因为两轮都是自洽的。
- **解法**：集合体在 alias map 里标 `kind: pool`；`classify()` 见到这个标记
  直接返回 `None` —— 池子只由 `pools.json` 生成，永不参与 inventory。
  配套给 `legacy` 加了守卫：带渠道前缀的 key 必须真能对上目标条目的某一跳，
  否则视为陈旧映射（否则一个旧 key 会把新模型静默指到别的条目上）。
- **验证**：连续跑两次 `model_alias.py --slot auto --apply`，alias map 条目数
  稳定在 52；`--check` 退出码 0。

## 27. 桥接模型整段缓冲 → 首字像卡死；改成流式后又必须保住回落安全 【通用】

- **现象**：走协议桥（Messages / Responses）的模型首字要等整段生成完才一次性
  吐出来（实测 Conatus 12.06s 才收到唯一一个 chunk，Qwen-3.8-Flash-Msg 5.07s
  单块），而原生 chat 模型 0.98s 就开始逐 token；用户体感是「很多模型首字很慢」。
- **根因**：`bridge.Forward` 调上游时写死 `stream: false`，收完整段 JSON 后才用
  `sseOf()` 合成一个 chat SSE chunk。上游完整生成的时间全被算进了首字。
- **解法**：`Options` 增加 `Stream` / `OnChunk`，`bridge.Forward` 在客户端要求
  流式时改调 `forwardStream`——上游按 `stream: true` 请求，边解析 SSE 边通过
  `OnChunk` 抛出 chat chunk。文本、`thinking`、`tool_use`（`input_json_delta`）、
  Responses 的 `function_call` 增量都要各自翻译。
- **代价与边界**：**只有链尾跳走流式**。前面某跳一旦写出半截 SSE 就收不回来、
  无法再回落；非尾跳仍整段缓冲。另外上游在写出任何 chunk 前报错时，必须把
  真实错误码经 JSON 回给客户端（`finishBridge` 用 `cw.written` 判断），否则
  客户端会挂在一个空流上。
- **上游自己不流式就没办法**：Qoder 渠道直连实测首字 32.6s（`stream: true` 也
  一样），这是上游整段缓冲，桥接器改不了——这类模型别放主力。
- **验证**：`go test ./internal/bridge/...`（含流式文本、流式工具调用、上游报错
  三条用例）；实测 `claude-haiku-5-5` / `gpt-6-luna` 工具调用流式返回
  `finish_reason: tool_calls` 且参数完整。

## 28. zgate 停掉后忘了拉起来 = 全站模型不可用；启动必须带 `serve` 【通用】

- **现象**：为了让新二进制生效 `taskkill` 掉 zgate，之后用
  `start "" zgate.exe` 启动，进程立刻消失，`/health` 不通，ZCode 里所有模型
  一起报错。直接前台跑，报 `panic: slice bounds out of range [2:1]`
  （`main.loadConfig` 里的 `os.Args[2:]`）。
- **根因**：zgate 没有默认子命令，`usage()` 要求显式 `serve`；`os.Args[2:]`
  在只有 1 个参数时越界。另外 `zgate.exe` 是 GUI 子系统，用 `start` 时的参数
  传递方式容易被 shell 吞掉。
- **解法**：停旧进程 → `python gateways/zgate/build.py` 重新构建（会校验 PE
  子系统是 WINDOWS_GUI）→ 用显式参数列表启动：

  ```powershell
  Start-Process -FilePath 'F:\Project\ZcodeAIModels\gateways\zgate\zgate.exe' `
    -ArgumentList 'serve' `
    -WorkingDirectory 'F:\Project\ZcodeAIModels\gateways\zgate' -WindowStyle Hidden
  ```

  起来后必须验证：`netstat -ano | grep 7871` 有 LISTENING，且
  `curl http://127.0.0.1:7871/health` 返回 `"ok":true`。
- **教训**：**这是单点故障**。重启网关属于「会切断用户所有模型」的操作，
  停机窗口要压到最短，重建失败就立刻回退旧二进制，不能停着慢慢查。

## 29. 渠道级「一律免费」定价会把将来的付费模型也记成 0 【通用】

- **现象**：`price_of()` 对 `QN`（七牛）渠道无条件返回 0（只判 `QN_FREE_UNTIL`
  日期），不校验模型 id 是不是 `-free`。当前只收了两个限免模型所以看不出问题，
  一旦将来播种任何七牛付费模型，它会以 0 价进免费组，扣费完全不可见。
- **根因**：把「这家渠道现在有免费活动」当成了「这家渠道的一切都免费」。
- **解法**：按 **模型 id** 判定优惠，不按渠道。`QN` 分支先检查
  `upstream.endswith("-free")`，不是就返回 `None`（缺价 → 剔除）。千问的
  预付额度仍是渠道级（整账号共用一份 ¥300），所以 `QW` 保持渠道级。
- **验证**：`tests/test_model_alias_price.py` 的价格派生用例；`--check` 零漂移。

## 30. 组内排序交给「厂商最低价」会把常用模型挤到列表末尾 【通用】

- **现象**：省钱组按 `vendor_min`（每个厂商的最低价）排序后，MiMo 这类价格
  不是最低但最常用的模型被排到列表最后，用户要在选择器里翻到底才能点到。
- **根因**：排序键选了「价格」这个与使用频率无关的量，还按厂商聚合，等于让
  便宜厂商永久霸占前排。`set` 本身更是无序的，两次运行顺序还可能不同。
- **解法**：**顺序权收归人工有序列表**。`MAIN_ORDER` / `LOW_ORDER` 是唯一权威，
  `MAIN_IDS` / `LOW_PICKS` 由它们派生（`set(...)`），组内按列表下标排，未命中
  名单的排最后。这样「常用的在最前」是写死的，不受价格波动影响。
- **配套规则**：省钱组只留**各厂 1–2 个代表作**（小米留 Flash + Pro），前旗舰 /
  上一代（MiMo-2.5、GLM-5.2、Qwen-3.7 等）不进组；不在名单里的模型直接不收录，
  而不是「收进来排在后面」。
- **验证**：`--check` 零漂移；`/v1/models` 里组内顺序与 `LOW_ORDER` 逐项一致。

## 31. 模型自述不可信；集合体/中转模型没有单一作者 【通用】

- **现象**：问七牛 `qiniu/conatus-free`「你是谁」，它答「我是 deepseek-v4.1-flash」；
  但七牛官方把它描述成**多种模型的集合体**。问 `iceman-contributor-free`，它答
  「微软 AI 开发的 MAI 大语言模型」；而 `GET /v1/models` 的 `owned_by` 只有
  `opencode`（转售方），没有作者字段。两处自述都拿不出可核对的依据。
- **根因**：①自述是模型的生成结果，不是元数据 —— 见过大量带自家名字语料的模型会
  复读训练语料里的身份；②中转/聚合类产品（集合体、路由池、contributor 免费池）
  **本来就没有单一作者**，后端可能按请求换供应商，问「你是谁」本身就没有稳定答案。
- **口径**：**以 `GET /models` 的 `id` / `owned_by` 与结算账目为事实，自述只当参考**。
  `owned_by` 是转售方时不要推断模型作者；集合体只记「它是聚合体」，不追作者。
- **实操建议**：判断「值不值得用」看 AA 榜单分数、单价、上下文、实测速度与稳定性，
  不要用「它说自己是谁」下结论；同一模型两次自述不一致是正常现象，不是接口坏了。
- **验证**：`curl -s https://opencode.ai/zen/go/v1/models -H "Authorization: Bearer $KEY"`
  看 `owned_by`；七牛同理看 `/v1/models` 元数据。

## 32. 上游「连上但不说话」要设空闲上限；429 要先退避再摘跳 【通用】

- **现象 1**：七牛 Conatus（聚合端点）会接受连接后**一个字节都不发**，唯一的兜底是
  桥接 `DefaultTimeout`(120s) —— 用户端表现为「2 分钟没响应」，重试有时又好。
- **现象 2**：主力 DeepSeek 的首跳 WorkBuddy 频繁 429，每个请求都要先撞它一次再回落
  OC，白付一次往返；当 OC 同时 429 时整条链失败，用户得手动重试。
- **根因**：①只有「总超时」没有「空闲超时」，静默等待和正常慢生成无法区分；
  ②429 被当成普通失败直接回落，既没退避也没在跳级别记住「它现在很挤」。
- **解法**：
  1. 桥接（流式与非流式都）加**空闲看门狗** `DefaultIdle = 30s`：连续 30 秒没有任何
     字节就断开连接并返回 `504 upstream_timeout`。首块 role 延迟到真有数据时才写，
     这样超时前没写过任何 SSE，路由还能正常报错/回落。
  2. 429 先**就地退避 700ms 重试同一跳一次**（限流窗口通常很短），仍 429 才把该跳
     **短冷却 45 秒**；桥接上游静默超时（504）冷却 **5 分钟**，死跳仍是 30 分钟。
- **为什么冷却时长要分级**：429 是瞬时拥挤，冷却太久会白白弃用一个能用的跳；
  静默超时说明上游真僵死，冷却短了就每个请求都要再等一次 30 秒。
- **验证**：`go test ./...`（`TestForwardStreamIdleTimeout` 断言静默上游 200ms 内
  返回 504 且零 chunk）；实测 Conatus 从 120s 干等变为 30s 内可判定错误。
