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
