# 千问 AI 平台（qianwenai / maas）

> **一句话**：千问平台是**只提供 Anthropic Messages 协议**的直连上游，经 `zgate`
> 协议桥接入免费组；免费额度是「每模型 1M tokens、2026-12-15 到期、用完即停」的试用池，
> 由**四道漏斗**从 506 条额度里筛出 14 个真能用的模型，全部按 0 积分进免费组。
>
> **状态：已接入（2026-10-28）。** 本篇是接入正本；通用方法见
> [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0，命名与链路规则见 [MODEL-ALIAS.md](MODEL-ALIAS.md)。

---

## 1. 现状

| 项 | 值 |
|---|---|
| 控制台 | `platform.qianwenai.com/home/benefits`（免费额度页） |
| 网关 | `https://maas.qianwenaiapi.com/apps/anthropic`（**只有 Messages**） |
| zgate 渠道 | `QW`（远程，无本地进程） |
| 协议 | `anthropic-messages` → 由 zgate 协议桥把 chat 请求转成 Messages |
| 凭据 | `QWEN_API_KEY`（`providers/qwen/.env.local`，gitignored） |
| 额度 | 两段：① 每模型 1M tokens 试用池，**2026-12-15** 到期；② ¥300 学生预付额度，**一年有效、到期作废** |
| 「免费额度用尽即停」 | **已开启**（全部 506 个模型） |
| 账单 | ¥0.00 |
| 已收录 | **只保留 `deepseek-v4.1-flash` 一条跳**，并进主力链路尾跳（¥300 预付额度）。集合体与其它单型号 2026-10-29 全部下线 |

已收录（显示名 → 上游 id）：

| 显示名 | 上游 id | 探测延迟 |
|---|---|---:|
| `Qwen-Max` | `qwen-max` | 1.9s |
| `Qwen-Plus` | `qwen-plus` | 0.9s |
| `Qwen-Flash` | `qwen-flash` | 0.3s |
| `Qwen-3-Coder-Flash` | `qwen3-coder-flash` | 0.4s |
| `Qwen-3-VL-Plus` | `qwen3-vl-plus` | 1.1s |
| `Qwen-3.7-Max` | `qwen3.7-max` | 5.3s |
| `Qwen-3.7-Plus-Free` | `qwen3.7-plus` | 4.9s |
| `Qwen-3.8-Max-Msg` | `qwen3.8-max` | 1.7s |
| `Qwen-3.8-Flash-Free` | `qwen3.8-flash` | 0.9s |
| `DeepSeek-4.1-Flash-Msg` | `deepseek-v4.1-flash` | 0.7s |
| `DeepSeek-4-Pro-Msg` | `deepseek-v4-pro` | 2.1s |
| `GLM-5.3-Msg` | `glm-5.3` | 1.7s |
| `Kimi-K3` | `kimi-k3` | 2.4s |
| `MiniMax-M2.5` | `MiniMax-M2.5` | 3.4s |

> 延迟是 `max_tokens=32` 的一次探测耗时。桥接是**非流式上游**（见 §7.1），
> 真实长回答的首字 ≈ 整段生成时间。

---

## 2. 平台事实（2026-10-28 实测）

### 2.1 端点与协议

| 路径 | 结果 |
|---|---|
| `POST /apps/anthropic/v1/messages` | **200**，`x-api-key` + `anthropic-version: 2023-06-01` |
| `GET /apps/anthropic/v1/models` | 404 `{"code":"InvalidParameter","message":"Not support"}` |
| `POST /apps/openai/v1/chat/completions` | 404（**没有 OpenAI 兼容层**） |
| `GET /api/models?page_no=…`（maas 主机） | 偶然 200（`total=371`），多数时候 404，**不稳定** |

结论：**只能走 Messages 桥**，目录只能靠控制台导出（脚本里的 `cache/freetier_*.txt`）。

### 2.2 错误形态（决定链路能否回落）

| 情况 | 返回 |
|---|---|
| 模型 id 不存在 | **400** `InvalidParameter: Model not exist.` |
| 路径不支持 | 404 `InvalidParameter: Not support` |
| 正常 | 200，`content` 里带 `thinking` 块 |

注意：控制器比服务端宽 —— 控制台**列出**的模型不等于 API **能调**（§4.4 的三个反例）。

### 2.3 免费额度的真实口径

抓自「权益 → 模型调用额度」页：

| 指标 | 数量 |
|---|---:|
| 免费额度条目总数 | **506** |
| 其中按 token 计量 | **294** |
| 再筛掉非对话用途（图/视频/TTS/ASR/向量/重排/OCR） | **209** |
| 按家族去快照版本（`-2026-05-17`、`-0902`、`-latest`） | **118** |
| **本次收录** | **14** |

- 每个模型独立 1M tokens（个别 100K / 10M），**不跨模型合并**；
- 统一到期 **2026-12-15**，过期不补发；
- 主账号与 RAM 子账号共用额度；
- 「用完即停」关闭时超额会走付费（当前余额 ¥0.00，会直接失败）；
  开启时到点就停 —— **不会产生费用，但那条请求就废了**。

> 全部 506 个都用满 ≈ 5 亿 tokens，但其中绝大多数与 ZCode 无关。
> 真正的可用面是 §4 筛出来的那十几个。

---

## 3. 为什么按 0 积分定价

`model_alias.py` 里 `QW_CREDIT_UNTIL = "2027-10-28"`：窗口内 `price_of("QW", …) = 0.0`，
窗口外返回 `None` → 该跳缺价、被自动剔除。

为什么按一年算而不是按 12-15：¥300 是**预付额度**，边际单价就是 0，用完为止、
到期作废。所以整段窗口内按 0 记账是对的；真烧光时上游回
`403 AccessDenied / Free quota exhausted`，路由把它判成死跳并冷却，
不需要有人回来改配置（2026-10-28 实测到这条错误）。

- **不用手工回来删配置**：过期当天重跑一次 `--apply`，千问的跳自然消失；
- 不用把「限免到期仍显示 0」的老毛病再犯一遍（详见 [MODEL-ALIAS.md](MODEL-ALIAS.md) §3.1）；
- 代价：14 条全在免费组，与 `Beam` / `HY3-Free` 等并列（§5）。

---

## 4. 怎么从 506 条里整理（漏斗）

### 4.1 四道漏斗

| 层 | 规则 | 剩下的 |
|---|---|---:|
| 0 | 抓全量额度页（含每模型已消耗 / 到期 / 开关） | 506 |
| 1 | **计量单位 = tokens**：砍掉 images / seconds / chars / 张 / units | 294 |
| 2 | **对话能力**：砍掉 embedding、rerank、asr、tts、ocr、omni-realtime、image、video（wan/wanx）、wordart、sambert、cosyvoice 等 | 209 |
| 3 | **去快照**：`-YYYY-MM-DD` / `-MMDD` / `-latest` / `-preview` 归并到家族，每家族留主 id | 118 |
| 4 | **人工收口**：只留旗舰 + 每厂商代表 + 一个多模态 | 18 |
| 5 | **真实体探测**：经 7871 用 ZCode 真实 body 打一遍，`Model not exist.` 即删 | **14** |

第 4 层不是必需，但**第 5 层是** —— 控制台列出的模型有 3 个 API 里根本没有（§4.4）。

### 4.2 命名与分组怎么落

- `qwen:<id>` 前缀播种 → `model_alias.py` 归一化成型号名；
- 同型号已有 chat 条目时，桥接那条自动加 **`-Msg`**（如 `GLM-5.3` 是 Qoder 聊天，
  `GLM-5.3-Msg` 是千问桥接）；同一型号既有免费又有付费跳时，免费那条加 **`-Free`**；
- 全部 0 积分 → 落在 **免费** 组。

### 4.3 剩下 104 个家族怎么办

**不建议塞进 ZCode。** 免费组塞 100+ 条目，选择器就没法用了，而且每一条都要过桥。
如果目的是「把额度烧掉」，用 `--all-chat` 收齐后跑批处理，或直接按
`cache/freetier_*.txt` 写个一次性脚本；用完一次就清掉，不要长驻配置。

### 4.5 集合体（池子）——2026-10-29 已停用

> **为什么下线**：千问每模型只有 1M 免费 tokens。实测用量 4 天 74.6 亿（约 18.6 亿/天），
> 一个模型的额度 **30 秒**就烧完；114 个模型全加起来也只值约 1.5 小时，而当时只有 30 个
> 存活（约 23 分钟）。维持池子要每天探测 114 个上游 + 重建跳序，且单跳额度耗尽后是
> **硬 403 `auth failed`**（没有下一跳可退），用户点一下就报错。
> **收益 23 分钟 vs 每天维护 + 持续报错，不划算。**
>
> 保留的唯一千问用法是主力链尾跳：它零维护（额度没了路由自动冷却跳过），
> 只在 WB / OC 同时不可用时才轮到，正好把一年期 ¥300 当兜底烧掉。
>
> 下层内容保留为历史记录，`POOL_SPECS` 已清空，`--write-pools` 产出空池子。

#### 历史：原来的池子设计：把剩下的模型编成 3 条长链路

剩下 100 多个家族不值得单独占一个显示名，编成 **2 个集合体**：每个显示名背后是一条
按顺序试的长链路，路由从第一跳开始用，这一跳没额度了就自动换下一跳 —— 也就是
「一个一个往上烧」。

| 集合体 | 跳数 | 池内前几跳 | 编入规则 |
|---|---:|---|---|
| `Qwen-Pool-Max` 旗舰池 | 23 | qwen3.8-max → deepseek-v4-pro → glm-5.3 → kimi-k3 → … | 档位 ≥2.8 且非开源权重版；**代码模型（`coder`/`-code`）也编进来**（2026-10-29 起三池合两池） |
| `Qwen-Pool-Fast` 快速池 | 91 | qwen3.8-2.4t-a95b → deepseek-r1 → glm-5.1 → … | 其余全部，按档位降序 |

- **排序口径**：先按「档位（max/pro > coder/plus > flash/turbo > air > 其余）→ 版本号 →
  名字长度」降序，再按厂商（Qwen → DeepSeek → GLM → Kimi → MiniMax → QwQ → QvQ）
  **轮转打散**，保证相邻两跳不同公司 —— 一家整体挂了，下一跳就换家。
- 这是**排序启发式，不是跑分**。想改顺序就直接改 `providers/qwen/pools.json` 里
  `hops` 数组的顺序；想改编入规则就改 `qwen_zcode_sync.py` 的 `tier_of()` 再
  `--write-pools` 重生成。
- 池子会**包含已知调不通的 id**（如 `qwen3-max`）：路由撞到一次就把它冷却，之后跳过。

生成与关闭：

```bash
python providers/qwen/qwen_zcode_sync.py --write-pools   # 重算 pools.json
python tools/model_alias.py --slot auto --apply          # 池子进免费组
python tools/model_alias.py --no-pools --apply           # 只要单型号，不要池子
```

### 4.6 死跳自动跳过（冷却）

池子里每一跳都可能随时变成「不能用」：模型 id 不存在、1M 额度烧完、欠费。这些响应
与请求本身无关，所以：

- `zgate` 把 **400 带 `Model not exist` / `model_unavailable` / `Arrearage` /
  `AllocationQuota` / `FreeTierOnly`** 和 **402** 判为「这跳作废」，立刻换下一跳；
- 同时把该跳放进**冷却表**（30 分钟），期间请求**直接跳过**，不再付那一次失败往返。
  `/health` 的 `cooling` 字段是当前冷却中的跳数。
- 冷却只在内存里：**重启 zgate 会清零**，重启后第一轮请求会重新撞一遍死跳。
- 冷却表与额度窗口无联动 —— 30 分钟后会再试一次，如果还是没额度就再冷却 30 分钟。

> 没有冷却时，烧过 20 个模型之后每个请求都要先撞 20 次 400（实测每次约 200ms），
> 一次正常对话要多花 4 秒。这是池子能不能用的分水岭。

### 4.6.1 免费 DeepSeek 并进主力（2026-10-28）

`DeepSeek-4.1-Flash` 现在是**一条三跳的链**，不是两个显示名：

```
DeepSeek-4.1-Flash
  1. WB  cn:deepseek-v4.1-flash   chat      0.11   ← 日常先用它（月度额度，用不完就浪费）
  2. OC  deepseek-v4.1-flash      chat      0.11   ← WB 挂了 / 限流时
  3. QW  deepseek-v4.1-flash      messages  0.00   ← ¥300 预付额度，兜底
```

- 第 3 跳排在**链尾**而不是按价格排第一：`TAIL_HOPS` 显式指定。因为 OC 的额度
  每月重置（不用就浪费），而 ¥300 是一年期，所以顺序是「先把 OC 用完，再动 300」。
- 链里**允许混协议**：路由按每跳自己的 `protocol` 派发，chat 跳直转、messages 跳过桥。
  这是 2026-10-28 新加的能力，之前一条链只能是同一种协议。
- 代价：第 3 跳是**非流式桥接**，真轮到它时首字会等整段生成。只在兜底时发生。

### 4.7 控制台列了但 API 调不通的三个

| id | 结果 |
|---|---|
| `qwen3-max` | 400 `Model not exist.`（`qwen-max` 才能调） |
| `qwen3-coder-plus` | 400 `Model not exist.` |
| `qwq-plus` | 400 `Model not exist.`（`qwq-32b` 也不行） |

判据是「有额度」不等于「可调用」。这三个已经从 `DEFAULT_MODELS` 删掉，
`--probe-file` 也会再拦一次。

---

## 5. 改动清单（已落地）

### 5.1 新增

| 文件 | 作用 |
|---|---|
| `providers/qwen/.env.local` | `QWEN_API_KEY` / `QWEN_BASE`（gitignored，唯一持久落点） |
| `providers/qwen/qwen_zcode_sync.py` | 目录 → `qwen:` 前缀播种进免费组；`--only` / `--all-chat` / `--probe-file` |
| `providers/qwen/cache/freetier_20261028.txt` | 118 个家族的控制台快照（`family <= id,id`），漏斗的输入 |

### 5.2 改

| 文件 | 改动 |
|---|---|
| `gateways/zgate/zgate.json` | `upstreams.QW` + `qwenEnvFile` |
| `internal/config/config.go` | `QwenEnvFile` 字段与默认值、`Upstreams["QW"]` 兜底 |
| `internal/keys/keys.go` | `Set.QW`：`QWEN_API_KEY` → `.env.local` → provider_config（base 含 `qianwenaiapi`） |
| `internal/router/router.go` | `/health` 加 `qwen`；`qwen:` 前缀兜底走桥（播种后、归一化前的窗口期）；非 chat 请求拒绝 |
| `internal/../main.go` | `keys.Load` 多一个参数；启动/状态日志加 `QW` |
| `tools/model_alias.py` | `QW_BASE`、`QW_TRIAL_UNTIL`、`price_of` 的 QW 分支、`classify` 的 `qwen:` 分支且**协议钉死 messages**、`CHANNEL_BASE`、`base_of()` 替换 1098 行的硬编码三渠道、桥接条目让出原型名 |

### 5.3 一个必须记住的副作用

`model_alias.py --apply` 会**整份替换** `providerRules`，所以手工加的 `new-provider`
（ZCode 里指 `maas.qianwenaiapi.com/apps/anthropic` 的那个）已经在第一次归一化时被删掉。
千问现在只以 `QW` 渠道的形式出现在分组里 —— 这是设计，不是事故。

---

## 6. 日常操作

```bash
# 播种（只在换清单/换 key 时跑；日常不用跑）
python providers/qwen/qwen_zcode_sync.py                 # dry run
python providers/qwen/qwen_zcode_sync.py --apply

# 归一化成三组（每天 12:00 的定时任务里已有这一步，会保留 QW 跳）
python tools/model_alias.py --slot auto --apply

# 定向探测
python tools/model_probe.py --only Qwen-Max,Qwen-Flash,GLM-5.3-Msg

# 漂移自检
python tools/model_alias.py --check
```

- 千问**不需要**每天同步：链路写在 alias map 的 `chain` 里，`model_alias` 幂等保留；
  只有目录或 key 变化时才需要重跑 sync。
- 探测经 7871，走的就是 ZCode 的真实路径。
- 重开控制台页面后想更新快照：把「权益」页的模型清单按
  `family <= id,id` 写进 `providers/qwen/cache/freetier_<日期>.txt`，
  或试 `--fetch`（`/api/models` 不稳定，失败会回落本地快照）。

---

## 7. 边界与风险

### 7.1 桥接不是真流式（结构性问题）

`gateways/zgate` 的桥用**非流式**请求上游，再把整段结果合成 chat SSE。所以：

- 首字 ≈ 整段生成时间（探测量级 0.3–5s，长回答会更久，思考模型尤其明显）；
- 千问**不提供** OpenAI 聊天端点，绕不开这个桥；
- 结论：**适合当免费备选 / 批处理，不适合当日常主力**。

### 7.1.1 免费额度烧完 = 403，不是 429

2026-10-28 实测：`deepseek-v4.1-flash` 的 1M 试用池用尽后，上游返回

```
HTTP 403  event:error
data:{"code":"AccessDenied","message":"Free quota exhausted. To continue accessing the model
on a paid basis, please add funds or disable the \"use free tier only\" mode ..."}
```

- 这是「用完即停」开着时的形态：**不会自动扣 ¥300**。要用那 300 块，必须去控制台
  把该模型的「免费额度用尽即停」关掉。
- 路由把这种 403 判成**死跳**（`hopFatal` 只认带配额字样的 403，普通 401/403 鉴权错误
  不受影响），冷却 30 分钟后才重试。
- 也就是说：额度烧光后这条跳会安静地失效，主力照常走 WB/OC，不会每轮都撞一次。

### 7.2 思考关不掉

协议桥只转发 `model/max_tokens/messages/system/tools/temperature/top_p/stop_sequences`，
**不转发任何思考字段**。所有这些模型因此始终按上游默认思考（探测响应里 100% 带
`thinking` 块，正文可能为空、`finish_reason=length`）。

后果：小 `max_tokens` 时正文可能被思考吃光；`optionSpecs.reasoningLevel.map = "{}"`
（`model_alias.py` 对非 chat 协议自动写入）在这里是**必需的**，不是可选项。

### 7.3 额度耗尽 = 那条请求直接失败

「用完即停」已开，1M 用完之后该模型返回 4xx，而不是降级：

- 这些条目都是**单跳**（没有同型号 chat 跳可回落），所以失败会直接暴露；
- 探测会把它们判成 `error`，`--probe-file` 随后把它们从配置里清掉 —— 这是预期的「跑不通即清」；
- 想延长寿命就少用 `-Msg` 那几个，把额度留给真正需要的模型。

### 7.4 命名会随协议/免费状态变化

`-Msg` / `-Free` 是**状态后缀**：

- 同一型号某个渠道变成免费时，免费那条会带 `-Free`；
- 某型号新出现 chat 渠道时，桥接那条会从原型名让位成 `-Msg`。
  本次接入就触发了这条规则（`Qwen-3.8-Flash` 从 messages 条目变成 Qoder chat，
  原来那条改名 `Qwen-3.8-Flash-Msg`）。老会话会跟随 `legacy` 映射，但**显示名会变**。

### 7.5 池子的两个边界

- **链路过长时首跳失败仍要付一次往返**：冷却只记住失败过的跳，第一个请求撞到新死跳
  时仍会多花约 200ms。
- **全部冷却 = 502**：三个池子共享同一批上游 id，某个模型被某个池子烧光后，
  另一个池子用它时也会立刻失败并冷却。想彻底避免重复烧，就要把 `hops` 拆成不重叠的集合。

### 7.6 凭据

`providers/qwen/.env.local` 是唯一持久落点，`.gitignore` 已排除；
`zgate` 只报「key 是否存在」，不返回值。轮换 key 后重启 zgate 即可。

---

## 8. 相关

- 接入通用方法 / 参数矩阵：[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0、§4.10
- 命名 / 链路 / 分组：[MODEL-ALIAS.md](MODEL-ALIAS.md) §2–§4
- 同类实例（有本地反代）：[QODER.md](QODER.md)
- 凭据位置：[SECRETS.md](SECRETS.md) §2、§3.5
- 排错：[TROUBLESHOOTING.md](TROUBLESHOOTING.md)
