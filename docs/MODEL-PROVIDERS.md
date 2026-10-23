# Provider 与模型参数矩阵

> **一句话**：ZCode 里现在有哪几个 provider、每个 provider 走什么协议、每个模型属哪一档、
> 工具调用能不能用、思考参数怎么关 —— 这篇是正本，其它文档只引用不重述。
>
> **范围**：本篇列的是**本仓已配置的两组 provider** ——
> OpenCode-Go 七个（§2）与 WorkBuddy2API 四个（§4.2，分离模式）。Qoder 不是
> 独立 provider：模型加 `qoder:` 前缀后并入五个 chat 组（§4.9）。
> **接别的供应商**：方法见 §0；本篇的表是**快照**，不是通用规则。

数据快照：**2026-10-20**（§4 WorkBuddy 的倍率与分档于 **2026-10-22** 复核，倍率 / 分档无变化；
§4.9 Qoder 的模型与价格于 **2026-10-23** 实测）。

> **2026-10-23 起 provider 结构统一为四组**（主力 / 免费 / 低耗 / 高耗），模型 ID 改为
> `渠道/积分/型号`，跨协议由本地路由桥接。**当前分组与命名以
> [MODEL-ALIAS.md](MODEL-ALIAS.md) 为准**；本文 §2 / §4 的价格、协议与思考参数仍是
> 数据来源，旧的七组 provider 口径保留作历史。
价格 / 额度 / 倍率随服务商变动，改之前先看 [MAINTENANCE.md](MAINTENANCE.md) §1。

---

<a id="connect-new-provider"></a>

## 0. 接一个新的模型供应商（通用方法）

> **一句话**：本篇的 §2 / §4 是**数据**；这一节是**方法** —— 换供应商时照这里做。

四个步骤，与具体供应商无关。本仓的三个接入器（`opencode-go/`、`workbuddy/`、
`qoder/`）是参照实现。

### 0.1 四步

| 步 | 做什么 | 通用要点 | 本仓实例 |
|---|---|---|---|
| 1 | 摸清接口面 | 目录从哪个接口拿、每个模型走哪种协议、怎么计价 | §2.1 / §4.1 |
| 2 | 取目录与价格 → **归一化成一张表** | 归一化之后分档就是纯本地计算 | [MAINTENANCE.md](MAINTENANCE.md) §1.1、§1.3 的字段表 |
| 3 | 探测 | 必须用 **ZCode 真实请求体** + 限速 | [MAINTENANCE.md](MAINTENANCE.md) §2.2、§2.3；思考参数见 §5 |
| 4 | 分档并写配置 | 按成本档切、档内按单价升序；只写 ZCode 配置的三个落点 | §1、§4.2 |

### 0.2 通用概念 ↔ 本仓叫法

接新供应商时，下面这一列是**方法**，右边是本仓三个实例各自的叫法。

| 通用概念 | 本仓实例 A（OpenCode-Go） | 本仓实例 B（WorkBuddy2API） |
|---|---|---|
| 计价单位 | 美元 / M token（输入 / 输出单价） | 积分倍率（`credits` 牌价 / `promo_credits` 生效价） |
| 「这个模型多耐用」 | 额度可撑输出 = 月额度 ÷ 输出单价 | 倍率越小越便宜 |
| 分档口径 | 按额度可撑输出切七档（主力人工精选） | 按倍率切三档 + 备用价值档（免代 / 低代 / 高代 / 备用） |
| 协议种类 | chat / messages / responses 三种并存 | 全部 OpenAI 兼容（`openai-chat-completions`） |
| 目录接口 | `/zen/go/v1/models` + 文档页 + 全量目录页 + 本地配置（**四源并集**） | `/panel/api/models`（与 `/v1/models` 同源） |
| 账号池限制 | 套餐额度按模型分别计算 | 账号池有类型限制（`personal_free_user`，见 §4.7） |

第三个实例（Qoder）的计价单位是 `price_factor`（免费 = 0，越小越便宜），目录接口
是 `/v1/models`；它**并入** OpenCode 的五个 chat 组，模型 id 加 `qoder:` 前缀，
由 7871 路由剥前缀转发，见 §4.9。

### 0.3 不随供应商变的三件事

1. **ZCode 侧的落点** —— 只有 §1 那三处，换供应商不用改；
2. **思考参数覆盖机制** —— `optionSpecs.reasoningLevel.map`（§5），换供应商不用改；
3. **探测的两条铁律** —— 用 ZCode 真实 body、必须限速（限速的具体数值看对方账号池规模）。

---

## 1. ZCode 侧的关系：配置落点与写入行为

> **一句话**：脚本改 ZCode 的哪几处、三个同步脚本各自怎么写、写了怎么回退 —— 本节是这些口径的**正本**。

脚本只碰 `provider_config.json` 的三个位置（完整路径 `~/.zcode/v2/provider_config.json`）：

| JSON 路径 | 装什么 |
|---|---|
| `config.providerConfigRules.providerRules[]` | provider：`providerId` / `providerName` / `config.api.type` / `config.api.baseUrl` / `config.personalModelIds` / `config.modelOrder` |
| `config.modelConfigRules.providerModelRules[]` | 模型级规则：`modelId` / `providerId` / `config.enabled` / `config.properties`（`contextWindow` / `supportsToolCall` / `inputFormat.supportsImage`）/ `config.optionSpecs`（`reasoningLevel.map` / `maxOutputTokens.max`） |
| `config.providerOrder[]` | provider 在 ZCode 界面里的先后顺序 |

`providerId` 是**稳定标识**（旧会话可能引用它），`providerName` 只是显示名 ——
改显示名不影响引用，改 `providerId` 会让旧会话找不到模型。

**ZCode 约 1 秒轮询该配置**，写完一般不用重启客户端；但**不要在 ZCode 的 provider
设置界面里同时改** —— 界面保存时会整份写回，把脚本写的覆盖掉
（机制见 [PITFALLS.md](PITFALLS.md) §8，热重载的其余注意事项见 [MAINTENANCE.md](MAINTENANCE.md) §5）。

### 1.1 三个同步脚本的写入行为

| 脚本 | 默认行为 | 风险 |
|---|---|---|
| `opencode-go/ops/go_model_sync.py --apply` | 只**追加**模型 + 备用档重排（`BACKUP_MODEL_IDS`）+ 改一个 provider 显示名（"备用"→"响应"） | 低。已有模型的**组内顺序**可能被打乱（新模型追加到组尾） |
| `workbuddy/workbuddy_zcode_sync.py --apply` | 默认**合并** WorkBuddy 模型到五个 OpenCode chat 组（不改 OpenCode 模型与顺序）；`--separate` 才整条替换四个 `workbuddy-*` provider | 低（统一）/ 中（分离）。统一模式只动 WorkBuddy 模型与五个 chat 组的 `baseUrl`；分离模式会冲掉 `workbuddy-*` 上手工加的模型 |
| `qoder/qoder_zcode_sync.py --apply` | 默认**合并**：拉 `/v1/models`，按 `price_factor` 把 `qoder:` 前缀模型并入免费/低耗/高耗三个 chat 组；`--separate` 才写独立 `qoder` provider；默认 `--max-price 0.8`；`--probe-file` 只保留探测 `ok`（或曾 ok 的瞬时限流） | 低。只增删 `qoder:` 条目与（separate 模式的）`qoder` provider，不碰其它模型 |

**正确姿势**：先不带 `--apply` 跑一遍，看清它要写什么，再决定。

```bash
python opencode-go/ops/go_model_sync.py            # 只出报告
python workbuddy/workbuddy_zcode_sync.py           # 只打印计划
python qoder/qoder_zcode_sync.py                   # 只打印 Qoder 计划
```

三个脚本都**先备份再原子替换** `provider_config.json`（备份文件名与回退步骤见
[MAINTENANCE.md](MAINTENANCE.md) §4）。写配置期间**同一个时间只有一个写入者** ——
脚本与 ZCode 界面不能同时改。

---

## 2. OpenCode-Go 套餐（本次实例一）

入口：`https://opencode.ai/zen/go/v1`（Go 套餐，$10 与 $40 两档价格相同、额度不同）。
限额**按模型分别计算**：5 小时 = 月额度 20%、每周 50%、每月 100%。

### 2.1 七个 OpenCode-Go provider（另有 Qoder，见 §4.9）

| providerId | 显示名 | 协议 `api.type` | 模型数 | 收录口径 |
|---|---|---|---:|---|
| `opencode-go-chat` | 主力 | `openai-chat-completions` | 6 | **人工精选**，自动收录脚本不往这里放 |
| `opencode-go-chat-free` | 免费 | `openai-chat-completions` | 8 | 输出单价 = 0（含名字带 free 的） |
| `opencode-go-chat-fast` | 低耗 | `openai-chat-completions` | 10 | 「额度可撑输出」≥ 80M token |
| `opencode-go-chat-slow` | 高耗 | `openai-chat-completions` | 4 | 其余有价模型（输出单价 ≤ $1.60） |
| `opencode-go-chat-backup` | 备用 | `openai-chat-completions` | 3 | 以 DeepSeek 为基准性价比 < 1，人工指定 |
| `opencode-go-messages` | 对话 | `anthropic-messages` | 4 | 协议归属 = messages |
| `opencode-go-responses` | 响应 | `openai-responses` | 4 | 协议归属 = responses |

> **2026-10-21 起为统一模式**：五个 chat provider 的 `api.baseUrl` 指向
> `tools/unified-router.js`（`http://127.0.0.1:7871/v1`），模型列表同时包含
> OpenCode-Go 与 WorkBuddy；路由按 model 前缀分流。`对话` / `响应` 仍直连 OpenCode。
> 分离模式（`workbuddy_zcode_sync.py --separate`）见 §4.2。
>
> **ZCode 里仍然只有 7 个 provider**：Qoder 模型以 `qoder:` 前缀并入五个 chat 组（见 §4.9）。

> 「额度可撑输出」= **月额度 ÷ 输出单价**，是分档与排序的依据（每个模型额度独立，
> 换模型 = 换一份独立额度）。
> `opencode-go-responses` 的显示名原先叫「备用」，2026-10-20 改名「响应」——
> 现在装的是最耐用的模型，不再是备胎；**`providerId` 未变**。
> 2026-10-21 新增的「备用」是另一个 provider `opencode-go-chat-backup`，与这次改名无关。
> `opencode-go-chat-backup` 是 2026-10-21 新增的**价值档**：不按价格自动进，
> 只收 `BACKUP_MODEL_IDS`（当前 `minimax-m3`）；依据见 [BENCHMARKS.md](BENCHMARKS.md) §5.4。

### 2.2 主力 `opencode-go-chat`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| **deepseek-v4.1-flash** | chat + messages + responses（三协议全通） | ✅ 已实测 | `thinking:{type:"disabled"}` | 0.15–0.30 / 0.60–1.20 | **$80** | 133M（谷）/ 67M（峰） | 默认主力，额度全场最大 |
| deepseek-v4-flash-vision-exp | 多协议 | 待补 | 待补 | 文档未列 | 未列 | — | **不在 `/models` 清单里**，要图片输入时用 |
| mimo-v2.5-pro | 仅 chat | ✅ 已实测 | 待补 | 0.435 / 0.87 | $15 | 17M | 额度小，别当主力 |
| mimo-v2.6-pro | 仅 chat | ✅ 已实测 | 待补 | 0.435 / 0.87 | $15 | 17M | 输出速度波动大 |

> 统一模式下本组还包含 WorkBuddy 的 `cn:deepseek-v4.1-flash`、`global:deepseek-v4.1-flash-sg`。

### 2.3 免费 `opencode-go-chat-free`

| 模型 | 协议 | 工具调用 | 关思考 | 价格 | 实测首字 | 备注 |
|---|---|---|---|---|---|---|
| **beam-free** | 仅 chat | ✅ 已实测 | 天生关不掉（配了空 map 覆盖） | 0 / 0 | 1.0–1.5s | 免费无限，质量一般 |
| **minimax-m3.1-flash-free** | 仅 chat | 待补 | `enable_thinking:false`（配了空 map 覆盖） | 0 / 0 | ~1.1s | 免费里最快；参数最宽松 |
| longcat-2.5-preview-free | 仅 chat | ✅ 已实测 | `thinking:{type:"disabled"}` | 0 / 0 | 5.9–24s | 慢，只适合夜里批量 |

> 统一模式下本组还包含 WorkBuddy 的 `cn:hy3`、`cn:step-5-preview`、
> `global:deepseek-v4.1-flash`、`global:hy3`、`global:step-5-preview`。

### 2.4 低耗 `opencode-go-chat-fast`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| **glm-5.3-flash** | 仅 chat | ✅ 已实测 | **关不掉**（三种参数都 400） | 0.15 / 0.50 | $60 | 120M | 工具调用稳，日常主力替代 |
| **mimo-v2.6-flash** | 仅 chat | ✅ 已实测 | 待补 | 0.14 / 0.28 | $60 | **214M** | 每美元最耐用，慢 |
| mimo-v2.5 | 仅 chat | ✅ 已实测 | 待补 | 0.14 / 0.28 | $60 | **214M** | 同上，稍快 |
| hy3 | 仅 chat | ✅ 已实测 | 待补 | 0.14 / 0.58 | $60 | 103M | 慢，后台任务 |

> 统一模式下本组还包含 WorkBuddy 的 `cn:glm-5.3-flash`、`global:glm-5.3-flash`、
> `cn:hy3-x`、`cn:minimax-m3.1-flash`、`cn:space-bunny`、`global:minimax-m3.1-flash`。

### 2.5 高耗 `opencode-go-chat-slow`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| longcat-2.0 | 仅 chat | ✅ 已实测 | `thinking:{type:"disabled"}` | 0.30 / 1.20 | $60 | 50M | 慢且贵，只适合批处理 |

> 统一模式下本组还包含 WorkBuddy 的 `cn:hy4-preview`、`global:hy4-preview`、`cn:mimo-v2.6-pro`。

### 2.5.1 备用 `opencode-go-chat-backup`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| minimax-m3 | 仅 chat | ✅ 已实测 | `thinking:{type:"disabled"}`（配了空 map 覆盖） | 0.30 / 1.20 | $60 | 50M | 1M 上下文；性价比 0.82（DeepSeek 基准），只按需用 |

> 统一模式下本组还包含 WorkBuddy 的 `cn:deepseek-v4-flash`、`cn:minimax-m3`。

### 2.6 对话 `opencode-go-messages`（`anthropic-messages`）

| 模型 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|
| **claude-haiku-5-5** | ✅ 已实测 | 待补 | 0.10 / 0.50 | $15 | 30M | 子代理、小改动；>100K 上下文涨价 5 倍 |
| qwen3.8-flash | ✅ 已实测 | 待补 | 0.15 / 0.47 | $30 | 64M | 中文任务、翻译 |
| qwen3.7-plus | ✅ 已实测 | 待补 | 0.40 / 1.60 | $60 | 37.5M | 输出极长，一次性生成大段内容 |
| minimax-m2.7 | ✅ 已实测 | 待补 | 未列 | 未列 | — | 通用备选 |

### 2.7 响应 `opencode-go-responses`（`openai-responses`）

| 模型 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|
| **muse-spark-1.3-contributor** | 待补 | 不接受 `reasoning_effort`（配了空 map 覆盖） | 0.10 / 0.20 | $60 | **300M** | 全场最耐用；**Contributor 档：请求数据会被用来训练** |
| muse-spark-1.2-contributor | 待补 | 同上（配了空 map 覆盖） | 0.10 / 0.20 | $60 | **300M** | 旧版；同样会训练数据 |
| gpt-6-luna | ✅ 已实测 | 待补 | 0.10 / 0.50 | $15 | 30M | OpenAI 风格推理 |
| gpt-5.6-luna | ✅ 已实测 | 待补 | 0.20 / 1.20 | $15 | 12.5M | 额度最不经花 |

> **Contributor 档** = 用它的请求数据会拿去训练模型 —— 只放不敏感的活。
> 另外 `gemini-4-argon-contributor` 需要在 OpenCode Console 的 workspace Privacy 里
> 允许「付费且训练数据的端点」，否则 400，**本仓未收录**。

### 2.8 未收录但知道协议的模型（供扩容参考）

| 协议 | 模型 |
|---|---|
| 仅 chat | glm-5.1 / 5.2 / 5.3、hy4-preview、space-bunny、step-5-preview、omen-alpha、qwen3.6-plus、qwen3.7-max、kimi-k2.6、kimi-k2.7-code、minimax-m2.5 |
| 仅 messages | （除 qwen3.8-flash / qwen3.8-max 外） |
| 仅 responses | grok-4.6、grok-4.7 |
| 多协议 | kimi-k3、qwen3.8-max |

未收录的**原因**：官方已过弃用日（minimax-m2.5，2026-08-05）、输出单价超过门槛
（$1.60）、或价格表里查不到（只列候选不自动收录）。

### 2.9 自动收录的硬门槛

`go_model_sync.py` 的四道门槛，缺一不收：

1. 上游**未弃用**（410 `ModelDeprecated` 或官方弃用日期表已过）；
2. 三种协议里**至少一种能跑通**（200）；401 一律不收（凭据 / workspace 隐私问题，脚本解决不了）；
3. 输出单价 **≤ $1.60 / M token**（门槛取现有配置里最贵的 qwen3.7-plus）；
4. **价格未知**的模型只列候选，不自动收录。

价格 / 额度 / 协议提示来自**四源并集**（任一源都不完整）：
`/zen/go/v1/models` + Go 套餐文档页 + 全量目录页 + `provider_config.json` 里已配置的模型。

---

## 3. OpenCode-Go 的调用硬约束

| 约束 | 说明 |
|---|---|
| `x-opencode-session` | **必须带**。缺了报 `Request is missing x-opencode-session and cannot be routed efficiently`。`x-session-id` / `session_id` / `x-claude-code-session-id` 也能过；`x-stainless-session-id` 不行 |
| User-Agent | Cloudflare 会拦默认的 Python / SDK UA（403 error 1010），必须像正常客户端 |
| **鉴权头分协议** | `chat/completions` 与 `responses` 认 `Authorization: Bearer <apiKey>`；**`anthropic/messages` 只认 `x-api-key: <apiKey>`**（用 Bearer 会 401 `Go requires a credential`） |
| 协议唯一性 | 把模型塞进错误协议的 provider 直接 400 `ModelProtocolUnsupported` —— 这是本仓最大的一个坑，见 [PITFALLS.md](PITFALLS.md) §1 |
| 不支持自定义头的客户端 | 用 `opencode-go/ops/opencode-header-proxy.js`（默认 `127.0.0.1:8787`）补头 |

---

## 4. WorkBuddy2API 网关（本次实例二）

网关：`wb2api` 面板版（MIT），默认 `http://127.0.0.1:7863`，OpenAI 兼容。
把腾讯 CodeBuddy 账号池变成 OpenAI 兼容 API。模型 id 形如 `cn:xxx` / `global:xxx`。

网关生命周期默认由 `workbuddy/zcode_gateway_watch.ps1` 跟随 ZCode（ZCode 起 → 网关起，
全部退出 → 停），安装与副作用见 [MAINTENANCE.md](MAINTENANCE.md) §8。

### 4.0 统一模式（默认，2026-10-21 起）

默认**不再创建** `workbuddy-*` 四个 provider。18 个 WorkBuddy 模型并入 §2 的五个
chat 组，五个 chat 组的 `api.baseUrl` 指向本地路由 `tools/unified-router.js`
（`http://127.0.0.1:7871/v1`）。路由按 model 分流：

- `cn:` / `global:` → 网关 `http://127.0.0.1:7863/v1`
- 其余 → OpenCode-Go `https://opencode.ai/zen/go/v1`

| WorkBuddy 档 | 并入的 provider | 模型 |
|---|---|---|
| 主力 | `opencode-go-chat` | `cn:deepseek-v4.1-flash`、`global:deepseek-v4.1-flash-sg` |
| 低耗 | `opencode-go-chat-fast` | `cn:glm-5.3-flash`、`global:glm-5.3-flash`、`cn:hy3-x`、`cn:minimax-m3.1-flash`、`cn:space-bunny`、`global:minimax-m3.1-flash` |
| 免费 | `opencode-go-chat-free` | `cn:hy3`、`cn:step-5-preview`、`global:deepseek-v4.1-flash`、`global:hy3`、`global:step-5-preview` |
| 高耗 | `opencode-go-chat-slow` | `cn:hy4-preview`、`global:hy4-preview`、`cn:mimo-v2.6-pro` |
| 备用 | `opencode-go-chat-backup` | `cn:deepseek-v4-flash`、`cn:minimax-m3` |

- `对话` / `响应` 仍直连 OpenCode-Go，不经过路由。
- 路由随 ZCode 起停（`zcode_gateway_watch.ps1`）；手动启动
  `node tools/unified-router.js`，健康检查 `GET http://127.0.0.1:7871/health`。
- **分离模式**：`workbuddy_zcode_sync.py --separate --apply` 会重建 §4.2 的四个
  `workbuddy-*` provider；默认（不带 `--separate`）是统一模式。

### 4.1 目录与别名

- `/panel/api/models` 与 `/v1/models` 同源。**注意**：网关未重启时 `/panel/api/models`
  只返回 34 个 global 模型，重启后返回全部 56 个（cn 22 + global 34）。
- **路由别名**（无自身价格，只是路由到别的模型）—— 一律排除：
  `cn:auto`、`global:auto-chat`、`global:default-model`、`global:primary-model`、
  `global:deep-model`、`global:fast-model`、`global:balanced-model`、`global:enhance-1.0`。

### 4.2 分离模式：倍率与四档（`--separate`）

> 以下四档只在 `workbuddy_zcode_sync.py --separate --apply` 时出现；默认统一模式
> 不创建 `workbuddy-*`，WorkBuddy 模型并入 §4.0 的五个 chat 组。

`credits` = 牌价，`promo_credits` = 生效价（取 `promo_credits` 优先）。
**倍率越小越便宜**。

| providerId | 显示名 | 分档口径 | 模型数 |
|---|---|---|---:|
| `workbuddy-low` | 低代 | 0 < 倍率 ≤ 0.16（主力价位） | 8 |
| `workbuddy-free` | 免代 | 生效价 = 0.00 | 5 |
| `workbuddy-high` | 高代 | 0.16 < 倍率 ≤ 0.30 | 3 |
| `workbuddy-backup` | 备用 | 以 DeepSeek 为基准性价比 < 1（不是倍率区间） | 2 |

**分离模式的界面顺序是 低代 → 免代 → 高代 → 备用**（`providerOrder`）。低代排第一，是因为
日常主力 `cn:deepseek-v4.1-flash` 在这一档；免代虽然免费，但模型不是主力；
备用是价值档，排最后。统一模式下这四个 provider 不出现，顺序见 §4.0。

**分价口径（2026-10-21 起）：只接受主力价位的模型。** 锚点是主力的
`cn:deepseek-v4.1-flash` = **x0.11**——

- ≤ x0.16（主力及更便宜的）→ 低代；
- x0.17 – x0.30（约 1.5–2.7 倍）→ 高代；
- **x0.30 以上"贵不加"**：同步脚本一律排除，自动收录也不会再引进
  （原高代 x0.50–0.79 = 主力的 **4.5–7.2 倍**，整组移出）。

`workbuddy-backup` **不按倍率区间分**：命中 `BACKUP_MODEL_IDS` 的模型优先于倍率分档，
用来收「价格仍在 x0.30 以内、但按 DeepSeek 基准性价比 < 1」的模型；
依据见 [BENCHMARKS.md](BENCHMARKS.md) §5.4。

**组内顺序**（`personalModelIds` 与 `modelOrder` 写同一份列表）：

1. `cn:deepseek-v4.1-flash` 钉在最前；
2. 其余 **CN 在前、全球在后**；
3. 每个区域内部**按模型公司分组**：深度求索 → 智谱 → MiniMax → 月之暗面 →
   小米 MiMo → 腾讯混元 → 阶跃星辰 → 匿名/其他；
4. 同公司内按倍率升序，同倍率按 id 字典序。

排序与分价规则的正本是 `workbuddy/workbuddy_zcode_sync.py` 的 `PINNED_MODEL_IDS`
/ `VENDOR_ORDER` / `LOW_MAX` / `DEFAULT_MAX_RATE` / `BACKUP_MODEL_IDS`；改完用
`--reorder-only --apply` 只重排、不动成员与档位，改分价阈值则重新 `--apply`；
只搬备用档用 `--reclassify-only --apply`。

> **2026-10-21 促销漂移已并入分档**：`cn:hy4-preview` 生效价回到 `x0.29` →
> 从免代移到高代（统一模式下它在 `opencode-go-chat-slow`）；
> `cn:glm-5.2` 促销 x0.50 在新上限之外 → 随原高代一起移出。

### 4.3 免代 `workbuddy-free`（分离模式，生效倍率 0.00）

| 模型 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---|---:|---|---|---|
| cn:hy3 | 192K | 64K | ❌ | low / high | 200 |
| cn:step-5-preview | 1M | 64K | ❌ | low / medium / high | 200 |
| global:deepseek-v4.1-flash | 1M | 128K | ❌ | low / high / max | 200 |
| global:hy3 | 192K | 64K | ❌ | low / high | 200 |
| global:step-5-preview | 1M | 64K | ❌ | low / medium / high | 200 |

### 4.4 低代 `workbuddy-low`（分离模式，0 < 倍率 ≤ 0.16，主力价位）

| 模型 | 倍率 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---:|---:|---:|---|---|---|
| **cn:deepseek-v4.1-flash** | 0.11 | 1M | 393K | ✅ | low / high / max | 200 |
| cn:glm-5.3-flash | 0.08 | 1M | 131K | ✅ | low / high / max | 200 |
| cn:minimax-m3.1-flash | 0.08 | 1M | 128K | ❌ | low / medium / high / xhigh / max | 200 |
| cn:hy3-x | 0.05 | 192K | 64K | ❌ | low / high | 200 |
| cn:space-bunny | 0.08 | 1M | 128K | ❌ | low / medium / high / xhigh / max | 200 |
| global:deepseek-v4.1-flash-sg | 0.03 | 1M | 128K | ❌ | low / high / max | 200 |
| global:glm-5.3-flash | 0.08 | 1M | 32K | ✅ | low / high / max | 200 |
| global:minimax-m3.1-flash | 0.08 | 1M | 128K | ❌ | low / medium / high / xhigh / max | 200 |

### 4.5 高代 `workbuddy-high`（分离模式，0.16 < 倍率 ≤ 0.30，略高于主力）

| 模型 | 倍率 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---:|---:|---:|---|---|---|
| cn:hy4-preview | 0.29 | 1M | 64K | ❌ | high | 200 |
| cn:mimo-v2.6-pro | 0.18 | 1M | 128K | ❌ | 未标 | 200 |
| global:hy4-preview | 0.29 | 1M | 64K | ❌ | high | 200 |

### 4.5.1 备用 `workbuddy-backup`（分离模式，性价比 < 1，不受倍率区间约束）

| 模型 | 倍率 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---:|---:|---:|---|---|---|
| cn:deepseek-v4-flash | 0.17 | 1M | 50K | ✅ | low / high / xhigh | 200 |
| cn:minimax-m3 | 0.25 | 512K | 512K | ❌ | medium | 200 |

**全部 18 个模型都支持工具调用**（网关 `supports_tool_call` 全为真）。

### 4.6 被排除的 38 个

| 类别 | 数量 | 例子 |
|---|---:|---|
| 倍率 > 0.30（贵不加） | 25 | 原高代 12 个（cn:glm-5.1/5.2/5.3/5v-turbo、cn:kimi-k2.6/2.7/2.8-preview、cn:deepseek-v4-pro、global 同款）+ gpt / gemini / grok / kimi-k3 系列 13 个 |
| 无挂牌价 | 3 | `cn:hy4-preview-f`、`global:hy4-preview-f`、`global:o4-mini` |
| 路由别名 | 8 | 见 §4.1（`global:enhance-1.0` 兼限流） |
| 账号类型不允许（blocked） | 2 | `global:gpt-6-luna`、`global:gpt-5.6-luna` |

### 4.7 账号池限制：`personal_free_user` 导致 global 高端模型 503

账号池 4 个号 = **3 个 global**（`www.workbuddy.ai`）+ **1 个 cn**（`www.codebuddy.cn`）。

**3 个 global 号是 `personal_free_user` 类型 → 多数 global 高端模型上游直接
`503 not allowed for user type`，无论倍率多低都调不通。**
实测 `global:gpt-6-luna`（x0.07）、`global:gpt-5.6-luna`（x0.14）都被拒。
cn 账号是普通账号，cn 系模型基本全通。

推论：

- **global 域的模型清单看起来很大，实际可用的很少** —— 便宜不等于能调通；
- 想要 global 的高端模型，唯一路径是**换非 `personal_free_user` 类型的账号**，
  不是改配置；
- 网关日志里的 `pool.credit_floor=100` 表示余额低于 100 的号不参与收费模型选号
  （实测有号 credits=59 被 hold out）→ global 域付费模型实际只剩 2 个号可用。

### 4.8 探测量化参考

网关 `/status` 的 `accounts[].model_costs`（credits / 1k token）：
多数 cn 模型实测 **0**（免费额度覆盖）；hy4-preview 0.1087、kimi-k2.8-preview 0.156、
deepseek-v4-flash 0.182、kimi-k2.7 0.313、deepseek-v4-pro 0.361、kimi-k3 0.394、
glm-5v-turbo 0.454、kimi-k3-1 0.901、gpt-5.3-codex 0.976。

网关日志还显示 global 域存在「free tier ended, now 0.227 credits/1k」→
**限时免费会到期**，届时 global 模型的实际积分消耗会上升，`wb_pricing.json` 需定期刷新。

---

### 4.9 Qoder（qoder2api-hub，本次实例三）

网关：qoder2api-hub（MIT），`http://127.0.0.1:8790/v1`，OpenAI Chat Completions。
它**并入** §2 的五个 chat 组：模型 id 加 `qoder:` 前缀，由 7871 路由剥前缀后转给
8790；WorkBuddy2API 与 OpenCode-Go 不受影响。完整操作见 [QODER.md](QODER.md)。

**目录与计价**：`GET /v1/models` 直接给 `price_factor`、峰谷价、`reasoning_efforts`、
`context_windows`、`disabled_reason`、`realm`。**price_factor 越小越便宜，0 = 免费**。
目录是动态的，还会出现 `Auto` / `Fast` 这类路由别名（`upstream_key` 同名）—— 一律排除。

| 模型 | price_factor | 落到 | 上下文 | 思考档位 | 2026-10-23 探测 |
|---|---:|---|---:|---|---|
| `DeepSeek-Flash` | 0.0 | 免费 | 200K（可选 1M） | low/high/max | 200，平时 1.1s；排队时 64s+ 或 502 |
| `GLM-5.3-Flash` | 0.1 | 低耗 | 200K（可选 1M） | high/max | 200 |
| `MiniMax-M3.1-Flash` | 0.1 | 低耗 | 200K | — | 200 |
| `DeepSeek-V4-Pro` | 0.5 | 高耗 | 200K（可选 1M） | high/max | 200 |
| `Qwen3.8-Max` | 0.5 | 高耗 | 200K（可选 1M） | low/medium/xhigh | 200；错峰 4 折 |
| `GLM-5.3` | 0.8 | 高耗 | 200K（可选 1M） | low/high/max | 200 |
| `Kimi-K2.8-Preview` | 0.8 | 高耗 | 200K（可选 1M） | low/high/max | 200 |

排除项（2026-10-23）：

- `Auto` / `Fast`：路由别名，无自身价格（同 §4.1 的 WorkBuddy 规则）；
- `Kimi-K3`：price_factor 1.4，超过同步脚本默认上限 0.8；
- `Qwen3.8-Flash`：免费，但上游 **10605 排队**（queueCount ≈ 19k，p3），75s 超时，
  按「跑不通即清」暂时移出；复通后重新探测 + 同步会自动加回。

`--probe-file` 的判定带 `ever_ok`：曾经 200 的模型遇到 `queued` / `timeout` /
`rate_limited` 仍保留；只有从未成功过的模型才会因排队被排除。

**落组规则**：`price_factor=0` → `opencode-go-chat-free`（免费）；
`0 < x ≤ 0.2` → `opencode-go-chat-fast`（低耗）；`> 0.2` → `opencode-go-chat-slow`
（高耗）。模型 id 带 `qoder:` 前缀，路由器剥掉后再发给 8790；`--separate` 才写
独立 `qoder` provider。

**思考参数**：7 个模型用 ZCode 原生四件套（`thinking` + `enable_thinking` +
`reasoning_effort` + `reasoning`）探测全部 200，**没有配任何
`optionSpecs.reasoningLevel.map` 覆写**。

**脚本**：

```bash
python qoder/qoder_zcode_sync.py                                  # dry run
python qoder/qoder_probe_zcode.py                                 # 真实 body 探测
python qoder/qoder_zcode_sync.py --probe-file qoder/qoder_probe.json --apply
```

---

## 5. 关思考参数矩阵

> §5.1 是**上游实测数据**（哪个模型认哪种写法，随模型变）；
> §5.2 / §5.3 是**ZCode 侧的通用机制**（换供应商照样成立）。

### 5.1 上游接受哪种写法（直连实测 2026-10-19）

| 模型 | 有效写法 | 效果 |
|---|---|---|
| longcat-2.0、longcat-2.5-preview-free、minimax-m3、deepseek-v4.1-flash | `{"thinking":{"type":"disabled"}}` | 不再输出 reasoning（longcat-2.0 3.6s→1.7s，deepseek 2.5s→1.4s） |
| minimax-m3.1-flash-free | `{"enable_thinking":false}` | 1.2s 出正文；`thinking:disabled` 和 `reasoning_effort:none` 都会 400 |
| glm-5.3-flash | **无** | `thinking:disabled` 400、`reasoning_effort:none` 400、`enable_thinking:false` 仍思考；给足 max_tokens 即可 |
| beam-free | 不需要 | 天生带思考关不掉，但本身就是 1 秒级 |
| muse-spark-1.2 / 1.3-contributor | **无** | 带 `reasoning_effort` 报错 |

### 5.2 ZCode 侧怎么配

ZCode 会在请求里注入思考字段，**「关掉」是靠 `optionSpecs.reasoningLevel.map` 覆盖实现的**。
map 是**一段 JS 表达式**，引擎求值成 JSON 对象后再发出去。

| 写法 | 什么时候用 |
|---|---|
| `map = "{}"` | **不发送任何思考参数**。给「上游只认裸 body」的模型用：beam-free、minimax-m3.1-flash-free、minimax-m3、muse-spark-1.2 / 1.3-contributor |
| `map = '{"thinking":{"type":"disabled"}}'` | 需要显式告诉上游「关掉思考」，且上游认这个字段 |
| `map = '{"thinking":{"type":"enabled"},"reasoning_effort":reasoningLevel}'` | 上游只认 deepseek 系那套（thinking + reasoning_effort），不认 `enable_thinking` / `reasoning` |
| `map = '{"thinking":{"type":"enabled"}}'` | 上游只认 thinking 一个字段 |
| 不配 | 模型正常认 ZCode 默认注入的字段（`thinking` + `enable_thinking` + `reasoning_effort` + `reasoning`） |

**当前 ZCode 里配了空 map 的模型**（5 个）：
`beam-free`、`minimax-m3.1-flash-free`、`minimax-m3`、
`muse-spark-1.3-contributor`、`muse-spark-1.2-contributor`。

**WorkBuddy 侧 18 个模型一个都没配覆盖** —— 探测确认它们**全部接受 ZCode 原生 body**。
（与 OpenCode-Go 侧不同：那边 minimax-m3 会拒 `thinking:{type:"enabled"}`，这边 CodeBuddy 上游接受。）

**Qoder 侧 7 个模型（带 `qoder:` 前缀，经 7871）也没有配覆盖** —— 2026-10-23 用
`zcode_effective_body.js` 复算后探测，原生四件套全部 HTTP 200；`Qwen3.8-Max` 的合法档位是 low/medium/xhigh，
`DeepSeek-V4-Pro` / `GLM-5.3` / `Kimi-K2.8-Preview` 是 low/high/max。

### 5.3 ZCode 内置规则的形状（为什么要复刻）

ZCode 的内置规则 `resources/config/provider/zcode-builtin.json` 里：

- `modelApiRules` 有 **73 条**，**按文件顺序叠加，后面的规则覆盖前面的**；
- `modelMatch` 是**全匹配正则** `^(?:pattern)$`（大小写不敏感），不是子串匹配；
- `apiTypeMatch` 相同的规则才会互相覆盖；
- 通用规则在**前面**（`openai-chat-completions` 的 `.*` 在第 3 条），
  各模型专属规则在**后面**（如 `.*deepseek-v4[.-]1-flash.*` 在第 68 条）——
  专属规则因此盖得住通用规则；
- 通用规则在 `openai-chat-completions` 下会注入
  `thinking` + `enable_thinking` + `reasoning_effort` + `reasoning` **四个字段**，
  且**不看模型是否支持**。

`workbuddy/zcode_effective_body.js` 就是复刻这套语义，用来算「ZCode 真实会发什么」。
**任何时候改了规则或换了模型 id，都要用它重算，不要手写规则表。**

---

## 6. 一句话选择

| 场景 | 选谁 |
|---|---|
| 日常写代码 | 主力 `deepseek-v4.1-flash`；想省额度 → 低耗 `glm-5.3-flash` |
| 零成本 | 免费 `beam-free`（快）或 `minimax-m3.1-flash-free`；网关侧 `workbuddy-free` |
| 长上下文 | 高耗 `minimax-m3`（1M）；网关侧 `cn:deepseek-v4.1-flash`（1M） |
| 子代理 / 小改动 | `claude-haiku-5-5`（主力）、`space-bunny`；更省 → 低耗 `mimo-v2.5` |
| 中文任务 | `qwen3.8-flash` |
| 后台批量 | `hy3`、`longcat-2.0`，夜里用 `longcat-2.5-preview-free` |
| 别用于交互 | `longcat-2.0`、`longcat-2.5-preview-free`、`qwen3.7-plus` |

> 本表只按**成本 / 额度 / 延迟**取舍，不按跑分排序。主力里的榜单扩充成员
> （`mimo-v2.6-flash`、`space-bunny`、`claude-haiku-5-5`）见
> [BENCHMARKS.md](BENCHMARKS.md) §8。

### 6.1 按能力方向选（外部榜交叉，2026-09-11）

| 方向 | 首选 | 备选 | 约束 |
|---|---|---|---|
| 文字（写作 / 翻译 / 总结） | `qwen3.8-flash`（messages） | `deepseek-v4.1-flash` | qwen 不是主力 chat |
| 前端（页面 / 3D） | `hy4-preview`（WorkBuddy） | `qwen3.8-flash` | hy4 受账号池 / 倍率影响 |
| 后端（修复 / 长任务） | `qwen3.8-flash`（messages） | `glm-5.3-flash` | 扩 `glm-5.3` 可到榜上后端最高 |
| 知识（论文 / 问答） | `hy4-preview`（WorkBuddy） | `qwen3.8-flash` | 同上 |
| 综合 / 日常写代码 | `deepseek-v4.1-flash` | `qwen3.8-flash` | 四项均前三，额度最大 |

> 方向首选只回答「这个用途先试谁」，**不改 provider 分档**；
> 分数、口径与平台差异见 [BENCHMARKS.md](BENCHMARKS.md) §5.1–§5.3。

### 6.2 按 DeepSeek 基准的性价比分档（外部榜交叉，2026-09-11）

以 `deepseek-v4.1-flash` = 智力 100 / 价格 100；规则与逐项指数见
[BENCHMARKS.md](BENCHMARKS.md) §5.4。

| 档位 | 模型（统一模式下的实际归属） |
|---|---|
| 主力 | `deepseek-v4.1-flash`、`qwen3.8-flash`（messages，优先用）、`cn:deepseek-v4.1-flash`、`global:deepseek-v4.1-flash-sg`（global 受限）；2026-10-23 榜单扩充：`mimo-v2.6-flash`、`space-bunny`、`claude-haiku-5-5` |
| 低耗 | `glm-5.3-flash`、`muse-spark-1.3/1.2`（responses）、`hy3`、`cn:glm-5.3-flash`、`global:glm-5.3-flash`、`cn:hy3-x` |
| 高耗 | `longcat-2.0`、`cn:hy4-preview`、`global:hy4-preview`、`cn:mimo-v2.6-pro` |
| 免费 | `beam-free` 等（未上榜，按原组）、`global:deepseek-v4.1-flash`、`cn/global:hy3`、`cn/global:step-5-preview` |
| 备用 | `minimax-m3`、`cn:deepseek-v4-flash`、`cn:minimax-m3`（`opencode-go-chat-backup`） |

> 统一模式下 WorkBuddy 模型已在同一 provider 内，不再是独立组；providerId 仍是
> 五个 chat 组（见 §4.0）。`cn:hy4-preview` 的实时价已回到 x0.29，2026-10-21
> 全量同步把它从免代移到高耗。价格与分数的口径见 BENCHMARKS §5.4。
>
> **2026-10-23 起以 [MODEL-ALIAS.md](MODEL-ALIAS.md) 的四组为准**：`备用` 已解散，
> 分组按积分实时计算；上表是旧榜质量快照，只用来判断「同一档里优先试谁」。

---

## 7. 维护本文档的规则

- **分组 / 协议 / 参数矩阵**变了 → 同步本篇 + [PITFALLS.md](PITFALLS.md)。
- **数值要带时点**。价格、额度、倍率、实测首字都是某一时刻的快照，
  换新快照时把日期一起改掉。
- **区分通用与实例**。§0 是方法（跨供应商成立），§2 / §4 是本仓两组 provider 的数据快照。
  新增供应商时**加一节数据 + 在 §0 的表里补一行**，不要把实例数据混进 §0。
- **不要在本篇写排查步骤** —— 那是 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 的事；
  **也不要写「为什么会这样」** —— 那是 [PITFALLS.md](PITFALLS.md) 的事。
