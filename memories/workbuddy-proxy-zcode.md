---
name: workbuddy-proxy-zcode
description: WorkBuddy2API 反代接入 ZCode：免代/低代/高代 三组按积分倍率分层，含账号类型限制与 ZCode 真实 body 探测法
metadata:
  node_type: memory
  type: project
  originSessionId: session_550e6ccf44a392219d274ea2dc3f8921
---

2026-10-20：把腾讯 CodeBuddy 反代（WorkBuddy2API Panel，本机安装）
接进 ZCode，在 `~/.zcode/v2/provider_config.json` 建了三个 provider：

| providerId | 显示名 | 模型数 | 倍率区间 |
|---|---|---|---|
| `workbuddy-free` | 免代 | 5 | x0.00 |
| `workbuddy-low` | 低代 | 13 | x0.03–x0.29 |
| `workbuddy-high` | 高代 | 12 | x0.51–x0.79 |

共 30 个模型，**组内按积分倍率升序**（用户要求「排列按积分」「不能高于 deepseek-v4.1 太多」，
故上限取 x0.80，排除 x0.95+ 的 gemini/gpt-6/grok/kimi-k3 档）。全部指向
`http://127.0.0.1:7863/v1`，协议 `openai-chat-completions`。

**关键事实**

- **积分倍率 = 上游 `credits` 字段**（`x0.11` 这种，`/panel/api/models` 返回）；
  `promo_credits` 是生效价（限时免费/夜间折扣），`promo_label` 说明。**牌价 = 生效价 = 0**
  的才是真免费。cn:hy3（限时免费）、cn:step-5-preview（独家限免）、
  global:deepseek-v4.1-flash / global:hy3 / global:step-5-preview（Free now）都是 x0.00。
- **账号类型是硬门槛**：池里 4 个号 = 3 global + 1 cn（`/status` 的 `realm_totals`）。
  3 个 global 号是 `personal_free_user` 类型 → 多数 global 高端模型上游直接
  `503 not allowed for user type`，**倍率再低也调不通**（实测 x0.07 的 gpt-6-luna、
  x0.14 的 gpt-5.6-luna 全被拒）。cn 号是普通账号，cn 系基本全通。
- 路由别名（无自身价格，只是路由到别的模型）必须排除：`cn:auto`、`global:auto-chat`、
  `global:default-model`、`global:primary-model`、`global:deep-model`、
  `global:fast-model`、`global:balanced-model`、`global:enhance-1.0`。
- 网关的 `pool.credit_floor=100`：余额 <100 的号不参与**收费**模型选号
  （免费模型不受限）。所以 global 域实际只有 2 个号能跑付费模型。
- 网关进程会**因探测过密而挂**：池子只有 4 个号，4 秒间隔会把 global 全部打进
  `no_healthy_account` 冷却，连网关进程都一度消失。探测间隔必须 ≥20 秒。
- `/panel/api/models` 在网关**刚重启时**只返回 34 个 global 模型，重启完成后才返回全部 56 个
  （cn 22 + global 34）→ 脚本要能容忍列表缺失，或先确认网关已热身完。

**ZCode 侧坑（本次实测，与 opencode.ai 那套不同）**

- ZCode 内置 `modelConfigRules.modelApiRules` 按**文件顺序叠加，后面的规则覆盖前面的**；
  匹配是全量正则 `^(?:pattern)$`（大小写不敏感），`modelMatch` 匹配**完整 modelId**
  （含 `cn:`/`global:` 前缀）。通用规则 `.*`（idx 2）发
  `thinking` + `enable_thinking` + `reasoning_effort` + `reasoning` 四件套；
  但 `.*deepseek-v4[.-]1-flash.*`（idx 67）只发 `thinking` + `reasoning_effort`，
  `.*kimi-k2\.6.*`（idx 33）只发 `thinking`。**手写规则表极易错**。
- 已写 `workbuddy/zcode_effective_body.js`：复刻引擎解析顺序并用 Node
  `new Function` 求值 `optionSpecs.reasoningLevel.map`，直接算出某 modelId 的**真实请求体**。
- 网关**不删** ZCode 发的 thinking 类字段，原样透传上游 → 上游不认就 400。
  所以探测必须用 ZCode 真实 body，不能用裸 body（否则会漏判）。
  本次 41 个模型**全部接受 ZCode 原生 body**，因此三个 provider 里**没有**任何
  `reasoningLevel.map` 覆写（与 [[beam-free-thinking-param-fix]] 的 opencode.ai 情况相反：
  那边 minimax-m3 拒 `thinking:{type:"enabled"}`，这边 CodeBuddy 上游接受）。
- ZCode 热加载 `provider_config.json`（~1s 轮询）——改完无需重启，用 `ListModels` 工具
  即可确认新 provider 是否已生效。

**脚本产物**（都在仓内 `workbuddy/`）

| 文件 | 作用 |
|---|---|
| `cache/wb_pricing.json` | 网关 56 模型倍率/上下文/输出上限/effort 档快照 |
| `workbuddy_probe_zcode.py` | 用 ZCode 真实 body 探测（可断点续跑，逐条写缓存） |
| `cache/wb_zcode_probe.json` | 探测缓存（status/variant/http/detail/rate） |
| `zcode_effective_body.js` | 复刻引擎规则解析，算真实请求体 |
| `workbuddy_zcode_sync.py` | 按倍率分档生成三个 provider 并写配置（`--apply` 才写） |

配置备份：`provider_config.json.bak-wbproxy-20261020-163755`（分层写入）、
`.bak-wbproxy-rm-20261020-163800`（删旧 provider）。

相关：[[opencode-go-zcode-models]]、[[zcode-ui-ordering-preferences]]、[[beam-free-thinking-param-fix]]
