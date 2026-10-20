# PROGRESS — AI 模型接入 ZCode

> **一句话**：把模型供应商接进 ZCode 的台账 —— 本仓已跑通两个实例
> （OpenCode-Go 套餐、WorkBuddy2API 网关）。
>
> 本文件是本仓库**唯一**的进度台账（追加式批次日志）。
> 规则正本见 [docs/DOC-RULES.md](docs/DOC-RULES.md) 与 [docs/MAINTENANCE.md](docs/MAINTENANCE.md)。
> 拆分自原单文件 `PROGRESS.md`（2026-10-20 之前与路由器运维线合并的调优记录）。

---

# 2026-10-19 第六轮：ZCode 模型分组重排（chat 按成本档）

## 任务目标
ZCode 的 chat 模型原按用途分组（速度/经济），组名与价格脱节（"经济"组里是最贵的 longcat-2.0）。改为按成本档分组，依据「额度可撑输出 = 月额度 ÷ 输出单价」。

## 已完成变更
- [x] `provider_config.json` 重排为 6 个 provider：主力 / 免费（新建 `opencode-go-chat-free`）/ 低耗 / 高耗 / 对话 / 备用；providerId 保留以兼容旧会话引用。
- [x] 各档模型：免费 = beam-free、minimax-m3.1-flash-free、longcat-2.5-preview-free；低耗 = glm-5.3-flash、mimo-v2.6-flash、mimo-v2.5、hy3；高耗 = minimax-m3、longcat-2.0；主力/对话/备用不变。
- [x] 给 minimax-m3.1-flash-free、minimax-m3 加空 map 覆盖（`optionSpecs.reasoningLevel.map="{}"`，不发送思考参数），与 beam-free 一致；三个模型不再受 UI 思考等级影响。
- [x] 脚本 `~/.zcode/v2/apply-chat-regroup.js`（默认 dry-run，--apply 才写；备份 + 原子替换 + 写前哈希校验）；备份 `provider_config.json.bak-regroup-20261019150317`。
- [x] 重写 `模型速查表.md`：新增"额度可撑输出"列、关思考写法表、调用硬约束；实测脚本 `scripts/thinking-off-probe.js`、`scripts/opencode-header-proxy.js`。

## 验收
- 19/19 模型规则与 providerId 一一对应；provider 顺序 主力→免费→低耗→高耗→对话→备用；文件 8591 字节、JSON 合法。
- 引擎 1s 轮询热加载，日志无 provider config 报错；写入后未被应用覆盖。
- 直连实测（2026-10-19 22:50）：关思考 `thinking:{type:"disabled"}` 有效 = longcat-2.0（3.6s→1.7s）、longcat-2.5-preview-free（8.7s→7.4s）、minimax-m3、deepseek-v4.1-flash（2.5s→1.4s）；`minimax-m3.1-flash-free` 用 `enable_thinking:false`（1.2s），`thinking:disabled` 会 400；glm-5.3-flash 三种参数都关不掉；beam-free 不需要关。

## 状态: 已完成

---


---

# 2026-10-19 第七轮：Go 套餐"新增模型自动收录"可行性评估

## 探针结果（只读，未改任何配置）
- `GET /zen/go/v1/models` → 200，**37 个 id**；已配置 19 个；差集 19 个。
- **反例**：`deepseek-v4-flash-vision-exp`（主力组）在列表里没有，但带 API key 三协议实测全 200 → `/models` 不是完整目录。
- `space-bunny` → 410 `ModelDeprecated`（replacement=minimax-m3.1-flash-free）。
- 缺 `Authorization: Bearer <apiKey>` → 401 `Go requires a credential`。
- 价格/额度表 `opencode.ai/v2/docs/console/go/` → 200，210 个 table row。

## 结论
技术上全自动可行，缺的是"触发器"。检测须用四源并集；验证用三协议+弃用+思考参数探测；落盘按「月额度÷输出单价」定成本档、原子写+备份+复用 apply-chat-regroup.js。

## 第七轮续：自动收录脚本 + 定时任务落地（2026-10-20 00:00–00:20）

- [x] 写 `scripts/go_model_sync.py`：四源并集检测 → 三协议+思考参数探测 → 按成本档分组 → 备份+原子写 provider_config.json → 报告落 `audit/go-model-sync-*.md`
- [x] 踩坑修复：探测必须带 `x-opencode-session`；`anthropic/messages` 只认 `x-api-key` 不认 Bearer；价格表要用"显示名去括号后归一化"再对 id；弃用表第一列是显示名不是 id
- [x] 首次 --apply：收录 muse-spark-1.2/1.3-contributor（$0.10/$0.20、月额度 $60、额度可撑 300M，全场最耐用，只支持 openai-responses），配 `reasoningLevel.map="{}"`；provider 标签"备用"→"响应"（providerId 不变）
- [x] 排除：minimax-m2.5（官方弃用日 2026-08-05 已过）、17 个价格带外/价格未知模型
- [x] 建定时任务"每天 10:00 自动收录 Go 套餐新模型"（automationId automation-5ad749e3-0d25-4323-afbc-7ae30cdc7288，模型继承为免费 minimax-m3.1-flash-free）
- [x] 更新 `模型速查表.md`（响应组改名+ muse-spark 两行、分协议鉴权头、自动收录说明）
- [x] 体检：19 个已配置模型全部 200，无弃用/协议漂移

## 状态: 已完成

---


---

# 2026-10-20 10:00-10:50：全服务复盘（10 个子代理）+ 两次事故 + 干净出口体系

## 一、复盘方法论（本次最大的收获）

**同一个出口 IP，各家服务方的判定完全不同**——第三方 GeoIP 一律不可信：

| 服务 | 判定口径 | 实测结果（出口 66.90.99.58） |
|---|---|---|
| Google | `support.google.com` 页里 `var cc='XX'` + `www.google.com` 跳 `google.com.hk?hl=zh-CN&pref=hkredirect` | **CN**（被判中国大陆） |
| HBO Max | `set-cookie: countryCode=` | JP |
| Steam | `set-cookie: steamCountry=` | JP |
| PrimeVideo | body `currentTerritory` | JP |
| Netflix | `Location: /sg/` + body `"country":"SG"` | SG |
| OpenAI | `api.openai.com/v1/models` 不带 key：**401=放行 / 403 `unsupported_country_region_territory`=真封锁** / `cf-mitigated: challenge`=仅机器人挑战 | 放行（仅香港WAP×3 被封） |
| GitHub | 无地区判定，只有 IP 信誉：`x-ratelimit-remaining` | 共享 IP 配额被用尽 → 403 |

**逐服务实测清单**（8 份报告在 `audit/agent-*.md`）：
- Google 判 CN 的节点 12 个；OpenAI 只封 3 个（香港WAP×3）；**交集 = 香港WAP**。
- 官方清单：OpenAI `supported-countries`（208 条）不含港澳；Gemini 三份清单不含中国大陆。
- 节点名与真实地理**完全不可信**：🇯🇵 日本-优化 的出口被 Google 判成 CN；🇺🇲 美国LA-优化 实为墨西哥 IP（140.84.191.235, Oracle Querétaro）。
- Play 商店币种（USD）是**账号侧**属性，与出口 IP 无关——任何换 IP 都修不了。
- `accounts.google.com` → `hl=en-US` 也是非 IP 派生。
- 浏览器/客户端层**无残留阻断项**（8 个扩展全查 manifest：AdGuard 的 77019 条 DNR 对 Google 域命中 0、无 UA 改写、无代理扩展）；仅需用户自行清 Chrome 的 `variations_country="cn"` 种子与磁盘里的旧 `google.com.hk` 缓存页。

## 二、干净出口体系（本次落地）

- 新建 **`🤖 干净出口`**（select，**只含 🇮🇳 印度-优化 = 157.245.110.32**）→ 挂在 `🤖 人工智能` 下。
  选 select 不用 url-test：实测 28 节点里印度延迟排第 17，url-test 永远选不到它。
- `🤖 AI网页` 的 filter 收窄到 `(印度|India|IN)`，同样变成单成员 → **出口确定、不会漂**。
- **所有 Google 家族域名规则一律指向 `🤖 干净出口`**（gstatic/googleusercontent/googleapis/google.com/
  clients*/accounts/oauth2/tools/mtalk/generativelanguage/gemini*/gvt*/g.co/goo.gl/gcr.io/ggpht/c.gle/
  appspot/blogger/android/firebaseio/1e100/blogspot/gmail + GFE 两段 74.125.0.0/16、173.194.0.0/16 +
  YouTube 全族 + api.github.com）→ **一次 Google 会话只有一个出口 IP**，不再分裂。
- `🎥 NETFLIX` / `🎥 DISNEY` **保持新加坡**（印区不提供该服务，挪过去会制造新故障）。
- `🐟 漏网之鱼`（唯一 Match 兜底）**保持通用池**（全压单点更糟）。

## 三、两次事故与教训

1. **09:55 看门狗复位**：10 个子代理同时密集探测，负载冲到 2.6 → mtk-wdt（31s）复位。
   **恢复零人工干预**（配置/nft/分组选择/cron 全部自动回来）→ 反而验证了持久化工作 ✓。
2. **10:43 OOM 杀 mihomo**：`Killed process CrashCore anon-rss:77240kB` → 代理整体下线。
   链路：hotupdate 关服务 → 进程被 OOM 杀 → **重启要拉订阅、而拉订阅又需要代理** → 死锁 → 代理起不来。
   修法：① 守护进程加"最近 30 分钟存活记录"状态文件，OOM 后能自动拉起（不依赖 pid 文件）；
        ② 清掉子代理在 tmpfs 留下的 48MB 垃圾（/tmp 51MB→3MB，可用内存 51MB→77MB）；
        ③ **子代理的密集探测本身就是 OOM/看门狗的元凶**——批量审计必须限速、串行化。

## 四、当前状态
- Google 侧判定 **IN**；OpenAI 401 放行；`🤖 人工智能`/`🤖 AI网页`/`🤖 干净出口` 全部锁定印度节点。
- 全部 Google 家族域名 → 干净出口（60+ 条规则），一次会话一个出口 IP。
- `ai-api-check.sh` 1–15 节全绿；nft 四表齐备；内存 69MB avail；overlay 45%；负载 0.38。
- 守护进程每 5 分钟自愈：出口组漂移、nft 表缺失、静默回退、OOM 后拉起、内存水位告警。

## 状态: 已完成

---


---

# 2026-10-21 README 收敛 + 流水线修复

## 背景
- 参照系列仓 gsauxiliary 的门面格式，根 `README.md` 收敛为面向用户的说明。
- `.gitlab-ci.yml` 只定义了隐藏模板 `.python`（无可见作业），流水线零作业、创建即失败。

## 已完成变更
- [x] 重写根 `README.md`（logo 头 + 徽章 + 九节用户门面）
- [x] 新增 `docs/TOOLS.md`（工具清单正本），DOC-RULES / MAINTENANCE / MODEL-PROVIDERS / docs/README 引用同步
- [x] 重写 `.gitlab-ci.yml`：`syntax` + `docs` 两个真实作业
- [x] CHANGELOG 增补「README 收敛批次」

## 自检
- `python tools/check-docs.py` ✓（19 篇）
- ast.parse 全部 `.py` ✓；`node --check` 全部非 vendored `.js` ✓

## 状态: 已完成

---
