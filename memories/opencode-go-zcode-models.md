---
name: opencode-go-zcode-models
description: OpenCode Go 订阅的模型价格/额度、协议归属（chat/messages/responses）、ZCode provider
  配置结构与已实测的可用模型
metadata:
  node_type: memory
  type: project
  originSessionId: sess_45231509-4e0a-42d5-b258-b22ab0e27a40
---

用户通过 **OpenCode Go** 订阅（Go $10/月、Go Plus $40/月）在 ZCode 里用第三方模型，API key 配在 `~/.zcode/v2/provider_config.json`。2026-10-19 做过一次全量实测。

**额度机制**：按模型分别计算美元额度，5 小时 = 月度 20%、每周 50%、每月 100%。DeepSeek V4.1 Flash 月额度 $80（全表最高），GLM-5.3-Flash/MiMo Flash/LongCat-2.0/MiniMax M3/Hy3 各 $60，Qwen3.8 Flash/Space Bunny/Hy4 $30，Claude Haiku 5.5、GPT Luna、Grok、GLM-5.3、DeepSeek V4 Pro 各 $15。

**价格带（≤ V4.1 Flash 或略高）**：beam-free、longcat-2.5-preview-free、minimax-m3.1-flash-free 三个 free 模型官方定价表里 Input/Output/Cached Read 全是 `Free`、月额度列写 **`Unlimited`**、"Estimated requests" 表里 5 小时/周/月三档也是 `Unlimited`（Go 与 Go Plus 都是）；但脚注逐个写 **"Free for a limited time"**——即无限的是配额不是永久供应，官方说"model list 可能随时变""usage limits may change"，没有公布截止日。官方 Tip：**"If you reach the usage limit, you can continue using the free models"**——付费额度全用光后还能靠 free 模型续命，free 组是兜底不是补充。**2026-10-20 00:53 复核官方页面**：M3.1 Flash Free 仍是 Free/Free/Free + 月额度 `Unlimited`，Estimated requests 5h/周/月三档全 `Unlimited`（Go 与 Go Plus 一致）→ 官方口径下"额度无限"，但脚注仍是 "Free for a limited time"（无截止日）。models 页明写它**零保留、不用于训练**；官方弃用表里**没有**它 = 未公布退役日。Console 通用页另有更多 free 模型（glm-5.3-flash-free、deepseek-v4.1-flash-free、exo-free、mimo-v2.5/v2.6-flash-free、nemotron 3 ultra/3.5 系列、big-pickle、ll-alpha-free、jev-1.13-free），但 Go 套餐表只承认 3 个 free。地区限制名单（安哥拉/白俄/柬埔寨/**中国含港澳**/古巴/伊朗/伊拉克/老挝/利比亚/尼日利亚/朝鲜/俄罗斯/叙利亚/土库曼/乌兹别克/委内瑞拉+乌克兰三州）**只挂在 Beam Free 头上**，M3.1 Flash Free 和 LongCat 2.5 Preview Free 无地区排除；但整个 Go 服务"主要面向国际用户"，直连中国出口会 403 `unsupported_country_region_territory`（见 [[shellcrash-ai-routing-fix]]）。free 模型没有公布 RPM/并发数，只有"traffic is monitored for abuse"的口径。官方价表解析入口 `https://opencode.ai/v2/docs/console/go/`（HTML），请求估算表在同页 "Estimated requests" 段。MiMo 系列 $0.14/$0.28；GLM-5.3-Flash $0.15/$0.50；Qwen3.8 Flash $0.15/$0.47；Space Bunny $0.15/$0.60；Hy3 $0.14/$0.58；DeepSeek V4.1 Flash $0.15–0.30/$0.60–1.20；MiniMax M3、LongCat-2.0 $0.30/$1.20；GPT-6-Luna $0.10/$0.50；Claude Haiku 5.5 $0.10/$0.50；GPT-5.6-Luna $0.20/$1.20；Qwen3.7 Plus $0.40/$1.60。

**协议是最大坑**：模型按协议锁死，塞错 provider 直接 400 `ModelProtocolUnsupported`。
- 仅 `openai-chat-completions`：glm 全系、mimo 全系、hy3/hy4、space-bunny、longcat 全系、step-5、beam-free、omen-alpha、qwen3.6-plus、qwen3.7-max、kimi-k2.6/k2.7-code
- 仅 `anthropic-messages`：claude-haiku-5-5、minimax-m2.7
- 仅 `openai-responses`：grok-4.6/4.7、gpt-5.6-luna、gpt-6-luna、muse-spark-1.2/1.3
- 多协议：deepseek-v4.1-flash（三种全通）、deepseek-v4-flash-vision-exp、kimi-k3、qwen3.8-max、qwen3.8-flash（chat+messages）

**调用硬约束**：所有模型都必须带 `x-opencode-session`（或 `x-session-id`/`session_id`/`x-claude-code-session-id`），否则 400 `Request is missing x-opencode-session and cannot be routed efficiently`。2026-10-19 晚对 deepseek/glm/minimax/longcat/mimo 逐一实测：无头全 400、带头全 200，**不是 longcat 独有**。ZCode 引擎会自动加：`createModelRequestAttributionHeaders`（`resources/glm/zcode.cjs`）在 baseURL 命中 `opencode.ai/zen/go/v1` 且 `traceContext.sessionId` 存在时写入该头；本会话用 `opencode-go-chat/deepseek-v4.1-flash` 正常跑通即证明头已发出，无需在 `provider_config.json` 里另配。Cloudflare 会拦默认 Python UA（403 error 1010）；`muse-spark-1.2/1.3` 和 `gemini-4-argon-contributor` 需在 workspace Privacy 允许"训练数据的付费端点"才能用。

**ZCode 配置（2026-10-19 23:03 重排后）**：支持 `anthropic-messages` / `openai-chat-completions` / `openai-responses` 三种 `api.type`。ZCode 模型级 schema 只有 `enabled/contextWindow/reasoningLevel/maxOutputTokens`，**没有 displayName/备注字段**，所以用 providerName 当标签；providerId 保持不变（老会话的 modelSelection 引用 providerId，改名会破坏旧会话）。最终 6 个 provider（两字中文、无 emoji），chat 按**成本档**而不是用途拆分，依据「额度可撑输出 = 月额度 ÷ 输出单价」：
- `opencode-go-chat` = **主力**（chat）：deepseek-v4.1-flash、deepseek-v4-flash-vision-exp、mimo-v2.5-pro、mimo-v2.6-pro
- `opencode-go-chat-free` = **免费**（chat，新建）：beam-free、minimax-m3.1-flash-free、longcat-2.5-preview-free
- `opencode-go-chat-fast` = **低耗**（chat，原"速度"，100M+ 溢流池）：glm-5.3-flash、mimo-v2.6-flash、mimo-v2.5、hy3
- `opencode-go-chat-slow` = **高耗**（chat，原"经济"，50M 档）：minimax-m3、longcat-2.0
- `opencode-go-messages` = **对话**（anthropic-messages）：claude-haiku-5-5、qwen3.8-flash、qwen3.7-plus、minimax-m2.7
- `opencode-go-responses` = **响应**（openai-responses，原名"备用"，2026-10-20 因 muse-spark 入驻改名）：gpt-6-luna、gpt-5.6-luna、muse-spark-1.3-contributor、muse-spark-1.2-contributor

**成本分档（额度可撑输出 token，按输出单价）**：mimo-flash/mimo-v2.5 各 214M（每美元最耐用）、deepseek-v4.1-flash 133M（谷 $0.60）/67M（峰 $1.20）、glm-5.3-flash 120M、hy3 103M、qwen3.8-flash 64M、minimax-m3 与 longcat-2.0 各 50M、qwen3.7-plus 37.5M、claude-haiku/gpt-6-luna 各 30M、mimo-pro 17M、gpt-5.6-luna 12.5M。结论：deepseek 峰谷双价夹住列表中部，是最耐用的付费模型之一（$80 额度全场最大）；真正贵的是 gpt-5.6-luna、mimo-pro、claude-haiku、qwen3.7-plus、minimax-m3、longcat-2.0。

**思考参数覆盖（`optionSpecs.reasoningLevel.map="{}"` = 不发送任何思考参数）**：beam-free、minimax-m3.1-flash-free、minimax-m3 已配，使其在任意思考等级下都不会 400（beam-free 上游拒收 thinking；m3.1 拒收 `thinking:disabled`/`reasoning_effort:none`；m3 拒收 `thinking:enabled`）。重排脚本 `~/.zcode/v2/apply-chat-regroup.js`（默认 dry-run，--apply 才写，原子替换+写前校验），备份 `.bak-regroup-20261019150317`。

baseUrl 均为 `https://opencode.ai/zen/go/v1`（三种路径都实测可用）。`opencode-go-chat` 这个 providerId 必须保留（当前会话的默认模型挂在它下面）。改配置前先备份为 `provider_config.json.bak-YYYYMMDD-HHMMSS`。引擎对 `provider_config.json` 默认每 1s 轮询热加载（`NodePersonalProviderConfigRepository`，`pollingIntervalMs` 默认 1000），外部编辑通常无需重启；若模型选择器没刷新再重启 ZCode。避免在 UI 改 provider 设置的同时外部写文件（原子写竞态）。19/19 模型按各自协议实测 HTTP 200。ZCode 是 opencode 官方 listed validated client。

**实测快慢（2026-10-19，经路由器代理）**：第一梯队（交互首选）beam-free ~1.2s、glm-5.3-flash ~1.3s、space-bunny ~1.3s、minimax-m3 ~1.5s、gpt-6-luna ~1.6s、claude-haiku-5-5 ~1.7s、mimo-v2.5-pro ~2.0s；第二梯队 deepseek-v4.1-flash ~2.4s、qwen3.8-flash ~2.2s、gpt-5.6-luna ~1.7s、qwen3.7-plus（首字 4s、输出极长）；首字慢/别交互 hy3、mimo-v2.5、mimo-v2.6-flash、longcat-2.0；极慢 longcat-2.5-preview-free（18.6s）。带 reasoning 的模型给太小 max_tokens 会正文为空，属正常。

**地区限制的真相**：opencode.ai 经港/日/新/美/台/英/印/加/德任意节点都能 200。此前看到的 403 `unsupported_country_region_territory` 是路由器自身 curl 没走透明代理（直连中国出口）导致的，不是节点问题；详见 [[shellcrash-ai-routing-fix]]。

**2026-10-19 晚补测（带 ZCode 真实参数体 thinking:{type:"enabled"} 等四件套）**：`space-bunny` 上游已 410 弃用（官方提示改用 `minimax-m3.1-flash-free`，实测可用且接受该参数体，免费）；`minimax-m3` 拒收 `thinking.type:"enabled"`（只许 adaptive/disabled），在 ZCode 里把思考设"关闭"即通，详见 [[beam-free-thinking-param-fix]]。其余此前未在 ZCode 跑过的模型全部 200。前文"space-bunny ~1.3s 可用"的实测结论已作废。

**2026-10-19 22:40 配置收尾**：beam-fix 已应用（beam-free 带 `optionSpecs.reasoningLevel.map="{}"`，备份 `.bak-beamfix-20261019143257`）；速度组已把 `space-bunny` 换成 `minimax-m3.1-flash-free`（备份 `.bak-speedgroup-20261019143939`），实测新模型带 ZCode 全套 thinking 参数体 200。当前速度组：glm-5.3-flash、beam-free、minimax-m3.1-flash-free、minimax-m3。

**非 ZCode 客户端补 session 头**：其他客户端（ChatBox/Open WebUI 等）若不支持自定义请求头，用本地注入代理 `providers/opencode-go/ops/opencode-header-proxy.js`（`node` 启动，监听 127.0.0.1:8787，客户端 base URL 填 `http://127.0.0.1:8787/v1`；优先透传客户端自带 x-session-id，否则用固定值/`--session`）。已实测 longcat-2.0、glm-5.3-flash、minimax-m3.1-flash-free 非流式与流式全部 200。客户端“自定义请求头”要写成 JSON 键值对 `{"x-opencode-session":"my-client-001"}`（个别客户端要求数组 `[{"name":...,"value":...}]`）；“提供商选项”同理。**2026-10-19 22:50 复测**：longcat-2.0 关思考后首字 1.7s（基线 3.6s）、longcat-2.5-preview-free 7.4–8.7s，好于白天最差的 17–24s，波动很大；关思考写法见 [[beam-free-thinking-param-fix]]。

**自动收录新模型的数据源（2026-10-19 23:5x 实测，四个源都可脚本化）**：
1. `GET https://opencode.ai/zen/go/v1/models` → 200，返回 37 个 id（**不需要** Authorization）。**但它不是完整目录**：`deepseek-v4-flash-vision-exp` 实测三协议都能跑，却在列表里没有；而 `space-bunny` 已 410 弃用且已从列表消失。所以"不在列表"≠不可用，只按它做差集既会漏新增也会误报消失——检测源必须取并集：`/models` ∪ 文档价格表 ∪ 现有 provider_config ∪ 主动探测。
2. 价格/额度表在 `https://opencode.ai/v2/docs/console/go/`（HTML，200），表头 `Model | Input | Output | Cached Read | Cached Write | Monthly limit`，可直接正则解析出"输出单价 + 月额度"来算成本档。
3. 协议判定：POST 三端点各一次，协议错 → 400 `ModelProtocolUnsupported`；可用 → 200。**必须带 `Authorization: Bearer <provider_config.json 里的 apiKey>`**，否则 401 `Go requires a credential`（`/models` 不需要）。
4. 弃用判定：410 `ModelDeprecated`，响应带 `metadata.replacement`（如 space-bunny → minimax-m3.1-flash-free）。
5. 思考参数：带 ZCode 真参数体（`thinking:{type:"enabled"}` 等四件套）复测，400 就退 `adaptive`/`disabled`，全拒就写 `optionSpecs.reasoningLevel.map="{}"`。
另有 3 个模型（muse-spark-1.2/1.3-contributor、gemini-4-argon-contributor）报 `trains on request data`，属 workspace 隐私授权问题，脚本解决不了。

**额度计费真相（2026-10-20 复核官方 budgets 文档 + 实测账号）**：
- 官方 `/v2/docs/console/budgets/` 的 "What counts" 表：Paid Console models=Yes、own providers with a price=Yes、Web search=Yes、**Free models=No**、**Go usage within the plan=No**、**Go extra usage paid from credits=Yes** → 结论：**免费模型不产生任何费用，也不推高任何预算/配额百分比；Go 套餐内用量同样不计入预算**。所以拿 free 模型狂蹬，费用恒为 0，Go 计量器也不动。
- **新接口**：`GET https://opencode.ai/zen/go/v1/usage`（Bearer 认证，返回 200）→ `{"usage":{"rolling":{"percent":N,"resetsAt":...},"weekly":{...},"monthly":{...}}}`。rolling=5 小时窗口，weekly 每周一 00:00 UTC 重置，monthly 按订阅周期。**该接口不支持 per-model 拆分**（?model= / ?include=details 等参数都无效）。
- `GET https://opencode.ai/console/api/v1/budgets/members`（官方 budgets API，需 service key）→ 本账号的 `oc_sk_` key 返回 **403 Forbidden**（该 key 无预算管理权限），查不到分模型花费；分模型明细只能在 console 网页 Usage 页看（按天/模型/人拆分，支持 Export CSV 7/30/90 天）。
- apiKey 实际存放路径：`config.providerConfigRules.providerRules[i].config.access.apiKey`（**不是** `config.api.apiKey`；`config.api` 里只有 type + baseUrl）。`go_model_sync.py` 里 `api_key()` 读的正是 `access.apiKey`，路径正确。

**2026-10-20 00:00 自动收录落地**：
- 脚本 `providers/opencode-go/ops/go_model_sync.py`（`--apply` 才写配置；先备份 `.bak-gosync-<ts>`，原子替换）；定时任务"每天 10:00 自动收录 Go 套餐新模型"（ZCode cron，automationId `automation-5ad749e3-0d25-4323-afbc-7ae30cdc7288`）。
- 数据源补全：`https://opencode.ai/v2/docs/console/models` 有**全量目录**（Model→Model ID→Endpoint=协议、公开价、"Free" 标记、**弃用日期表**）；`/v2/docs/console/go/` 有 Go 套餐的模型表 + 定价表（Go $10 档第一张 / Go Plus 第二张）。官方弃用表已过期 18 个（含 minimax-m2.5 2026-08-05、minimax-m2.7 **未**过期）。
- **鉴权头分协议**：`chat/completions`、`responses` 用 `Authorization: Bearer <apiKey>`；`anthropic/messages` 只认 `x-api-key: <apiKey>`（用 Bearer 会 401 `Go requires a credential`）——这解释了之前 muse-spark 在 messages 上 401 而 responses 200。
- **ZCode 请求体形态**（从 `resources/glm/zcode.cjs` 读出，探测要照抄）：chat/messages 带思考时是 `thinking:{type:"enabled",budget_tokens:1024}` 且删掉 temperature；responses 用 `reasoning_effort`。
- **训练开关打开后** muse-spark-1.2/1.3-contributor 可用（只支持 openai-responses），$0.10/$0.20、月额度 $60 → **额度可撑 300M，全场最耐用**；已自动收录进"响应"组并配 `optionSpecs.reasoningLevel.map="{}"`（带 reasoning_effort 会报错）。`gemini-4-argon-contributor` 三协议仍不通（401，权限没给到它）。
- 收藏门限：输出单价 ≤ $1.60（现有配置里最贵的 qwen3.7-plus）；主力组人工精选不自动进；价格查不到的模型只列候选。
- **定时任务能不能指定模型**：`automations` 表有 `model/provider/mode/thought_level/model_selection` 字段，但 **CronCreate 工具入参没有 model**，会自动继承"创建时那个会话"的模型；**CronUpdate 明确不能改 model/provider/mode/thought_level**，只能改标题/提示词/时间。实测本次继承到 `opencode-go-chat-free/minimax-m3.1-flash-free`（免费模型，正好零成本）。另外同一会话内**第二次 CronCreate 会被拒**（"session that already belongs to a scheduled task"），需先用 CronUpdate 改现有任务。
- **Agent 固定模型**（原生支持）：agent 目录 = 用户级 `~/.zcode/agents/` + 项目级 `<工作区>\.zcode\agents\`；frontmatter 支持 `model:`（如 `model: opencode-go-chat/deepseek-v4.1-flash`）、`thoughtLevel`、`tools`。这是"按用途分模型"零延迟的官方做法。
- **ZCode hook 事件**只有 `SessionStart / UserPromptSubmit / PreToolUse / PermissionRequest / PostToolUse / PostToolUseFailure / Stop`，`UserPromptSubmit` 只能返回 `additionalContext`（注入上下文），**不能改模型**——所以"前置 AI 换模型"不能在 hook 层做。

完整报告：`docs/archive/OPENCODE-GO-模型与订阅优化分析.md`；速查表：`docs/模型速查表.md`（2026-10-19 23:03 重写：按主力/免费/低耗/高耗 + 对话/备用分组，含价格、月额度、额度可撑输出、快慢、关思考写法）；实测脚本在 `providers/opencode-go/probe/`。相关：[[shellcrash-ai-routing-fix]]、[[zcode-ui-ordering-preferences]]
