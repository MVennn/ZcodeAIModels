---
name: beam-free-daily-quota
description: beam-free 2026-10-20 报 429 是上游免费池日配额打满（每日 00:00 UTC 重置），不是配置/弃用/地区问题
metadata:
  node_type: memory
  type: project
  originSessionId: session_a3174cf4491b4a9acb7071922bb2012e
---

2026-10-20 17:2x：用户报"beamfree 没法用了"。实测结论——**是上游免费池的日配额打满，不是本地配置、不是弃用、不是地区限制**。

**现象**：所有 beam-free 请求返回 `HTTP 429` + `{"error":{"type":"server_error","message":"Upstream request failed: Rate limit exceeded. Please try again later."}}`，响应头带 `Retry-After: 52557`。

**判定为"日配额"的依据**：`Retry-After` 换算出的重置点正好落在 **2026-10-21T00:00:00.000Z = 北京时间 08:00**（00:00 UTC 整点），是标准日窗口边界。

**排除项（逐个实测）**：
- 与请求参数无关：裸请求、带 ZCode 四件套（thinking/enable_thinking/reasoning_effort/reasoning）、只带 `reasoning_effort:high` —— 三种全是 429。
- 不是账号额度问题：`GET /zen/go/v1/usage` → rolling 7% / weekly 28% / monthly 19%，三项 status 全 ok。
- 不是弃用：`/zen/go/v1/models` 里 beam-free 仍在；官方 `/v2/docs/console/go/` 仍列 "Beam Free (limited time, limited regions)"；官方弃用表里没有它。
- 不是地区限制：出口 IP `<REDACTED-EXIT-IP>`（loc=JP，日本），不在 beam-free 的排除名单（中国含港澳等 17 国）里；真被地区拦会是 403 `unsupported_country_region_territory`。
- 不是本地配置回归：`provider_config.json` 里 beam-free 的 `optionSpecs.reasoningLevel.map="{}"` 完好，也仍在"免费"组。
- 每日同步脚本 `scripts/go_model_sync.py` 不会误删：已配置模型体检只 log（429 落进"探测异常"分支），只有 410 弃用才提示移除。

**同时可用/不可用（Go 端点）**：Go 套餐只认 3 个 free——beam-free（429）、**minimax-m3.1-flash-free 200**、longcat-2.5-preview-free 200（带 ZCode 四件套也过）。Console 文档里的其它 free（glm-5.3-flash-free、deepseek-v4.1-flash-free、ll-alpha-free、exo-free、big-pickle-free、mimo-v2.5-free、mimo-v2.6-flash-free、nemotron-3-ultra-free、jev-1.13-free、step-5）在 `/zen/go/v1/chat/completions` 上全部 400 `Model is unavailable` —— Go 凭据用不了它们。

**处置**：等日窗口重置（北京时间次日 08:00）自动恢复；在此之前用 minimax-m3.1-flash-free 顶替。

相关：[[beam-free-thinking-param-fix]]、[[opencode-go-zcode-models]]
