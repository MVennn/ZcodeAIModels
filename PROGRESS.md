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

| 服务 | 判定口径 | 实测结果（出口 <REDACTED-EXIT-IP>） |
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
- 节点名与真实地理**完全不可信**：🇯🇵 日本-优化 的出口被 Google 判成 CN；🇺🇲 美国LA-优化 实为墨西哥 IP（<REDACTED-EXIT-IP>, Oracle Querétaro）。
- Play 商店币种（USD）是**账号侧**属性，与出口 IP 无关——任何换 IP 都修不了。
- `accounts.google.com` → `hl=en-US` 也是非 IP 派生。
- 浏览器/客户端层**无残留阻断项**（8 个扩展全查 manifest：AdGuard 的 77019 条 DNR 对 Google 域命中 0、无 UA 改写、无代理扩展）；仅需用户自行清 Chrome 的 `variations_country="cn"` 种子与磁盘里的旧 `google.com.hk` 缓存页。

## 二、干净出口体系（本次落地）

- 新建 **`🤖 干净出口`**（select，**只含 🇮🇳 印度-优化 = <REDACTED-EXIT-IP>**）→ 挂在 `🤖 人工智能` 下。
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
- 当时的流水线配置只定义了隐藏模板 `.python`（无可见作业），流水线零作业、创建即失败。

## 已完成变更
- [x] 重写根 `README.md`（logo 头 + 徽章 + 九节用户门面）
- [x] 新增 `docs/TOOLS.md`（工具清单正本），DOC-RULES / MAINTENANCE / MODEL-PROVIDERS / docs/README 引用同步
- [x] 重写流水线配置：语法 + 文档两组真实作业
- [x] CHANGELOG 增补「README 收敛批次」

## 自检
- `python tools/check-docs.py` ✓（19 篇）
- ast.parse 全部 `.py` ✓；`node --check` 全部非 vendored `.js` ✓

## 状态: 已完成

---

# 2026-10-21 反代模型排序：主力置顶 + CN 优先 + 厂商分组

## 任务目标
WorkBuddy2API 三个 provider 里的模型顺序原为「整表按倍率升序 + id」，导致
CN/全球交织、不同厂商混排，主力 `cn:deepseek-v4.1-flash` 落到低代第 8 位。
改为：主力置顶 → CN 在前、全球在后 → 每个区域按模型公司分组 → 同公司按倍率升序。

## 已完成变更
- [x] `workbuddy/workbuddy_zcode_sync.py`：新增 `PINNED_MODEL_IDS` / `VENDOR_ORDER`
  / `vendor_of()` / `model_sort_key()`；`personalModelIds` 与 `modelOrder` 用同一排序
- [x] 新增 `--reorder-only` 模式（只重排现有 provider，不改成员 / 档位 / 模型规则），
  写入仍走备份 + 原子替换
- [x] `providerOrder` 改为 低代 → 免代 → 高代（低代含主力），三个 workbuddy provider 连续排列
- [x] 实写 `~/.zcode/v2/provider_config.json`（备份 `provider_config.json.bak-wbproxy-20261021-020103`）
- [x] 文档同步：MODEL-PROVIDERS §4.2–§4.5（顺序规则 + 行序 + 促销漂移）、TOOLS 脚本说明

## 验收
- 新顺序：低代首位 `cn:deepseek-v4.1-flash`；低代 13 / 免代 5 / 高代 12，共 30 个模型；
  组内 CN 全部在 global 之前，同厂商连续。
- 写前写后对比：workbuddy 三组模型集合不变；51 条 model rules 的 key 与内容完全不变；
  opencode-go 六个 provider 与其余 `providerOrder` 项不变；`personalModelIds == modelOrder`。
- `python -m py_compile workbuddy/workbuddy_zcode_sync.py` ✓；dry-run 与实写输出一致。

## 待解决 / 注意事项
- 复核时发现促销漂移：`cn:hy4-preview` 生效价已变 0（`0x`）、`cn:glm-5.2` 促销 x0.50。
  本次只重排未改档，下次完整 `workbuddy_zcode_sync.py --apply` 会把 `cn:hy4-preview` 挪进免代。
- 若之后改了排序偏好，只改 `PINNED_MODEL_IDS` / `VENDOR_ORDER`，再跑 `--reorder-only --apply`。

## 状态: 已完成

---

# 2026-10-21 每日自动收录扩展：Go + WorkBuddy

## 任务目标
每天 10:00 的 Go 自动收录任务加上 WorkBuddy；并评估「高代」相对
`cn:deepseek-v4.1-flash` 的价格水平。

## 已完成变更
- [x] 新建当前仓库的定时任务 `automation-cfcb5c6d-a68f-410b-ba27-3dd6032115c9`
  （每天 10:00）：Go sync → WorkBuddy 刷新价格 → 补探未探模型 → 写配置
- [x] 旧任务 `automation-5ad749e3-0d25-4323-afbc-7ae30cdc7288` 指向已删除的
  `F:\Project\Openwrt`，已停用（`enabled=0` / `completed`）；
  DB 备份 `tasks-index.sqlite.bak-automation-20261021-020918`
- [x] `docs/MAINTENANCE.md` §6 定期动作同步为 Go + WorkBuddy 双线

## 价格评估（2026-10-21 倍率口径）
- 主力 `cn:deepseek-v4.1-flash` = **x0.11**。
- 「低代」上限 x0.29（hy4-preview）= **2.6 倍**；x0.17 / 0.18 / 0.25 分别是
  1.5 / 1.6 / 2.3 倍。
- 「高代」x0.50–0.79 = **4.5–7.2 倍**；最便宜的高代（glm-5.2 促销 0.50、
  deepseek-v4-pro 0.51、kimi-k2.6 0.52）也要 4.5–4.7 倍。
- 积分来自签到 / 任务（免费获取），所以「贵」表现为积分烧得快，不是现金账单。

## 验收
- `CronList` 只剩一个 10:00 任务，绑定当前仓库，`nextRunAt` = 2026-10-21 10:00。
- 旧任务已不在 `enabled` 集合内；新任务提示词里的脚本路径均为仓库相对路径。

## 待解决 / 注意事项
- 若要求严格「和 deepseek-v4.1-flash 同价」，需把 `--max-rate` 从 0.80 下调：
  `0.30` → 去掉整个高代；`0.16` → 只留主力价位（0.17/0.18 也会被排除）。
  改的时候要同时改脚本默认值与定时任务里的 `--max-rate`。
- 新任务继承了当前会话模型 `workbuddy-low/cn:deepseek-v4.1-flash`（x0.11），
  旧任务用的是免费模型；每次编排只消耗少量积分。

## 状态: 已完成

---

# 2026-10-21 WorkBuddy 分价收紧：只收主力价位，原高代整组移出

## 任务目标
用户口径：**只接受低代（主力 deepseek-v4.1-flash 价位）的模型，贵的不加，
原本的高代整组切掉**。落实为分档阈值改造 + 一次全量重写。

## 已完成变更
- [x] `workbuddy_zcode_sync.py`：`LOW_MAX 0.30 → 0.16`，`DEFAULT_MAX_RATE 0.80 → 0.30`；
  分档注释与 `--max-rate` 帮助文案同步（"贵不加"）
- [x] 全量 `--apply` 重写配置（备份 `provider_config.json.bak-wbproxy-20261021-021855`）：
  免代 6（`cn:hy4-preview` 促销 0 并入）、低代 8（只留 ≤0.16）、
  高代 4（0.17–0.29：deepseek-v4-flash / minimax-m3 / mimo-v2.6-pro / global:hy4-preview）
- [x] 原高代 12 个（x0.50–0.79）全部移出（模型规则与 provider 一并清理）
- [x] 定时任务提示词 `--max-rate 0.8 → 0.3`（probe 与 sync 两处），贵模型不会随每日任务回流
- [x] 文档：MODEL-PROVIDERS §4.2–4.6 重写（分价口径 + 新成员表 + 排除 38 个）、
  MAINTENANCE §6、TOOLS、CHANGELOG

## 验收
- 56 个网关模型 → 收 18 / 排 38（>0.30 的 25 个、无牌价 3、别名 8、blocked 2）。
- `workbuddy-low` 首位仍为 `cn:deepseek-v4.1-flash`；CN 在前、厂商分组规则不变。
- 模型规则总数 39（workbuddy 18 + opencode-go 21）；opencode-go 未动；
  `providerOrder` 仍为 低代 → 免代 → 高代。

## 待解决 / 注意事项
- 若 promo 降价把某个 >0.30 的模型打到 ≤0.30，每日任务会自动收进高代，
  仍符合"主力价位左右"口径；超过 0.30 的永远不会自动回来。
- 如需临时用高代模型，跑 `workbuddy_zcode_sync.py --max-rate 0.8 --apply` 可整体找回
  （会同时恢复低代旧成员，用完再跑默认参数还原）。

## 状态: 已完成

---

# 2026-10-21 网关生命周期跟随 ZCode：打开自动起反代，关闭自动停

## 任务目标
用户要求：不要再手动开 cmd 拉起 `wb2api` 再开 ZCode —— 打开 ZCode 时反代自动就绪，
关闭 ZCode 时反代跟着停；日常只点 ZCode。

## 已完成变更
- [x] 新增 `workbuddy/zcode_gateway_watch.ps1`：无窗口守护器。ZCode 进程出现 → 静默拉起网关；
  全部退出 → 宽限 8 秒后停；运行期间每 15 秒探活，网关挂了自动重启（失败退避 60 秒）
- [x] 新增 `workbuddy/zcode_gateway_watch.vbs`：用 wscript 无窗口启动 ps1
- [x] `-Install` 注册开机自启（`%APPDATA%\...\Startup\ZCode Gateway Watch.lnk` →
  `wscript.exe "F:\Project\ZcodeAIModels\workbuddy\zcode_gateway_watch.vbs"`）并立即启动守护器
- [x] 接管原先 `run.bat` 手动拉起的网关；杀掉旧 cmd 树后 1 秒内静默重启（新 pid，无窗口）
- [x] 文档：TOOLS 工具表、MAINTENANCE §8（新增，原「相关文档」改 §9）、
  TROUBLESHOOTING §11（新增）、docs/README 索引、README 适用环境、MODEL-PROVIDERS §4、CHANGELOG

## 验收
- `-Status`：ZCode 运行中 / 网关监听 7863 / 守护器运行中；
  日志 `%LOCALAPPDATA%\ZCodeGateway\watchdog.log`（UTF-8）。
- 杀掉手动 cmd 树后日志：`网关无响应，尝试重启` → `已静默启动网关 pid=32400` → `网关就绪`；
  新进程 `MainWindowHandle=0`（无窗口）。
- 干跑状态机（`-DryRun -ProcessName ping`）：进程出现 → `将拉起网关`；退出 2 秒后 → `将停止网关`。
- 开机自启快捷方式目标 / 参数 / 工作目录已核对；当前守护器与 wscript 均无可见窗口。

## 待解决 / 注意事项
- 关 ZCode 后网关在 8 秒宽限后停止；网关内的定时任务（签到 9/21、活跃 10、保活 22、
  夜猫子 23–08、余额刷新每 5 分钟）只在网关进程活着时执行，ZCode 不在的时段不会跑。
- 「关闭 ZCode → 停网关」的真实路径本次未实际触发（不能关掉正在使用的 ZCode），
  状态机已用假进程名干跑验证；下次正常关 ZCode 可看日志确认。
- 回退到手动：`zcode_gateway_watch.ps1 -Uninstall`，之后照旧 `run.bat` / `stop-gateway.bat`。

## 状态: 已完成

---

# 2026-10-21 网关目录并入本仓：上游无更新，clone 迁到 workbuddy/gateway

## 任务目标
用户要求：检查反代项目是否更新，有更新就拉；把网关并入当前仓库，避免两个目录来回切；
合并后删除原目录。

## 已完成变更
- [x] 上游检查：`git fetch` + `pull --ff-only` → `origin/main` = `6b31db6`，
  0 ahead / 0 behind，无更新
- [x] 用 robocopy 把整个 clone（216 个文件，含 `.git`）复制到 `workbuddy/gateway/`；
  源码 / 配置 / 二进制哈希一致
- [x] 停旧守护器与旧网关 → 最后一次同步 `data/`、`auths/`、`config.json` →
  从新目录启动（pid 17924）→ `/panel/` 200 → 新守护器（pid 36472）接管
- [x] 删除旧目录 `E:\Tool\AITool\workbuddy2api-panel`（数据已迁走）
- [x] `zcode_gateway_watch.ps1` 默认目录改为 `$PSScriptRoot\gateway`；主仓 `.gitignore`
  排除整个 `workbuddy/gateway/`；`tools/check-docs.py` 跳过该目录
- [x] 文档：MAINTENANCE §8、TOOLS、SECRETS、TROUBLESHOOTING §11、NOTICE、CHANGELOG

## 验收
- `-Status`：网关监听 7863（pid 17924，路径
  `F:\Project\ZcodeAIModels\workbuddy\gateway\wb2api.exe`），守护器运行中；
  网关日志显示恢复 139 个用量桶、4 个账号、cn / global 模型速率正常。
- `/panel/` 200；当前 ZCode 会话（走 workbuddy-low）请求正常。
- `git status` 不显示 `workbuddy/gateway/`（整目录已忽略）。
- 旧目录 `Test-Path` = False。

## 待解决 / 注意事项
- 新机器 / 新克隆没有 `workbuddy/gateway/`（被 .gitignore 排除）：按 MAINTENANCE §8 的
  `git clone` + `config.json` + `auths/` + `go build` 重建。
- 本机 clone 有两处本地改动（`.gitignore` 补 `.api_key_secret` / `server.log`；
  `go.mod` 把 redis 提为直接依赖），以后 `git pull` 前留意冲突。
- 上游后续更新：`git -C workbuddy/gateway pull --ff-only`。

## 状态: 已完成

---

# 2026-10-21 网关 ↔ ZCode 联动优化：主进程判据、就绪判定、排空与 provider 校验

## 任务目标
用户要求：联动、优化，让 ZCode 适配更好。落点放在守护器与 ZCode 的联动机制上
（provider 的模型元数据已齐全，不在本次改动范围）。

## 已完成变更
- [x] 主进程判据：只跟随命令行既不含 `--type=` 也不含 `zcode.cjs` 的 `ZCode.exe`；
      GPU / renderer / crashpad / CLI 宿主晚退不拖住网关
- [x] 启动：轮询 1000→500 ms；就绪判定由 TCP 端口改为 `/panel/` HTTP 200；
      网关 stdout / stderr 启动前轮转为 `.1`
- [x] 停网关：宽限 8 秒后最多再等 `-DrainTimeoutSeconds`（默认 30 秒）排空在途连接；
      宽限内 ZCode 重开则取消停止
- [x] `-Status`：显示 ZCode 主进程 PID、网关就绪、`workbuddy-*` 三个 provider 的
      模型数 / baseUrl / key 状态；ZCode 启动时做同一校验，不匹配写「联动警告」
- [x] 修复 `-Uninstall`：过滤掉当前进程，避免自杀
- [x] 文档：MAINTENANCE §8、TOOLS、TROUBLESHOOTING §11、CHANGELOG

## 验收
- `-Status`：主进程 pid=18360（共 37 个 ZCode 进程）、网关 pid=17924 且 `/panel/` 200、
  守护器运行中；低代 8 / 免代 6 / 高代 4 三个 provider 全部 `[OK；key 已配置]`。
- 干跑（`-DryRun -ProcessName ping`）：`检测到 ping 主进程启动` → `将拉起网关`；
  退出 2 秒后 `主进程已退出，2s 后停网关` → `将停止网关`。
- 新守护器（pid 23172）启动后日志显示 `检测到 ZCode 主进程启动（pid=18360）` →
  `网关已在监听...接管`；网关未重启，当前会话无断流。
- GUI / 渲染子进程（共 37 个）不影响主进程判定；`-Status` 的 provider 校验可读且不打印 key。

## 待解决 / 注意事项
- 「主进程退出 → 排空 → 停网关」的真实路径仍未在本次触发（不能关正在用的 ZCode）；
  状态机已用假进程名干跑，排空逻辑待下次正常关 ZCode 时验证。
- 若 ZCode 升级改变主进程命令行，`Get-ZCodeMainProcess` 的过滤条件需要跟着改；
  `-Status` 会显示「未识别到主进程」作为提示。

## 状态: 已完成

---

# 2026-10-21 README 门面统一（对齐 GSAuxiliary 七节）

## 背景
- 在「README 收敛批次」之后再收一轮：门面向读者是使用者，开发者内容下沉 `docs/`；
  门面资源统一由 `assets/icon.svg` 渲染。

## 已完成变更
- [x] 根 `README.md` 收敛为七节门面（107 行）：这是什么 / 环境要求 / 使用 / 反馈 / 免责声明 / 开源鸣谢 / 许可证
- [x] 「接一个新的模型供应商」四步下沉 `docs/MODEL-PROVIDERS.md` §0；
      `provider_config.json` 的三个落点与 `--apply` 写入差异下沉同篇 §1 / §1.1
- [x] 统一路由与各脚本产物下沉 `docs/TOOLS.md` §2；上游调研与分发文件来源下沉 `docs/UPSTREAM.md` §5
- [x] 新增 `tools/make_social_preview.py`（自带 SVG 渲染器，无第三方依赖），生成
      `assets/logo.png` 与 `assets/social-preview.png`
- [x] `docs/DOC-RULES.md` 正本映射表、`docs/README.md` 索引同步
- [x] CHANGELOG 增补「门面统一批次」

## 自检
- `python tools/check-docs.py` ✓（20 篇）
- GitHub 侧：仓库描述与话题已更新；社交预览图已上传并与仓内资产逐字节一致

## 状态: 已完成

---

