# 工具清单

> **一句话**：本仓全部脚本的产物与去留标记 —— 哪些是长期工具、哪些是一次性探测、哪些是活数据；根 README 只留「使用」速览。

下表列的是**三个示例接入器**（`providers/opencode-go/`、`providers/workbuddy/`、`providers/qoder/`）的脚本。换供应商时照同样的结构加一份
（通用方法见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0）。

> **2026-10-23 起**：`tools/model_alias.py` 是 ZCode 配置的**唯一最终写入者**
> （三组 + alias map）。下面旧的三个 sync / 两个 probe 只作为**数据采集与兼容**
> 工具；先跑它们，再跑 `model_alias.py` 归一化。日常顺序还多一步：
> `arena_leaderboard.py --refresh --write` 更新主力候选。命名、积分与榜单扩充规则见
> [MODEL-ALIAS.md](MODEL-ALIAS.md)、[BENCHMARKS.md](BENCHMARKS.md) §8。

## 0. 运行环境

| 项 | 要求 | 说明 |
|---|---|---|
| Python | 3.x，**只用标准库**（无第三方依赖） | 所有 `.py` 脚本 |
| Node.js | 18+ | 跑 `.js` 脚本（探测、统一路由、思考字段映射） |
| 凭据 | **只走环境变量** | 变量名与取值见 [SECRETS.md](SECRETS.md) §3.5 |
| 客户端 | ZCode 桌面端（Windows） | 脚本读它的 `provider_config.json`，路径见 [SECRETS.md](SECRETS.md) §3.4 |

## 1. 工具清单

| 脚本 | 作用 | 输出产物 | 长期 |
|---|---|---|---|
| `providers/opencode-go/ops/go_model_sync.py` | 四源并集检测 Go 套餐新模型 → 三协议探测 → 按成本档 + 备用档分组 → 写 `provider_config.json`（`--reclassify-only` 只搬备用档；统一模式下五个 chat 组指向统一路由）。已配置模型**跑不通即清**（400/402/404/410/5xx 移除，仅豁免 401/429），复通后自动加回。已配置的 `W/…`、`O/…`、`Q/…` 显示名会先按 `model-alias-map.json` 还原成上游裸 id 再体检，WorkBuddy/Qoder 渠道跳过，不会拿显示名去 Go 上游探测 | 报告 `go-model-sync-<时间戳>.md`；备份 `provider_config.json.bak-gosync-<时间戳>` | ✅ 长期 |
| `providers/opencode-go/ops/opencode-header-proxy.js` | 给不支持自定义头的客户端（ChatBox / Open WebUI 等）补 `x-opencode-session` | 常驻 HTTP 代理，默认 `127.0.0.1:8787` | ✅ 长期 |
| `gateways/zgate/` | **统一入口（Go）**：监听 `127.0.0.1:7871`，按 `model-alias-map.json` 分流；无 map 时回退旧前缀（`cn:`/`global:`/`qoder:`）；messages/responses 模型内置协议桥；同时按策略拉起/回收两个上游子进程（WB `ondemand`、Qoder `always`）。子命令 `serve` / `status` / `reload` / `install` / `uninstall` / `version`；子进程默认全部 `ondemand`，签到/保活用 `windows` 定时窗口兜底；改策略后 `zgate reload` 热加载。策略与配置见 [MAINTENANCE.md](MAINTENANCE.md) §8 | 日志 `%LOCALAPPDATA%\ZCodeGateway\zgate.log`（5 MB 轮转）；子进程输出同目录 `workbuddy.*` / `qoder.*` | ✅ 长期 |
| `gateways/zgate/build.py` | **zgate 构建入口**：带 `-H windowsgui` 编译（GUI 子系统 → 登录自启零窗口），并**强制校验产物的 PE `Subsystem` 必须为 2**；`--check` 只校验现有产物，`--cross-check` 交叉编译一份 windows/amd64 到临时目录再校验（CI 用，Linux 上也生效） | `gateways/zgate/zgate.exe`（`.gitignore` 排除）；临时目录里的交叉编译产物 | ✅ 长期 |
| `gateways/zgate/smoke_test.py` | 冒烟测试：四条通道 + 两种桥 + 流式各打一发微小请求，断言 200 / `chat.completion` / `[DONE]` | 只打印 PASS/FAIL；`ZGATE_BASE` 可改目标 | ✅ 长期（每次改路由后跑） |
| `tools/model_alias.py` | **最终写入者**：把当前配置里的模型归一成纯型号名，同型号跨渠道合并成按价格升序的 `chain`，按人工有序名单分**三组**（主力 `MAIN_ORDER` / 免费按 0 价 / 省钱 `LOW_ORDER` 严格白名单），组内顺序也按名单下标，生成 alias map；**价格每轮从源重算、不继承旧值**（死跳直接剔除）；`--probe-file` 只保留 ok（或曾 ok 的瞬时限流，超过 `--probe-max-age-hours` 默认 72h 视为未知）；`--check` 只做漂移检测（有差异退出码 1）；`--arena-main` 读榜单候选扩充主力，`--no-arena` 回到纯人工 | `provider_config.json.bak-alias-<时间戳>`；`~/.zcode/v2/model-alias-map.json` | ✅ 长期 |
| `tools/arena_leaderboard.py` | **主力扩充取数**：拉 ArenaGalleri 榜单接口，按 DeepSeek 基准（分数 ≥95%、积分 ≤0.11、非临时名次、≥50 局、不含 0 积分）从**已配置模型**里筛候选；候选集合或规则变化才触发重写。`--refresh` 联网重拉、`--write` 落候选、`--apply` 接着调 `model_alias.py`、`--status` 看已保存候选 | `~/.zcode/v2/arena-leaderboard.json`（榜单缓存）、`~/.zcode/v2/arena-main.json`（主力候选） | ✅ 长期 |
| `tools/sync_report.py` | **同步报告**：对比上一轮快照（`~/.zcode/v2/model-sync-state.json`），写出本次新增 / 移除 / 分组变化 / 链路变化；`--write` 落 `docs/reports/MODEL-SYNC-<时间>.md` 并更新索引，`--push` 再 `git add/commit/push`。自动化最后一步跑它 | 报告 `docs/reports/*.md`、索引 `docs/reports/README.md`、快照 `model-sync-state.json` | ✅ 长期 |
| `tools/model_probe.py` | 用 **ZCode 真实 body**（`zcode_effective_body.js` + provider id）探测三组模型；经 7871，含桥接模型；结果带 `ever_ok` | `~/.zcode/v2/model_probe.json`（活数据） | ✅ 长期 |
| `gateways/legacy-router/protocol_bridge.js` | chat ↔ Anthropic Messages / OpenAI Responses 转换（旧 Node 实现，已由 zgate 内置桥取代） | 由 `unified-router.js` require | ⚠️ 回退用（保留一个版本） |
| `providers/workbuddy/workbuddy_fetch_pricing.py` | 拉网关目录接口 → 归一化 → 写价格表（打印倍率变化 / 新增 / 下架摘要） | `providers/workbuddy/cache/wb_pricing.json`（写前自动备份） | ✅ 长期 |
| `providers/workbuddy/workbuddy_probe_zcode.py` | 用 **ZCode 真实 body** 探测网关模型可用性，可断点续跑 | `providers/workbuddy/cache/wb_zcode_probe.json`；`workbuddy/logs/wb_zcode_probe.log` | ✅ 长期 |
| `providers/workbuddy/workbuddy_zcode_sync.py` | **默认统一模式**：把 WorkBuddy 模型并入 OpenCode 的五个 chat 组（组内 CN 优先、按厂商分组、主力置顶）；`--separate` 才写免代 / 低代 / 高代 / 备用四个独立 provider。倍率取价格表归一化的 `eff_rate`/`list_rate`（免费 `-f` 条目 0.0 进免代）；probe 为 blocked/unavailable 的模型移除，复通后自动加回。`--reclassify-only` 只搬备用档，`--reorder-only` 只重排（分离模式） | 备份 `provider_config.json.bak-wbproxy-<时间戳>` | ✅ 长期 |
| `providers/workbuddy/zcode_effective_body.js` | 复刻 ZCode 引擎的规则解析顺序，算某 modelId **真实会发的请求体** | stdout JSON | ✅ 长期（`probe_zcode.py` 依赖它，必须同目录） |
| `gateways/legacy-router/unified-router.js` | **旧 Node 路由**（回退用）：与 zgate 行为对齐；P3 验收通过后删除 | 日志 `router.stdout.log` / `router.stderr.log` | ⚠️ 回退用（保留一个版本） |
| `gateways/upstream/workbuddy/` | 上游 WorkBuddy2API Panel 的**独立 clone** + 运行时（`config.json` / `auths/` / `data/` / `wb2api.exe`）；整目录被 `.gitignore` 排除 | 网关自身的 `data/` 与日志 | ✅ 长期（更新：`git -C gateways/upstream/workbuddy pull --ff-only`） |
| `gateways/upstream/qoder/` | 上游 qoder2api-hub 的**独立 clone** + 运行时（`accounts/` / `usage/` / `umid/`）；整目录被 `.gitignore` 排除。默认 `127.0.0.1:8790`，`start-qoder-proxy.bat` / `stop-qoder-proxy.bat` 管理 | 网关自身的 `accounts/scheduler/state.json`、`qoder-proxy.log` / `.err.log` | ✅ 长期（更新：`git -C gateways/upstream/qoder pull --ff-only`） |
| `providers/qoder/qoder_zcode_sync.py` | **默认合并**：拉 qoder2api-hub `/v1/models` → 排除 `Auto`/`Fast` 别名 → 按 `price_factor` 把 `qoder:` 前缀模型并入免费/低耗/高耗三个 chat 组；`--separate` 才写独立的 `qoder` provider；`--probe-file` 只保留探测 `ok`（或曾 ok 的瞬时限流），默认 `--max-price 0.8`。每天 12:00 定时任务里与 `qoder_probe_zcode.py` 成对执行（见 [MAINTENANCE.md](MAINTENANCE.md) §6） | 备份 `provider_config.json.bak-qoder-merge-<时间戳>`（separate 模式 `.bak-qoder-<时间戳>`）；dry run 打印落组 | ✅ 长期 |
| `providers/qoder/qoder_probe_zcode.py` | 用 **ZCode 真实 body**（复算 `zcode_effective_body.js`）探测 Qoder 模型；默认经 7871 + `qoder:` 前缀（与 ZCode 实际路径一致），`--direct` 直连 8790；候选从 8790 `/v1/models` 取；状态 ok / fallback / queued / rate_limited / blocked / unavailable / timeout / error；结果带 `ever_ok`，瞬时限流不误杀曾 ok 的模型 | `providers/qoder/qoder_probe.json`（`.gitignore` 排除） | ✅ 长期 |
| `providers/opencode-go/probe/probe_models.py` | 34 个模型最小 token 连通性 + 首字节延迟 | `probe_results.json`（**写到当前工作目录**，需手动归档到 `results/<日期>/`） | ❌ 一次性 |
| `providers/qwen/qwen_zcode_sync.py` | 千问平台：从控制台快照（`cache/freetier_<日期>.txt`，`family <= id,id`）或 `--fetch`（`/api/models` 不稳定）取目录 → 四道漏斗筛对话模型 → 把 `qwen:<id>` 写进免费组；`--only` 指定 id、`--all-chat` 收全部 118 家族、`--write-pools` 生成集合体、`--probe-file` 只留探测 ok。**2026-10-29 起 `POOL_SPECS` 已清空**，只播种 `deepseek-v4.1-flash`（主力链尾跳），集合体与其它单型号下线（见 [QWEN.md](QWEN.md) §4.5） | 备份 `provider_config.json.bak-qwen-<时间戳>`；dry run 打印落组 | ⚠️ 仅兜底跳 |
| `providers/qwen/qwen_pool_probe.py` | 千问上游探测：逐个试 `pools.json` 里每一跳，产出 `qwen_pool_probe.json`（`--sleep`/`--timeout` 可调）。**手动工具，定时任务不跑**；重新启用集合体时先跑它，再 `qwen_zcode_sync.py --write-pools --probe-file` 剔死跳 | 只发 8 tokens 的探活请求；额度耗尽会标 `fatal` | ⚠️ 手动 |
| `providers/opencode-go/probe/probe_protocols.py` | 判定每个模型走哪种协议 | 只打印，不落盘 | ❌ 一次性 |
| `providers/opencode-go/probe/bench_models.py` | 吞吐 + 工具调用基准 | `bench_results.json`（同上，需手动归档） | ❌ 一次性 |
| `providers/opencode-go/probe/bench_clean.py` | 干净串行基准，每模型 3 采样 | `bench_clean.json`（同上，需手动归档） | ❌ 一次性 |
| `providers/opencode-go/probe/thinking-off-probe.js` | 逐模型试「关思考」参数 | 只打印 | ❌ 一次性 |
| `providers/opencode-go/probe/archive/validate_zcode_models.py` | 校验 ZCode 已配模型与其 provider 协议是否一致 | 只打印 | ❌ 一次性（已归档） |
| `providers/workbuddy/archive/workbuddy_probe_models.py` | 早期裸 body 探测（已被 `workbuddy_probe_zcode.py` 完全取代） | — | ❌ 已归档 |
| `providers/workbuddy/cache/wb_pricing.json` | 网关 56 个模型的倍率 / 上下文 / 输出上限 / effort 档位快照 | 由 `workbuddy_fetch_pricing.py` 生成 | ⚠️ 活数据 |
| `providers/workbuddy/cache/wb_zcode_probe.json` | 探测结果缓存（status / variant / http / detail / rate） | 被 `workbuddy_zcode_sync.py` 读取 | ⚠️ 活数据 |
| `providers/qoder/qoder_probe.json` | Qoder 模型探测结果（status / variant / http / detail） | 被 `qoder/qoder_zcode_sync.py --probe-file` 读取；`.gitignore` 排除 | ⚠️ 活数据 |
| `~/.zcode/v2/model_probe.json` | 三组统一探测结果（status / http / provider / ever_ok） | 被 `tools/model_alias.py --probe-file` 读取 | ⚠️ 活数据 |
| `~/.zcode/v2/arena-leaderboard.json` | ArenaGalleri 榜单原始响应 + `_fetched_at` | 榜单接口不可用时的缓存；`--refresh` 覆盖 | ⚠️ 活数据 |
| `~/.zcode/v2/arena-main.json` | 主力候选（基准分 / 窗口规则 / 每个候选的 channel、upstream、分数、积分） | 由 `tools/arena_leaderboard.py` 生成，被 `model_alias.py` 读取 | ⚠️ 活数据 |
| `~/.zcode/v2/model-alias-map.json` | 显示名 → 上游模型/base/protocol 的映射 | 由 `tools/model_alias.py` 生成，路由按 mtime 热加载 | ⚠️ 活数据（不含凭据） |
| `evidence/wb_panel_models.json` | 网关模型目录原始快照 | 只读证据 | — |
| `third-party/zcodium/reasoning-rules.js` | 按协议算「最小且正确」的思考字段；并比对本机 ZCode 内置规则与上游切片，报漂移 | stdout | ✅ 长期 |
| `third-party/zcodium/zcode-builtin-reasoning-rules.json` | ZCodium 内置思考规则的最小切片（4 条，逐字抄录，带来源 URL + SHA + license） | 只读参考 | ✅ 长期 |

---

## 2. 统一模式与分离模式

> **2026-10-28 起**：ZCode 只有三组（主力 / 免费 / 省钱，2026-10-29 起低耗与高耗合并为省钱组），由
> `tools/model_alias.py` 生成；下面的统一/分离模式是 WorkBuddy 旧数据采集口径，
> 只作历史参考。当前命名与分组见 [MODEL-ALIAS.md](MODEL-ALIAS.md)。

`workbuddy/workbuddy_zcode_sync.py` 有两种写法，**默认是统一模式**：

| 模式 | 怎么触发 | 结果 |
|---|---|---|
| 统一模式（默认） | 不带 `--separate` | WorkBuddy 模型并进 OpenCode 的三组，三组的 `baseUrl` 指向统一入口 `gateways/zgate`（`127.0.0.1:7871`） |
| 分离模式 | `--separate` | 重建四个独立的 `workbuddy-*` provider（免代 / 低代 / 高代 / 备用），`baseUrl` 直指网关 |

统一入口按 alias map 分流：`W/…` → WorkBuddy 网关（`127.0.0.1:7863`），
其余 → OpenCode-Go。它由 `gateways/zgate` 常驻提供（登录自启，见
[MAINTENANCE.md](MAINTENANCE.md) §8），健康检查 `GET http://127.0.0.1:7871/health`。

模型怎么分档、哪些模型进哪一组，见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4.0、§4.2；
守护器与开机自启，见 [MAINTENANCE.md](MAINTENANCE.md) §8。

**Qoder 经过统一路由**：模型 id 带 `qoder:` 前缀，7871 剥掉前缀后转给
`127.0.0.1:8790`；ZCode 侧没有独立 `qoder` provider。模型矩阵见
[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4.9，操作见 [QODER.md](QODER.md)。

---

一次性脚本的结论已固化进 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)，**不用重跑**；
要重跑先改源码里的模型清单。凭据与环境变量口径见 [SECRETS.md](SECRETS.md)；
三个同步脚本各自的写入行为见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §1.1，
`--apply` 的备份与回退见 [MAINTENANCE.md](MAINTENANCE.md) §4。
