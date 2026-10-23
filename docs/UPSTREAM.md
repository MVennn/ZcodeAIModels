# 同类型开源项目调研（上游生态）

> **一句话**：本篇把「把模型接进 coding agent」这条线上能找到的开源项目过了一遍，
> 逐个说清**它解决什么、与本仓重叠在哪、我们能借鉴什么、以及为什么不把它整个搬进来**，
> 并把真正落地的借鉴写进 [../upstream/](../third-party/zcodium/) 与 [../NOTICE](../NOTICE)。

---

## 1. 调研口径

| 项 | 口径 |
|---|---|
| 快照日期 | **2026-10-20**（star 数、最近推送时间都是这一天的快照，会变） |
| 检索方式 | GitHub REST API `search/repositories`（`multi-provider ai gateway`、`llm proxy provider manager`、`claude code router`、`openai compatible proxy coding agent`、`zcode`）+ `repos/{owner}/{repo}` 元数据 |
| 取源码方式 | `git ls-remote` 取 HEAD SHA；`codeload` tarball 与 `raw.githubusercontent.com` 取文件。**没有整仓 clone 大仓库**（ZCodium 的 tarball 有 84 MiB，用完即删） |
| license 判定 | **逐个下载该 SHA 下的 `LICENSE` 原文核对**，不采信 GitHub API 的自动识别（见下文 ZCode-Agent-Kit 的反例） |
| 未做的事 | 没有实际运行任何上游项目；没有把上游代码并进本仓的运行路径 —— 本仓的脚本改动不在本次范围内 |

**引用格式**：本文每个外部项目都带「仓库 URL + commit SHA + license」三件套。
SHA 是 2026-10-20 的 HEAD，可复现。

---

## 2. 候选清单

### 2.1 多供应商 AI 网关 / 统一管理

| 项目 | star | license | 体积 | 最近推送 | 一句话 |
|---|---|---|---|---|---|
| [mozilla-ai/otari](https://github.com/mozilla-ai/otari) | 702 | Apache-2.0 | tarball ≈ 14.1 MiB | 2026-10-20 | 自建 OpenAI 兼容网关：40+ 供应商、虚拟密钥、预算、用量 |
| [hkqr/my-free-code](https://github.com/hkqr/my-free-code) | 624 | MIT | tarball ≈ 0.5 MiB | 2026-10-17 | 给 Claude Code 等用的多供应商网关：**分档路由 + 有序降级 + 限流** |
| [soulvon/AnyBridge](https://github.com/soulvon/AnyBridge) | 57 | MIT | tarball ≈ 11.4 MiB | 2026-10-19 | BYOK 配置工作台：16+ 智能体统一写入，**含 ZCode / WorkBuddy** |

### 2.2 把第三方模型接进 coding agent

| 项目 | star | license | 体积 | 最近推送 | 一句话 |
|---|---|---|---|---|---|
| [musistudio/claude-code-router](https://github.com/musistudio/claude-code-router) | 37767 | MIT | tarball ≈ 20 MiB | 2026-10-10 | 本地控制面：跨模型/跨供应商路由 + 能力目录 |
| [decolua/9router](https://github.com/decolua/9router) | 31119 | MIT | tarball ≈ 5.2 MiB | 2026-10-15 | 免费模型路由器 + 自动降级到免费/便宜模型 |
| [12errh/zen-proxy](https://github.com/12errh/zen-proxy) | 73 | MIT | tarball ≈ 3.2 MiB | 2026-10-19 | **和本仓同一个上游**（opencode.ai）：会话头铸造 + 免费模型目录同步 + 降级链 |

### 2.3 ZCode 生态

| 项目 | star | license | 体积 | 最近推送 | 一句话 |
|---|---|---|---|---|---|
| [zai-org/ZCode](https://github.com/zai-org/ZCode) | 8028 | Apache-2.0 | repo 100 023 KB | 2026-10-20 | 目标客户端本体 |
| [TriDefender/zcode-api](https://github.com/TriDefender/zcode-api) | 457 | **无 LICENSE 文件** | tarball > 30 MiB | 2026-10-20 | 反代到 bigmodel.cn / z.ai |
| [liu5269/zcode2api](https://github.com/liu5269/zcode2api) | 309 | **AGPL-3.0** | — | 2026-06-16 | 反代 ZCode 免费额度 |
| [ZCodium-project/ZCodium](https://github.com/ZCodium-project/ZCodium) | 238 | MIT | repo 109 671 KB | 2026-10-20 | ZCode 的独立审计 fork，**含内置规则源码** |
| [xhwxt/zcode-token-usage-statusbar](https://github.com/xhwxt/zcode-token-usage-statusbar) | 102 | MIT | repo 2459 KB | 2026-10-12 | 只读本地 SQLite 的用量状态栏 |
| [dengyie/zcode2api](https://github.com/dengyie/zcode2api) | 119 | **AGPL-3.0** | tarball ≈ 0.23 MiB | 2026-10-02 | 账号运营 + Anthropic 反代一体机 |
| [techysy/CreditDaddy](https://github.com/techysy/CreditDaddy) | 100 | MIT | tarball ≈ 1.3 MiB | 2026-10-20 | 多账号本地管理 + 每日积分签到（Qoder/WorkBuddy/ZCode） |
| [ZepiGit/ZCode-Agent-Kit](https://github.com/ZepiGit/ZCode-Agent-Kit) | 79 | MIT（见下） | repo 7647 KB | 2026-10-03 | 把 ZCode token 用到别的 harness，附带 `EFFORT_MAPPING.json` |

> ⚠️ **ZCode-Agent-Kit 的 license 是个坑**：GitHub API 判成 `NOASSERTION`，
> 但仓库里的 `LICENSE` 文件是标准 MIT 全文（`Copyright (c) 2026 ZepiGit and
> zcode-agent-kit contributors`）。**以文件为准**，别信 API 的自动识别。

---

## 3. 深读：四个最值得的项目

### 3.1 AnyBridge —— 唯一认真实现了 ZCode 配置写入的开源项目

**是什么**：Tauri（Rust）桌面应用，本地 BYOK 工作台。把渠道（OneAPI/NewAPI/CPA 等）
和模型统一管理，再一键写进 16+ 款智能体的原生配置文件；封闭界面的（Cursor/Windsurf/Devin）
走本地代理接管。

**解决什么**：「换个渠道要挨个翻配置文件」「模型名手输容易错」「Cursor 这类没有自定义
API 入口」。

**与本仓的关系**：**重叠度最高，但层次不同**。
本仓是**脚本 + 文档**（写死目标协议、分档规则、探测流程）；
AnyBridge 是**图形化配置管理器**（渠道池、模型下拉、连通性体检、一键还原）。
本仓做的事 AnyBridge 也做了一遍，而且做得更细 —— AnyBridge 一个 provider 只写**默认模型**，
本仓按成本档/积分倍率把几十个模型铺进多个 provider。

**供应商接入方式**：GUI 里填「渠道地址 + API Key」→ **在线拉取模型列表**（下拉勾选）；
也可以从 Cherry Studio / CC Switch / Cockpit Tools 扫配置导入。
ZCode 的写入路径是 `~/.zcode/v2/config.json`（legacy）+ `~/.zcode/cli/config.json`，
**外加 `~/.zcode/v2/provider_config.json`（个人配置）** —— 和本仓写的是同一个文件。

**模型能力探测**：填完点「测试」，一次性检测**接口连通 / 模型列表 / 流式响应 / 工具调用 /
视觉多模态**五项。是「真实请求一次」的路子，和本仓的 `workbuddy_probe_zcode.py` 同源。

**thinking / reasoning 参数**：这是它最值钱的部分。文件
`sidecar/lib/thinking-effort.js`（248 行）把思考档位处理成一张**协议 → 字段**的映射：

| 目标协议 | 写入请求体的字段 |
|---|---|
| `anthropic` | `thinking: {type: 'adaptive'}` + `output_config: {effort}` |
| `openai` + `/responses` | `reasoning: {effort}` |
| `openai` + `/chat/completions` | `reasoning_effort` |
| 关掉 | anthropic → `thinking: {type: 'disabled'}`；OpenAI → `none` |

两条关键取舍：
1. **只发该协议认的字段**，其余一个都不发；
2. **档位要钳到目标模型族的词表里**（claude 只认 `low|medium|high|max`，
   `xhigh` 就近降为 `high`；GPT 族 `none|minimal|low|medium|high|xhigh`）。

**分档 / 限流 / 降级**：内置「专属解锁」补协议指纹（`anthropic-beta` 头、Thinking 参数），
避免中转站 503/400；429 自动重试、并发控制、长推理超时保护。

**写 ZCode 配置的两条值得抄的做法**（`src-tauri/src/commands/platforms.rs`）：

1. **托管命名空间**：providerId 一律用 `AnyBridge-{hash(vendor|baseURL)}`，
   清理时**只删自己前缀的规则**，别人的 provider 一根汗毛都不动。
2. **只管自己管的字段**：`providerModelRules` 里只写 `contextWindow` 与
   `inputFormat.supportsImage`，**保留用户在 ZCode 界面里手勾的 `supportsVideo` /
   `supportsPdf` / `supportsNativeWebSearch`**。
   它写 `optionSpecs.reasoningLevel` 的语义也跟本仓一致 ——
   注释原文：*「map 由条目字段 reasoningLevelMap 提供：空 = 移除（回落 ZCode 内置 "{}"，即值透传）」*。

**能借鉴什么**：①「按协议发最小思考字段」的映射表（**已落地**，见 §4.1）；
②托管命名空间 + 只写自己管的字段（对应本仓 `workbuddy_zcode_sync.py` 分离模式的
「整条替换四个 provider」写法，是明确的改进方向，见 §6）。

**为什么没有 vendor 它的代码**：仓库 11.4 MiB、Rust + Tauri + 内嵌 `cursor-core` 子项目
（另带 `LICENSE.upstream`），本仓是纯 Python/Node 脚本，**技术栈完全对不上**；
真正有用的只有一张协议映射表和两个写入策略，**抄思路不抄代码**。

- 来源：https://github.com/soulvon/AnyBridge @ `f40dcc23c76f1b641462fb2a5544a252c5738b27` — MIT
- 参考文件：`sidecar/lib/thinking-effort.js`、`src-tauri/src/commands/platforms.rs`

---

### 3.2 zen-proxy —— 和本仓同一个上游（opencode.ai）的另一种解法

**是什么**：零依赖 Node 代理，把 OpenCode Zen 的免费模型给任意 coding agent 用，
对外同时暴露 OpenAI 与 Anthropic 兼容端点，默认 `http://127.0.0.1:8787`。

**解决什么**：免费档只认「来自 OpenCode CLI 自己的请求」，别人直连会拿到
`403 FreeTierError`。

**与本仓的关系**：**上游完全一样**（opencode.ai），但**解法不同**：
本仓是「用合法 API key 直接写进 ZCode 配置」；zen-proxy 是「伪造成 OpenCode CLI 的请求」。
本仓的 `providers/opencode-go/ops/opencode-header-proxy.js` 和它是同一类东西。

**供应商接入方式**：不是配置文件 —— 它**根本不配供应商**，只有一个上游地址
（`OPENCODE` → `https://opencode.ai/inference/v1`），模型清单来自上游 `/models`。

**模型能力探测 —— 它的结论对本仓有直接价值**。`scripts/sync-models.mjs` 的注释写得很清楚：

> 合成探针会被 free tier 用 403 FreeTierError 拒绝，**和「模型已下线」的表现完全一样**，
> 所以探针测不出哪些模型活着；`/models` 目录才是唯一权威来源，而且不需要鉴权。
> 模型健康度不该由这个文件负责 —— 代理从**真实客户端流量**里学，那才是可信的信号。

**thinking / reasoning**：不处理。免费档不暴露思考参数。

**分档 / 限流 / 降级 —— 三条可以直接抄的规则**：

1. **错误分级**：429 / 5xx / 410 / `model_not_found` / `FreeTierError` / `model is unavailable`
   → **走降级链**；400 / 401 这类确定性错误 → **立刻原样报错**，不浪费后面的模型。
2. **先重试再换模型**：每个模型自己先重试 N 次，失败才走到链上下一个。
3. **整链失败时报「客户端要的那个模型」的错误**，不要把链尾的 `410 deprecated` 泄漏给客户端。

另外两个工程细节值得记：
- **会话头要两个一起发**：`x-opencode-session` **和** `x-opencode-session-id` 同值，
  缺一个就 403。
- **会话 id 不是随便的 hex**：上游会把前 12 位 hex 当创建时间戳解，
  时间戳不合理的 id 同样被拒。它的生成器是 `ses_` + 12 位 hex（`~ms*0x1000 + counter`）+ 14 位随机 base62。
- **目录同步有护栏**：上游返回空清单时**拒绝覆盖本地目录**，避免一次网络抖动把清单清空。

**能借鉴什么**：①「错误分级 → 决定是重试还是换模型」；
②「降级链末端的错误要还原成客户端要的那个模型」；
③「目录为准、真实流量为准，探针测不出死活」—— 这直接影响本仓怎么解读探测结果，
见 §6。

**为什么没有 vendor 它的代码**：它是一整个常驻代理服务（2549 行 `zen-proxy.mjs`），
本仓要的是「写配置」不是「再插一个代理」；而且它针对**免费档**，
本仓走的是 **Go 付费套餐**（`/zen/go/v1` + 真实 API key），会话头规则是否相同
**未经验证**（见 §6 待验证项）。

- 来源：https://github.com/12errh/zen-proxy @ `b107e45e4f1b940f9bba6c022fe3ac6254bce72b` — MIT
- 参考文件：`zen-proxy.mjs`、`scripts/sync-models.mjs`

---

### 3.3 my-free-code —— 「分档 + 降级 + 限流」三件套的最小实现

**是什么**：FastAPI 网关，把 Anthropic Messages 协议转成 OpenAI 兼容调用，
对外提供 `/v1/messages`、`/v1/responses`、`/v1/models` 与一个本地 Admin UI。

**解决什么**：Claude Code 想用便宜/免费模型，但各供应商协议不一、限流不一。

**与本仓的关系**：**分档思路可直接对照**。本仓分离模式是把模型静态切成
「免代 / 低代 / 高代 / 备用」四档；统一模式则把它们并入五个 chat 组。它是**动态**的：
一个公共模型名（`provider/model`），路由到按档位配置的具体模型，失败再按顺序降级。

**供应商接入方式**：**环境变量 + 静态供应商目录表**。
`my_free_code/providers/catalog.py` 里是一张 50 行的表：

```python
("opencode_go", "OpenCode Go", "OPENCODE_API_KEY", "https://opencode.ai/zen/v1"),
("openai", "OpenAI", "OPENAI_API_KEY", "https://api.openai.com/v1"),
...
```

key 的**变量名**写在表里，值从环境变量读 —— 这跟本仓 AGENTS.md §2 的纪律同源。
**注意第一行就是 OpenCode Go，和本仓同一个上游。**

**模型能力探测**：不主动探测，靠 `/v1/models` 目录 + 各供应商适配器的运行时反馈。

**thinking / reasoning**：`core/reasoning.py` 极简（16 行）——
把请求里的 `thinking` 字段解析成一个 `ReasoningPolicy(mode=auto|on|off, effort, budget_tokens)`，
再由各适配器决定怎么落回去。另外提供「no-thinking gateway IDs」这种**用模型名表达开关**的技巧。

**分档 / 限流 / 降级 —— 三个可以直接抄的写法**：

| 能力 | 它的实现 |
|---|---|
| 分档 | `MODEL_FABLE` / `MODEL_OPUS` / `MODEL_SONNET` / `MODEL_HAIKU` 四个环境变量；`select_model()` 把客户端报的模型名里的 `opus`/`sonnet`/`haiku` 关键词映射到对应档位 |
| 降级 | `FALLBACK_MODELS` 逗号分隔的有序链；`candidates()` 去重后按序返回 |
| 限流 | `PROVIDER_MAX_CONCURRENCY`（信号量）+ `PROVIDER_RATE_LIMIT` + `PROVIDER_RATE_WINDOW`（滑动窗口计数）三件套，**按供应商分别限** |
| 健康退避 | 某供应商一抛异常就 `unhealthy_until[provider] = now + 2s`，窗口内直接拒 |
| 错误分级 | `RETRYABLE_STATUS = {408,409,425,429,500,502,503,504}` |

**能借鉴什么**：本仓分离模式的「四档」目前是**静态分组**，它给的是「**档位 → 候选序列 → 降级**」的
完整链条模型，能把本仓的静态分档变成「先降级、再换档」。

**为什么没有 vendor 它的代码**：它是 Python，但**依赖 FastAPI + python-dotenv**，
而本仓的纪律是**只用标准库**；且它是一整套网关服务，本仓不需要。抄它的
「档位/降级/限流三元组」这个**模型**即可。

- 来源：https://github.com/hkqr/my-free-code @ `6a88525f70f310f5befc3e4004905faa7251ea17` — MIT
- 参考文件：`my_free_code/config.py`、`my_free_code/core/router.py`、
  `my_free_code/core/failures.py`、`my_free_code/providers/runtime.py`

---

### 3.4 ZCodium —— 让本仓最大的那个坑从「实测」变成「可引用的源码依据」

**是什么**：ZCode 的独立审计 fork（Apache-2.0 → **MIT**），逐提交审阅上游改动、
移除监控与遥测。**含 ZCode 全部源码**。

**解决什么**：给 ZCode 一条「可审计、可自己编译」的路。

**与本仓的关系**：**本仓只读它的源码，不碰它的代码**。
本仓的 `providers/workbuddy/zcode_effective_body.js` 是**复刻** ZCode 引擎的规则解析顺序，
用来算出「某个 modelId 在 ZCode 里实际会发什么请求体」。而 ZCodium 仓库里
**就有那份规则的原文**：`config/provider/zcode-builtin.json`。

**它证实了什么**（本仓 `docs/PITFALLS.md` §2 的结论，逐字对上）：

| 规则 | `apiTypeMatch` | `modelMatch` | 注入的字段 |
|---|---|---|---|
| 第 2 条 | `anthropic-messages` | `.*` | `thinking.type`（adaptive/disabled）+ `output_config.effort` |
| **第 3 条** | `openai-chat-completions` | `.*` | **`thinking` + `enable_thinking` + `reasoning_effort` + `reasoning` 四个一起发** |
| 第 4 条 | `openai-responses` | `.*` | 只发 `reasoning.effort` |

第 3 条的 map 原文（逐字）：

```
{
  "thinking": { "type": reasoningLevel == "disabled" || reasoningLevel == "none" ? "disabled" : "enabled" },
  "enable_thinking": reasoningLevel != "disabled" && reasoningLevel != "none",
  "reasoning_effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel,
  "reasoning": { "effort": reasoningLevel == "disabled" ? "none" : reasoningLevel == "enabled" ? "high" : reasoningLevel }
}
```

**这正是本仓踩的坑**：通用规则**不检查模型是否支持**，四个字段一起甩给上游，
上游不认其中任何一个就 400。第 3 条是「通用规则」、第 67 条
（`.*deepseek-v4[.-]1-flash.*`）是「专属规则」—— 后者覆盖前者，这跟本仓
`docs/PITFALLS.md` §4「规则按序叠加、后者胜」的结论一致。

**另外两个交叉验证**：
- ZCodium 里 `anthropic-messages` + `ox-alpha|glm-x-preview-f|x-preview-f-free` 的专属规则
  声明 `values: ["low","high","max"]`；
  [ZepiGit/ZCode-Agent-Kit](https://github.com/ZepiGit/ZCode-Agent-Kit) 的
  `EFFORT_MAPPING.json` 也写 `glm-5.3: efforts ["low","high","max"]` —— **两个独立项目对同一档位的描述一致**。
- **与 ZCode 本体逐字一致**：把
  [zai-org/ZCode](https://github.com/zai-org/ZCode) @ `3c5b227649371507ddc4eb46ac5133afe6db1cab`
  的 `config/provider/zcode-builtin.json`（`revision: 33`，73 条 `modelApiRules`）与
  ZCodium 的（`revision: 32`，72 条）逐条比对，**上面这三条通用规则的 map 表达式三处全部逐字相同**。
  也就是说：**这份切片不只对上 fork，对上游客户端本体同样成立。**

**能借鉴什么**：把「ZCode 内置通用思考规则」的原文**抄一份最小切片**进本仓当依据，
以后 ZCode 客户端升级、规则变了，**一条命令就能发现**（见 §4.2）。

**为什么没有 vendor 它的代码**：仓库 100+ MB，是**整个客户端**（含 Electron 应用、
Android 模拟器插件、几十个 package）。本仓只需要那份 2.5 KB 的规则切片 ——
**只抄切片，不抄仓库**。

- 来源：https://github.com/ZCodium-project/ZCodium @ `192f9b8c7b7b61c694920203f1b5c7524bdc7d09` — MIT
- 参考文件：`config/provider/zcode-builtin.json`（`schemaVersion: 1`，`revision: 32`）

---

### 3.5 claude-code-router 与 otari —— 读到了「能力目录」的思路

**claude-code-router**（MIT，37 767★，最新版本已是 `packages/core` 单体仓架构）：
它是「一个本地控制面管所有 agent」的代表作。跟我们相关的是它的**能力目录**：
`packages/core/src/gateway/model-catalog.ts` 里的 `readCatalogCapability()` 与
`modelCatalogReasoningEffortConfig()` —— 从上游目录的 metadata 里读出
「支不支持推理」「支持哪些 effort 档」「默认档位是什么」，再据此决定发什么。

> **和本仓的关系**：本仓的「哪些模型支持思考、支持哪几档」目前来自
> **WorkBuddy 网关的 `supportedEfforts`**（`providers/workbuddy/cache/wb_pricing.json`）。
> CCR 的做法是**从上游目录读**，而不是从网关面板读 —— 值得对照，但本仓的网关侧没有目录接口，
> 暂时改不了。

**otari**（Apache-2.0，702★）：自建 OpenAI 兼容网关，40+ 供应商、**虚拟密钥**、
**预算硬上限**、用量追踪。跟本仓的重叠很小（本仓不做网关），但它的
「虚拟密钥 + 预算」思路对应本仓的**分档配额**问题：将来若要给别人共用网关，
本仓的「按积分倍率分档」可以升级成「按 key 限预算」。

- 来源：https://github.com/musistudio/claude-code-router @ `057abaa1f95519ab8faf999e1ccef2b80ccdeb9e` — MIT
- 来源：https://github.com/mozilla-ai/otari @ `ba9498fcdf9686a58017f5b77d38b5f28a10443b` — Apache-2.0

---

## 4. 借鉴落地：进本仓的两件东西

两件都在 [../third-party/zcodium/](../third-party/zcodium/)，都是**自写的落地件**
（一件逐字切片 + 一件自写实现），只借鉴思路与必要的表达式。

### 4.1 按协议发「最小且正确」的思考字段

**问题**：本仓现在的做法是给不支持思考的模型配 `optionSpecs.reasoningLevel.map = "{}"`，
**一个思考字段都不发**。这能躲开 400，但也让模型**退到上游默认档**，
而不是本仓想给的档位。AnyBridge 的做法更细：**该协议认哪个字段就只发哪个**。

**落地**：[../third-party/zcodium/reasoning-rules.js](../third-party/zcodium/reasoning-rules.js)

```bash
# 协议认哪个字段就发哪个
node third-party/zcodium/reasoning-rules.js map --api-type=openai-chat-completions --effort=high
# => {"reasoning_effort":"high"}

node third-party/zcodium/reasoning-rules.js map --api-type=anthropic-messages --effort=high
# => {"thinking":{"type":"enabled"},"output_config":{"effort":"high"}}

# 档位超纲 → 钳到模型词表内（借鉴 AnyBridge 的 clampEffortLevel）
node third-party/zcodium/reasoning-rules.js map --api-type=openai-responses --effort=xhigh --supported-efforts=low,high,max
# => {"reasoning":{"effort":"high"}}

# 不支持思考 / 未知协议 → 空 map
node third-party/zcodium/reasoning-rules.js map --api-type=openai-chat-completions --effort=high --supports-thinking=false
# => {}
```

它与 ZCode 内置规则的对齐关系（`third-party/zcodium/reasoning-rules.js` 里的 `PROTOCOL_FIELDS`）：
`openai-chat-completions` → `reasoning_effort`；`openai-responses` → `reasoning.effort`；
`anthropic-messages` → `thinking` + `output_config`。
**这正是 ZCodium 内置规则里三条通用规则各自发的字段**，所以本仓产出的 map
与 ZCode 自带的那一套**字段口径一致**，只是**少发了上游不认的那几个**。

### 4.2 内置规则从「实测」变成「可 diff 的源码依据」

**问题**：本仓 `docs/PITFALLS.md` §2 关于「ZCode 内置规则无条件发思考字段」的结论，
此前只能靠**实测反推**。ZCodium 提供了这份规则的 MIT 原文，可以直接抄一小片当依据。

**落地**：
- [../third-party/zcodium/zcode-builtin-reasoning-rules.json](../third-party/zcodium/zcode-builtin-reasoning-rules.json)
  —— 从 ZCodium 的 `config/provider/zcode-builtin.json` **逐字抄录**的 4 条规则
  （3 条通用 + 1 条 `deepseek-v4[.-]1-flash` 专属规则示例），文件里带 `_source`
  字段写明来源 URL / SHA / license，另带 `_cross_check` 字段记录与
  `zai-org/ZCode` 本体（revision 33）的逐字一致结论。
- `third-party/zcodium/reasoning-rules.js` 的 `check` 子命令 —— 把**本机** ZCode 的内置规则文件
  与这份切片逐条比对，报漂移：

```bash
node third-party/zcodium/reasoning-rules.js check                       # 读环境变量 ZCODE_BUILTIN
node third-party/zcodium/reasoning-rules.js check /path/to/zcode-builtin.json
```

> **实测**：拿 `zai-org/ZCode` 本体的 `config/provider/zcode-builtin.json`
> （revision 33）跑这个检查，**结果一致，退出码 0**。

退出码 0 = 一致，1 = 有漂移（并提示「思考参数矩阵需要重测」）。

> **用法边界**：这是**发现漂移**的工具，不是**自动修复**的工具。
> 真有漂移时，正确做法是重新探测并更新
> [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §5 的参数矩阵，不是自动改配置。

---

## 5. 没有 vendor 它们代码的理由（汇总）

| 项目 | 不 vendor 的理由 |
|---|---|
| AnyBridge | 技术栈对不上（Rust + Tauri + 内嵌 `cursor-core`），且它是**图形化配置管理器**，本仓是脚本工具。有用的只有一张协议映射表和两个写入策略 |
| zen-proxy | 是常驻代理服务（2549 行），本仓要的是「写配置」；且它针对免费档，本仓走付费 Go 套餐，会话头规则**未经本仓实测** |
| my-free-code | 依赖 FastAPI + python-dotenv，本仓**只用标准库**；且它是网关服务 |
| claude-code-router | tarball 20 MiB 的单体仓；本仓只用到「能力目录」这个思路 |
| otari | 本仓不做网关；「虚拟密钥 + 预算」是**将来**的方向，现在抄过来是死代码 |
| ZCodium | 100+ MB 的整个客户端；**只抄了 2.5 KB 的规则切片** |
| ZCode-Agent-Kit | 有 `EFFORT_MAPPING.json` 这个有用的小文件，但它是给别的 harness 用的；本仓的档位来自网关面板，**数据源不同**，抄过来会造成两份会漂移的真相 |
| zcode-token-usage-statusbar | 读 ZCode 本地 SQLite，跟本仓「配置写入」这条线不相干 |
| CreditDaddy | 账号运营 + 签到，跟本仓「模型接入」这条线不相干 |
| **zcode-api** | **仓库里没有 LICENSE 文件** —— 默认「保留所有权利」，**不可复制、不可 vendor** |
| **zcode2api（两家）** | **AGPL-3.0** —— 强 copyleft。抄进 MIT 仓库会传染，**只读不抄** |

> **随仓分发的上游文件共三处**，都在 [../third-party/](../third-party/README.md)，
> 每个子目录一份 `UPSTREAM.md` 写清来源 URL、钉住的 SHA 与 license：
> 1. `third-party/zcodium/zcode-builtin-reasoning-rules.json` —— ZCodium 的规则切片（MIT），**逐字**；
> 2. `third-party/zcodium/reasoning-rules.js` —— **本仓自己写的实现**，只借鉴 AnyBridge 的
>    「协议 → 字段」映射思路与 ZCodium 的表达式写法，代码是新的；
> 3. `third-party/zcode/` 下的 4 个原样文件（`zcode-builtin.json`、`model-config.ts`、
>    `schema.ts`、`rule-data-schema.ts`，**一个字节未改**，Apache-2.0）——
>    让探测复刻 ZCode 的请求体语义时不依赖本机是否装了 ZCode。
>
> 许可兼容性与逐项声明见 [../NOTICE](../NOTICE) 与
> [../third-party/README.md](../third-party/README.md)。

---

## 6. 待验证 / 待补

| 项 | 状态 | 说明 |
|---|---|---|
| Go 套餐是否也要求 `x-opencode-session-id` | **待验证** | zen-proxy 说免费档要**两个头一起发**且 id 前 12 位 hex 要像时间戳。本仓的 `opencode-header-proxy.js` 只发一个头、用固定字符串兜底。付费 Go 套餐是否同样要求**未实测** —— 需拿真实 key 打一次 `/zen/go/v1` 比对 |
| WorkBuddy 网关是否吞掉多余的思考字段 | **待验证** | 本仓 PITFALLS §2 说网关只重写 `reasoning_effort`、其余原样透传。AnyBridge 的做法（只发该协议的字段）能绕开这个问题，但**网关侧的实际行为需再确认** |
| `workbuddy_zcode_sync.py` 是否改成「托管命名空间 + 只写自己管的字段」 | **待落地** | 借鉴 AnyBridge §3.1：分离模式下脚本是**整条替换**四个 provider，用户手加的模型会被冲掉。改成按 providerId 前缀 upsert + 只写 `contextWindow` / `inputFormat.supportsImage` 后可保留用户在 ZCode 界面里的其它勾选 |
| 静态分档是否要升级成「有序降级链」 | **待落地** | 借鉴 my-free-code §3.3 与 zen-proxy §3.2：档位 → 候选序列 → 逐个降级；并按错误分级决定「重试」还是「换模型」 |
| 探测结果该不该再解读一次 | **待落地** | 借鉴 zen-proxy §3.2：合成探针与「模型已下线」在上游侧表现相同。本仓的探测用 ZCode 真实 body，**比裸 body 强**，但仍不等于真实业务流量 —— 结论应区分「目录里没有」与「探针没探通」 |
| CCR / otari 的能力目录读法 | **待补** | 本仓的思考档位来自 WorkBuddy 面板；CCR 是从上游目录 metadata 读。本仓的网关没有目录接口，暂不可用 |
| `docs/README.md` 索引未收录本篇 | **已补** | 索引已收录（分类：参考资料），见 [README.md](README.md) |

---

## 7. 相关文档

- [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) —— provider 分组 / 协议 / 关思考参数矩阵正本
- [PITFALLS.md](PITFALLS.md) —— 「ZCode 内置通用规则无条件发思考字段」的机制解释（§2）与规则叠加语义（§4）
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) —— 现象 → 排查步骤
- [../README.md](../README.md) —— 门面（这是什么 / 环境要求 / 使用 / 反馈 / 免责声明 / 开源鸣谢 / 许可证）
- [../NOTICE](../NOTICE) —— 第三方声明与借鉴来源
