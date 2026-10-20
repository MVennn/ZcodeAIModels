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
   `workbuddy/workbuddy_probe_zcode.py` 就是干这个的（先算真实 body，失败再退
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

**解法**：写规则一律用 `.*` 头尾包；改完用 `workbuddy/zcode_effective_body.js`
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

**现象（未来）**：仓库上传到公开 GitLab，**API key 一起公开了**。

**现状**：`opencode-go/probe/` 下的 `probe_models.py`、`probe_protocols.py`、
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

**历史实例**：`opencode-go/ops/go_model_sync.py` 的 `REPORT_DIR` 原先指着拆仓前的旧仓库目录，
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
