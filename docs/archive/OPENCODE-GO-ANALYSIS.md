# OpenCode Go 模型筛选 + ShellCrash 订阅优化分析

> **一句话**：Go 套餐模型与订阅结构的阶段性分析（2026-10-19；结论已被 [../MODEL-QUICK-REF.md](../MODEL-QUICK-REF.md) 与 [../MODEL-PROVIDERS.md](../MODEL-PROVIDERS.md) 取代大半，故归档）。

日期：2026-10-19
数据来源：opencode.ai/v2/docs/console/go/、`https://opencode.ai/zen/go/v1/models`、路由器 10.0.0.1 实测

---

## 一、结论先行

1. **订阅本身是健康的**：机场订阅有效，28 个可用节点。
2. **"切换模型用不了" 的根因不是网络，而是协议**：opencode Go 的模型分三种协议
   （`chat/completions`、`anthropic/messages`、`openai/responses`），把模型塞进错误的
   provider 会直接 400 `ModelProtocolUnsupported`。ZCode 必须按协议分三个 provider。
3. **当前订阅模板不缺功能，缺的是 AI API 的出口可靠性**：`opencode.ai` 现在走
   `🤖 人工智能 → 🇸🇬 新加坡节点`，而实测到 opencode.ai 最快的是日本（264ms），
   新加坡是 369–420ms；且新加坡组只有 3 个节点，全挂就没有 failover。
4. **建议不整体换模板**，用 ShellCrash 官方扩展点 `yamls/proxy-groups.yaml` 新增一个
   AI API 专用组即可（健康检查 URL 直接用 opencode.ai）。
5. 价格带内实测可用、值得加进 ZCode 的模型共 **10 个**（见第四节）。

---

## 二、opencode Go 订阅规则

- 两档：**Go $10/月**、**Go Plus $40/月**；价格相同，只有额度不同。
- 限额是**按模型分别计算的美元额度**：
  - 5 小时 = 月度额度的 20%
  - 每周 = 50%
  - 每月 = 100%
- 也就是说：用 DeepSeek V4.1 Flash 每月有 $80 的消耗额度，GLM-5.3-Flash 有 $60，
  Claude Haiku 5.5 / GPT Luna 只有 $15。**换模型 = 换一份独立额度**，这是这个订阅
  最有价值的地方。

### 关键调用约束（实测）

| 约束 | 说明 |
|---|---|
| `x-opencode-session` | **必须**。缺少时报 400 `MissingSessionID`。`x-session-id`、`session_id`、`x-claude-code-session-id` 也能过；`x-stainless-session-id` 不行。ZCode 是官方 validated client，会带自己的 session 头。 |
| User-Agent | Cloudflare 会拦默认的 Python/SDK UA（403 error 1010），必须是像客户端的 UA。 |
| 隐私设置 | `muse-spark-1.2/1.3`、`gemini-4-argon-contributor` 会报 `trains on request data`，需要在 workspace Privacy 里允许「付费且训练数据的端点」。 |
| 协议 | 见第三节，**这是最大的坑**。 |

---

## 三、协议归属（实测 2026-10-19）

ZCode 支持三种 `api.type`：`openai-chat-completions`、`anthropic-messages`、`openai-responses`。

| 协议 | 模型 |
|---|---|
| **仅 chat/completions** | glm-5.1/5.2/5.3/5.3-flash、mimo-v2.5/2.5-pro/2.6-flash/2.6-pro、hy3、hy4-preview、space-bunny、longcat-2.0、longcat-2.5-preview-free、step-5-preview、beam-free、omen-alpha、qwen3.6-plus、qwen3.7-max、kimi-k2.6、kimi-k2.7-code、minimax-m2.5 |
| **仅 anthropic/messages** | claude-haiku-5-5、minimax-m2.7 |
| **仅 openai/responses** | grok-4.6、grok-4.7、gpt-5.6-luna、gpt-6-luna、muse-spark-1.2/1.3-contributor |
| **多协议** | deepseek-v4.1-flash（三种全通）、deepseek-v4-flash-vision-exp、kimi-k3、qwen3.8-max、qwen3.8-flash（chat+messages） |
| **不可用** | muse-spark-1.2/1.3、gemini-4-argon-contributor（隐私设置拦截） |

> 注：文档表格写 `minimax-m3`、`qwen3.7-plus` 走 anthropic 端点，但实测 chat 也能通；
> 反过来 `qwen3.8-flash` 文档写 anthropic，实测 chat 也通。zcode 里优先放 anthropic
> 那一组更稳。

---

## 四、价格带筛选（≤ DeepSeek V4.1 Flash，或略高 ~$0.1）

基准：DeepSeek V4.1 Flash = off-peak $0.15/$0.60，peak $0.30/$1.20，月额度 **$80**。

| 模型 | 输入 $/M | 输出 $/M | 月额度 | 协议 | 实测速度 | 备注 |
|---|---|---|---|---|---|---|
| **beam-free** | 0 | 0 | 无限 | chat | 极快（TTFT 1.5s） | 免费无限，质量一般 |
| **glm-5.3-flash** | 0.15 | 0.50 | $60 | chat | 快（~87 tok/s） | 工具调用稳，日常主力 |
| **minimax-m3** | 0.30 | 1.20 | $60 | chat / messages | 快（TTFT 1.5s） | 1M 上下文 |
| **claude-haiku-5-5** | 0.10 | 0.50 | $15 | messages | 快（~365 tok/s） | >100K 后涨到 0.50/2.50 |
| **space-bunny** | 0.15 | 0.60 | $30 | chat | 快，缓存极好 | 输出短 |
| **qwen3.8-flash** | 0.15 | 0.47 | $30 | chat+messages | 中（TTFT 2–5.5s） | 中文好 |
| **deepseek-v4.1-flash** | 0.15–0.30 | 0.60–1.20 | **$80** | 全协议 | 中（~45 tok/s） | 额度最高，当前默认 |
| **mimo-v2.5-pro** | 0.435 | 0.87 | $15 | chat | 中快（~106 tok/s） | |
| **mimo-v2.6-pro** | 0.435 | 0.87 | $15 | chat | 中（~17 tok/s，波动大） | |
| **gpt-5.6-luna** | 0.20 | 1.20 | $15 | **responses** | 中快（~45 tok/s） | |
| **gpt-6-luna** | 0.10 | 0.50 | $15 | **responses** | 中（~38 tok/s） | |
| **hy3** | 0.14 | 0.58 | $60 | chat | 首字慢（7s+） | 批处理合适 |
| **mimo-v2.5** | 0.14 | 0.28 | $60 | chat | 中慢（~39 tok/s） | |
| **mimo-v2.6-flash** | 0.14 | 0.28 | $60 | chat | 慢（TTFT 3–6s） | |
| **longcat-2.0** | 0.30 | 1.20 | $60 | chat | 首字很慢（17s+） | 不推荐交互 |
| **longcat-2.5-preview-free** | 0 | 0 | 无限 | chat | 极慢（TTFT 11–24s） | 后台批处理 |
| **qwen3.7-plus** | 0.40 | 1.60 | $60 | messages | 首字 17s，话极多 | 一次生成大段内容 |

**超出价格带（不推荐默认添加）**：deepseek-v4-pro（$0.66/$1.98）、kimi-k2.7-code（$0.95/$4）、
step-5-preview（$1/$2.7）、hy4-preview（$0.834/$2.501）、glm-5.2/5.3（$1.4/$4.4）、
qwen3.8-max（$2/$6）、grok-4.7（$2/$6）、kimi-k3（$3/$15）、gemini-4-argon（$4/$20）。

---

## 五、建议增加到 ZCode 的模型

现有配置已可用（实测全部 200）：chat 组 7 个 + messages 组 2 个。

### 5.1 chat 组（`openai-chat-completions`）新增 6 个
`mimo-v2.5`、`mimo-v2.5-pro`、`hy3`、`minimax-m3`、`longcat-2.0`、`beam-free`

### 5.2 messages 组（`anthropic-messages`）新增 2 个
`qwen3.7-plus`、`minimax-m2.7`

### 5.3 新建 responses 组（`openai-responses`）2 个
`gpt-6-luna`、`gpt-5.6-luna`
- baseUrl 同为 `https://opencode.ai/zen/go/v1`（实测 `/responses` 可用）
- 注意：不建这个 provider，这两个模型永远加不进来

### 5.4 不建议加
`muse-spark-1.2/1.3`、`gemini-4-argon-contributor` —— 需要先在 OpenCode Console 的
workspace Privacy 里开启「允许训练数据的付费端点」，否则全是 400。

---

## 六、ShellCrash 侧方案

### 6.1 现状
```
机场订阅 (<REDACTED-sub-host>:5000)
  → api.v1.mk (server_link=2) + ShellClash.ini (rule_link=1)
  → /etc/ShellCrash/yamls/config.yaml
  → starts/clash_modify.sh 打补丁
  → /tmp/ShellCrash/config.yaml
```
- `yamls/rules.yaml`（192 条内联 AI 规则）会被插入 `rules:` 最前面。
- `yamls/proxy-groups.yaml` 是官方支持的自定义策略组扩展点（clash_modify.sh 会合并）。
- `provider_temp_clash=DustinWin_RS_Full.yaml` 是死设置，当前模式不生效。

### 6.2 实测：各节点到 opencode.ai 的握手延迟

| 节点 | 延迟 |
|---|---|
| 日本-优化 | **264 ms** |
| 香港-优化2 | 291 ms |
| 台湾-优化2-GPT | 307 ms |
| 日本-优化2 | 307 ms |
| 新加坡-优化2-GPT | 369 ms |
| 新加坡-优化3 | 397 ms |
| 新加坡-优化-GPT | 420 ms |
| 英国-优化-GPT | 436 ms |
| 印度-优化 | 497 ms |
| 德国-优化 | 567 ms |
| 加拿大-优化 | 超时 |

当前 `🤖 人工智能` 选的是 `🇸🇬 新加坡节点`，比日本慢 100–150 ms。

### 6.3 建议改动

1. **新增 `/etc/ShellCrash/yamls/proxy-groups.yaml`**，定义一个 AI API 专用组：
   ```yaml
   - name: 🤖 AI接口
     type: url-test
     url: https://opencode.ai/
     interval: 180
     tolerance: 50
     include-all-proxies: true
     filter: "(日本|新加坡|香港|台湾|美国|JP|SG|HK|TW|US)"
     exclude-filter: "过滤|流量|到期"
   ```
   这样节点名变化后仍能自动匹配，且健康检查打的是真正的 API 域名。

2. **修改 `yamls/rules.yaml`**：把
   ```yaml
   - DOMAIN-SUFFIX,opencode.ai,🤖 人工智能
   ```
   改成
   ```yaml
   - DOMAIN-SUFFIX,opencode.ai,🤖 AI接口
   ```
   并在 `ai-rules-update.sh` 生成逻辑里保留这条覆盖，避免下次更新被改回去。
   `🤖 人工智能` 继续负责 ChatGPT/Gemini/Claude（排除香港，防止地区限制）。

3. **模板选择**：建议**保持 `ShellClash.ini` 不动**。
   - 上一轮已经用 192 条内联规则补掉了它 AI 规则太旧的短板；
   - 换 DustinWin 的风险：`DustinWin_Lite.ini` 转出来 13 MB，路由器只有 239 MB 内存；
     `DustinWin_Nano.ini` 约 467 KB 可以但收益有限；
   - 更致命的是记忆里那条：订阅一旦自带顶层 `rule-providers:`，和 `clash_modify.sh`
     注入的会撞键，mihomo 直接拒载。现在这套是验证过不会撞的。

4. **机场更新节点后的重转**：其实不需要手工转换。ShellCrash 自带：
   ```sh
   /etc/ShellCrash/task/task.sh hotupdate      # 热更新订阅，不重启
   /etc/ShellCrash/task/task.sh update_config  # 更新并重启
   ```
   只有当用户直接给的是裸节点链接（不是订阅 URL）时，才需要生成
   `yamls/proxies.yaml` 让 ShellCrash 合并。

---

## 七、快慢与任务匹配

### 第一梯队（交互首选）
- **beam-free**：极快，免费无限。适合格式转换、小函数、批量草稿；不适合生产级代码。
- **glm-5.3-flash**：快且工具调用稳，$60 额度。适合日常编码 agent 主力。
- **minimax-m3**：首字 1.5s，1M 上下文。适合大仓库/长文档分析。
- **claude-haiku-5-5**：最快输出之一，工具调用规范。适合子代理、小改动、快速问答。
  注意 >100K 上下文价格翻 5 倍。
- **space-bunny**：缓存命中极高、输出短。适合重复前缀长的多轮/agent 场景。

### 第二梯队（可用，略慢）
- **deepseek-v4.1-flash**：中速但额度 $80 最高、三协议全通。适合重度日常使用（当前默认）。
- **qwen3.8-flash**：中文表现好，TTFT 波动 2–5.5s。适合中文任务、翻译。
- **mimo-v2.5-pro / v2.6-pro**：中速，$15 额度。适合中等复杂度推理。
- **gpt-5.6-luna / gpt-6-luna**：仅 responses 协议；需要单独 provider。适合 OpenAI 风格任务。
- **qwen3.7-plus**：首字很慢且输出极长（一次 1000+ token）。适合一次性生成大段内容，不适合交互。

### 第三梯队（首字慢，别用于交互）
- **hy3**（7s+）、**mimo-v2.5**（~39 tok/s）、**mimo-v2.6-flash**（3–6s）、
  **longcat-2.0**（17s+）。适合不赶时间的批处理/后台任务。

### 第四梯队（极慢）
- **longcat-2.5-preview-free**：11–24s 首字，免费无限。只适合夜里跑批量。

> 测速口径：从本机经路由器透明代理到 opencode.ai，TTFT 包含 ~300–400ms 网络握手；
> 带 reasoning 的模型如果 max_tokens 给小了，会把预算全花在思考上（实测 glm-5.3-flash、
> deepseek-v4.1-flash、hy3 在 400 token 预算下正文为 0 字符），这是正常行为，不是故障。

---

## 八、执行结果（2026-10-19 已完成）

### 路由器
- 新增 `/etc/ShellCrash/yamls/proxy-groups.yaml`：
  - `🤖 AI接口`（url-test，健康检查 `https://opencode.ai/`，27 个候选，排除占位节点与香港）
  - `🇮🇳 印度节点`、`🇨🇦 加拿大节点`、`🇩🇪 德国节点`、`🇬🇧 英国节点`
  - 五个组都已挂进 `🚀 节点选择`
- `yamls/rules.yaml` 第 74 行改为 `- DOMAIN-SUFFIX,opencode.ai,🤖 AI接口`
- `ai-rules-update.sh` 已修补：重新生成时会把 opencode 覆盖规则写在最前面，并跳过 geosite 里的同名条目
- 新增 `ai-api-check.sh`（自检）、`opencode.key`（600），两者已加入 `/etc/sysupgrade.conf`
- 原文件备份在路由器 `/root/backup/pre-ai-api/`
- 实测：`opencode.ai` 命中 `DomainSuffix → 🤖 AI接口 → 🇯🇵 日本-优化`
- 自检结果：三种协议（chat / messages / responses）全部 HTTP 200

### ZCode
- 备份：`provider_config.json.bak-20261019-184111`
- messages 组：4 个（新增 qwen3.7-plus、minimax-m2.7）
- chat 组：13 个（新增 mimo-v2.5、mimo-v2.5-pro、hy3、minimax-m3、longcat-2.0、beam-free）
- 新建 responses 组：2 个（gpt-6-luna、gpt-5.6-luna）
- 19/19 模型按各自协议实测 HTTP 200

### 两个重要修正
1. **路由器自身的 curl 不走透明代理**，直连出口是中国，调 opencode.ai 会 403
   `unsupported_country_region_territory`。自检脚本必须显式加 `-x http://127.0.0.1:7890`。
2. 香港节点实测对 opencode.ai 也是 200，但考虑到 OpenAI/Anthropic 对香港的官方限制，
   AI 组仍保留排除香港（日本 264ms vs 香港 291ms，差距很小）。

### 关于 `过滤掉14条线路`
这是机场订阅的占位/元数据节点（订阅前两条是"剩余流量"和"套餐到期"），
server/port/UUID 与 `日本-优化` 完全相同，所以它实际就是日本节点的复制品。
模板的 `.*` 会把它带进 `♻️ 自动选择` 和 `🚀 手动切换`；自定义的 AI/地区组已用
`exclude-filter` 或 `filter` 排除。它不影响使用，只是列表噪音。要彻底删除需要改模板
或加后处理，收益不大，本次未动。

### 排序调整（追加）
- 新增 `/etc/ShellCrash/reorder-groups.sh`，并在 `starts/clash_modify.sh` 的
  `merger_yaml` 与 `test_yaml` 之间加了一行钩子；`ai-api-check.sh` 会检测钩子是否
  丢失并自动补回。
- 最终策略组顺序：`🚀 节点选择 → ♻️ 自动选择 → 🤖 AI接口 → 🚀 手动切换 →
  香港/日韩/美国/台湾/新加坡/印度/加拿大/德国/英国 → 🤖 人工智能 → 其余`
- ZCode 模型按厂商分组排序，provider 顺序改为 chat → messages → responses：
  - chat：DeepSeek → 智谱 → MiniMax → 小米 MiMo → 美团 LongCat → 腾讯混元 → 其他
  - messages：Anthropic → 阿里 Qwen → MiniMax
  - responses：OpenAI
- 说明：协议把模型分成三个 provider，跨 provider 无法混排；同一 provider 内已按厂商连续排列。

## 九、待执行清单（已完成）

- [x] 备份 `provider_config.json`，新增 responses provider + 10 个模型
- [x] 路由器新增 `yamls/proxy-groups.yaml` + 改 `rules.yaml` 的 opencode 指向
- [x] 新增 `ai-api-check.sh` 自检 + `opencode.key`
- [x] 重启 ShellCrash 并验证三协议
- [x] 19/19 模型验证通过
- [ ] 用户重启 ZCode 使新模型列表生效
