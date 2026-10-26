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
- [x] 重写 `MODEL-QUICK-REF.md`（原 `模型速查表.md`）：新增"额度可撑输出"列、关思考写法表、调用硬约束；实测脚本 `scripts/thinking-off-probe.js`、`scripts/opencode-header-proxy.js`。

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
- [x] 更新 `MODEL-QUICK-REF.md`（原 `模型速查表.md`；响应组改名+ muse-spark 两行、分协议鉴权头、自动收录说明）
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

# 2026-10-21 守护器退出路径加固（关 ZCode 后 wb2api 残留）

## 任务目标
用户报告：wb2api 只跟随 ZCode 启动，不跟随退出。查清真实原因，
并让网关 / 统一路由可靠地跟着 ZCode 主进程退出。

## 已完成变更
- [x] 用 ZCode 自身日志（`~/.zcode/v2/logs/2026-10-21.log`）核对主进程时间线：
      当天 10 次托盘退出里 9 次在 2–5 秒内又被拉起，正好落在 8 秒宽限内 →
      守护器按设计取消停止（旧版不写这条日志）；23:51 那次间隔 18 秒，
      真实停过一次（8 秒宽限 + 30 秒排空），证明停止分支本身是通的。
- [x] `zcode_gateway_watch.ps1`：主进程改用 `Process.HasExited` 按句柄判存活，
      PID 被复用不再把已退出的 ZCode 误判成还在跑；连续两次认不出才按退出处理。
- [x] 启动对账：没有 ZCode 主进程却还有网关 / 路由在监听 → 清掉遗留进程
      （`-KeepOrphans` 跳过）。
- [x] 停止时 pid 未知 → 按端口反查，并校验 `wb2api` 进程名 / `unified-router.js` 命令行。
- [x] 宽限 / 排空期 ZCode 回来：写日志、取消停止；排空期回来立刻重新拉起路由。
- [x] 排空上限默认 30 → 5 秒；新增 15 分钟心跳（`-HeartbeatSeconds`）；
      `-Status` 显示脚本版本 / 守护器 pid，并在守护器进程早于脚本修改时间时提示旧代码。
- [x] 换上新守护器（pid 40976，VBS 无窗口启动），原网关 35732 / 路由 43136 被接管，未断流。
- [x] 文档：TOOLS、MAINTENANCE §8、TROUBLESHOOTING §11、CHANGELOG。

## 验收
- 语法：`[Parser]::ParseFile` → SYNTAX OK。
- `-Status`：`守护器：运行中 v2026-10-21.2（pid=40976）`；网关 35732 `/panel/` 200；
  路由 43136 `/health` 就绪；五个 chat 组全部 `[OK；key 已配置]`。
- `-Once -DryRun -ProcessName Notepad`：正确输出「启动时没有 Notepad 主进程：
  将清理遗留网关 pid=35732 / 路由 pid=43136」。
- `-Once -DryRun`（真实 ZCode）：`检测到 ZCode 主进程启动（pid=9488）` →
  `将拉起网关/统一路由`。
- 真实退出路径不能在本会话触发（会杀掉正在使用的 ZCode）；待下次托盘退出验证
  日志里的「已停止」或「宽限期内重新出现」两行。

## 待解决 / 注意事项
- 点窗口 × 只是最小化到托盘（`closeToTrayOnWindows=true`），主进程仍在；
  这种「看着关了」的情况不会再停网关，文档已写明。
- 若之后又出现「ZCode 长时间不在但网关还在」：先看 `watchdog.log` 是否有心跳和停止记录；
  没有心跳说明守护器被结束，`-Install` 重装即可，启动对账会清掉遗留进程。

## 状态: 已完成

---

# 2026-10-22 自动收录定时任务修复 + 首次真跑通

## 任务目标
「触发收录的运行失败了」：查清 ZCode 定时任务触发失败的根因并修好；
修好后按该任务的指令完整跑一轮 Go 套餐 + WorkBuddy 同步。

## 已完成变更
- [x] 定位触发失败：自动化的 `target_task_id` 指向的会话已 `deleted=1`
      → 派发报 `Session not found`（5 次手动触发全失败，`run_count` 一直是 0）；
      另有两班 10:00 定时窗口因机器睡眠被跳过（`computer_asleep_or_app_not_running`，
      ZCode 不补跑）。
- [x] 重建自动化 `automation-3e2f8a53`：每天 **12:00**，模型
      `免费/minimax-m3.1-flash-free`；prompt 取网关 key 改读
      `workbuddy/gateway/config.json` 的 `api_key`（原 `workbuddy-low` 在统一路由
      并组后已不存在，会抛 `StopIteration`）。
- [x] 解绑目标会话：`target_task_id` 置空 → ZCode 派发走 `createTask` 分支，
      **每次运行新建独立会话**，上下文不累积；该字段全流程只读不写回，解绑永久。
- [x] 12:00 真跑验证：`dispatched` → `succeeded`，`run_count=1`，下次 10-23 12:00。
- [x] 同步本身：Go **建议收录 0 个**、配置未改动；WorkBuddy 18 个模型并入五个 chat 组
      （主力 2 / 低代 6 / 免代 5 / 高代 3 / 备用 2），与同步前逐个对账一致，
      无新增 / 下架 / 换档；备份 `provider_config.json.bak-wbproxy-20261022-125559`。

## 验收
- `automation_runs`：今天那班 `dispatched / succeeded`，error 为空。
- Go：报告 `evidence/go-model-sync/go-model-sync-20261022-125539.md`
  （「建议收录 0 个」「配置未改动」）。
- WorkBuddy：同步前后逐 provider 对账模型集合，18 个模型全部在位、档位未变。
- 凭据复核：全仓无明文 key（`oc_sk_` 全文检索只命中文档里的前缀说明），
  `workbuddy/cache/` 与 `workbuddy/gateway/` 仍被 `.gitignore` 排除。

## 待解决 / 注意事项
- **Go 体检 18 条误报**：体检固定探 OpenCode-Go 的公共 API，WorkBuddy 模型一律 400
  `Model is unavailable`。解法与另外两条脚本待办见
  [docs/MAINTENANCE.md](docs/MAINTENANCE.md) §7 待办 6 / 7 与
  [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) §13。
- **mimo-v2.5-pro 上游已下架**（400 `Unsupported model`），还挂在主力组，待确认移除。
- **longcat-2.0 / longcat-2.5-preview-free** 402 `Endpoint is unavailable`，等上游恢复。
- **漏收**：`cn:hy4-preview-f` / `global:hy4-preview-f` 探测 ok、实际免费，
  但价格表 `credits` 为空 → 判成「无公布倍率」排除。
- **cn:deepseek-v4.1-flash 曾在 503**：唯一 CN 账号上该模型被 6004 模型频率限制锁住
  （网关 `/status` 的 `model_locks` 里有 `unlock_at`），到点自愈。
- 代理在 **OpenWrt 侧 ShellCrash**（网关透明代理），本机没有代理客户端；
  上游 403 地区限制类报错先查路由器侧，**别在任务里加「开梯子」前置条件**。

## 状态: 已完成

---

# 2026-10-22 仓库门面：Issue 表单

## 任务目标
对齐 GSAuxiliary 的仓库门面：补上 Issue 表单，让反馈自带版本、脚本、命令与脱敏后的输出。

## 已完成变更
- [x] 新增 `.github/ISSUE_TEMPLATE/bug_report.yml` —— ZCode 版本、provider / 模型、脚本、
      完整命令、输出与配置片段；确认已备份 `provider_config.json`、贴出的内容不含凭据
- [x] 新增 `.github/ISSUE_TEMPLATE/feature_request.yml` —— 场景、期望效果、范围确认
- [x] 新增 `.github/ISSUE_TEMPLATE/config.yml` —— 关掉空白 Issue，挂排错手册与接入方法

## 自检
- `python tools/check-docs.py` ✓，退出码 0
- 三份 YAML 均可被 `yaml.safe_load` 解析

## 状态: 已完成

---

# 2026-10-22 收尾大扫除（L1-L4）

## 任务目标
按《系列仓大扫除共用作业书》（2026-10-22）做 L1-L4：清可再生产物、对齐文档漂移、
记账、验证并本地提交；只做减法，不改功能与用户可见行为。

## 已完成变更
- [x] L1 清 `workbuddy/__pycache__/`（40K，可再生成）
- [x] L1 清 `workbuddy/cache/wb_pricing.json.bak-20261022-125554`（20K，
      价格表自动备份，保留最新 `wb_pricing.json`）
- [x] L3 `docs/MODEL-PROVIDERS.md`：范围行 6/3 → 7/4；WorkBuddy 快照改 2026-10-22；
      补两个模型的 effort 档位、`cn:minimax-m3` 输出上限 524K → 512K；§5.2 模型数 30 → 18
- [x] L3 `docs/release-notes/README.md` 补「反馈入口」规则（绝对地址 `issues/new/choose`）
- [x] L3 `AGENTS.md` §3 改为「有 `.codegraph/` 就优先用」
- [x] 记账：CHANGELOG「收尾大扫除」段（含两笔脱敏提交）、本批次、MAINTENANCE §10 维护记录
- [x] 保留：`workbuddy/gateway/`（含凭据与二进制）、`.codegraph/`、`evidence/`、
      `opencode-go/probe/results/`、`workbuddy/cache/` 活数据、`workbuddy/logs/wb_zcode_probe.log`

## 验收
- `python tools/check-docs.py` → 退出码 0（20 篇）
- 12 个 `.py` `python -m py_compile` → 全部退出码 0
- 6 个 `.js` `node --check` → 全部退出码 0
- 仓库 `du -sk` 53109 → 53053（净 -56K）
- `git status --porcelain` 仅含本轮改动，无在途文件

## 待解决 / 注意事项
- `wb_pricing.json` 2026-10-22 快照把全部模型的 `can_disable` 改为 false（10-21 备份里部分为 true），
  与 MODEL-PROVIDERS §5.1 的实测结论不一致；表内「可关思考」列未改，待用探测复核后再定。
- `mimo-v2.5-pro` 上游已下架但仍挂在主力组（既有待办，上一批已登记）。

## 状态: 已完成


---

# 2026-10-23 第 N 轮：同步脚本自动清理失效模型

## 任务目标
用户要求：弃用的、模型列表里已没有的模型，在同步时就地移除，不要只写在报告里。
范围限三个同步脚本；不改定时任务、不手改 provider_config.json。

## 已完成变更
- [x] `opencode-go/ops/go_model_sync.py`：`--apply` 时移除弃用（410 / 弃用日期表）
      与上游不可用（402 Endpoint unavailable / 400 Unsupported model / 404）的已配置模型，
      删 `personalModelIds` + `modelOrder` + `modelConfigRules` 三处
- [x] 同上：体检跳过 `cn:` / `global:` 前缀的 WorkBuddy 模型，不再误报 Go 探测异常
- [x] `workbuddy/workbuddy_zcode_sync.py`：统一模式下清理不再被选中的 `cn:` / `global:` 模型；
      网关返回残缺列表时只报 kept、不删
- [x] `workbuddy/workbuddy_fetch_pricing.py`：新表比旧表少 30% 以上拒写（退出码 2），`--force` 覆盖
- [x] 实测清掉 4 个模型：`minimax-m3.1-flash-free`（410）、`longcat-2.0` / `longcat-2.5-preview-free`（402）、
      `mimo-v2.5-pro`（400）；18 个 WorkBuddy 模型未动；备份 `provider_config.json.bak-gosync-20261023-000011`

## 验收
- 三个脚本 `python -m py_compile` 全部退出码 0
- 干跑复核：Go dry-run 列 4 个待删、0 个新收录；WorkBuddy dry-run 仍选中 18 个、stale 0
- 单测：残缺列表（34/56）下 `apply_unified` stale=0 / uncertain=18 且模型原样保留；
      完整列表下 stale=18；价格表脚本残缺输入 ret=2 且文件未被覆盖，`--force` 后 ret=0
- `git grep` 配置备份确认 4 个名字在 provider_config.json 中出现次数为 0

## 待解决 / 注意事项
- `cn:hy4-preview` 因夜间免费促销（0.29x → 0x）从高代移入免代，促销结束后倍率变化会再次移动它
- `mimo-v2.5-pro` 若上游恢复支持需人工加回主力组（脚本只删不加）

## 状态: 已完成

---

# 2026-10-23 脱敏审查：修泄漏源 + 补敏感信息守卫

## 任务目标
8 仓公开化后的脱敏复审发现本仓提交 `92baac2`（已推送）在两个 evidence 报告里
写入本机用户目录下的 `provider_config.json`。目标：找到
持续产生这个泄漏的机制并修掉，补上本仓缺失的守卫，脱敏已泄漏的文件。

## 已完成变更
- [x] 修根因：`opencode-go/ops/go_model_sync.py` 两处 `log("已写入 %s" % args.config)`
      改为 `os.path.basename(args.config)` —— 报告只写文件名，不再回显绝对路径。
      第 617 行（备用档重排）与第 757 行（主同步）都改了
- [x] 新增 `tools/check-secrets.py`：凭据规则 + 「本机用户目录」+ 「真实邮箱域名」，
      扫 `git ls-files`，占位符行跳过；`--all` 扫工作树
- [x] 接入 CI：`.github/workflows/ci.yml` 加「敏感信息扫描」步骤
- [x] 脱敏两个 evidence 文件：`evidence/go-model-sync-20261022-234800.md`、
      `evidence/go-model-sync-20261023-000011.md`，路径改为 `provider_config.json`

## 验收
- 守卫有效性正反验证：注入测试行（本机路径 + 真实邮箱）→ 退出码 1 且两条都报出；
      当前工作树 → 退出码 0（270 个文件）
- `python tools/check-secrets.py` 与 `python tools/check-docs.py` 均通过
- 本机用户目录在全历史 blob 中零命中（工作树与 HEAD 树均已清）

## 待解决 / 注意事项
- 历史提交 `92baac2` 的旧 blob 仍在 GitHub 上（force-push 不会立刻删服务端旧对象），
  旧 SHA 仍能读到泄漏内容。要彻底清需 `git filter-repo --replace-text` 重写并强推，
  本仓 28 个提交、0 star / 0 fork，重建成本低但属破坏性操作，未擅自执行
- 同类残留（仅历史可见）：`PROGRESS.md` / `docs/SECRETS.md` / `memories/*` /
  `go_model_sync.py` 的旧 blob 仍含本机用户目录路径，HEAD 已清
- 8 仓里只有 AX3000TOpenwrt 与 ShellcrashRules 原有守卫，且规则不含用户路径；
  建议按本仓这份给其余仓补齐

## 状态: 已完成

---

# 2026-10-23 第 N+1 轮：修免费 -f 模型被漏收 + 收进免代档

## 任务目标
用户指出 `cn:hy4-preview-f`（及 `global:hy4-preview-f`）是夜间/免费入口，应进
ZCode 免代档；此前同步把它们漏了。定位根因并修复，再把模型收录进配置。

## 已完成变更
- [x] 修根因：`workbuddy/workbuddy_zcode_sync.py` 的 `rate_of()` 只看原始
      `credits`/`promo_credits` 字符串；免费 `-f` 模型网关 `credits` 为空串，
      返回 `None` 被当成「无价格」排除。改为优先信任价格表已归一化的
      `eff_rate`/`list_rate`（fetch 脚本已算好的 0.0），缺失才回退原始串解析。
      模块 docstring 本就写 `wb_pricing.json` 是分档唯一价格输入。
- [x] 重跑同步：`workbuddy_fetch_pricing.py` → `workbuddy_probe_zcode.py --max-rate 0.3 --sleep 20`
      → `workbuddy_zcode_sync.py --max-rate 0.3 --apply`
- [x] 新收录进 `opencode-go-chat-free`（免代）：`cn:hy4-preview-f`、`global:hy4-preview-f`
      两个模型规则已建（contextWindow 1M、supportsImage、supportsToolCall、maxOutput 64k）

## 验收
- 同步 selected 18 → 20；免代档 5 → 7，仅新增上面两个 `-f`，其余档零位移
- config diff 确认：除两个 `-f` 加入免代外，main/low/high/backup 档成员与顺序均未变
- 备份：`provider_config.json.bak-wbproxy-20261023-141008`

## 待解决 / 注意事项
- `-f` 模型 probe 的 `rate` 字段为 null（价格表无原始倍率串可比对），但归一化
  `eff_rate=0.0` 已正确归免代，不依赖 null 字段
- `cn:hy4-preview`（付费 0.29x）仍归高代；如夜间促销把它的 `credits` 也清成 0，
  下轮 fetch 会把 `eff_rate` 变成 0.0 而移入免代，属预期行为

## 状态: 已完成

---

# 2026-10-23 第 N+2 轮：mimo/longcat 400/402 排查 + 落地「跑不通即清」永久策略

## 任务目标
用户后台看到 mimo 系列 + longcat 系列请求全 400/402。排查根因，并落实
「跑不通就清掉，复通了下次同步再加回」的永久策略。

## 排查结论（根因）
- 400/402 是上游(OpenCode Go / WorkBuddy 网关)已停服/临时故障，非脚本或配置 bug。
  - 历史证据：`longcat-2.0`/`longcat-2.5-preview-free` 上游 402 `Endpoint is unavailable`；
    `mimo-v2.5-pro` 上游 400 `Unsupported model`；本轮 13:50 的 Go 同步还抓到
    `mimo-v2.6-flash` 探测 HTTP 500。
  - 实时核对(2026-10-23 14:36)：4 个 mimo 模型当前全部 HTTP 200 可达 ——
    用户看到的 400/402 是**瞬时上游抖动**，模型现在并没死。
- 残留 4 个 mimo 仍在配置里（mimo-v2.5 / mimo-v2.6-flash / mimo-v2.6-pro 直连 Go，
  cn:mimo-v2.6-pro 走网关）。因当前均复通，未做删除（删了下一轮 Go 同步又会从
  实时清单加回，徒劳）。

## 永久策略落地（改脚本）
- [x] `opencode-go/ops/go_model_sync.py` 的 `stale_reason()` 收紧移除口径：
      `error` 类里只豁免 **401(授权)** 与 **429(限频冷却)**（环境/用量问题，脚本无解、会自恢复），
      其余 400/402/404/410 与 5xx 一律判「跑不通」并移除；复通后由新模型评估自动加回。
      （此前 400/402/404 仅当上游报 unavailable 标记且不在清单才删，其他 error 只打 ⚠ 不删。）
- WorkBuddy 侧 `workbuddy_zcode_sync.py` 本就按 probe 的 blocked/unavailable 移除
  `cn:/global:` 模型、且 live 列表缺员即判 stale —— 已符合策略，未改。

## 验收
- 本次 `go_model_sync.py --apply`：4 个 mimo 实测 HTTP 200，按新策略正确「保留」，
  配置未改动（与现状一致）；`longcat`/`mimo-v2.5-pro` 等确死的仍正常判不收录。
- 策略生效验证：下次若这些模型再 400/402/5xx，Go 同步 `--apply` 会直接 prune_model，
  不再只打 ⚠。
- 备份：`provider_config.json.bak-gosync-20261023-143619`（未触发，因无移除）

## 待解决 / 注意事项
- 若要让当前这 4 个 mimo「立刻清掉再等复通加回」无意义（会立刻被加回）；
  真正需要清理的是永久下线的模型，由策略自动处理，无需手改。
- 建议把 Go / WorkBuddy 两套同步接进同一定时任务（cron），保证「跑不通即清」
  策略按日自动执行；本次未创建定时任务（用户此前要求不擅建）。

## 状态: 已完成

---

# 2026-10-23 第 N+3 轮：接入 Qoder（qoder2api-hub 独立 provider）

## 任务目标
按用户确认：Qoder 用 qoder2api-hub，Agent2API 暂不采用；WorkBuddy2API 与
OpenCode-Go 保持不动。把 Qoder 做成 ZCode 里的独立 provider，并保留可重复的
探测 / 清理 / 同步流程。

## 已完成变更
- [x] clone `qoder2api-hub` 到 `qoder/gateway/`（整目录 gitignore，含自己的 `.git`）
- [x] 8790 启动：API key + 面板密码持久化到 `accounts/settings.json`，改用
      `start-qoder-proxy.bat` detached 运行；`qoder/.env.local` 只给脚本读
- [x] Qoder CN OAuth 设备授权，账号入库（`qoder.com.cn`，personal_professional_trial）；
      `python _install_umid.py` 装好 UMID；启动巡检签到 +100 Credits（余额 399）
- [x] `qoder/qoder_zcode_sync.py`：拉 `/v1/models` → 排除 Auto/Fast 别名 →
      按 price_factor 升序 → 写独立 `qoder` provider（默认 `--max-price 0.8`）
- [x] `qoder/qoder_probe_zcode.py`：用 ZCode 真实 body 探测，状态写
      `qoder/qoder_probe.json`；`--probe-file` 只保留 `ok`
- [x] `provider_config.json` 写入 `qoder` provider（7 个模型，排在免费组之后）；
      备份 `provider_config.json.bak-qoder-20261023-165457`
- [x] 文档：新增 `docs/QODER.md`；更新 `MODEL-PROVIDERS.md`（§4.9、§5.2、§1.1）、
      `TOOLS.md`、`SECRETS.md`、`TROUBLESHOOTING.md`、`README.md`、`NOTICE`、
      `docs/README.md`、`.gitignore`

## 验收
- `GET /health`：`ok=true`、version 1.7.0、accounts 1、accounts_ready 1、
  api_key_required true
- `/v1/models`：CN 目录 14 个（含 Auto/Fast）；探测 7 个 `ok`
- `qoder/DeepSeek-Flash`（免费）：HTTP 200、1.1s、`billable:false`；流式 SSE 200
- `ListModels`：`qoder/DeepSeek-Flash`、`qoder/GLM-5.3-Flash`、
  `qoder/MiniMax-M3.1-Flash`、`qoder/DeepSeek-V4-Pro`、`qoder/Qwen3.8-Max`、
  `qoder/GLM-5.3`、`qoder/Kimi-K2.8-Preview` 均可见，顺序按 price_factor
- 签到：2026-10-23 16:56 启动巡检 +100 Credits，余额 399；下一次 21:00

## 待解决 / 注意事项
- `Qwen3.8-Flash` 免费但上游 10605 排队（queueCount ≈ 19k，p3），75s 超时，
  按「跑不通即清」暂不收录；复通后重新 probe + sync 会自动加回
- 免费 `DeepSeek-Flash` 也会排队：2026-10-23 17:10 服务端 64s 后 200，
  17:14 复测 93.9s 后 502（10605，queueCount 0）；probe 结果已加 `ever_ok`，
  排队/超时不误杀曾 200 的模型，只有从未成功过的才会被排除
- qoder2api-hub 目前是常驻 detached 进程，**未**接进 `zcode_gateway_watch.ps1`；
  重启机器后需要手动 `start-qoder-proxy.bat`（或以后再加守护）
- ZCode CLI 没有 `--model` 参数，无法用一条命令指定 `qoder/...` 做端到端对话；
  已用 `zcode_effective_body.js` 真实 body 探测 + `ListModels` 验证 provider 可用
- 付费模型会消耗试用额度（300 起步），日常优先用免费的 `DeepSeek-Flash`

## 状态: 已完成

---

# 2026-10-23 第 N+4 轮：Qoder 并入现有 chat 组（qoder: 前缀 + 7871 分流）

## 任务目标
用户要求把 Qoder 从独立 provider 合并到之前的「免费 / 低耗 / 高耗」分组，减少
provider 列表；Qoder hub 与 WorkBuddy/OpenCode 的现有链路保持不变。

## 已完成变更
- [x] `tools/unified-router.js` 新增 `qoder:` 分支：路由到 8790、剥掉前缀、
      用 `QD_API_KEY` 鉴权；`/health` 与启动日志加 `qoder`；key 从
      `qoder/.env.local` / 环境变量 / 旧 provider 规则读取
- [x] `opencode-go/ops/go_model_sync.py`：`is_non_go_id()` 把 `qoder:` 视作
      非 Go 模型，体检/清理跳过，日志改为 `cn:/global:/qoder:`
- [x] `qoder/qoder_zcode_sync.py` 默认改为**合并模式**：
      price 0 → 免费、0 < x ≤ 0.2 → 低耗、> 0.2 → 高耗；模型 id 加 `qoder:`；
      移除旧的独立 `qoder` provider；`--separate` 保留旧模式；切换模式可重复执行
- [x] `qoder/qoder_probe_zcode.py` 默认经 7871 + `qoder:` 前缀探测（与 ZCode
      实际路径一致），候选从 8790 `/v1/models` 取（不在配置里的模型也能复探）；
      `--direct` 可直连 8790
- [x] 重启 7871 路由；写入合并配置：免费 1 个、低耗 2 个、高耗 4 个 Qoder 模型；
      provider 列表仍是 7 个
- [x] 文档同步：QODER.md、MODEL-PROVIDERS.md §4.9、TOOLS.md、SECRETS.md、
      MAINTENANCE.md §8.1、TROUBLESHOOTING.md、README.md、CHANGELOG.md

## 验收
- `ListModels`：`opencode-go-chat-free/qoder:DeepSeek-Flash`；
  `opencode-go-chat-fast/qoder:GLM-5.3-Flash`、`qoder:MiniMax-M3.1-Flash`；
  `opencode-go-chat-slow/qoder:DeepSeek-V4-Pro`、`qoder:Qwen3.8-Max`、
  `qoder:GLM-5.3`、`qoder:Kimi-K2.8-Preview`；独立 `qoder` provider 不再出现
- `curl http://127.0.0.1:7871/health`：`qoder.key=true`
- 经 7871 发 `qoder:GLM-5.3-Flash`：HTTP 200，0.9s
- 经 7871 + 真实 ZCode body 探测：7 个 ok；`Qwen3.8-Flash` 仍 10605 排队
- Go 侧 `is_non_go_id("qoder:...")=True`；WorkBuddy dry-run 只处理自己的模型，
  不删除 `qoder:` 条目
- 备份：`provider_config.json.bak-qoder-merge-20261023-172830`

## 待解决 / 注意事项
- `Qwen3.8-Flash` 仍因上游排队不收录；复通后 probe ok + sync 自动加回
- `qoder:` 模型依赖 7871 路由；hub 常驻、router 随 ZCode 起停
- 若以后想回到独立 provider：`python qoder/qoder_zcode_sync.py --separate --apply`
- 免费 `DeepSeek-Flash` 高峰仍可能排队/502；交互优先用低耗档的 0.1 模型

## 状态: 已完成

---

# 2026-10-23 第 N+5 轮：统一模型命名（四组 + 积分 + alias map + 协议桥）

## 任务目标
用户要求把三家渠道统一成 `渠道 : 型号 : 积分`，按渠道/公司排序，只留
主力/免费/低耗/高耗四组，并让本地路由处理格式差异（一步到位）。

## 已完成变更
- [x] 新增 `tools/model_alias.py`：从当前 provider 配置收集模型，按
      WB/OC/QD 与地区/系列重命名，按积分分到四组；生成
      `~/.zcode/v2/model-alias-map.json`；备份 `.bak-alias-*`；可重复执行
- [x] 积分口径：WB `eff_rate` 原样；OC 以 `deepseek-v4.1-flash`
      $0.15/$0.60 ↔ 0.11（1 积分 = $3.409/M，1:1 混合）；QD `price_factor × 0.86`
- [x] 四组：主力 4 / 免费 9 / 低耗 18 / 高耗 12，共 43 个模型；`备用` 解散，
      `对话`/`响应` 折入四组
- [x] 新增 `tools/model_probe.py`：用 `zcode_effective_body.js`（带 provider id）
      复算真实 body，经 7871 探测；结果 `~/.zcode/v2/model_probe.json`，带 `ever_ok`
- [x] 新增 `tools/protocol_bridge.js`：chat ↔ Anthropic Messages / OpenAI Responses，
      非流式上游 + 合成 chat SSE，工具调用双向转换
- [x] `tools/unified-router.js`：优先读 alias map，按 channel 还原上游并注入 key；
      旧前缀保留为 legacy 回退；`/health` 增加 alias 条数
- [x] `workbuddy/zcode_effective_body.js`：叠加用户 `providerModelRules`，
      让新 ID 的 `map="{}"` 在探测里生效
- [x] `go_model_sync.py`：`WB:`/`OC:`/`QD:` 视作非 Go 模型跳过
- [x] 文档：新增 `docs/MODEL-ALIAS.md`；更新 MODEL-PROVIDERS / TOOLS / MAINTENANCE /
      TROUBLESHOOTING / README / CHANGELOG / docs 索引

## 验收
- `ListModels`：4 个 provider、43 个模型；ID 形如
  `WB : DeepSeek-V4.1-FS : 0.11`、`OC : DeepSeek-V4.1-FS : 0.11`、`QD : GLM-5.3 : 0.69`
- 直连：WB/OC/QD 各取一个 → HTTP 200（1–2s）
- 桥接：`OC : Qwen3.8-FS : 0.09`（messages）、`OC : GPT-6-Luna : 0.09`（responses）→ 200；
  工具调用返回 `tool_calls`；流式桥接返回 SSE
- 空 map：`OC : MiniMax-M3 : 0.22`、`OC : Beam : 0.00` 的 effective body 只剩
  `max_completion_tokens`，请求 200
- 全量探测：37 ok；5 个 WB GB 模型 `no_healthy_account`（池冷却，按瞬时限流保留）
- 旧 ID：`cn:deepseek-v4.1-flash`、`qoder:GLM-5.3`、`glm-5.3-flash` 仍可走
- 备份：`provider_config.json.bak-alias-20261023-180240`

## 待解决 / 注意事项
- 5 个 WB GB 模型当前是池冷却，不是模型死；恢复后 probe 会转 ok
- `deepseek-v4-flash-vision-exp`、`minimax-m2.7` 无公布价格，暂不收录
- 桥接模型是非流式上游 + 合成 SSE，首字不是逐 token；chat 模型仍原生流式
- 价格写进 ID：调价会改名，旧会话靠 alias map 的 legacy 继续可用
- 旧 sync/probe 现在是数据采集器；最终写入只跑 `model_alias.py`
- 项目规模已明显变大，下一步需要重新规划（用户已提出）

## 状态: 已完成

---

# 2026-10-23 第 N+6 轮：可读模型名 + 峰谷价

## 任务目标
用户要求去掉 `-f`/`-sg` 等噪音、显示名改成可读大小写（如
`WB : DeepSeek-V4.1-FS : 0.11`），并让早晚不同的模型倍率随时段变化。

## 已完成变更
- [x] `model_alias.py` 的 `ABBR` 改为可读名字：`DeepSeek-V4.1-FS`、`GLM-5.3-FS`、
      `MiniMax-M3.1-FS`、`MiMo-V2.6-Pro`、`HY4-Preview` 等；去掉 `-f`/`-sg`/`-free`
- [x] 价格后缀去掉 `X`：`WB : DeepSeek-V4.1-FS : 0.11`、`QD : GLM-5.3 : 0.69`
- [x] `--slot auto|peak|offpeak`：Qoder 用 `price_factor_peak/valley` 与
      22:00–08:00 Asia/Shanghai 窗口；WorkBuddy 用 `list_rate`/`eff_rate`
      （峰价取 list，谷价取带夜间/错峰标签的 eff，auto 取刷新后的 eff）
- [x] 生成器输出/alias map 增加 `slot` 字段；备份 `.bak-alias-*`（时间戳到微秒，避免同秒覆盖）
- [x] `model_probe.py` 结果改为按**原始模型 ID** 存 key，显示名只作 `display`；
      `model_alias.py` 的 probe 过滤沿 legacy 链匹配，改价/换时段不会丢探测记录
- [x] 文档：MODEL-ALIAS 增加峰谷价小节；QODER/README/CHANGELOG/TOOLS/MAINTENANCE
      示例统一为可读名

## 验收
- `ListModels`：43 个模型 / 4 组，ID 形如 `WB : DeepSeek-V4.1-FS : 0.11`、
  `OC : GLM-5.3-FS : 0.10`、`QD : Qwen3.8-Max : 0.43`
- 峰谷价：`QD:CN-DeepSeek-V4-FS` 峰 0.09 / 谷 0.00；
  `QD:CN-Qwen3.8-Max` 峰 0.43 / 谷 0.17
- 直连/桥接：WB/OC/QD、messages（`OC:Qwen3.8-FS`）、responses（`OC:GPT-6-Luna`）
  均 200；旧 ID `WB:CN-DSP-V41-F:X0.11` 仍可路由
- 峰谷切换实测：offpeak 时 QD DeepSeek `0.00`（免费 9 / 低耗 18），
  Qwen3.8-Max `0.17`；auto（当前峰价）恢复 `0.09` / `0.43`（免费 8 / 低耗 19）
- 备份：`provider_config.json.bak-alias-20261023-181125`

## 待解决 / 注意事项
- 自动早晚切换需要每天 08:00 / 22:00 跑
  `python workbuddy/workbuddy_fetch_pricing.py` → `python tools/model_alias.py --slot auto --apply`
  （当前未注册定时任务）
- 峰谷切换会改显示名；旧 ID 由 alias map 的 legacy 兼容，ZCode 模型选择器需重新点一次
- WorkBuddy 的谷价依赖时段刷新 `eff_rate`；不刷新时 auto 停在最后一次取价
- 项目规模继续变大，重新规划时把“时段取价/定时重写”纳入维护层

## 状态: 已完成

---

# 2026-10-23 第 N+7 轮：CN/GB 合并 + 空格格式 + OC 峰谷价

## 任务目标
用户要求 WorkBuddy 的 CN/GB 合成一个 `WB` 口子（GB 优先、GB 全不可用回退 CN），
显示名加空格（`WB : DeepSeek-V4.1-FS : 0.03`），并确认 OpenCode-Go 的夜间折扣
也要纳入峰谷价。

## 已完成变更
- [x] `model_alias.py` 的 WB 合并：按 base model 分组（`-sg` 视为地区变体，
      不单独分组）；GB 为 primary，CN 进 `fallbacks`；同价 CN/GB 合并；
      GB 免费/付费价档各自保留
- [x] 显示名格式：去掉地区、冒号两侧加空格，`WB : 模型 : 积分`；
      `-f`/`-sg` 不再出现
- [x] alias map 增加 `fallbacks` 与 `legacy_ids`；CN 旧 ID 映射到主价档，
      旧会话仍可路由
- [x] `unified-router.js` 新增 `forwardChain`：429/502/503/504 时按
      primary → fallback 重试；GB SG 503 实测回退 CN 成功（1.2s 200）
- [x] OpenCode-Go 峰谷价：仅 DeepSeek V4.1 Flash / V4 Pro；峰时 UTC 周一至周五
      01:00–04:00、06:00–10:00；V4.1 Flash 0.22/0.11，V4 Pro 0.77/0.39；
      其他 OC 模型固定
- [x] `model_alias.py --slot auto|peak|offpeak` 同时覆盖 WB/OC/QD
- [x] 文档示例统一成空格格式；MAINTENANCE 增加工作日 09/12/14/18 的 OC 边界

## 验收
- 合并后 36 个显示名 / 4 provider：主力 3、免费 5、低耗 17、高耗 11
- `WB : DeepSeek-V4.1-FS : 0.03` 在 GB 503 时自动回退 `cn:deepseek-v4.1-flash`，
  HTTP 200；router 日志出现 `[router] ... -> 503, fallback ...`
- `WB : GLM-5.3-FS : 0.08`、`WB : HY4-Preview : 0.29` 均配置了 CN fallback
- OC 峰价 `OC : DeepSeek-V4.1-FS : 0.22` / 谷价 `0.11`；auto 当前（18:xx CST）
  为谷价 0.11
- 空间格式的模型 ID 在 ListModels / 7871 请求中正常
- 备份：`provider_config.json.bak-alias-20261023-184142-356100` 等

## 待解决 / 注意事项
- 5 个 WB GB 模型仍在池冷却；fallback 已生效，但 CN 号也冷却时会返回 503
- 自动峰谷切换需要 08:00/22:00 + 工作日 09:00/12:00/14:00/18:00 跑
  `workbuddy_fetch_pricing.py` → `model_alias.py --slot auto --apply`；当前未注册
- 显示的是 GB 主价；回退 CN 时实际扣费可能更高（CN 价档未显示）
- 项目继续变大，重新规划时把“合并/回退/时段取价”作为独立层

## 状态: 已完成

---

# 2026-10-23 第 N+8 轮：Qwen3.8-Flash 提进主力

## 任务目标
按用户之前推荐的「AI 能力专项测试」榜单和「DeepSeek = 100 基准」规则，找性能与
价格都和 DeepSeek 接近的模型，加进主力组。

## 选型依据
- 基准：DeepSeek V4.1 Flash，榜单 #11，总分 **342.40**，积分 **0.11**
- 候选：Qwen3.8-Flash，榜单 #4，总分 **372.95**，积分 **0.09**
  - 智力指数 108.9（372.95 ÷ 342.40 × 100）
  - 价格指数 81.8（0.09 ÷ 0.11 × 100）
  - 满足「智力 ≥100 且价格 ≤100」的主力规则
- 其他接近项：GLM-5.3-Flash 334.15 / 0.10（智力 97.6，未过 100）；
  GLM-5.3 345~351 / 0.69（价格 6 倍）；HY4-Preview 350.71 / 0.29（价格 2.6 倍）。

## 已完成变更
- [x] `tools/model_alias.py` 的 `MAIN_IDS` 加入 `qwen3.8-flash`
- [x] 重新生成：主力 3 → 4，低耗 17 → 16，其余不变；
      主力模型：WB DeepSeek-V4.1-FS 0.03、OC DeepSeek-V4.1-FS 0.11、
      OC Qwen3.8-FS 0.09、OC MiMo-V2.6-Pro 0.19
- [x] 文档：MODEL-ALIAS 主力规则、BENCHMARKS §5 角色与说明、CHANGELOG

## 验收
- `ListModels`：`opencode-go-chat/OC : Qwen3.8-FS : 0.09` 出现在「主力」
- 经 7871 发 `OC : Qwen3.8-FS : 0.09`（messages 桥接）→ HTTP 200，1.8s
- 备份：`provider_config.json.bak-alias-20261023-184640-938600`

## 待解决 / 注意事项
- 该分数来自 `qoder` 平台的 QWEN3.8-FLASH · XHIGH；本仓走 OpenCode-Go messages，
  平台差异存在，实测只验证了可用性，不代表分数完全一致
- 主力现在有两个 DeepSeek 和两个 Qwen/MiMo；后续是否把 OC Qwen3.8-FS 设为默认
  由用户决定，当前只是加入列表
- 峰谷价/CN-GB fallback 逻辑不受本次调整影响

## 状态: 已完成

---

# 2026-10-23 第 N+9 轮：ArenaGalleri 榜单自动扩充主力

## 任务目标
用户给出 <https://gallery.arenaofbias.icu/#/leaderboard>（会持续更新），要求每次更新
重拉榜单、看排名，把「性能和 DeepSeek 差不多、价格也差不多」的模型扩进主力。

## 榜单事实
- 页面是 SPA；数据在 <https://api.arenaofbias.icu/api/leaderboard>，返回 `rows`
  （模型 × effort 一行）、`updatedAt`、`refreshIntervalSeconds = 600`
- 2026-10-23 拉取：242 行 / 94 题 / 822 位投票者
- 基准 `deepseek-v4.1-flash`：非临时、≥50 局的最高分是 `XHigh` 1100（#47，241 局）
- 行里有 `provisional`（临时名次）；直接按最高分取会拿到 7～9 局的小样本，默认排除

## 选型规则（写进脚本默认值）
分数 ≥ 基准 95%、积分 ≤ 0.11、非临时、≥50 局、积分 > 0；价格按谷价/eff/valley 判断，
峰时切价不影响主力成员；0 积分模型留在免费组，避免免费组被抽空。

## 已完成变更
- [x] 新增 `tools/arena_leaderboard.py`：拉榜（失败回落缓存）→ 归一化模型名 →
      按上述窗口从 `model-alias-map.json` 的**已配置模型**里筛候选 → 写
      `~/.zcode/v2/arena-main.json`；`--refresh / --write / --apply / --status`
- [x] 名字归一：只留字母数字，`claude-haiku-5.5` ↔ `claude-haiku-5-5` 自动对齐；
      `-sg`、`-contributor`、`hy4-preview-f` 的 `-f` 视为同模型；
      `-next` / `-1017` 不合并
- [x] `tools/model_alias.py`：新增 `--arena-main` / `--no-arena`，按
      `(channel, upstream)` 扩充主力；alias map 条目增加 `main_reason`；
      修复 `--probe-file` 分支 `transient_kept` 未初始化的 `NameError` 隐患
- [x] 候选集合或规则没变时不重写配置，避免榜单 10 分钟一更新就抖模型 ID
- [x] 文档：BENCHMARKS §8（接口/口径/候选表/映射边界/回退）、MODEL-ALIAS §4.2、
      TOOLS、MAINTENANCE §2.1、README、CHANGELOG
- [x] 重新生成四组：主力 4 → 7，免费 5、低耗 16 → 13、高耗 11，共 36 个

## 验收
- 新增主力：`OC : MiMo-V2.6-FS : 0.06`（1112，101.1%）、
  `WB : Space-Bunny : 0.08`（1075，97.7%）、
  `OC : Claude-Haiku-5.5 : 0.09`（1064，96.7%）
- 经 7871 实测 chat：三者均 HTTP 200（8.2s / 1.2s / 1.7s）；
  `OC : Qwen3.8-FS : 0.09` 仍 200
- `provider_config.json`：主力 7 / 免费 5 / 低耗 13 / 高耗 11；
  alias map 36 个模型 / 122 条 legacy
- 重复跑 `arena_leaderboard.py`：候选未变 → 打印「跳过 model_alias.py」
- 备份：`provider_config.json.bak-alias-20261023-185721-025500`

## 待解决 / 注意事项
- 榜单里 `qwen3.8-flash` 只有 `-next` 版本，`minimax-m3.1-flash` 只有 `m3.1`，
  两者不自动匹配；Qwen 的主力资格仍来自旧榜（§5）
- 自动刷新尚未注册定时任务；建议随 08:00/22:00 与工作日峰谷边界跑
  `arena_leaderboard.py --refresh --write`，再跑 `model_alias.py --apply`
- 榜单分数是原平台成绩，经本仓中转不等价；主力成员只代表「值得优先试」，
  不等于本仓实测质量
- 掉出窗口会自动退回原积分组，主力不是只增不减

## 状态: 已完成

---

# 2026-10-23 第 N+10 轮：显示名压缩为 `W/0.03/DeepSeek-41-Fs`

## 任务目标
用户认为 `WB : DeepSeek-V4.1-FS : 0.03` 仍然太长，指定格式
`W/0.03/DeepSeek-41-Fs`，其余模型跟进。

## 已完成变更
- [x] `model_alias.py`：显示名改为 `单字母/积分/紧凑型号`；新增
      `CHANNEL_LETTER = {WB:W, OC:O, QD:Q}`；`ABBR` 全部换成紧凑名
      （去 `V`、去版本点、`Flash`→`Fs`）
- [x] 未知模型的后备缩写也做同样压缩（去版本点、去前缀 `V`、`Flash`→`Fs`）
- [x] 重新生成四组 + alias map：36 个模型，主力 7 / 免费 5 / 低耗 13 / 高耗 11；
      旧空格 ID 进 `legacy`（86 条）
- [x] 重写 `arena-main.json`，候选的 `display` 同步为新格式
- [x] 文档示例全部改为新格式；CHANGELOG / PROGRESS / 记忆同步

## 验收
- 新 ID：`W/0.03/DeepSeek-41-Fs`、`O/0.11/DeepSeek-41-Fs`、`O/0.09/Qwen-38-Fs`、
  `O/0.06/MiMo-26-Fs`、`W/0.08/Space-Bunny`、`O/0.09/Claude-Haiku-55`
- 经 7871 实测：上述新 ID 均 200（Qoder 的 `Q/0.09/GLM-53-Fs`、
  `Q/0.09/MiniMax-M31-Fs` 也 200）
- 旧 ID 仍可路由：`OC : Qwen3.8-FS : 0.09`、`WB : DeepSeek-V4.1-FS : 0.03` → 200
- `Q/0.09/DeepSeek-4-Fs` 90s 超时：Qoder 免费 DeepSeek-Flash 上游排队（已知问题），
  非命名问题；同渠道其他模型正常
- 备份：`provider_config.json.bak-alias-20261023-190833-508200`

## 待解决 / 注意事项
- 旧空格 ID 只在 legacy 里，等 ZCode 会话都切换后可以自然淘汰；暂时不要清
- `Q/…/DeepSeek-4-Fs` 免费排队严重，交互优先用 `Q/0.09/GLM-53-Fs` 或
  `Q/0.09/MiniMax-M31-Fs`
- 榜单候选文件里的 `display` 会随 alias map 重新生成；`channel/upstream` 不受影响

## 状态: 已完成

---

# 2026-10-23 第 N+11 轮：每日自动化加入 Qoder 模型查询

## 任务目标
每天 12:00 的定时任务只收录 Go 套餐与 WorkBuddy 新模型，Qoder 的实时目录变化
（新模型、复通、下架）没有自动查询。把 Qoder 的「拉目录 → 真实 body 探测 →
并入 chat 组」接进同一个定时任务，并保证最终仍由 `model_alias.py` 归一化四组。

## 已完成变更
- [x] 定时任务 `automation-3e2f8a53-b408-4bf8-90ff-4a331a721f5c` 扩为四段：
      Go → WorkBuddy → Qoder → `model_alias.py --slot auto --apply`；标题改为
      「每天 12:00 自动收录 Go 套餐、WorkBuddy 与 Qoder 新模型」
- [x] Qoder 段：`qoder_probe_zcode.py --timeout 90 --sleep 3` →
      `qoder_zcode_sync.py --probe-file qoder/qoder_probe.json --apply`；
      全部超时时检查 7871，必要时 `--direct` 直连 8790 重探
- [x] 修 `go_model_sync.py`：新增 `display_alias()` / `probe_targets()`，已配置的
      `W/…`/`O/…`/`Q/…` 显示名按 alias map 还原上游裸 id 再体检；WB/QD 渠道跳过。
      不修的话，明天 12:00 会把显示名当 Go 模型探测，404 后误删
- [x] 文档：`MAINTENANCE.md` §6、`TOOLS.md`、`QODER.md` §4/§5、`CHANGELOG.md`

## 验收
- `go_model_sync.py` dry run：36 个配置识别为 Go 16 / 非 Go 跳过 20，无一条被误判
- Qoder 探测 8 个：7 个 200，`DeepSeek-Flash` 排队超时但 `ever_ok` 保留；
  `Qwen3.8-Flash` 复通 200
- `qoder_zcode_sync.py --probe-file … --apply`：备份 `provider_config.json.bak-qoder-merge-20261023-192423`
- `model_alias.py --slot auto --apply`：备份 `provider_config.json.bak-alias-20261023-192436-451700`
- 最终四组 37 个模型（主力 7 / 免费 5 / 低耗 14 / 高耗 11），Qoder 8 个
  （低耗 `Q/0.09/DeepSeek-4-Fs`、`Q/0.09/Qwen-38-Fs`、`Q/0.09/GLM-53-Fs`、
  `Q/0.09/MiniMax-M31-Fs`；高耗 4 个）；无未归一化 id
- `GET 7871/health` alias.models=37；`Q/0.09/Qwen-38-Fs` 经 7871 实测 200

## 待解决 / 注意事项
- Qoder 免费模型峰谷价不同：`DeepSeek-Flash` / `Qwen3.8-Flash` 谷价 0 积分进免费组、
  峰价 0.09 进低耗，12:00 定时任务取的是峰价
- 定时任务整轮耗时可能 20–30 分钟（WorkBuddy `--sleep 20` + Qoder 最长 90s/模型）
- 若 8790 网关没起，Qoder 段会全 timeout；`--direct` 也救不了，需要先
  `start-qoder-proxy.bat`

## 状态: 已完成

---

# 2026-10-23 第 N+12 轮：显示名 `Preview` 缩为 `Pre`

## 任务目标
用户要求把模型显示名里的 `Preview` 统一缩成 `Pre`，继续压缩名字长度。

## 已完成变更
- [x] `tools/model_alias.py`：`ABBR` 改为 `Kimi-K28-Pre` / `HY4-Pre` /
      `Step-5-Pre` / `LongCat-25-Pre`；`abbreviate()` 兜底新增
      `preview\b -> Pre`（未列入 `ABBR` 的新模型也生效）
- [x] 重跑 `model_alias.py --slot auto --apply`，四组与 alias map 重新生成
- [x] 文档：`MODEL-ALIAS.md` 的名字映射表与变体说明、`BENCHMARKS.md` 的
      `HY4-Pre`、`CHANGELOG.md`

## 验收
- 配置里新显示名：免费 `W/0.00/HY4-Pre`、`W/0.00/Step-5-Pre`；
  高耗 `W/0.29/HY4-Pre`、`Q/0.69/Kimi-K28-Pre`
- `W/0.00/HY4-Pre` 经 7871 实测 200（上游回 `model: hy4`）
- 四组仍为 37 个模型（主力 7 / 免费 5 / 低耗 14 / 高耗 11）
- 备份：`provider_config.json.bak-alias-20261023-192910-362000`

## 待解决 / 注意事项
- 旧显示名（含 `Preview`）已进 alias map 的 `legacy`，老会话仍可路由；
  等会话都切换后可自然淘汰
- `Kimi-K2.8-Preview` 带点的是 Qoder 上游模型 id，不能改；显示名只去掉点并缩为
  `Kimi-K28-Pre`

## 状态: 已完成

---

# 2026-10-23 第 N+13 轮：运行架构整合（zgate 单入口 + 目录两轴）

## 任务目标
用户确认 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 的提案：把三个反代收进一个目录，
能用 Go 合并的合并，减少常驻内存；当前「每家一个目录 + 路由在 tools + 守护器在 workbuddy」
的结构不再适合仓库体量，一并整理可删可并的东西。

## 已完成变更
- [x] 新增 `gateways/zgate`（Go 1.22，零第三方依赖）：7871 路由 + alias map 热加载 +
      chat ↔ Anthropic Messages / OpenAI Responses 协议桥 + 子进程守护
      （Job Object / 单飞拉起 / 健康检查 / 空闲回收 / 崩溃退避重启）
- [x] 子命令：`serve` / `status` / `install` / `uninstall` / `version`；配置 `zgate.json`；
      GUI 子系统 + `AttachConsole`，计划任务不闪窗、终端里照常输出
- [x] 等价性：旧路由与新入口并行（7871 / 7971）跑 9 个用例，9/9 一致后才切流
- [x] 目录重构：`workbuddy/gateway` → `gateways/upstream/workbuddy`，
      `qoder/gateway` → `gateways/upstream/qoder`，三家脚本 → `providers/<vendor>/`，
      旧 JS 路由 → `gateways/legacy-router/`（回退用）
- [x] 同步修改：`.gitignore`、`tools/model_alias.py`、`tools/model_probe.py`、
      `tools/check-docs.py`、`tools/check-secrets.py`、旧路由的两处凭据回退路径
- [x] 删除：`zcode_gateway_watch.ps1` / `.vbs`、3 份过期的 `wb_pricing.json.bak-*`、
      `__pycache__`
- [x] 文档：`MAINTENANCE.md` §8 重写（zgate 生命周期/配置/日志/上游更新）、
      `TOOLS.md` 工具表重排、`TROUBLESHOOTING.md` §11/§12 改写、
      `MODEL-PROVIDERS.md` / `MODEL-ALIAS.md` / `PITFALLS.md` / `QODER.md` /
      `SECRETS.md` / `README.md` / `CONTRIBUTING.md` / `AGENTS.md` / `NOTICE` /
      issue 模板的路径与措辞
- [x] 新增 `docs/ARCHITECTURE.md`（提案 + §10 落地记录）、`docs/release-notes/0.3.0.md`，
      `CHANGELOG.md` 开 0.3.0
- [x] 测试：`bridge` / `alias` / `router` / `supervisor` 共 12 个用例 + 冒烟
      `gateways/zgate/smoke_test.py`；CI 增加 Go 格式 / 构建 / 测试

## 验收
- `go vet ./...`、`gofmt -l .`、`go test ./...` 全绿（supervisor 的两个用例会真实拉起子进程）
- 等价性 9/9（OC / WB（含 fallback chain）/ QD / messages 桥 / responses 桥 / 三种流式 / 未知模型）
- 切换后冒烟 6/6：四条通道 + 两种桥 + 流式；WB 冷启动 1.6 秒
- 内存（WorkingSet）：改造前 293.4 MB（4 进程）→ 99.3 MB（zgate 18.5 + Qoder 57.2 + wb2api 23.2）；
  WB 空闲回收后 76.1 MB
- 端口：7871 = zgate，7863 = wb2api（子进程），8790 = qoder（子进程），7863 只在 WB 请求后出现
- 登录自启：`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ZcodeAIModels zgate.lnk`
- `python tools/check-docs.py`（25 篇）、`python tools/check-secrets.py`（97 文件）通过

## 待解决 / 注意事项
- **切 7871 会断掉正在走这条路由的会话** —— 本轮切换时把正在跑这份工作的会话也断了
  （用户当时切了模型才恢复）。以后重启 zgate 前先在 ZCode 里切到直连模型。
- `gateways/legacy-router/` 保留一个版本作回退；确认稳定后删除。
- Qoder 仍是 `always`；`ondemand` / 窗口档未启用 —— 需要先实测「窗口拉起能补签」。
- WorkBuddy 的签到/夜猫子/额度刷新只在进程活着时跑；要 24/7 就把
  `children.workbuddy.policy` 改成 `always`（多占约 23 MB）。
- `zgate.exe` 不入库，换机器要 `cd gateways/zgate && go build -ldflags "-s -w" -o zgate.exe .`。

## 状态: 已完成

---

# 2026-10-23 第 N+14 轮：代码优化 + 三个网关全部随用随拉

## 任务目标
用户要求：① 按上一条评审把代码问题修掉；② 没被调用就不要拉起任何网关（含 Qoder），随用随拉；
③ 兼顾自动化（签到 / 保活）。

## 已完成变更
- [x] **P0 桥超时**：`bridge.DefaultTimeout = 120s`，`Forward` 用 `context.WithTimeout`；新增超时用例
- [x] **P1 句柄双关闭**：`winproc.Process.Release` 改 `sync.Once`
- [x] **P1 接管实例监控**：`tick` 对 `external` 子进程每 5 秒健康检查，失败转回自管并自动重启
- [x] **P1 日志运行时轮转**：`logx` 按累计写入量在 5 MB 处 rename + 重开；`status` 不再打开写句柄
- [x] **全部按需**：`zgate.json` 两个 child 都改 `ondemand` + `idleSeconds: 300`
- [x] **签到窗口**：新增 `children.*.windows`（`HH:MM-HH:MM`，支持跨午夜）；
      WB 四档、Qoder 三档；窗内按 `always`，窗口结束后按空闲回收
- [x] **热加载**：`POST /admin/reload` + `zgate reload`（策略 / 空闲 / 窗口生效；
      新增 child、监听地址、上游 base 仍需重启）
- [x] **退避**：1s→2s→4s→…→60s（与 ARCHITECTURE §3.2 一致）
- [x] **杂项**：`qoder:` 前缀大小写不敏感；`args` 解析不再把 `/c` 当路径；
      删除 `WaitExit` / `Missing` / `Redacted` / `doForward` 包装 / `sseOf` 死参数；
      `normalizePath` 直接用 `r.URL`
- [x] **冒烟改造**：`smoke_test.py` 从 alias map 按渠道挑最低价模型，不再写死 ID
- [x] 文档：`MAINTENANCE.md` §8（策略表 / 窗口表 / reload 命令）、`ARCHITECTURE.md` §10.6、
      `TOOLS.md`、`CHANGELOG.md`、`release-notes/0.3.0.md`

## 验收
- `go test ./...` 20 个用例全绿（新增窗口解析/跨午夜、ApplyConfig、退避、桥超时、reload）
- `go vet` / `gofmt -l` 干净；`check-docs`（25 篇）/ `check-secrets`（97 文件）通过
- 旁路实例（7971）实测：启动时无窗口的子进程保持 `stopped`；窗口内自动 `running`；
  `POST /admin/reload` 去掉窗口 + `idleSeconds=1` 后一个 tick 内回到 `stopped`
- 二进制已构建为 `gateways/zgate/zgate-next.exe`（运行中的 `zgate.exe` 被锁，需重启替换）

## 待解决 / 注意事项
- **替换需要重启 zgate**：已安排延迟执行（停 → 覆盖 → 起 → 等 /health）并写
  `%LOCALAPPDATA%\ZCodeGateway\update-0.3.1.log`；这一步会中断经过 7871 的在途请求（约 2 秒）
- 重启后两个子进程都应为 `stopped`；第一条 WB / Qoder 消息会有 1–2 秒冷启动
- 签到窗口能否真正补签，还需要观察一个真实 09:00 / 21:00 窗口（Qoder 启动巡检
  `_allow_complement_checkin` 的实测未做）

## 状态: 已完成

### 第 N+14 轮补充：上线 + DeepSeek 限流核查（2026-10-23 20:33）

- 二进制替换与重启已由一次性计划任务完成（20:33:02 停 → 替换 → 20:33:04 健康），
  日志 `%LOCALAPPDATA%\ZCodeGateway\update-0.3.1.log`；任务已删除。
- 线上生效：两个 child 都是 `ondemand`，`windows` 已在 `/health` 可见；Qoder 空闲已回收（stopped）。
- **回退链缺陷已修并上线**：WB 把上游 6004 转成 `400 model_unavailable`，旧逻辑不重试；
  现在按池故障触发 region fallback（普通 400 仍直通），日志出现
  `Bad Request model_unavailable, fallback cn:deepseek-v4.1-flash`。
- 但实测该回退仍失败：`deepseek-v4.1-flash` 的冷却按**模型名**（不带 region）记在 4 个账号上，
  sg 与 cn 共用同一冷却键，所以 `global → cn` 换区也救不回来。
  可用的是另一个模型 `cn:deepseek-v4-flash`（`W/0.17/DeepSeek-4-Fs`，200）。

---

# 2026-10-23 第 N+15 轮：显示名恢复版本点号 + 免费 DeepSeek 进主力置顶

## 任务目标
用户要求：① 把免费的 `DeepSeek-41-Fs`（`W/0.00`）也整合进主力并优先使用；
② 显示名里的 `41` / `38` / `26` 这类连写恢复成 `4.1` / `3.8` / `2.6`，其他同类一起改。

## 已完成变更
- [x] `tools/model_alias.py`：`MAIN_IDS` 加入 `global:deepseek-v4.1-flash`；
      新增 `MAIN_FIRST` 集合，组内排序时该模型固定第一
- [x] `ABBR` 全部改成带点号：`DeepSeek-4.1-Fs` / `Qwen-3.8-Fs` / `Qwen-3.8-Max` /
      `Qwen-3.7-*` / `GLM-5.3(-Fs)` / `GLM-5.2` / `MiniMax-M3.1-Fs` / `MiniMax-M2.7` /
      `MiMo-2.6-*` / `MiMo-2.5*` / `Claude-Haiku-5.5` / `Kimi-K2.8-Pre` / `Kimi-K2.6` /
      `Kimi-K2.5` / `GPT-5.6-Luna` / `Muse-Spark1.2` / `Muse-Spark1.3` / `LongCat-2.0` /
      `LongCat-2.5-Pre`
- [x] `abbreviate()` 兜底不再删除数字之间的点号
- [x] 重新生成：36 个模型（主力 8 / 免费 5 / 低耗 12 / 高耗 11），
      主力第一位 = `W/0.00/DeepSeek-4.1-Fs`；备份 `provider_config.json.bak-alias-20261023-212104-841800`
- [x] 文档：`MODEL-ALIAS.md`（命名规则、组规则、示例）、`BENCHMARKS.md`、`PITFALLS.md`、
      `CHANGELOG.md`
- [x] `gateways/zgate/smoke_test.py` 改为每个渠道取最便宜的前 3 个候选逐个试，
      冷却中的模型不再让整轮冒烟假红

## 验收
- `~/.zcode/v2/model-alias-map.json`：36 条模型、99 条 legacy；旧名（`DeepSeek-41-Fs`、
  `MiMo-26-Fs`…）全部映射到新名
- 实测经 7871：`W/0.00/DeepSeek-4.1-Fs` 200（免费档已可用，早于网关提示的 21:54）、
  `W/0.03/DeepSeek-4.1-Fs` 200、`Q/0.09/GLM-5.3-Fs` 200、`O/0.06/MiMo-2.6-Fs` 200；
  旧名 `O/0.06/MiMo-26-Fs` 也仍 200（legacy 生效）
- `check-docs` 25 篇通过

## 待解决 / 注意事项
- 免费 DeepSeek 是**移动**进主力（不是双份），免费组因此少一条（5 条）
- 冒烟时 OC 桥接出现过两次 `EOF`（HTTP/2 连接复用导致的上游瞬断，重试即 200）；
  考虑把 zgate 的 Transport 切回 HTTP/1.1（与旧 Node 路由一致）或对 EOF 做一次重试，
  需要再重启一次 zgate，留待下次空档
- Qoder `DeepSeek-Flash` 仍偶发 `10605` 限流（既有问题）

## 状态: 已完成

### 第 N+15 轮修正：免费档并入 `W/0.03`（同日 21:26）

- 用户澄清：不是单列 `W/0.00` 进主力，而是把免费档**并入 `W/0.03` 这一条**。
- 实现：`MERGE_FREE_GB = {"deepseek-v4.1-flash"}` —— 该 base model 的 GB 多价档合并成一个条目，
  `upstream` 取最便宜的 GB 档（免费），其余档与 CN 依次进 `fallbacks`；显示价保留最高档 0.03。
- 结果：`W/0.03/DeepSeek-4.1-Fs` 的链路 = `global:deepseek-v4.1-flash`（免费）→
  `global:deepseek-v4.1-flash-sg`（0.03）→ `cn:deepseek-v4.1-flash`；
  `W/0.00/DeepSeek-4.1-Fs` 不再单独存在。
- 配置：35 个模型（主力 7 / 免费 4 / 低耗 13 / 高耗 11），
  备份 `provider_config.json.bak-alias-20261023-212649-949100`。
- 实测：经 7871 请求 `W/0.03/DeepSeek-4.1-Fs` 返回 200，日志链路显示
  `free -> sg -> cn`。

### 第 N+15 轮修正 2：合并幂等（同日 21:28）

- 发现：第一次合并后，下一次 `--apply` 会丢掉付费档（配置里只剩免费 upstream），
  条目又退回 `W/0.00`。
- 修法：`MERGE_FREE_GB` 分支改为**从 `wb_pricing.json` 重建 `global:<base>` 与
  `global:<base>-sg` 两个档位**，不再依赖配置里残留的条目；链路 = 免费 → 付费 SG → CN。
- 实测：连续两次 dry run / apply 都稳定输出 `W/0.03/DeepSeek-4.1-Fs`；
  alias map 的 `upstream` 为 `global:deepseek-v4.1-flash`，
  `fallbacks` 为 `[global:deepseek-v4.1-flash-sg, cn:deepseek-v4.1-flash]`；
  线上请求 200，日志链路 `free -> sg -> cn`。
- 备份：`provider_config.json.bak-alias-20261023-212838-434500`。

---

# 2026-10-23 第 N+16 轮：显示名只留型号 + 跨渠道合并链路

## 任务目标
用户要求：去掉 `W/O/Q` 与积分，同型号整合到一个口子；低于 DeepSeek 的进低耗、
高于的进高耗、免费的进免费；免费与付费同名时保留免费那条；其余名字只留型号。

## 已完成变更
- [x] 命名：`<型号>`，不再带渠道/积分；版本点号保留
- [x] 分组：免费（最低价 0）/ 低耗（0 < 最低价 ≤ 0.11）/ 高耗（> 0.11）；
      主力仍由 `MAIN_IDS` + 榜单决定并优先
- [x] 跨渠道合并：`family_entries()` 按「型号 + 协议」聚合，链路按价格升序，
      同价 GB → CN → 其它渠道；每跳自带 `base` / `channel` / `upstream` / `price`
- [x] 免费重复：单独成条加 `-F`；`deepseek-v4.1-flash` 走 `MERGE_FREE_GB` 并入付费条目置顶
- [x] 幂等：链路写回 alias map 的 `chain`，`classify` 会带回 `chain`，
      重复 `--apply` 不再丢渠道（修过一次：`MiMo-2.6-Pro` 曾因此掉出主力）
- [x] legacy：改名链传递解析（`A -> B -> C` 自动落到 C）
- [x] router：`alias.Target.Chain` + `routeChain` / `attemptBridge`，按跳切 base/key；
      旧 `base`+`fallbacks` 路径保留兼容
- [x] 删除：`merge_inventory` / `group_of` / `CHANNEL_LETTER` 等死代码
- [x] 文档：`MODEL-ALIAS.md` 重写（命名 / 链路 / 分组 / 峰谷），README、TOOLS、
      MODEL-PROVIDERS、PITFALLS、BENCHMARKS、docs 索引同步

## 验收
- 生成结果：28 个模型（主力 6 / 免费 5 / 低耗 8 / 高耗 9）；连续两次生成结果一致
- 链路示例：`DeepSeek-4.1-Fs` = WB 免费 0.00 → WB sg 0.03 → WB cn 0.11 → OC 0.11；
  `GLM-5.3-Fs` = WB 0.08（GB→CN）→ QD 0.09 → OC 0.10
- 线上（21:41 切换后）：`DeepSeek-4.1-Fs`、`GLM-5.3-Fs`、`HY3-F`、`Claude-Haiku-5.5`
  全部 200；旧名 `W/0.03/DeepSeek-4.1-Fs` 经 legacy 仍 200
- `go test ./...` 25 个用例（新增跨渠道 chain 用例）全绿；`check-docs` / `check-secrets` 通过

## 待解决 / 注意事项
- 分组基准 0.11 是固定常数；DeepSeek 调价后需要手动改 `LOW_MAX`
- 同名不同协议目前用 `-Msg` / `-Resp` 兜底，当前没有触发
- 峰谷价现在只影响链路顺序与分组归属，不再改显示名

## 状态: 已完成

---

# 2026-10-23 第 N+17 轮：Flash/-Free 命名、按消耗排序、自动化同步报告

## 任务目标
用户要求：`Fs` 改回 `Flash`、`-F` 改 `-Free`；组内按积分消耗从低到高排，同厂商粘块、
按该厂商最便宜的那条定位；自动化结束后输出 markdown 说明新增、改文档并推送。

## 已完成变更
- [x] `ABBR` / 兜底缩写：`-Fs` → `-Flash`；免费后缀 `-F` → `-Free`
- [x] 组内排序：`(厂商最低价, 厂商顺序, 价格, 名字)`，同厂商聚块
- [x] 新增 `tools/sync_report.py`：对比 `~/.zcode/v2/model-sync-state.json`，
      输出新增 / 移除 / 分组变化 / 链路变化；`--write` 写 `docs/reports/MODEL-SYNC-<时间>.md`
      并更新索引与快照，`--push` 执行 `git add/commit/push`
- [x] 新增 `docs/reports/README.md` 索引并接入 `docs/README.md`
- [x] `MAINTENANCE.md` §6 的每日自动化补第 ⑤ 步；`TOOLS.md` 增加工具条目
- [x] 线上应用：28 个模型（主力 6 / 免费 5 / 低耗 8 / 高耗 9），无需重启 zgate

## 验收
- 线上 `DeepSeek-4.1-Flash`、`HY3-Free`、`GLM-5.3-Flash` 均 200
- 排序：低耗 = Muse 0.04 → HY 0.05/0.11 → MiMo 0.06 → GLM 0.08 → MM 0.08 → GPT 0.09
- `sync_report.py`：首轮基线、次轮 0 变化、人工扰动后能报出新增/分组/链路变化
- `check-docs` 27 篇通过

## 待解决 / 注意事项
- ZCode 的定时任务本体（`automation-3e2f8a53…`）无法从仓库侧修改；
  需要把 `python tools/sync_report.py --write --push` 加到自动化提示词最后一步
- 本轮改动尚未提交/推送；`--push` 的提交范围只有 `docs/reports/`

## 状态: 已完成

---

# 2026-10-26 第 N+18 轮：zgate 登录自启零窗口（GUI 子系统）+ 修管道吞输出

## 任务目标
用户反馈：开机弹 cmd 窗口、中文乱码；并问 zgate 为何不跟随 ZCode 启动。
结论：设计本就要求 GUI 子系统无窗构建，但已发布的二进制是裸 `go build` 的
控制台程序；乱码是 UTF-8 日志 tee 进 GBK 控制台；跟随 ZCode 的方案 0.3.0
已按 [ARCHITECTURE.md](docs/ARCHITECTURE.md) §10.2 有意放弃（19 MB 常驻换
签到窗口与 ZCode 解耦），维持登录自启。用户确认后按 GUI 子系统重编译落地。

## 已完成变更
- [x] `gateways/zgate/internal/winproc/console_windows.go`：`AttachParentConsole`
      改为先判 `GetStdHandle`+`GetFileType` —— 管道/文件句柄保留原样（旧逻辑
      无条件重绑 CONOUT$，mintty/CI/脚本/`> 文件` 场景输出被吞进隐藏 conhost），
      仅句柄无效或本就是控制台时才 attach 父控制台
- [x] 重编译 `zgate.exe`：`go build -C gateways/zgate -ldflags "-H windowsgui"
      -o zgate.exe .`（`file` 验证为 GUI 子系统；exe 不入库）
- [x] `zgate.json`、启动文件夹快捷方式零改动（GUI 下 WindowStyle 自然失效）
- [x] 文档：`MAINTENANCE.md` §8.1 加「重新构建 zgate」命令行 + 无窗行为与
      忘带 flag 的后果说明（构建命令正本）；`CHANGELOG.md` 0.3.0 追加
      「登录自启零窗口落地」小节；`docs/release-notes/0.3.0.md` 补一行
- [x] 顺带修复：`CHANGELOG.md` 0.3.0 段落四个小节整块重复的历史残留（并发写坏），
      删 70 行（两块 diff 字节级一致，删任一份等价，保留带正文的 Pre 节）

## 验收
- `go vet` / `gofmt -l` / `go test ./...`（bridge/alias/router/supervisor）全绿
- `zgate.exe version`/`status`：Git Bash 管道、cmd `> 文件` 重定向均正常输出
- 分离启动后 `MainWindowHandle=0`（无任何窗口）、`/health` 200（28 个 alias 模型、
  三上游 key 齐、两子进程按需未起 —— 不在签到窗口内，符合预期）
- 日志文件 `%LOCALAPPDATA%\ZCodeGateway\zgate.log` UTF-8 正常，无控制台 tee
- `python tools/check-docs.py`（27 篇）、`python tools/check-secrets.py`（125 文件）通过

## 待解决 / 注意事项
- 修复前那次启动（今早 07:40）的进程 07:47 被 terminated —— 用户关掉了弹出的
  控制台窗口即杀网关，正是本轮要消除的故障路径；07:54 起新实例已无窗运行
- `gateways/zgate/zgate-next.exe` 是 0.3.0 开发期被文件锁时的暂存产物（仍为
  控制台程序、未被任何脚本引用），可手动删除
- 0.3.0 尚未打 tag，本轮并入 0.3.0 段落；`zgate` 二进制内版本串仍是 0.3.0

## 状态: 已完成

---

# 2026-10-26 第七轮：五段模型同步（Go / WorkBuddy / Qoder / 命名 / 报告）

## 任务目标
按用户给定五段流程把 OpenCode-Go 套餐、WorkBuddy2API 网关、Qoder 新模型收录进
ZCode（不改脚本、不动 provider_config.json、不建定时任务）。

## 已完成变更
- [x] **Step 3 Qoder 已完成并落盘**：8790 子代理被 zgate 按策略停掉（08:17 不在
      签到窗口），先 `start-qoder-proxy.bat` 起 `qoder_proxy.py`（本地、可逆，
      有 `stop-qoder-proxy.bat`），`8790/ping=pong` 后重探。
- [x] Qoder 探测 8 个全 `ok`（DeepSeek-Flash / Qwen3.8-Flash / GLM-5.3-Flash /
      MiniMax-M3.1-Flash / DeepSeek-V4-Pro / Qwen3.8-Max / GLM-3.5 / Kimi-K2.8-Preview），
      经 7871 统一入口真实 body 探测，全部 200。
- [x] Qoder 合并写盘：免代 +2、低耗 +2、高耗 +4（共 8 个 `qoder:` 前缀模型）；
      备份 `provider_config.json.bak-qoder-merge-20261026-082520`。

## 阻塞处理（用户拍板「恢复+根治」后的处置）
- [x] `tools/model_alias.py` 三处修复：`inventory()` / `raw_models()` 跳过非管理的
      4 组之外的 provider（避免保留 provider 的裸 id 被重复归并成显示名）；
      写入段保留非管理 provider 及其模型规则，`providerOrder` 追加而非截断。
      此前每跑一次 Step4 就把 `opencode-go-messages` / `opencode-go-responses` /
      `opencode-go-chat-backup` 三个 provider 清掉，是本轮 Step1/2 崩溃的根因。
- [x] 从 `bak-gosync-20261023-000011` 把 3 个 provider 及 11 条模型规则写回 live
      配置（先做安全备份 `bak-restore3-20261026-083619`），providerOrder 恢复 7 个。
- [x] Step1 重跑成功：建议收录 5 个（deepseek-v4.1-flash、glm-5.3-flash →
      chat-fast；longcat-2.0、mimo-v2.6-pro、minimax-m3.1-flash → chat-slow；
      minimax-m2.7 已随恢复的 messages provider 在册，不再重复收录），体检无
      ⚠/✗（首轮 5 个 ✗ 消失：协议模型回到各自协议 provider，不再被误用 chat 探测）。
      备份 `bak-gosync-20261026-083732`。
- [x] Step2 重跑成功：18 个 WB 模型并入（主力 2 / 低耗 6 / 免费 5 / 高耗 3 /
      备用 2），37 个排除。备份 `bak-wbproxy-20261026-083751`。
- [x] Step4（打补丁后）成功：四组 30 个显示名（6/5/9/10）；备份
      `bak-alias-20261026-083818-404500`，alias map 已写。
- [x] Step5 成功：报告 `docs/reports/MODEL-SYNC-20261026-0838.md` 已推送。

## 更正：3 个 provider 是用户主动删掉的，不是丢失
- 用户指出「对话 / 响应 / 备用」（`opencode-go-messages` / `-responses` /
  `-chat-backup`）是他早就删掉的 —— 它们正是 `model_alias.py` 每次收尾时把
  非 4 成本档 provider 折叠进 4 组后删除的结果（原行为，不是 bug）。
- [x] 已从 live 配置删除这 3 个 provider 及其 11 条模型规则（安全备份
      `bak-drop3-20261026-085017`），恢复为用户要的 4 个成本档组：6/5/9/10=30 个
      显示名（只丢 `minimax-m2.7`，它本就不在用户配置里）。
- [x] 已 `git checkout -- tools/model_alias.py` 回退本轮对它的改动（保留
      fold-and-wipe 原行为）。
- ⚠️ **遗留**：`go_model_sync.py` 仍把 messages 协议模型写入
  `opencode-go-messages`、responses 写入 `opencode-go-responses`；
  `workbuddy_zcode_sync.py` 仍把备用档写入 `opencode-go-chat-backup`。这 3 个
  provider 不在时，这两个脚本下次 `--apply` 仍会 `provider not found` 崩溃。
  要彻底去掉这 3 个 provider，需改这两个脚本的落点策略（跳过 messages/responses
  协议、备用档并入 chat-slow 等），属独立改动，待用户决定。

## 根治：脚本解耦 3 个 provider，全部按成本进 4 组（用户授权「符合分组理念去修」）
- [x] `go_model_sync.py`：
  - `CHAT_PROVIDER["备用"]` 与 `BACKUP_PROVIDER` 改为 `opencode-go-chat-slow`；
    `reclassify_backup` 不再 `ensure_provider`/改 providerOrder，直接并入高耗。
  - 新模型不再按协议分流：messages / responses 也走 `CHAT_PROVIDER[tier]`，
    删除 `MESSAGES_PROVIDER` / `RESPONSES_PROVIDER` 及「响应」重命名分支。
  - 体检按 alias map 的真实 `protocol` 探测（`probe_targets` 返回三元组 +
    `_probe_protocol`），消除「用 chat 探 messages 模型」的假 ✗。
  - 新增协议提示缓存 `providers/opencode-go/cache/go_protocols.json`
    （`{model: chat|messages|responses}`，.gitignore 已排除），供 model_alias 兜底。
  - 修潜伏 bug：`row` 在「按名含 free 兜底价格」前就捕获了 `price`，导致免费模型
    打印时 `AttributeError: 'NoneType'`；把 `row` 创建挪到价格解析之后。
- [x] `workbuddy_zcode_sync.py`：`UNIFIED_TARGETS["backup"]` → `opencode-go-chat-slow`；
  `UNIFIED_ORDER` 只留 4 组；清理循环对重复 target 去重。
- [x] `model_alias.py`：`classify()` 对无 alias 记录的裸 OC id 读协议提示缓存
  （`protocol_hints()`），把 messages/responses 正确写进 alias map 供 zgate 桥接。
  保留其 fold-and-wipe 原行为（REMOVE_PROVIDERS 未用，实际靠覆盖 4 组删除）。
- [x] 验证：go 同步「建议收录 5」全部落进 4 组、体检零 ✗/⚠、无新建 provider；
  WB 同步备用档 2 个并入高耗；model_alias 落盘 30 个显示名（6/5/9/10），
  无裸 `cn:/global:` 残留、无残留 provider 引用。备份 `bak-gosync-20261026-091357`、
  `bak-wbproxy-20261026-091428`、`bak-alias-20261026-091433-594900`。
- [x] 端到端验证（经 7871）：messages（Claude-Haiku-5.5）、responses（GPT-6-Luna /
  GPT-5.6-Luna / Muse-Spark1.2/1.3）、chat（LongCat-2.0 / Qwen-3.7-Plus）全部 200。
  注：首次 responses 502 是测试参数 `max_tokens:8` 低于上游最小 16，非桥接 bug。
- [x] 报告 `docs/reports/MODEL-SYNC-20261026-0916.md` 已推送（30 个模型，无变化）。
- 说明：`minimax-m2.7` 在 `model_alias.py` 的 `OC_PRICES` 里是显式 `None`（无价），
  故仍不收录（符合既有定价表意图）；如需收录给它定价即可。
- 脚本改动（`.gitignore` / `go_model_sync.py` / `workbuddy_zcode_sync.py` /
  `model_alias.py`）**未提交**（按仓库约定不擅自 commit）。

## 补收 minimax-m2.7（用户问「为啥是 None」后修复）
- 原因：`OC_PRICES["minimax-m2.7"]` 是 `None` 占位 —— 当时 OpenCode 未公布价格
  （`docs/MODEL-ALIAS.md` 原文「没有公布价格，暂不收录」，`MODEL-PROVIDERS.md`
  价格栏「未列/待补」），不是上游无价。
- [x] 按锚点换算（1 credit = $3.409/M，输入输出 1:1）：($0.30+$1.20)/2 ÷ 3.409 ≈ 0.22，
      与 longcat-2.0 同价 → 高耗。`OC_PRICES["minimax-m2.7"] = {"flat": 0.22}`。
- [x] 文档同步：`docs/MODEL-ALIAS.md` 改为「价格已公布，2026-10-26 起收录」；
      `docs/MODEL-PROVIDERS.md` 该行补 0.30/1.20、备注「仅 messages 协议」。
- [x] 重跑 go 同步（`bak-gosync-20261026-092433`）+ model_alias
      （`bak-alias-20261026-092443-232600`）：`MiniMax-M2.7` 进高耗组，四组 31 个
      （6/5/9/11），alias `protocol=messages`、`price=0.22`。
- [x] 端到端经 7871 实测 `MiniMax-M2.7` 200（messages 桥接正常）。
- [x] 报告 `docs/reports/MODEL-SYNC-20261026-0924.md` 已推送（新增 1：MiniMax-M2.7）。

## 状态: 已完成
