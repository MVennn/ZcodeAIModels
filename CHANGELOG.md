# 更新日志

> **一句话**：本仓每次改动记在这里 —— 改了什么、为什么、怎么回退；
> 首个版本段落记录本仓从原工作目录拆分建仓的全过程。

版本命名遵循三段式进位：**有功能更新进次版本（+0.1.0），没有就进补丁版本（+0.0.1）**；
破坏性变更同样走次版本，并在版本段落里显式标注。进位规则正本见
[docs/VERSIONING.md](docs/VERSIONING.md) §1 与 §2。

- 「功能更新」= 新增了脚本 / 新增了 provider 分组 / 现有脚本的行为变了。
- 只修 bug、改文档、调参数 → **+0.0.1**。
- 本仓库**没有编译产物**，版本号以本文件的段落标题为准
  （与 `docs/release-notes/<versionName>.md` 的文件名必须一致；文件名**不带 `v` 前缀**，
  发版 tag 才带 —— 口径见 [docs/VERSIONING.md](docs/VERSIONING.md) §3）。

---

## [未发布]

### 显示名压缩为 `W/0.03/DeepSeek-41-Fs`（2026-10-23）

- 模型 ID 从 `渠道 : 型号 : 积分` 改为 `单字母/积分/紧凑型号`：`W` WorkBuddy、
  `O` OpenCode-Go、`Q` Qoder；型号去掉版本里的 `V` 和点、`Flash` 缩写为 `Fs`
  （`DeepSeek-41-Fs`、`Qwen-38-Fs`、`GLM-53-Fs`、`MiniMax-M31-Fs`、`MiMo-26-Fs`、
  `Claude-Haiku-55`）。
- `model_alias.py` 新增 `CHANNEL_LETTER`，`ABBR` 全部换成紧凑名；alias map 的
  `legacy` 保留旧空格 ID，老会话仍可路由。
- 重新生成四组：仍是 36 个模型，主力 7 / 免费 5 / 低耗 13 / 高耗 11；
  新 ID 经 7871 实测 200，旧 ID 也仍 200。
- 文档/记忆中的示例同步为新格式。

### 主力按外部榜单自动扩充（2026-10-23）

- 新增 `tools/arena_leaderboard.py`：拉 ArenaGalleri 实时榜
  （`https://api.arenaofbias.icu/api/leaderboard`，10 分钟刷新），以
  `deepseek-v4.1-flash` 为基准，筛出「分数 ≥95%、积分 ≤0.11、非临时、≥50 局、
  积分 >0」的**已配置模型**，写 `~/.zcode/v2/arena-main.json`。
- `tools/model_alias.py` 新增 `--arena-main` / `--no-arena`：默认读候选文件，
  按 `(channel, upstream)` 扩充主力；alias map 条目增加 `main_reason`
  （`manual` / `arena`）。顺手修复 `--probe-file` 分支里 `transient_kept` 未初始化、
  一旦命中「改名未探测」就 `NameError` 的隐患。
- 2026-10-23 首次扩充：主力 4 → **7**，新增
  `OC : MiMo-V2.6-FS : 0.06`（1112 分，基准 101.1%）、
  `WB : Space-Bunny : 0.08`（1075，97.7%）、
  `OC : Claude-Haiku-5.5 : 0.09`（1064，96.7%）；三个模型经 7871 实测 chat 200。
  免费模型（0 积分）仍留在免费组；榜单掉出窗口会自动退回原组。
- 榜单接口失败时用本地缓存；候选集合或规则没变时不重写配置，分数波动不会引起
  模型 ID 抖动。
- 文档：`BENCHMARKS.md` 新增 §8（接口、口径、候选表、名字映射边界与回退），
  `MODEL-ALIAS.md` §4.2 / §6 / §7、`TOOLS.md`、`MAINTENANCE.md` §2.1、`README.md`
  同步更新。

### 同步脚本：免费 `-f` 模型漏收修复 + 「跑不通即清」策略（2026-10-23）

- 修复 `workbuddy/workbuddy_zcode_sync.py` 的 `rate_of()` —— 原先只重新解析原始
  `credits` / `promo_credits` 字符串，免费 `-f` 模型（网关 `credits` 为空串）被判
  `None`，按「无公布倍率」排除。改为优先信任价格表已归一化的 `eff_rate` / `list_rate`
  （`wb_pricing.json` 本就是分档的唯一价格输入），缺失才回退原始串解析。
  结果：`cn:hy4-preview-f`、`global:hy4-preview-f` 收进免代档（免代 5 → 7，其余档零位移）
- 调整 `opencode-go/ops/go_model_sync.py` 的 `stale_reason()` —— 已配置模型体检从
  「400/402/404 且带 unavailable 标记才移除」收紧为：`error` 类里仅豁免
  **401（凭据/隐私授权）** 与 **429（限频冷却）**，其余 400/402/404/410 与 5xx
  一律判「跑不通」并 `prune_model`；复通后由新模型评估自动加回。
  口径：跑不通即清、复通即加回（WorkBuddy 侧本就按 blocked/unavailable 移除，未改）
- 文档对齐：`MAINTENANCE.md` §7 待办 6/7 标记已修并新增第 8 条；
  `TROUBLESHOOTING.md` §13 对应三行改为「自动处理 / 已修」；`TOOLS.md` 同步两处脚本说明

### 统一模型命名：四组 + alias map + 协议桥（2026-10-23）

- ZCode provider 统一为四组：**主力 / 免费 / 低耗 / 高耗**；`备用` 按积分并入高耗，
  `对话` / `响应` 两个协议组折入四组。
- 模型 ID 改为 `渠道 : 型号 : 积分`（`WB : DeepSeek-V4.1-FS : 0.11`、`OC : DeepSeek-V4.1-FS : 0.11`、
  `QD : GLM-5.3 : 0.69`）；价格写进显示名，调价时靠 alias map 的 legacy 兼容旧会话。
- 显示名改为可读大小写并去掉 `-f` / `-sg` / `-free`（`DeepSeek-V4.1-FS`、`GLM-5.3-FS`、
  `HY4-Preview`），价格后缀不再带 `X`。
- `model_alias.py --slot auto|peak|offpeak`：Qoder 按 `price_factor_peak/valley` 与
  22:00–08:00 窗口取价；WorkBuddy 用时段刷新后的 `eff_rate`。08:00 / 22:00 各重写一次
  即可让倍率随早晚变化；模型 ID 变化由 legacy map 兼容旧会话。
- WorkBuddy 的 CN/GB 合并成一个 `WB` 口子：GB 优先、GB 全不可用时路由自动回退 CN；
  同价 CN/GB 对合并，GB 免费/付费价档保留；显示名去掉地区并改成
  `WB : DeepSeek-V4.1-FS : 0.03`（冒号两侧有空格）。
- OpenCode-Go 的 DeepSeek V4.1 Flash / V4 Pro 加入峰谷价：峰时 UTC 周一至周五
  01:00–04:00、06:00–10:00，其余时间谷价；V4.1 Flash 峰 0.22 / 谷 0.11，
  V4 Pro 峰 0.77 / 谷 0.39。
- `Qwen3.8-Flash` 提进主力：榜单 #4 总分 372.95、积分 0.09；DeepSeek V4.1 Flash
  #11 是 342.40 / 0.11，智力与价格都更优。它走 messages 桥接，已实测 chat 200。
- 积分换算：WorkBuddy `eff_rate` 原样；OpenCode-Go 以 `deepseek-v4.1-flash`
  $0.15 入 / $0.60 出 ↔ 0.11（1 积分 = $3.409/M，1:1 混合）；Qoder `price_factor × 0.86`
  （同名模型比值中位数）。
- 新增 `tools/model_alias.py`：生成四组 + `~/.zcode/v2/model-alias-map.json`；
  `--probe-file` 只保留 ok（或曾 ok 的瞬时限流）。
- 新增 `tools/model_probe.py`：用 ZCode 真实 body（含 provider 的 `optionSpecs`
  覆盖）探测四组，经 7871，桥接模型也覆盖。
- 新增 `tools/protocol_bridge.js`：chat ↔ Anthropic Messages / OpenAI Responses，
  非流式上游 + 合成 chat SSE，支持文本、思考与工具调用。
- `tools/unified-router.js` 优先按 alias map 还原上游，旧 `cn:`/`global:`/`qoder:`
  前缀保留为 legacy 回退；`/health` 增加 alias 条数。
- `go_model_sync.py` 把 `WB:`/`OC:`/`QD:` 视作非 Go 模型跳过，避免体检误删。
- 当前 43 个模型 / 4 个 provider；37 个 ok，5 个 WB GB 模型因账号池冷却暂为瞬时限流。
- 旧的三个 sync / 两个 probe 降级为数据采集与兼容；`model_alias.py` 是唯一最终写入者。



- 新增 `qoder/` 适配器：qoder2api-hub（MIT）clone 到 `qoder/gateway/`（整目录
  gitignore），默认 `127.0.0.1:8790`；API key 与面板密码持久化在
  `accounts/settings.json`，脚本从 git-ignored 的 `qoder/.env.local` 读 `QD_API_KEY`
- Qoder CN 账号通过 OAuth 设备授权入库；`_install_umid.py` 装好签到所需的 UMID；
  启动巡检签到 +100 Credits
- 新增 `qoder/qoder_zcode_sync.py`：拉 `/v1/models` → 排除 Auto/Fast 别名 →
  按 `price_factor` 升序 → 写独立 `qoder` provider（默认 `--max-price 0.8`）；
  `--probe-file` 只保留探测 `ok` 的模型
- 新增 `qoder/qoder_probe_zcode.py`：用 ZCode 真实 body 探测，7 个模型 200；
  `Qwen3.8-Flash` 因上游 10605 排队（≈19k，p3）暂不收录，复通后自动加回；
  结果带 `ever_ok`，排队/超时不误杀曾 200 的模型（免费 `DeepSeek-Flash` 排队时 64s 后 200，也可能 90s+ 后 502）
- （`--separate` 旧模式）独立的 `qoder` provider 排在 `opencode-go-chat-free`
  之后；7 个模型未配 `optionSpecs` 覆写（原生四件套全通）
- 默认改为**合并模式**（2026-10-23 同日调整）：模型加 `qoder:` 前缀并入免费
  （price 0）/ 低耗（≤0.2）/ 高耗（>0.2）三个 chat 组；7871 路由剥前缀后转 8790；
  不再创建独立 `qoder` provider，provider 列表仍是 7 个。`--separate` 保留旧模式
- 兼容性：`go_model_sync.py` 把 `qoder:` 视作非 Go 模型跳过体检/清理；
  `workbuddy_zcode_sync.py` 的合并逻辑只清 `cn:`/`global:`，不会动 `qoder:`
- 文档：新增 `docs/QODER.md`，更新 `MODEL-PROVIDERS.md` §4.9/§5.2、`TOOLS.md`、
  `SECRETS.md`、`TROUBLESHOOTING.md` §14、`MAINTENANCE.md` §8.1、`README.md`、`NOTICE`
- 边界：WorkBuddy2API 与 OpenCode-Go 不动；Agent2API 评估后暂不采用

> 未发版，版本号不动（[docs/VERSIONING.md](docs/VERSIONING.md) §5）。

---

## [0.2.0] — 2026-10-23

### 凭据守卫（2026-10-23）

- 修复 `tools/check-secrets.py` —— `PLACEHOLDER` 命中后整行 `continue`：行内只要
  出现 `example.com` / `<...>` / `YOUR-` 就把同一行的真值一起放过。改为只豁免
  匹配片段本身（示例 URL 仍按预期放行，真 token 不再逃检）
- 验证 —— `check-secrets.py` ✓（86 个文件）、`check-docs.py` ✓（20 篇）、
  全部 `.py` `ast.parse` ✓、全部 `.js` `node --check` ✓

### 脱敏：修掉报告回显本机路径的泄漏源，补敏感信息守卫（2026-10-23）

只修脱敏与守卫，不动版本号（规则见 [docs/VERSIONING.md](docs/VERSIONING.md) §5）。

- 修复 `opencode-go/ops/go_model_sync.py` —— 两处「已写入 %s」把 `--config` 的
  绝对路径原样回显到报告里，而报告会作为 evidence 提交，于是本机用户目录
  （`C:\Users\...\provider_config.json`）进了版本库：提交 `92baac2` 的两个 evidence
  文件就是这么漏的。改为只输出 `os.path.basename(args.config)`，报告里从此只有文件名。
  报告落盘路径那行（`log("报告: %s"`）在文件写完之后才执行，不进正文，无需处理
- 新增 `tools/check-secrets.py` —— 本仓原来没有守卫，凭据规则之外多两条：
  「本机用户目录」（`C:\Users\<名字>`，正反斜杠都拦）与「真实邮箱域名」，
  都是上面这个坑的直接产物。已接入 CI 的「敏感信息扫描」步骤
- 脱敏 `evidence/go-model-sync-20261022-234800.md` 与 `evidence/go-model-sync-20261023-000011.md`
  —— 两处 `已写入 <USER>\...\provider_config.json` 改为 `已写入 provider_config.json`。
  历史提交里的旧内容不会因此消失（旧 SHA 仍可访问），要彻底清需重写历史，见 PROGRESS 待解决段

### 同步脚本自动清理失效模型（2026-10-23）

脚本行为变了，按本文件第 10 行的口径「现有脚本的行为变了 = 功能更新」；未发版，
版本号不动（规则见 [docs/VERSIONING.md](docs/VERSIONING.md) §5）。

- 调整 `opencode-go/ops/go_model_sync.py` —— 已配置模型体检从「只报告」改为
  「`--apply` 时直接移除」：上游弃用（410 / 弃用日期表）、端点不可用（402
  `Endpoint is unavailable`）、模型不支持（400 `Unsupported model`）的模型，
  连同 `personalModelIds`、`modelOrder`、`modelConfigRules` 一并删掉，报告写
  「移除」和上游原话。原来只写「建议从配置移除」，删不删全靠人盯
- 调整 `opencode-go/ops/go_model_sync.py` —— 体检跳过 `cn:` / `global:` 开头的
  WorkBuddy 模型（统一路由把它们转给网关，不属于 Go 套餐），不再把它们报成
  Go 探测异常；本轮实测清掉 4 个：`minimax-m3.1-flash-free`（410 弃用）、
  `longcat-2.0` 与 `longcat-2.5-preview-free`（402）、`mimo-v2.5-pro`（400）
- 调整 `workbuddy/workbuddy_zcode_sync.py` —— 统一模式下，不再被选中的
  `cn:` / `global:` 模型从配置删除并列出名字（原来只重排选中的，网关下架的会一直留着）
- 调整 `workbuddy/workbuddy_zcode_sync.py` —— 加残缺列表保护：网关偶尔只返回
  部分模型（本轮实测遇到一次 34/56），这时缺失的模型只报告 `kept`、不删除，
  避免把正常模型误判成已下架
- 调整 `workbuddy/workbuddy_fetch_pricing.py` —— 新列表比旧表少 30% 以上时
  拒绝覆盖旧表（退出码 2），确认是真实下架需加 `--force`，防止残缺响应覆盖价格表

### 文档骨架对齐基准仓（2026-10-22）

不动版本号（只改文档，规则见 [docs/VERSIONING.md](docs/VERSIONING.md) §5）。

- 调整 文档 —— 文件命名统一为**全大写 + 连字符**：`docs/模型速查表.md` → `docs/MODEL-QUICK-REF.md`、
  `docs/archive/OPENCODE-GO-模型与订阅优化分析.md` → `docs/archive/OPENCODE-GO-ANALYSIS.md`；
  三处文件均用 `git mv`，引用方（docs/README.md、docs/DOC-RULES.md、AGENTS.md、PROGRESS.md）
  全部改到新名。命名规则写入 [docs/DOC-RULES.md](docs/DOC-RULES.md) §1
- 调整 文档 —— `docs/release-notes/v0.1.0.md` → `docs/release-notes/0.1.0.md`：
  基准仓口径是「文件名 = `versionName`，无 `v` 前缀」；**git tag 仍是 `v0.1.0`，未动**
- 调整 文档 —— `docs/README.md` 索引重写：开头引言块与结尾提醒对齐基准仓，
  四张表的链接逐条复核，过长的一句话定位（尤其 MODEL-PROVIDERS 那行）压缩到一行读完；
  索引行长度纪律写入 [docs/DOC-RULES.md](docs/DOC-RULES.md) §6
- 调整 文档 —— `docs/VERSIONING.md` 补「§5 不发版的时候：不动版本号」（按本仓情况改写，
  含「改文件名不算发版」这一条）；§2 判断口诀与边界情况表对齐基准仓，补两条本仓边界
- 调整 文档 —— `docs/MODEL-QUICK-REF.md` 补「一句话」引言块 + 降级声明
  （结论已并入 MODEL-PROVIDERS.md，本篇保留作历史快照）
- 验证 —— `python tools/check-docs.py` 通过（20 篇）

### WorkBuddy 价格表（2026-10-22）

- 修复 `workbuddy/workbuddy_fetch_pricing.py` —— `can_disable` 读错字段名：面板实际返回
  `can_disable_thinking`，旧脚本只找 `can_disable`，缺失时默认 `false`，导致 2026-10-22
  快照把全部模型的「可关思考」写成 false，与 `docs/MODEL-PROVIDERS.md` 的 ✅ 和实测矛盾。
  归一化改为 `can_disable_thinking` → `can_disable`；重新抓取后 15 个模型为 true，
  文档表里 4 个 ✅ 模型全部对上。重抓同时看到 `cn:glm-5.2` / `cn:hy4-preview` 的夜间促销
  （0.50x / 0x），文档表仍按标准价 0.79 / 0.29，不改。

### 收尾大扫除（2026-10-22）

- 清理 磁盘 —— 删 `workbuddy/__pycache__/`（40K，`.gitignore` 已排除、可再生成）与
  `workbuddy/cache/wb_pricing.json.bak-20261022-125554`（20K，价格表自动备份，
  保留最新 `wb_pricing.json`）；仓库 53109K → 53053K
- 调整 文档 —— `docs/MODEL-PROVIDERS.md` 对齐实际配置：范围行改为 OpenCode-Go 七个 /
  WorkBuddy2API 四个；WorkBuddy 快照日期改 2026-10-22（复核无倍率 / 分档变化）；
  补 `global:deepseek-v4.1-flash`、`global:deepseek-v4.1-flash-sg` 的 effort 档位；
  `cn:minimax-m3` 输出上限 524K → 512K；§5.2 的 WorkBuddy 模型数 30 → 18
- 调整 文档 —— `docs/release-notes/README.md` 补「反馈入口」规则：加粗总结后单独一行
  绝对地址 `https://github.com/MVennn/ZcodeAIModels/issues/new/choose`，然后才是 `## 本版内容`
- 调整 文档 —— `AGENTS.md` §3 改为「有 `.codegraph/` 就优先用」，与当前工作副本一致
- 清理 文档 —— PROGRESS 与 memories 里的机场出口 IP 脱敏（补记 2026-10-22 的两笔提交）
- 验证 —— `python tools/check-docs.py` 通过（20 篇）；全部 `.py` `py_compile`、
  全部 `.js` `node --check` 通过

### Issue 表单（2026-10-22）

- 新增 `.github/ISSUE_TEMPLATE/` —— 问题反馈（Bug）与功能建议两套表单，外加 `config.yml`：
  Bug 表单要求填 ZCode 版本、provider / 模型、脚本与完整命令、输出原文，
  并确认已备份 `provider_config.json`、贴出的内容不含凭据；功能建议要求先写场景并确认只改接入层

### 自动收录定时任务修复（2026-10-22）

ZCode 的每日自动收录任务报「触发运行失败」。根因是自动化的目标会话被删了
（`target_task_id` 指向 `deleted=1` 的会话 → 派发报 `Session not found`）；
另外 10:00 的两班定时窗口因机器睡眠被跳过，ZCode 不补跑。

- 修复 自动化 —— 重建每日自动收录任务为每天 **12:00**；取网关 key 的来源从
  `provider_config.json` 的 `workbuddy-low` 改成 `workbuddy/gateway/config.json`
  的 `api_key`（统一路由并组后 `workbuddy-*` provider 已不存在，原写法抛
  `StopIteration`）
- 调整 自动化 —— 目标会话置空：ZCode 派发走 `createTask` 分支，**每次运行新建
  独立会话**，上下文不再累积（该字段只读不写回，解绑永久）
- 验证 —— 12:00 那班 `dispatched → succeeded`；Go 建议收录 0 个、配置未改动；
  WorkBuddy 18 个模型并入五个 chat 组，与同步前逐个对账一致
- 调整 文档 —— MAINTENANCE §6 每日任务改 12:00 并补 key 来源、§7 登记两条脚本
  待办；TROUBLESHOOTING 补 §13「每日自动收录的体检刷出一片 400 / 403」
- 新增 数据 —— 两份 Go 同步报告（`evidence/go-model-sync/go-model-sync-20261022-*.md`）

### 守护器生命周期加固（2026-10-21 深夜）

排查「关掉 ZCode 后 wb2api 还在」：停止分支本来就有（当天 23:51 实测停过一次），
真正的问题是主进程只按 PID 判活、ZCode 退出后 2–5 秒又被拉起会**静默**取消停止、
守护器不在场时遗留的网关 / 路由没人清。

- 修复 脚本 —— `workbuddy/zcode_gateway_watch.ps1` 主进程改用**进程句柄**判存活
  （`Process.HasExited`），PID 被系统复用不再把已退出的 ZCode 误判成还在跑；
  连续两次认不出主进程才按退出处理
- 修复 脚本 —— **启动对账**：守护器启动时若没有 ZCode 主进程却还有网关 / 路由在监听，
  按遗留进程清掉（`-KeepOrphans` 可跳过，用于手动常驻网关）
- 修复 脚本 —— 停止时若没接管过 pid，按端口反查网关 / 路由再校验进程名与命令行，
  上次守护器留下的孤儿不会漏杀
- 调整 脚本 —— 宽限期 / 排空期 ZCode 回来都会写日志并取消停止（排空期回来还会把已停的
  统一路由立刻拉回）；排空上限默认 `30` → `5` 秒
- 新增 脚本 —— 每 15 分钟一条心跳日志（`-HeartbeatSeconds`），日志里没有心跳即说明守护器没了；
  `-Status` 增加脚本版本、守护器 pid，并在守护器进程早于脚本修改时间时提示「加载的是旧代码」
- 调整 文档 —— TOOLS / MAINTENANCE §8 / TROUBLESHOOTING §11 同步；补「关窗 ≠ 退出」

### 门面统一批次（2026-10-21）

在「README 收敛批次」之后再收一轮：门面压到与 GSAuxiliary 同款的七节，
开发者内容继续下沉 `docs/`，门面资源（logo / 社交预览）统一由 `assets/icon.svg` 渲染。

- 调整 文档 —— 根 README 收敛为七节（这是什么 / 环境要求 / 使用 / 反馈 / 免责声明 / 开源鸣谢 / 许可证）；
  顶部不写「一句话」引言块，定位由副标题承担（对齐 GSAuxiliary）
- 调整 文档 —— 「接一个新的模型供应商」四步下沉 [docs/MODEL-PROVIDERS.md](docs/MODEL-PROVIDERS.md) §0；
  `provider_config.json` 的三个落点与两个 `--apply` 脚本的写入差异下沉同篇 §1 / §1.1；统一路由下沉 [docs/TOOLS.md](docs/TOOLS.md) §2
- 新增 工具 —— `tools/make_social_preview.py`：自带 SVG 渲染器，从 `assets/icon.svg` 生成
  `assets/logo.png`（512×512）与 `assets/social-preview.png`（1280×640），不依赖 cairosvg 等外部程序
- 调整 资源 —— `assets/logo.png` 改为由 `assets/icon.svg` 渲染，图形不再有两份正本
- 调整 文档 —— `docs/DOC-RULES.md` 正本映射表与 `docs/README.md` 索引同步；
  各仓 docs 里指向根 README 章节的文字引用改指新正本
- 调整 仓库 —— GitHub 仓库描述与话题改成面向使用者的口径（与 README 副标题同调）

---

## [0.1.0] — 2026-10-21

本仓**首次建仓**：从同级的「OpenWrt 工作目录」里把
**AI 模型接入**这一条线整体拆出来，成为独立仓库 `ZcodeAIModels`。

拆分只做两件事：**搬文件** 与 **补文档**。**没有改动任何脚本逻辑**，
**没有改动 ZCode 的 `provider_config.json`**，也没有动原目录里的其它线
（路由器运维、ShellCrash、前端控制台等仍留在 OpenWrt 工作目录）。

### 调整

- 调整 仓库 —— 从 OpenWrt 工作目录拆出独立仓库 `ZcodeAIModels`，可独立上传 GitHub。
- 调整 目录 —— `opencode-go/ops/`：长期运维脚本（模型自动收录 + 请求头注入代理）。
- 调整 目录 —— `opencode-go/probe/`：一次性探测脚本（连通性 / 协议 / 基准 / 关思考）。
- 调整 目录 —— `opencode-go/probe/archive/`：已被取代的 `validate_zcode_models.py`。
- 调整 目录 —— `opencode-go/probe/results/20261019/`：探测原始结果快照（本地留存，不随仓库分发）。
- 调整 目录 —— `workbuddy/`：WorkBuddy2API 接入脚本 + 活数据缓存 + 日志。
- 调整 目录 —— `workbuddy/archive/`：已被取代的旧探测脚本与旧缓存。
- 调整 目录 —— `evidence/`：网关模型目录快照与自动收录报告。
- 调整 脚本 —— `go_model_sync.py`：从 `scripts/` 迁入 `opencode-go/ops/`。
- 调整 脚本 —— `opencode-header-proxy.js`：从 `scripts/` 迁入 `opencode-go/ops/`。
- 调整 脚本 —— `probe_models.py`：从 `scripts/` 迁入 `opencode-go/probe/`。
- 调整 脚本 —— `probe_protocols.py`：从 `scripts/` 迁入 `opencode-go/probe/`。
- 调整 脚本 —— `bench_models.py`：从 `scripts/` 迁入 `opencode-go/probe/`。
- 调整 脚本 —— `bench_clean.py`：从 `scripts/` 迁入 `opencode-go/probe/`。
- 调整 脚本 —— `thinking-off-probe.js`：从 `scripts/` 迁入 `opencode-go/probe/`。
- 调整 脚本 —— `validate_zcode_models.py`：从 `scripts/` 迁入 `opencode-go/probe/archive/`。
- 调整 脚本 —— `workbuddy_probe_zcode.py`：从 `scripts/` 迁入 `workbuddy/`。
- 调整 脚本 —— `workbuddy_zcode_sync.py`：从 `scripts/` 迁入 `workbuddy/`。
- 调整 脚本 —— `zcode_effective_body.js`：从 `scripts/` 迁入 `workbuddy/`（仍与探测脚本同目录，硬依赖未破）。
- 调整 脚本 —— `workbuddy_probe_models.py`：从 `scripts/` 迁入 `workbuddy/archive/`（已被取代）。
- 调整 数据 —— `wb_pricing.json`：从 `scripts/` 迁入 `workbuddy/cache/`（活数据）。
- 调整 数据 —— `wb_zcode_probe.json`：从 `scripts/` 迁入 `workbuddy/cache/`（活数据）。
- 调整 数据 —— `wb_zcode_probe.log`：从 `scripts/` 迁入 `workbuddy/logs/`。
- 调整 数据 —— `wb_model_status.json`：从 `scripts/` 迁入 `workbuddy/archive/`（已被取代）。
- 调整 数据 —— `wb_probe_rerun.log`：从 `scripts/` 迁入 `workbuddy/archive/`（一次性日志）。
- 清理 数据 —— `wb_probe_rerun.log`：一次性探测日志，结果已由 `wb_model_status.json`
  与 `workbuddy/cache/wb_zcode_probe.json` 覆盖，2026-10-21 删除。
- 调整 数据 —— `probe_results.json` / `bench_results.json` / `bench_clean.json`：从 `scripts/` 迁入 `opencode-go/probe/results/20261019/`。
- 调整 数据 —— `wb_panel_models.json`：从原 `audit/` 迁入 `evidence/`。
- 调整 数据 —— `go-model-sync-*.md`（5 份）：从原 `audit/` 迁入 `evidence/go-model-sync/`。
- 调整 文档 —— 新增根 `README.md`（门面：这是什么 / 适用环境 / 快速开始 / 文件清单 / 已知坑）。
- 调整 文档 —— 新增根 `AGENTS.md`（机器协议：PROGRESS 按逻辑任务分家 / 凭据走环境变量 / CodeGraph）。
- 调整 文档 —— 新增根 `CHANGELOG.md`（本文件）与根 `NOTICE`（第三方声明）。
- 调整 文档 —— 新增根 `.gitignore`（排除凭据、缓存、日志、大体积探测结果与字节码）。
- 调整 文档 —— 新增 `docs/README.md`（docs 唯一索引，四类分区）。
- 调整 文档 —— 新增 `docs/DOC-RULES.md`（文档规则正本）。
- 调整 文档 —— 新增 `docs/MODEL-PROVIDERS.md`（provider 分组 / 协议 / 工具调用 / 关思考参数矩阵的正本）。
- 调整 文档 —— 新增 `docs/PITFALLS.md`（踩坑总汇）。
- 调整 文档 —— 新增 `docs/TROUBLESHOOTING.md`（排错手册，现象 → 排查步骤 → 原因 / 解法）。
- 调整 文档 —— 新增 `docs/MAINTENANCE.md`（价格表刷新 / 探测限速 / 快照保留 / 备份回退 / 热重载注意事项）。
- 调整 文档 —— 新增 `docs/release-notes/README.md`（Release 说明格式正本）与 `docs/release-notes/0.1.0.md`（首版说明；当时文件名带 `v` 前缀，2026-10-22 统一去掉）。
- 调整 进度 —— 根 `PROGRESS.md` 承接本仓唯一进度台账（追加式批次日志）。
- 调整 进度 —— 原 `PROGRESS.workbuddy.md` 归档到 `evidence/`，作为 WorkBuddy 接入线的历史台账。

### 修复

- 修复 凭据外置 —— OpenCode-Go API key 从源码移到**环境变量**：
  `opencode-go/probe/` 下 **5 个探测脚本**（`probe_models.py`、`probe_protocols.py`、
  `bench_models.py`、`bench_clean.py`、`thinking-off-probe.js`）里的明文 `oc_sk_…`
  **全部删除**，改为 `os.environ.get("OPENCODE_GO_KEY")` /
  `process.env.OPENCODE_GO_KEY`；**未设置时明确报错退出**，不再带着空 key 去请求
- 修复 文档 —— [README.md](README.md) 的「适用环境」与「快速开始」补 `OPENCODE_GO_KEY`，
  「已知坑」第 6 条从「仍有明文 API key」改为「已改为环境变量读取，未设置时明确报错」

> 新增的环境变量：**`OPENCODE_GO_KEY`**（必填）。
> 复核结果：本仓已**不再有任何明文 key**（`oc_sk_` 全文检索无命中）。

### 待补

- `LICENSE` —— **已补**：仓库根的 MIT 全文（见 [LICENSE](LICENSE)）。
- `docs/VERSIONING.md` —— **已补**：版本晋升规则的独立正本（见 [docs/VERSIONING.md](docs/VERSIONING.md)）。
- ~~待补 `workbuddy_fetch_pricing.py`~~ —— **已补**：`workbuddy/workbuddy_fetch_pricing.py`
  从网关 `/panel/api/models` 拉价格、归一化后写入 `cache/wb_pricing.json`（写前自动备份），
  并打印倍率变化 / 新增 / 下架的摘要；`--dry-run` 可只看不写。
  归一化后的字段集与既有价格表**完全一致**（合成数据自测通过）。
- ~~待补 路径修正~~ —— **已修**：`go_model_sync.py` 的报告目录改为本仓内 `evidence/`，
  可用 `GO_SYNC_REPORT_DIR` 覆盖；`workbuddy_probe_zcode.py` 与 `workbuddy_zcode_sync.py`
  的价格表 / 探测缓存默认路径改为 `cache/`（拆仓时漏改，本次补上）。

### 新增

- 新增 `workbuddy_fetch_pricing.py` —— WorkBuddy 侧；`python workbuddy_fetch_pricing.py`
  一条命令刷新价格表，取代手工维护（详见 `docs/MAINTENANCE.md` §1.3）。

### 通用化（2026-10-20）

> 这一轮把仓库从「只对某一台机器/某一个人成立」改成「**任何用 ZCode 的人都能照着做**」。
> **规则与做法用通用措辞；WorkBuddy2API 与 OpenCode-Go 这两个具体实例单列。**

- 调整 定位 —— 根 [README.md](README.md) 从「把 OpenCode-Go 与 WorkBuddy2API 接进 ZCode」
  改成「把**任意**模型供应商接进 ZCode（以这两个为例）」，并新增
  「通用方法：接一个新的模型供应商」四步（摸清接口面 → 归一化价格表 → 用 ZCode 真实 body 探测 → 分档写配置）。
- 调整 文档 —— [docs/MODEL-PROVIDERS.md](docs/MODEL-PROVIDERS.md) 新增 §0「接一个新的模型供应商」
  与「通用概念 ↔ 本仓叫法」对照表；§2 / §4 标注为本次实例。
- 调整 文档 —— [docs/MAINTENANCE.md](docs/MAINTENANCE.md) §1 拆成「§1.1 通用做法（换供应商照这个做）」
  + 「§1.2 / §1.3 两个实例」，并给出「取目录 → 归一化 → 写盘 + 变动摘要」的三步通用做法。
- 调整 文档 —— [docs/SECRETS.md](docs/SECRETS.md) 凭据位置表补一行「其它供应商的凭据」，
  明确**任何**供应商的凭据都只走环境变量，并给出加新供应商时的三步清单。
- 调整 文档 —— [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) 与
  [docs/PITFALLS.md](docs/PITFALLS.md) 每条加【通用】/【实例 A】/【实例 B】标记，
  区分「换供应商也成立」与「只有本仓实例才有」。
- 修复 路径 —— 文档与脚本里的**本机绝对路径**（写死的用户名主目录、旧仓库目录）改为
  仓内相对路径 / `~/.zcode/...` / 按脚本位置与当前用户主目录推导。
- 修复 路径 —— `go_model_sync.py` 的 ZCode 配置路径默认值改为按当前用户主目录推导
  （**在本机解析结果不变**），仍可用 `--config` 覆盖。
- 调整 文档 —— `PROGRESS.md`、`evidence/PROGRESS.workbuddy.md` 里的设备型号改为通用措辞
  （历史探测结论与数据一律保留原样，并保留采集时点）。
- 调整 文档 —— `memories/` 下四个文件里的绝对路径改为仓内相对路径。

### README 收敛批次（2026-10-21）

参照系列仓 gsauxiliary 的门面格式，把根 `README.md` 收敛为**面向用户**的说明，
开发者向的内容下沉 `docs/`：

- 调整 文档 —— 根 README 顶部去掉「一句话」引言块，门面定位由副标题承担（对齐 gsauxiliary）；`tools/check-docs.py` 同步豁免根 README 的引言块检查

- 调整 文档 —— 根 README 重写为 logo 头 + 徽章 + 这是什么 / 适用环境 / 快速开始 /
  接一个新的模型供应商（四步概览）/ 与 ZCode 的关系 / 反馈 / 免责声明 / 开源鸣谢 / 许可证；
  删掉「文件清单」「目录结构」「已知坑」「记忆文档」「参与与治理」等开发者向章节
- 调整 文档 —— 新增 [docs/TOOLS.md](docs/TOOLS.md)：工具清单**正本**（产物与去留标记），
  取代原根 README 的「文件清单」；「已知坑」统一看 [docs/PITFALLS.md](docs/PITFALLS.md)
- 调整 文档 —— DOC-RULES / MAINTENANCE / MODEL-PROVIDERS / docs/README 里指向根 README
  「文件清单 / 已知坑」的引用，同步改指新位置
- 修复 CI —— 当时的流水线配置只定义了隐藏模板 `.python`、没有任何可见作业，
  流水线一创建就失败（零作业）；改为语法与文档两组真实作业

### 反代排序批次（2026-10-21）

WorkBuddy2API 三个 provider 的模型顺序改为「主力置顶 → CN 优先 → 按厂商分组」：

- 变更 脚本 —— `workbuddy_zcode_sync.py`：新增 `PINNED_MODEL_IDS` / `VENDOR_ORDER` /
  `model_sort_key()`，`personalModelIds` 与 `modelOrder` 按新规则排序；
  新增 `--reorder-only`（只重排，不改成员与档位）
- 变更 配置 —— 界面顺序改为 低代 → 免代 → 高代；低代首位固定 `cn:deepseek-v4.1-flash`
- 修复 排序 —— 原「全表按倍率升序 + id」把 CN/全球与不同厂商打散，
  主力 `cn:deepseek-v4.1-flash` 落到低代第 8 位
- 调整 文档 —— MODEL-PROVIDERS §4.2–§4.5、TOOLS 同步；记录促销漂移
  （`cn:hy4-preview` 已 `0x`、`cn:glm-5.2` 促销 x0.50，下次完整同步再改档）

### 自动收录扩展批次（2026-10-21）

- 变更 自动化 —— 每天 10:00 的收录任务从「只跑 Go」扩展为「Go + WorkBuddy」：
  执行 `go_model_sync.py --apply`、`workbuddy_fetch_pricing.py`、
  `workbuddy_probe_zcode.py --max-rate 0.3 --sleep 20`、
  `workbuddy_zcode_sync.py --max-rate 0.3 --apply`
- 变更 分档 —— WorkBuddy 收价上限从 0.80 收到 **0.30**（以主力 x0.11 锚定）：
  低代只留 ≤0.16 的主力价位；0.17–0.30 归高代；原高代 x0.50–0.79（4.5–7.2 倍）
  整组移出，自动收录也不再引进
- 修复 自动化 —— 旧任务 `automation-5ad749e3…` 指向已删除的 `F:\Project\Openwrt`，
  已停用；新任务 `automation-cfcb5c6d…` 绑定当前仓库
- 调整 文档 —— MAINTENANCE §6 定期动作同步为双线

### 网关随 ZCode 起停批次（2026-10-21）

反代（`wb2api`）不再需要手动开 cmd 拉起，网关寿命跟随 ZCode：

- 新增 脚本 —— `workbuddy/zcode_gateway_watch.ps1`：无窗口守护器。ZCode 启动 →
  静默拉起 `wb2api`（清空 HTTP(S)_PROXY，与 `run.bat` 一致）；ZCode 全部退出 →
  宽限 8 秒后停网关；运行期间每 15 秒探活，网关挂了自动重启（失败退避 60 秒）
- 新增 脚本 —— `workbuddy/zcode_gateway_watch.vbs`：wscript 无窗口启动上述 ps1，
  不出现控制台窗口
- 新增 开关 —— `-Install` 在启动文件夹注册快捷方式（登录自启）并立即启动守护器；
  `-Uninstall` 移除自启并停守护器；`-Status` 一次看 ZCode / 网关 / 守护器；
  `-DryRun` 只记状态迁移，用于验证状态机
- 调整 文档 —— TOOLS、MAINTENANCE §8、TROUBLESHOOTING §11、docs/README、
  README 适用环境、MODEL-PROVIDERS §4
- 注意 —— 网关的定时任务（签到 / 保活 / 夜猫子）只在网关进程活着时执行；
  绑到 ZCode 生命周期后，ZCode 不在的时段不会跑（详见 MAINTENANCE §8）

### 网关目录并入本仓批次（2026-10-21）

反代网关的整个 clone 搬进仓库，不再维护两个目录：

- 变更 目录 —— `E:\Tool\AITool\workbuddy2api-panel` → `workbuddy/gateway/`
  （含上游 `.git`、`config.json`、`auths/`、`data/`、`wb2api.exe`）；旧目录已删除
- 变更 忽略 —— 主仓 `.gitignore` 整目录排除 `workbuddy/gateway/`（账号凭据、密钥、
  运行时状态、二进制都不进公开仓库）；网关仍可用
  `git -C workbuddy/gateway pull --ff-only` 更新
- 变更 脚本 —— `zcode_gateway_watch.ps1` 的默认网关目录改为按脚本位置推导
  `<仓库>/workbuddy/gateway`（`WB_GATEWAY_DIR` 仍可覆盖）
- 变更 工具 —— `tools/check-docs.py` 跳过 `workbuddy/gateway/`（不入库的上游 clone）
- 调整 文档 —— MAINTENANCE §8（更新 / 重建网关目录的步骤）、TOOLS、SECRETS、
  TROUBLESHOOTING §11、NOTICE
- 说明 —— 上游检查：`origin/main` = 本地 `6b31db6`，无新提交，未产生 pull 变更

### 网关 ↔ ZCode 联动优化批次（2026-10-21）

守护器从「按进程名数数」升级为「盯主进程 + 就绪判定 + 排空」：

- 变更 判据 —— 只跟随 ZCode **主进程**（命令行既不含 `--type=` 也不含 `zcode.cjs`）；
  GPU / renderer / crashpad / CLI 宿主晚退不再拖住网关
- 变更 启动 —— 轮询 1000 → 500 ms；就绪判定从「TCP 端口打开」改为 `/panel/` 返回 200；
  网关 stdout / stderr 每次启动前轮转为 `.1`
- 新增 停网关前排空 —— 最多等 `-DrainTimeoutSeconds`（默认 30 秒）让在途连接结束；
  宽限期内 ZCode 重新打开则取消停止
- 新增 联动检查 —— `-Status` 增加 ZCode 主进程 PID、网关就绪状态，并校验
  `workbuddy-*` 三个 provider 的 `baseUrl` / `apiKey`（只报状态，不打印值）；
  ZCode 每次启动时也做同一校验，不匹配写「联动警告」到日志
- 修复 `-Uninstall` —— 排除当前进程，避免把自己的 PowerShell 一起结束
- 调整 文档 —— MAINTENANCE §8、TOOLS、TROUBLESHOOTING §11

### 外部跑分参考收录（2026-10-21）

- 新增 文档 —— `docs/BENCHMARKS.md`：收录第三方公开榜「AI 能力专项测试」
  （7 题 · 4 方向 · 总分 400）的四个榜单入口、评测口径、2026-09-11 总分榜快照、
  四方向 / 逐题前三，以及本仓在配模型在榜上的位置与读法
- 调整 文档 —— `docs/README.md` 参考资料索引、`docs/DOC-RULES.md` §1 / §2、
  `docs/MODEL-PROVIDERS.md` §6 补交叉链接
- 说明 —— 榜单数据非本仓实测，分数会随站点更新变化；本篇只做快照，不替代 `evidence/` 下的本仓探测结果
- 调整 文档 —— 按榜单四方向重排本仓在配模型：`BENCHMARKS.md` §5.1 / §5.2 增方向榜与
  每模型最强方向；`MODEL-PROVIDERS.md` §6.1 增方向首选表；**provider 分档未改**，
  方向只作第二轴（理由见 BENCHMARKS §5.3）
- 调整 文档 —— 以 `deepseek-v4.1-flash`（总分 342.40 / 输出 $1.20/M / 倍率 0.11）
  为 100 基准，新增 `BENCHMARKS.md` §5.4 与 `MODEL-PROVIDERS.md` §6.2：
  按智力指数、价格指数、性价比把在配模型分为主力 / 低耗 / 高耗 / 免费 / 备用；
  未上榜模型保持原组（本轮只做选型层，备用档落地见下一条）

### 备用档落地（2026-10-21）

- 新增 provider —— `opencode-go-chat-backup`（备用）：按 DeepSeek 基准性价比 < 1，
  移入 `minimax-m3`；`opencode-go-chat-slow` 只剩 `longcat-2.0`
- 新增 provider —— `workbuddy-backup`（备用）：移入 `cn:deepseek-v4-flash`、
  `cn:minimax-m3`；同时按实时价把 `cn:hy4-preview` 从免代移到高代（x0.29）
- 变更 脚本 —— `go_model_sync.py` 增 `BACKUP_MODEL_IDS` / `--reclassify-only`；
  `workbuddy_zcode_sync.py` 增第四档 `backup` / `--reclassify-only`
- 变更 配置 —— 本机 `provider_config.json` 已写入；备份
  `.bak-reclassify-20261021-174621`、`.bak-wbproxy-20261021-174621`、
  `.bak-wbproxy-20261021-174649`
- 调整 文档 —— MODEL-PROVIDERS §2.1 / §2.5.1 / §4.2 / §4.3 / §4.5.1 / §6.2、
  TOOLS、MAINTENANCE、TROUBLESHOOTING、BENCHMARKS §5.4
- 调整 文档 —— `BENCHMARKS.md` §5.4 把 OpenCode-Go / WorkBuddy 两张分档表
  合并为一张，按主力 → 低耗 → 高耗 → 免费 → 备用排序；价格列保留原单位，
  横比看已归一的「价格指数」

### 统一路由：WorkBuddy 并入五个 chat 组（2026-10-21）

- 新增 脚本 —— `tools/unified-router.js`：按 model 前缀分流 `cn:` / `global:` →
  WorkBuddy 网关，其余 → OpenCode-Go；监听 `127.0.0.1:7871`，`GET /health` 做健康检查
- 变更 配置 —— 删除 `workbuddy-low/free/high/backup` 四个 provider；18 个 WorkBuddy
  模型并入 `opencode-go-chat/-free/-fast/-slow/-backup`；五个 chat 组 `baseUrl`
  指向路由；`对话` / `响应` 仍直连 OpenCode。备份
  `provider_config.json.bak-unified-*` / `.bak-wbproxy-*`
- 变更 脚本 —— `workbuddy_zcode_sync.py` 默认 unified 模式（`--separate` 保留旧四档）；
  `--reclassify-only` 适配统一模式；`apply_unified` 每次先清掉目标组里的 WorkBuddy
  模型再重放，避免重复
- 变更 守护器 —— `zcode_gateway_watch.ps1` 随 ZCode 启停统一路由；`-Status` 显示
  路由与五个 chat 组；新增 `-RouterPort` / `-RouterScript` / `-NoRouter`；
  日志 `router.stdout.log` / `router.stderr.log`
- 调整 文档 —— MODEL-PROVIDERS §2 / §4 / §6.2、TOOLS、MAINTENANCE §4.4 / §8、
  TROUBLESHOOTING §11 / §12、PITFALLS §12、SECRETS、docs/README
- 说明 —— 统一路由是本地进程；ZCode 不开时由守护器停掉。回退：恢复
  `.bak-unified-*`，或 `workbuddy_zcode_sync.py --separate --apply` 重建四档


