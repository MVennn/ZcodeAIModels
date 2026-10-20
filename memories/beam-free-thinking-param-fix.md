---
name: beam-free-thinking-param-fix
description: beam-free 在 ZCode 里 400 的根因是内置通用 reasoningLevel map 无条件发 thinking
  字段；修复已于 2026-10-19 22:32 应用（optionSpecs.reasoningLevel.map="{}"）
metadata:
  node_type: memory
  type: project
  originSessionId: sess_90769d7e-e70e-467f-99bf-59617df8b1c1
---

2026-10-19：beam-free 在 ZCode 里一发消息就 400 `unsupported_parameter: thinking`，根因与修法如下。

**根因**：ZCode 内置配置 `resources/config/provider/zcode-builtin.json` → `modelConfigRules.modelApiRules[2]`（`modelMatch ".*"` + `apiTypeMatch "openai-chat-completions"`）给**所有 chat 协议模型**的请求体无条件拼四个字段：`thinking`、`enable_thinking`、`reasoning_effort`、`reasoning`（由 session 的 reasoningLevel 映射）。beam-free 上游只认 `reasoning_effort`，其余三个字段任意取值都 400；且 `reasoning_effort` 只接受 `max/xhigh/high/medium/low`（`none` 也 400）。glm/mimo/deepseek 等模型的上游容忍这四个字段，所以只有 beam-free 暴雷。

**已实测（curl 直连 opencode.ai/zen/go/v1，带 x-opencode-session）**：不带任何附加参数 → 200（beam-free 自己就会返回 reasoning_content，思考关不掉也不需要关）；`thinking` / `enable_thinking` / `reasoning` → 400；`reasoning_effort:"high"` → 200。UI 里把思考等级调到"关闭"没用——map 在 disabled 时仍会发 `thinking:{type:"disabled"}`。

**修法**（无需改 ZCode 本体）：在 `~/.zcode/v2/provider_config.json` 的 `modelConfigRules.providerModelRules` 里 beam-free 条目的 `config` 下加：

```json
"optionSpecs": { "reasoningLevel": { "map": "{}" } }
```

`"{}"` 是内置默认空 map（base modelRule 本来就用它）。优先级已从引擎源码验证：`FA.composeEffective(builtin, personal)` 把用户精确规则（带 providerId+modelId）拼在内置规则之后，`overlay` 逐字段合并——`HXe.overlay` 对 values/map 各取各的，所以只覆盖 map、保留 `values:["disabled","enabled"]`。引擎源码在 `resources/glm/zcode.cjs`（`setThoughtLevel`、`composeEffective`、`ModelConfigRules.resolve` 都在里面）。

**执行方式**：脚本 `~/.zcode/v2/apply-beam-fix.js`，默认 dry-run 只校验不写；`--apply` 才写入（自动备份 `provider_config.json.bak-beamfix-<时间戳>`，并在检测到 ZCode.exe 运行时拒绝执行）。必须完全退出 ZCode（含托盘）再 --apply，原因见 [[opencode-go-zcode-models]] 的配置改动注意事项，否则内存配置会覆盖文件。脚本自带幂等检查（已补过会直接退出）。

**当前状态（2026-10-19 22:32 已应用）**：`provider_config.json` 的 beam-free 条目已有 `optionSpecs.reasoningLevel.map = "{}"`，备份 `provider_config.json.bak-beamfix-20261019143257`。用户随后重启了 ZCode。若以后配置被重置，重跑 `node ~/.zcode/v2/apply-beam-fix.js --apply`（脚本幂等，已应用会直接退出）。

**配置热加载**：引擎的 `NodePersonalProviderConfigRepository`（`resources/glm/zcode.cjs` 的 `ohe` 类）对 `provider_config.json` 默认每 1000ms 轮询一次，外部修改会被加载；本次运行中直接改文件也未被应用覆盖。仍在 UI 改 provider 设置时避免同时外部写入（atomic update + 锁），改前照例备份。

**同款问题全面排查（2026-10-19 晚，日志 + 全模型预测性验证）**：
- 日志里 ZCode 实际发的思考等级是 `max`（60 次）/`enabled`（7 次），即 `thinking:{type:"enabled"}` 变体。
- **minimax-m3 是同款**：上游只允许 `thinking.type=adaptive/disabled`，max/enabled 变体 400；disabled 变体 200。修法不用改配置——在 ZCode 里把该模型思考等级设"关闭"即可。
- **space-bunny 已死**：410 `has been deprecated. Use minimax-m3.1-flash-free instead`，与 thinking 无关但任何设置都救不回；`minimax-m3.1-flash-free` 实测存在且接受 ZCode 参数体（免费）。
- 其余零记录模型带 ZCode 参数体全 200：hy3、longcat-2.0、mimo-v2.5、mimo-v2.5-pro、mimo-v2.6-pro、deepseek-v4-flash-vision-exp、qwen3.7-plus、minimax-m2.7、gpt-5.6-luna、longcat-2.5-preview-free（首次 socket hang up 属偶发，重试 200）。
- 历史里 thinking 相关但**不同款**的偶发错：claude-haiku-5-5 的 `Invalid signature in thinking block`（会话历史回放问题，新请求 200）；deepseek-v4.1-flash 的 `reasoning_content must be passed back`（2/2803 偶发，回传契约）；41 次"无正文"是 max_tokens 给小了，属已知正常。qwen3.8-flash 的 business error 复测 200 无法复现。
- 其余失败与 thinking 无关：协议放错组（glm-5.3-flash、gpt-6-luna 曾放 messages 组）、模型不在订阅（deepseek/glm 的 -free 变体）、额度、并发、DNS。
- 日志分析脚本：`~/.zcode/cli/exec/log-scan.js`、探测脚本 `probe-matrix.js`。

**关思考参数矩阵（2026-10-19 22:50，脚本 `opencode-go/probe/thinking-off-probe.js` 实测）**：
- `{"thinking":{"type":"disabled"}}` 能真正关掉思考：`longcat-2.0`（首字 3.6s→1.7s）、`longcat-2.5-preview-free`（8.7→7.4s，模型本身慢）、`minimax-m3`、`deepseek-v4.1-flash`（2.5→1.4s，`reasoning_effort:"none"` 也有效）。
- `minimax-m3.1-flash-free`：`thinking:disabled` 与 `reasoning_effort:"none"` 都返回 400，必须用 `{"enable_thinking":false}`（200、无 reasoning、约 1.2s 出正文）。
- `glm-5.3-flash`：三种写法都关不掉——`thinking:disabled` / `reasoning_effort:"none"` 是 400，`enable_thinking:false` 被忽略仍在思考；只能给足 max_tokens，否则思考吃光预算导致正文为空。
- `beam-free`：只认 `reasoning_effort`，天生带思考、关不掉（本身 1s 级，不必管）。
- `longcat-2.5-preview-free`：`enable_thinking:false`、`reasoning_effort:"none"` 都拦不住思考，只有 `thinking:{type:"disabled"}` 有效。
