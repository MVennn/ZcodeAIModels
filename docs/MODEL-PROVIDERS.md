# Provider 与模型参数矩阵

> **一句话**：ZCode 里现在有哪几个 provider、每个 provider 走什么协议、每个模型属哪一档、
> 工具调用能不能用、思考参数怎么关 —— 这篇是正本，其它文档只引用不重述。

数据快照：**2026-10-20**。价格 / 额度 / 倍率随服务商变动，改之前先看
[MAINTENANCE.md](MAINTENANCE.md) §1。

---

## 1. ZCode 侧的配置落点

脚本只碰 `provider_config.json` 的三个位置（完整路径 `~/.zcode/v2/provider_config.json`）：

| JSON 路径 | 装什么 |
|---|---|
| `config.providerConfigRules.providerRules[]` | provider：`providerId` / `providerName` / `config.api.type` / `config.api.baseUrl` / `config.personalModelIds` / `config.modelOrder` |
| `config.modelConfigRules.providerModelRules[]` | 模型级规则：`modelId` / `providerId` / `config.enabled` / `config.properties`（`contextWindow` / `supportsToolCall` / `inputFormat.supportsImage`）/ `config.optionSpecs`（`reasoningLevel.map` / `maxOutputTokens.max`） |
| `config.providerOrder[]` | provider 在 ZCode 界面里的先后顺序 |

`providerId` 是**稳定标识**（旧会话可能引用它），`providerName` 只是显示名 ——
改显示名不影响引用，改 `providerId` 会让旧会话找不到模型。

**ZCode 约 1 秒轮询该配置**，写完一般不用重启客户端；但**不要在 ZCode 的 provider
设置界面里同时改** —— 界面保存时会整份写回，把脚本写的覆盖掉。

---

## 2. OpenCode-Go 套餐

入口：`https://opencode.ai/zen/go/v1`（Go 套餐，$10 与 $40 两档价格相同、额度不同）。
限额**按模型分别计算**：5 小时 = 月额度 20%、每周 50%、每月 100%。

### 2.1 六个 provider

| providerId | 显示名 | 协议 `api.type` | 模型数 | 收录口径 |
|---|---|---|---:|---|
| `opencode-go-chat` | 主力 | `openai-chat-completions` | 4 | **人工精选**，自动收录脚本不往这里放 |
| `opencode-go-chat-free` | 免费 | `openai-chat-completions` | 3 | 输出单价 = 0（含名字带 free 的） |
| `opencode-go-chat-fast` | 低耗 | `openai-chat-completions` | 4 | 「额度可撑输出」≥ 80M token |
| `opencode-go-chat-slow` | 高耗 | `openai-chat-completions` | 2 | 其余有价模型（输出单价 ≤ $1.60） |
| `opencode-go-messages` | 对话 | `anthropic-messages` | 4 | 协议归属 = messages |
| `opencode-go-responses` | 响应 | `openai-responses` | 4 | 协议归属 = responses |

> 「额度可撑输出」= **月额度 ÷ 输出单价**，是分档与排序的依据（每个模型额度独立，
> 换模型 = 换一份独立额度）。
> `opencode-go-responses` 的显示名原先叫「备用」，2026-10-20 改名「响应」——
> 现在装的是最耐用的模型，不再是备胎；**`providerId` 未变**。

### 2.2 主力 `opencode-go-chat`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| **deepseek-v4.1-flash** | chat + messages + responses（三协议全通） | ✅ 已实测 | `thinking:{type:"disabled"}` | 0.15–0.30 / 0.60–1.20 | **$80** | 133M（谷）/ 67M（峰） | 默认主力，额度全场最大 |
| deepseek-v4-flash-vision-exp | 多协议 | 待补 | 待补 | 文档未列 | 未列 | — | **不在 `/models` 清单里**，要图片输入时用 |
| mimo-v2.5-pro | 仅 chat | ✅ 已实测 | 待补 | 0.435 / 0.87 | $15 | 17M | 额度小，别当主力 |
| mimo-v2.6-pro | 仅 chat | ✅ 已实测 | 待补 | 0.435 / 0.87 | $15 | 17M | 输出速度波动大 |

### 2.3 免费 `opencode-go-chat-free`

| 模型 | 协议 | 工具调用 | 关思考 | 价格 | 实测首字 | 备注 |
|---|---|---|---|---|---|---|
| **beam-free** | 仅 chat | ✅ 已实测 | 天生关不掉（配了空 map 覆盖） | 0 / 0 | 1.0–1.5s | 免费无限，质量一般 |
| **minimax-m3.1-flash-free** | 仅 chat | 待补 | `enable_thinking:false`（配了空 map 覆盖） | 0 / 0 | ~1.1s | 免费里最快；参数最宽松 |
| longcat-2.5-preview-free | 仅 chat | ✅ 已实测 | `thinking:{type:"disabled"}` | 0 / 0 | 5.9–24s | 慢，只适合夜里批量 |

### 2.4 低耗 `opencode-go-chat-fast`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| **glm-5.3-flash** | 仅 chat | ✅ 已实测 | **关不掉**（三种参数都 400） | 0.15 / 0.50 | $60 | 120M | 工具调用稳，日常主力替代 |
| **mimo-v2.6-flash** | 仅 chat | ✅ 已实测 | 待补 | 0.14 / 0.28 | $60 | **214M** | 每美元最耐用，慢 |
| mimo-v2.5 | 仅 chat | ✅ 已实测 | 待补 | 0.14 / 0.28 | $60 | **214M** | 同上，稍快 |
| hy3 | 仅 chat | ✅ 已实测 | 待补 | 0.14 / 0.58 | $60 | 103M | 慢，后台任务 |

### 2.5 高耗 `opencode-go-chat-slow`

| 模型 | 协议 | 工具调用 | 关思考 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 备注 |
|---|---|---|---|---|---|---|---|
| minimax-m3 | 仅 chat | ✅ 已实测 | `thinking:{type:"disabled"}`（配了空 map 覆盖） | 0.30 / 1.20 | $60 | 50M | 1M 上下文，单价高，按需用 |
| longcat-2.0 | 仅 chat | ✅ 已实测 | `thinking:{type:"disabled"}` | 0.30 / 1.20 | $60 | 50M | 慢且贵，只适合批处理 |

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

## 4. WorkBuddy2API 网关

网关：`wb2api` 面板版（MIT），默认 `http://127.0.0.1:7863`，OpenAI 兼容。
把腾讯 CodeBuddy 账号池变成 OpenAI 兼容 API。模型 id 形如 `cn:xxx` / `global:xxx`。

### 4.1 目录与别名

- `/panel/api/models` 与 `/v1/models` 同源。**注意**：网关未重启时 `/panel/api/models`
  只返回 34 个 global 模型，重启后返回全部 56 个（cn 22 + global 34）。
- **路由别名**（无自身价格，只是路由到别的模型）—— 一律排除：
  `cn:auto`、`global:auto-chat`、`global:default-model`、`global:primary-model`、
  `global:deep-model`、`global:fast-model`、`global:balanced-model`、`global:enhance-1.0`。

### 4.2 倍率与三档

`credits` = 牌价，`promo_credits` = 生效价（取 `promo_credits` 优先）。
**倍率越小越便宜**。

| providerId | 显示名 | 倍率区间 | 模型数 |
|---|---|---|---:|
| `workbuddy-free` | 免代 | = 0.00 | 5 |
| `workbuddy-low` | 低代 | 0 < 倍率 ≤ 0.30 | 13 |
| `workbuddy-high` | 高代 | 0.30 < 倍率 ≤ 0.80 | 12 |

上限 0.80 是为了**让清单里的模型都和 `deepseek-v4.1-flash`（牌价 x0.11 /
global 促销 x0.00）一个量级**，不引入 x1.3–x6.7 的高端档。

组内按倍率升序（同倍率按 id 字典序）。

### 4.3 免代 `workbuddy-free`（倍率 0.00）

| 模型 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---|---:|---|---|---|
| cn:hy3 | 192K | 64K | ❌ | low / high | 200 |
| cn:step-5-preview | 1M | 64K | ❌ | low / medium / high | 200 |
| global:deepseek-v4.1-flash | 1M | 128K | ❌ | high | 200 |
| global:hy3 | 192K | 64K | ❌ | low / high | 200 |
| global:step-5-preview | 1M | 64K | ❌ | low / medium / high | 200 |

### 4.4 低代 `workbuddy-low`（0.03 – 0.29）

| 模型 | 倍率 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---:|---:|---:|---|---|---|
| global:deepseek-v4.1-flash-sg | 0.03 | 1M | 128K | ❌ | 未标 | 200 |
| cn:hy3-x | 0.05 | 192K | 64K | ❌ | low / high | 200 |
| cn:glm-5.3-flash | 0.08 | 1M | 131K | ✅ | low / high / max | 200 |
| cn:minimax-m3.1-flash | 0.08 | 1M | 128K | ❌ | low / medium / high / xhigh / max | 200 |
| cn:space-bunny | 0.08 | 1M | 128K | ❌ | low / medium / high / xhigh / max | 200 |
| global:glm-5.3-flash | 0.08 | 1M | 32K | ✅ | low / high / max | 200 |
| global:minimax-m3.1-flash | 0.08 | 1M | 128K | ❌ | low / medium / high / xhigh / max | 200 |
| cn:deepseek-v4.1-flash | 0.11 | 1M | 393K | ✅ | low / high / max | 200 |
| cn:deepseek-v4-flash | 0.17 | 1M | 50K | ✅ | low / high / xhigh | 200 |
| cn:mimo-v2.6-pro | 0.18 | 1M | 128K | ❌ | 未标 | 200 |
| cn:minimax-m3 | 0.25 | 512K | 524K | ❌ | medium | 200 |
| cn:hy4-preview | 0.29 | 1M | 64K | ❌ | high | 200 |
| global:hy4-preview | 0.29 | 1M | 64K | ❌ | high | 200 |

### 4.5 高代 `workbuddy-high`（0.51 – 0.79）

| 模型 | 倍率 | 上下文 | 输出上限 | 可关思考 | effort 档位 | 实测 |
|---|---:|---:|---:|---|---|---|
| cn:deepseek-v4-pro | 0.51 | 1M | 393K | ✅ | low / high / xhigh | 200 |
| cn:kimi-k2.6 | 0.52 | 256K | 32K | ❌ | medium | 200 |
| global:kimi-k2.6 | 0.52 | 256K | 32K | ❌ | medium | 200 |
| cn:kimi-k2.7 | 0.57 | 256K | 32K | ❌ | medium | 200 |
| cn:glm-5.3 | 0.69 | 1M | 131K | ✅ | low / high / max | 200 |
| global:glm-5.3 | 0.69 | 1M | 48K | ✅ | low / high / max | 200 |
| cn:glm-5v-turbo | 0.71 | 200K | 64K | ❌ | medium | 200 |
| cn:kimi-k2.8-preview | 0.77 | 1M | 131K | ✅ | low / medium / high | 200 |
| global:kimi-k2.8-preview | 0.77 | 1M | 32K | ✅ | low / high / max | 200 |
| cn:glm-5.1 | 0.79 | 200K | 48K | ❌ | medium | 200 |
| cn:glm-5.2 | 0.79 | 1M | 131K | ✅ | high / xhigh | 200 |
| global:glm-5.2 | 0.79 | 1M | 48K | ✅ | high / xhigh | 200 |

**全部 30 个模型都支持工具调用**（网关 `supports_tool_call` 全为真）。

### 4.6 被排除的 26 个

| 类别 | 数量 | 例子 |
|---|---:|---|
| 账号类型不允许（blocked） | 2 | `global:gpt-6-luna`、`global:gpt-5.6-luna` |
| 上游不可用（unavailable） | 2 | `global:auto-chat`、`global:o4-mini`（上游 `11102 model not available`，且被 model_lock 锁到 2026-10-21） |
| 路由别名 | 8 | 见 §4.1 |
| 倍率 > 0.80 | 10 | gemini-3.8/3.5-flash、gpt-5.3-codex、gpt-6-sol、gpt-6.1-sol、gpt-5.6-terra、kimi-k3、kimi-k3-1、gpt-5.4、grok-4.7、gpt-5.5、gpt-5.6-sol、gpt-6-astra |
| 无挂牌价 | 2 | `cn:hy4-preview-f`、`global:hy4-preview-f` |
| 限流（rate_limited） | 1 | `global:enhance-1.0`（同时是别名） |

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

## 5. 关思考参数矩阵

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

**WorkBuddy 侧 30 个模型一个都没配覆盖** —— 探测确认它们**全部接受 ZCode 原生 body**。
（与 OpenCode-Go 侧不同：那边 minimax-m3 会拒 `thinking:{type:"enabled"}`，这边 CodeBuddy 上游接受。）

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
| 子代理 / 小改动 | `claude-haiku-5-5` |
| 中文任务 | `qwen3.8-flash` |
| 后台批量 | `hy3`、`longcat-2.0`，夜里用 `longcat-2.5-preview-free` |
| 别用于交互 | `longcat-2.0`、`longcat-2.5-preview-free`、`qwen3.7-plus` |

---

## 7. 维护本文档的规则

- **分组 / 协议 / 参数矩阵**变了 → 同步本篇 + 根 [README.md](../README.md) 的「已知坑」。
- **数值要带时点**。价格、额度、倍率、实测首字都是某一时刻的快照，
  换新快照时把日期一起改掉。
- **不要在本篇写排查步骤** —— 那是 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 的事；
  **也不要写「为什么会这样」** —— 那是 [PITFALLS.md](PITFALLS.md) 的事。
