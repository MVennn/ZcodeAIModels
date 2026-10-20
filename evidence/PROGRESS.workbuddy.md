# PROGRESS — WorkBuddy2API 反代接入 ZCode（独立任务文件）

> 根目录 `PROGRESS.md` 是路由器运维线任务的文件，其头部明确要求后续任务写各自独立文件，
> 故本任务单独维护 `PROGRESS.workbuddy.md`，不覆盖根文件。
>
> 本篇是**历史台账**（探测于 2026-10-20 在本地开发机上采集），结论与数据一律按原样保留。

## 任务目标

把 WorkBuddy2API 网关（`http://127.0.0.1:7863`，腾讯 CodeBuddy 反代）接入 ZCode：
新建「反代」分区，按积分倍率（越小越便宜）收录模型，并以 deepseek-v4.1-flash 为参照。

用户追加要求（2026-10-20 16:0x）：
1. 只收低积分模型，**不能高于 deepseek-v4.1 太多**；
2. **按积分倍率排列**；
3. 反代分区可拆成 **免费/低耗/高耗** 或 **免代/低代/高代** 三组。

## 状态: 进行中

---

## 已确认的事实（2026-10-20 实测）

### 网关与目录
- 网关进程 `wb2api.exe -config config.json`（本机的 WorkBuddy2API Panel 安装目录），监听 `:7863`。
- 模型清单 56 个：`/panel/api/models` 与 `/v1/models` 同源。**注意**：`/panel/api/models`
  在网关未重启时只返回 34 个 global 模型，重启后返回全部 56 个（cn 22 + global 34）。
- 路由别名（无自身价格、只是路由到别的模型）：`cn:auto` `global:auto-chat`
  `global:default-model` `global:primary-model` `global:deep-model` `global:fast-model`
  `global:balanced-model` `global:enhance-1.0` → 全部排除。
- 账号池：`auths/` 4 个账号 = 3 个 global（`www.workbuddy.ai`）+ 1 个 cn（`www.codebuddy.cn`）。
  `/status` realm_totals：cn 1 个、global 3 个，全部 healthy。

### 积分倍率（`credits`=牌价，`promo_credits`=生效价）
- 参考模型 deepseek-v4.1-flash：`cn:deepseek-v4.1-flash` x0.11；`global:deepseek-v4.1-flash`
  x0.00（促销「Free now」）。`global:deepseek-v4.1-flash-sg` x0.03。
- x0.00 免代：cn:hy3、cn:step-5-preview（独家限免）、global:deepseek-v4.1-flash、
  global:hy3、global:step-5-preview。
- x0.03–x0.29：global:deepseek-v4.1-flash-sg、cn:hy3-x、cn:glm-5.3-flash、
  cn:minimax-m3.1-flash、cn:space-bunny、global:glm-5.3-flash、global:minimax-m3.1-flash、
  cn:deepseek-v4.1-flash、cn:deepseek-v4-flash、cn:mimo-v2.6-pro、cn:minimax-m3、
  cn:hy4-preview、global:hy4-preview。
- x0.43–x0.79：cn:step-5-preview(牌价)、cn:deepseek-v4-pro、cn:kimi-k2.6、global:kimi-k2.6、
  cn:kimi-k2.7、cn:glm-5.3、global:glm-5.3、cn:glm-5v-turbo、cn:kimi-k2.8-preview、
  global:kimi-k2.8-preview、cn:glm-5.1、cn:glm-5.2、global:glm-5.2。
- **x0.95 以上一律排除**（用户要求「不能高于 deepseek-v4.1 太多」）：
  gemini-3.8/3.5-flash、gpt-5.3-codex、gpt-6-sol、gpt-6.1-sol、gpt-5.6-terra、kimi-k3/kimi-k3-1、
  gpt-5.4、grok-4.7、gpt-5.5、gpt-5.6-sol、gpt-6-astra。

### 账号类型限制（关键坑）
3 个 global 账号是 `personal_free_user` 类型 → 多数 global 高端模型上游直接
`503 not allowed for user type`，无论倍率多低都调不通（实测 gpt-6-luna x0.07、
gpt-5.6-luna x0.14 也被拒）。cn 账号是普通账号，cn 系模型基本全通。

### 网关内部行为（读源码确认）
- 模型 id 形如 `cn:xxx` / `global:xxx`；`resolveModel()` 剥前缀得到 realm + 裸模型名，
  出站时重写回裸名（上游不认前缀）。
- `payload.go` 出站前会：`stream=true` 强制、`max_completion_tokens`→`max_tokens` 翻译、
  `tool_choice`/`image_url`/`developer` 角色归一、工具配对修复、deepseek 系注入
  `thinking:{type:enabled}`、`reasoning_effort` 按模型 supportedEfforts 降级。
- ZCode 发的 `thinking`/`enable_thinking`/`reasoning` 字段**网关不删**，原样透传给上游
  → 上游不认的模型会 400。所以探测必须用 ZCode 真实请求体。

### ZCode 内置规则（`resources/config/provider/zcode-builtin.json`）
- `modelApiRules` 按**文件顺序叠加，后面的规则覆盖前面的**；匹配是全量正则
  `^(?:pattern)$`（大小写不敏感）。`modelMatch` 匹配的是完整 modelId（含 `cn:`/`global:` 前缀）。
- idx 2 `.*` 是通用规则（`thinking` + `enable_thinking` + `reasoning_effort` + `reasoning`），
  后面 idx 30/33/35/37/39/55/57/59/63/67 等是各模型专属规则，会覆盖通用规则。
  例：`.*deepseek-v4[.-]1-flash.*` → 只发 `thinking` + `reasoning_effort`；
  `.*kimi-k2\.6.*` → 只发 `thinking`。
- `modelRules` 提供 reasoningLevel 可选值；`optionSpecs.reasoningLevel.map` 是 JS 表达式，
  由引擎求值成 JSON 对象。
- **已用 `scripts/zcode_effective_body.js` 复刻引擎的解析顺序 + 求值**，得到每个模型
  ZCode 真实会发的 body，避免手写规则表出错。

## 脚本产物

| 文件 | 作用 |
|---|---|
| `scripts/wb_pricing.json` | 网关 56 个模型的倍率/上下文/输出上限/effort 档位快照 |
| `scripts/workbuddy_probe_zcode.py` | 用 ZCode 真实 body 探测可用性（可断点续跑，��行写缓存） |
| `scripts/wb_zcode_probe.json` | 探测结果缓存（status/variant/http/detail/rate） |
| `scripts/zcode_effective_body.js` | 复刻引擎规则解析，算出某 modelId 的真实请求体 |
| `scripts/workbuddy_zcode_sync.py` | 按倍率分档生成 免代/低代/高代 三个 provider 并写入配置 |
| `scripts/workbuddy_probe_models.py` | 早期裸 body 探测脚本（已被 zcode 版取代） |
| `scripts/wb_model_status.json` | 早期探测缓存（已被 wb_zcode_probe.json 取代） |

## 步骤清单

- [x] 读取网关模型清单与积分倍率（`/panel/api/models`，56 个）
- [x] 摸清账号池 realm/类型与「not allowed for user type」限制
- [x] 读网关源码：realm 前缀解析、出站 body 改写、effort 降级
- [x] 读 ZCode 内置 `modelApiRules`，复刻引擎规则解析（后覆盖前 + 全量正则）
- [x] 写 `zcode_effective_body.js` 算真实 body
- [x] 写 `workbuddy_probe_zcode.py`（真实 body 探测 + 变体回退）
- [x] 探测全部 ≤x0.8 模型（41 个，20s 间隔）：**36 ok / 2 blocked / 2 unavailable / 1 rate_limited**
- [x] 跑 `workbuddy_zcode_sync.py --apply` 生成 免代/低代/高代 三组
- [x] 删除被取代的单个 `workbuddy-proxy` provider（48 条 model rule 一并清掉）
- [x] 验证 ZCode 热加载生效（ListModels 已列出三组 30 个模型）
- [x] 端到端实测（cn:hy3 / cn:deepseek-v4.1-flash / cn:glm-5.3 / cn:kimi-k2.6 均 200 且有正文）
- [x] 写记忆文件 + 更新 MEMORY.md

## 最终落地结果（2026-10-20 16:38）

`provider_config.json` 新增三个 provider（替换原 `workbuddy-proxy`），全部指向
`http://127.0.0.1:7863/v1`，协议 `openai-chat-completions`：

| providerId | 显示名 | 模型数 | 倍率区间 |
|---|---|---|---|
| `workbuddy-free` | 免代 | 5 | x0.00 全部 |
| `workbuddy-low` | 低代 | 13 | x0.03 – x0.29 |
| `workbuddy-high` | 高代 | 12 | x0.51 – x0.79 |

组内按倍率升序（同倍率按 id 字典序），符合用户「排列按积分」的要求。
providerOrder 里排在三个 opencode-go provider 之后。

排除的 26 个：2 个 blocked（global:gpt-6-luna / global:gpt-5.6-luna，账号类型不允许）、
2 个 unavailable（global:auto-chat / global:o4-mini）、8 个路由别名、10 个倍率 >x0.8、
2 个无挂牌价（cn:hy4-preview-f / global:hy4-preview-f）、1 个 rate_limited
（global:enhance-1.0，同时是别名）。

**注意**：所有 41 个探测模型**全部接受 ZCode 原生 body**，没有出现需要覆写
`optionSpecs.reasoningLevel.map` 的情况 → 三个 provider 里没有任何 reasoningLevel 覆盖。
（注意这与 opencode.ai 那套不同：那边 minimax-m3 会拒 `thinking:{type:"enabled"}`，
这边 CodeBuddy 上游接受。）

## 待解决 / 注意事项

- **探测速率**：池子只有 4 个账号（global 仅 3 个），4s 间隔会把 global 全部打进
  `no_healthy_account` 冷却（首次探测即如此）。必须 ≥20s 间隔。
- 网关进程 16:0x 期间已退出过一次（探测打爆账号池后进程消失），已重启（后台 pid 30424）；
  后续跑脚本前先确认 `http://127.0.0.1:7863/status` 可达。
- `global:o4-mini` 上游 `11102 model not available`，且 `/status` model_locks 显示
  该模型被锁到 2026-10-21 → 排除。
- 探测量化参考（`/status` accounts[].model_costs，credits/1k token）：多数 cn 模型实测
  0（免费额度覆盖），hy4-preview 0.1087、kimi-k2.8-preview 0.156、deepseek-v4-flash 0.182、
  kimi-k2.7 0.313、deepseek-v4-pro 0.361、kimi-k3 0.394、glm-5v-turbo 0.454、
  kimi-k3-1 0.901、gpt-5.3-codex 0.976。
- 网关日志里可见 `pool.credit_floor=100`：余额低于 100 的号不参与收费模型选号
  （实测 uid 923af063 credits=59 被 hold out）→ global 域付费模型只剩 2 个号可用。
- 网关日志显示 global 域存在「free tier ended, now 0.227 credits/1k」→ 限时免费会到期，
  届时 global 模型的实际积分消耗会上升；`wb_pricing.json` 需定期刷新。

## 状态: 已完成
