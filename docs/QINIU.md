# 七牛云 AI 网关（api.qnaigc.com）

> **一句话**：七牛云的 AI 推理网关只提供 Anthropic Messages 端点，经 `zgate` 的
> `QN` 渠道 + 协议桥接入；目前收了 2 个**限时免费到 2026-11-30** 的模型
> （`Conatus` / `Kimi-K3`），过期后 `model_alias.py` 自动剔除，不需要人回来改配置。

---

## 1. 接入事实

| 项 | 值 |
|---|---|
| 上游 | `https://api.qnaigc.com/v1`（Anthropic Messages，`/messages`） |
| 渠道代号 | `QN` |
| 认证 | `x-api-key`（`anthropic-version: 2023-06-01`） |
| 凭据位置 | 环境变量 **`QINIU_API_KEY`**，或 `providers/qiniu/.env.local`（gitignored） |
| 现状 | 2 个模型，都在免费组：`qiniu/conatus-free` → **`Conatus`**，`moonshotai/kimi-k3-free` → **`Kimi-K3`**（显示名只留原名，不带 `-Free`） |
| 免费期 | **2026-11-30** 截止（`model_alias.py` 的 `QN_FREE_UNTIL`） |

为什么按「免费」记账：这段是**限时免费**，边际单价 0。注意 `price_of` 只对 id 以
`-free` 结尾的模型返 0；其它七牛模型没有仓库侧价格源，会因缺价被剔除。到期后
同样返回 `None`，该跳被自动剔除 —— 与千问的预付额度是同一套机制，只是窗口不同。

---

## 2. 它背后是什么模型

**官方口径：Conatus 是多种模型的集合体（聚合/路由类产品），没有单一作者。**

所以「让它自我介绍」得到的答案没有参考价值 —— 实测它回「我是
deepseek-v4.1-flash」，同目录里也确有 `deepseek/deepseek-v4.1-flash` 这条独立模型，
但那是它复读了语料，不是它的作者。口径见 [PITFALLS.md](PITFALLS.md) §31。

实操上把它当成「一个能力还行、但身份不透明的免费聚合端点」：值不值得用只看实测
（速度、稳定性、长文质量），不要去追「它是谁的模型」。它还有明显的频率限制，
连续追问会直接 429，这也是探身份容易失败的原因之一。

**稳定性**：实测它会**间歇性僵死** —— 接受连接后一个字节都不发，一直挂到网关超时。
网关侧用 30 秒空闲看门狗兜住（返回 `504`），并把该跳冷却 5 分钟，
所以最坏情况是「30 秒失败一次」，不会再出现两分钟无响应。

已知实测：

| 项 | 观测值 |
|---|---|
| 首字/整段（`max_tokens=32`，经 7871） | 约 3.1 s |
| 上下文 | 1,000,000（`/v1/models` 元数据） |
| 单次最大输出 | 128,000 |
| 思考块 | 有（`content[].type == "thinking"`） |

---

## 3. 同网关里其它免费模型（未收录）

`GET https://api.qnaigc.com/v1/models` 里名字带 `-free` 的共 4 个，实测：

| 模型 | 结果 | 说明 |
|---|---|---|
| `qiniu/conatus-free` | ✅ 200 | 已收录 |
| `moonshotai/kimi-k3-free` | ✅ 200，首字约 0.5 s | 1M 上下文；**已收录**（显示名 `Kimi-K3`，免费组） |
| `nvidia/nemotron-3-ultra-550b-a55b0-free` | ❌ 502 暂时不可用 | 上游偶发，可重试 |
| `z-ai/glm-4.5-air-free` | ❌ 已于 2026-06-25 退役 | 别收 |

只收这两个：免费组刻意保持精简（见 [MODEL-ALIAS.md](MODEL-ALIAS.md) §4），
多收一个就多一份「点进去报错」的概率；两个都在限免期内实测 200。

---

## 4. 怎么加/删模型

种子写在 `provider_config.json` 的 `opencode-go-chat-free` 里，带 `qn:` 前缀：

```
qn:qiniu/conatus-free
qn:moonshotai/kimi-k3-free
```

改了之后归一化：

```bash
python tools/model_alias.py --slot auto --apply
python tools/model_alias.py --check          # 要显示「无漂移」
```

删的时候注意：`model_alias.py --apply` 会用显示名整份重写 `providerRules`，
`qn:` 种子本身会被清掉，条目靠 alias map 的 chain 延续（与千问尾跳同一机制）。
alias map 被删重建时，种子要重新写回去。

---

## 5. 与千问的区别（别搞混）

| | 千问 `QW` | 七牛 `QN` |
|---|---|---|
| 端点数 | 只有 Messages | 只有 Messages |
| 免费性质 | 每模型 1M 试用 + ¥300 一年期预付 | 限时免费（到 2026-11-30） |
| 记账 | 0（`QW_CREDIT_UNTIL`） | 0（`QN_FREE_UNTIL`） |
| 收录策略 | 只留主力链尾跳，集合体已下线 | 只留 2 个限免模型进免费组 |

---

## 6. 相关

- 分组规则与名单：[MODEL-ALIAS.md](MODEL-ALIAS.md) §4
- 凭据位置：[SECRETS.md](SECRETS.md)
- 千问（同协议的另一家）：[QWEN.md](QWEN.md)
