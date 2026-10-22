# OpenCode Go 模型速查表（历史快照）

> **一句话**：2026-10-20 的速查快照 —— 价格、月额度、实测首字与关思考写法，
> 按成本档分好组。**结论已并入 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)，
> 本篇保留作历史快照**（分组与参数口径一律以 MODEL-PROVIDERS 为准，
> 本篇只补实测数据）。

> ZCode 里 chat 按成本档拆成 4 组 + 对话 / 响应，共 6 个 provider。
> 价格与月额度来自 opencode Go 文档（2026-10-19）；速度是本机经路由器代理实测（首字含约 300ms 握手），会随时段波动。
> **「额度可撑输出」= 月额度 ÷ 输出单价**。每个模型的额度独立计算，所以这个数比单价更能说明"一个月能用多少"，也是分组和排序的依据。
> 更新：2026-10-20 00:05 自动收录 muse-spark-1.2/1.3-contributor；"备用"组改名"响应"（现在装的是最耐用的模型，不再是备胎）。

## 主力（`opencode-go-chat`，openai-chat-completions）

| 模型 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 实测首字 | 最适合 |
|---|---|---|---|---|---|
| **deepseek-v4.1-flash** | 0.15–0.30 / 0.60–1.20 | **$80** | 133M（谷）/ 67M（峰） | 1.3–4s，~46 tok/s | 默认主力；额度全场最大，三协议全通 |
| deepseek-v4-flash-vision-exp | 文档未列 | 未列 | — | ~1.9s | 需要图片输入时 |
| mimo-v2.5-pro | 0.435 / 0.87 | $15 | 17M | 1.8–1.9s，45–106 tok/s | 中等推理；额度小，别当主力 |
| mimo-v2.6-pro | 0.435 / 0.87 | $15 | 17M | 1.8–2.3s，~17 tok/s | 同上，输出速度波动大 |

## 免费（`opencode-go-chat-free`）

| 模型 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 实测首字 | 最适合 |
|---|---|---|---|---|---|
| **beam-free** | 0 / 0 | 免费无限 | ∞ | 1.0–1.5s | 极快；质量一般，天生带思考关不掉 |
| **minimax-m3.1-flash-free** | 0 / 0 | 免费（限时） | ∞ | ~1.1s | 免费里最快；参数最宽松（已配 map 覆盖） |
| longcat-2.5-preview-free | 0 / 0 | 免费无限 | ∞ | 5.9–24s（今晚 7.4–8.7s） | 慢，只适合夜里批量、非交互 |

## 低耗（`opencode-go-chat-fast`）——额度 100M+ 的溢流池

| 模型 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 实测首字 | 最适合 |
|---|---|---|---|---|---|
| **glm-5.3-flash** | 0.15 / 0.50 | $60 | 120M | 1.0–4s，~87 tok/s | 工具调用稳，可当日常主力替代 |
| **mimo-v2.6-flash** | 0.14 / 0.28 | $60 | **214M** | 2.3–6.3s | 每美元最耐用；慢 |
| mimo-v2.5 | 0.14 / 0.28 | $60 | **214M** | 2.1–3.3s | 同上，稍快一点 |
| hy3 | 0.14 / 0.58 | $60 | 103M | 3–7.3s | 慢；后台任务 |

## 高耗（`opencode-go-chat-slow`）

| 模型 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 实测首字 | 最适合 |
|---|---|---|---|---|---|
| minimax-m3 | 0.30 / 1.20 | $60 | 50M | 1.0–2.2s，64–159 tok/s | 1M 上下文；单价高，按需用（已配 map 覆盖） |
| longcat-2.0 | 0.30 / 1.20 | $60 | 50M | 1.7–17s | 慢且贵；只适合批处理 |

## 对话（`opencode-go-messages`，anthropic-messages）

| 模型 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 实测首字 | 最适合 |
|---|---|---|---|---|---|
| **claude-haiku-5-5** | 0.10 / 0.50 | $15 | 30M | 1.4–1.8s，63–365 tok/s | 子代理、小改动；>100K 上下文涨价 5 倍 |
| qwen3.8-flash | 0.15 / 0.47 | $30 | 64M | 1.6–5.5s | 中文任务、翻译 |
| qwen3.7-plus | 0.40 / 1.60 | $60 | 37.5M | 3.4–17s | 输出极长，一次性生成大段内容 |
| minimax-m2.7 | 未列 | 未列 | — | 1.8–2.6s | 通用备选 |

## 响应（`opencode-go-responses`，openai-responses）

| 模型 | 输入/输出 $/M | 月额度 | 额度可撑输出 | 实测首字 | 最适合 |
|---|---|---|---|---|---|
| **muse-spark-1.3-contributor** | 0.10 / 0.20 | $60 | **300M** | 2.5s | 全场最耐用：每美元能换 300M 输出；Meta 贡献者档，**请求数据会被用来训练**（已在 workspace 打开） |
| muse-spark-1.2-contributor | 0.10 / 0.20 | $60 | **300M** | 1.9s | 同上，旧版；同样会训练数据 |
| gpt-6-luna | 0.10 / 0.50 | $15 | 30M | 1.6–2.9s，~38 tok/s | OpenAI 风格推理 |
| gpt-5.6-luna | 0.20 / 1.20 | $15 | 12.5M | 1.7–2.3s，~45 tok/s | 同上；额度最不经花 |

> muse-spark 两个都只支持 `openai-responses` 协议，且带 `reasoning_effort` 会报错，ZCode 侧已配空 map 覆盖（不发送任何思考参数）。
> 「Contributor」= 贡献者档：用它的请求数据会拿去训练模型，所以只放不敏感的活。

---

## 关思考写法（2026-10-19 晚直连实测）

| 模型 | 有效写法 | 效果 |
|---|---|---|
| longcat-2.0、longcat-2.5-preview-free、minimax-m3、deepseek-v4.1-flash | `{"thinking":{"type":"disabled"}}` | 不再输出 reasoning（longcat-2.0 3.6s→1.7s，deepseek 2.5s→1.4s） |
| minimax-m3.1-flash-free | `{"enable_thinking":false}` | 1.2s 出正文；`thinking:disabled` 和 `reasoning_effort:none` 都会 400 |
| glm-5.3-flash | 无 | `thinking:disabled` 400、`reasoning_effort:none` 400、`enable_thinking:false` 仍思考；给足 max_tokens 即可 |
| beam-free | 不需要 | 天生带思考关不掉，但本身就是 1 秒级 |

ZCode 侧已给 `beam-free`、`minimax-m3.1-flash-free`、`minimax-m3` 配了空 map 覆盖（不发送任何思考参数），这三个模型不再受 UI 思考等级影响。其他模型在 UI 里设"关闭"即可。

## 一句话选择

- **日常写代码** → 主力组 `deepseek-v4.1-flash`；想省额度 → 低耗组 `glm-5.3-flash`
- **零成本** → 免费组 `beam-free`（快）或 `minimax-m3.1-flash-free`
- **长上下文** → 高耗组 `minimax-m3`（1M）
- **子代理 / 小改动** → `claude-haiku-5-5`
- **中文任务** → `qwen3.8-flash`
- **后台批量** → `hy3`、`longcat-2.0`，夜里用 `longcat-2.5-preview-free`
- **别用于交互** → `longcat-2.0`、`longcat-2.5-preview-free`、`qwen3.7-plus`

## 额度规则

每个模型独立计算美元额度：5 小时 = 月额度 20%，每周 50%，每月 100%。换模型 = 换一份独立额度，可以按任务轮换着用。

## 调用硬约束

所有请求必须带 `x-opencode-session`（缺了报 `Request is missing x-opencode-session and cannot be routed efficiently`）；Cloudflare 会拦默认 Python UA。ZCode 会自动带头，其他客户端见 `scripts/opencode-header-proxy.js`。

**鉴权头分协议**：`chat/completions` 和 `responses` 认 `Authorization: Bearer <apiKey>`；`anthropic/messages` 只认 `x-api-key: <apiKey>`（用 Bearer 会 401 `Go requires a credential`）。

## 自动收录（每天 10:00）

`scripts/go_model_sync.py --apply` 每天自动跑：拉 `/zen/go/v1/models` + 官方定价/弃用日期表 → 探测新模型的三种协议与思考参数兼容性 → 按成本档写进 `provider_config.json`（写前备份）→ 报告落到 `audit/go-model-sync-*.md`。

收录门槛：上游未弃用、三协议至少一个 200、输出单价 ≤ $1.60（现有配置里最贵的 qwen3.7-plus）。主力组是人工精选，不自动进；价格查不到的模型只列候选不自动收录。
