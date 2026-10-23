# 工具清单

> **一句话**：本仓全部脚本的产物与去留标记 —— 哪些是长期工具、哪些是一次性探测、哪些是活数据；根 README 只留「使用」速览。

下表列的是**三个示例接入器**（`opencode-go/`、`workbuddy/`、`qoder/`）的脚本。换供应商时照同样的结构加一份
（通用方法见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0）。

> **2026-10-23 起**：`tools/model_alias.py` 是 ZCode 配置的**唯一最终写入者**
> （四组 + alias map）。下面旧的三个 sync / 两个 probe 只作为**数据采集与兼容**
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
| `opencode-go/ops/go_model_sync.py` | 四源并集检测 Go 套餐新模型 → 三协议探测 → 按成本档 + 备用档分组 → 写 `provider_config.json`（`--reclassify-only` 只搬备用档；统一模式下五个 chat 组指向统一路由）。已配置模型**跑不通即清**（400/402/404/410/5xx 移除，仅豁免 401/429），复通后自动加回 | 报告 `go-model-sync-<时间戳>.md`；备份 `provider_config.json.bak-gosync-<时间戳>` | ✅ 长期 |
| `opencode-go/ops/opencode-header-proxy.js` | 给不支持自定义头的客户端（ChatBox / Open WebUI 等）补 `x-opencode-session` | 常驻 HTTP 代理，默认 `127.0.0.1:8787` | ✅ 长期 |
| `tools/unified-router.js` | **统一路由**：优先读 `model-alias-map.json`，按显示名把请求还原到 WB/OC/QD 上游；无 map 时回退旧前缀（`cn:`/`global:`/`qoder:`）。messages/responses 模型交给 `protocol_bridge.js`。`GET /health` 含三家 key 与 alias 条数 | 监听 `127.0.0.1:7871`；日志由守护器写 `router.stdout.log` / `router.stderr.log` | ✅ 长期（随 ZCode 起停） |
| `tools/model_alias.py` | **最终写入者**：把当前配置里的模型按渠道/地区/系列重命名为 `渠道/积分/型号`，按积分分到四组，生成 alias map；`--probe-file` 只保留 ok（或曾 ok 的瞬时限流）；`--arena-main` 读榜单候选扩充主力，`--no-arena` 回到纯人工 | `provider_config.json.bak-alias-<时间戳>`；`~/.zcode/v2/model-alias-map.json` | ✅ 长期 |
| `tools/arena_leaderboard.py` | **主力扩充取数**：拉 ArenaGalleri 榜单接口，按 DeepSeek 基准（分数 ≥95%、积分 ≤0.11、非临时名次、≥50 局、不含 0 积分）从**已配置模型**里筛候选；候选集合或规则变化才触发重写。`--refresh` 联网重拉、`--write` 落候选、`--apply` 接着调 `model_alias.py`、`--status` 看已保存候选 | `~/.zcode/v2/arena-leaderboard.json`（榜单缓存）、`~/.zcode/v2/arena-main.json`（主力候选） | ✅ 长期 |
| `tools/model_probe.py` | 用 **ZCode 真实 body**（`zcode_effective_body.js` + provider id）探测四组模型；经 7871，含桥接模型；结果带 `ever_ok` | `~/.zcode/v2/model_probe.json`（活数据） | ✅ 长期 |
| `tools/protocol_bridge.js` | chat ↔ Anthropic Messages / OpenAI Responses 转换；非流式上游 + 合成 chat SSE；支持文本、思考、工具调用 | 由 `unified-router.js` require | ✅ 长期 |
| `workbuddy/workbuddy_fetch_pricing.py` | 拉网关目录接口 → 归一化 → 写价格表（打印倍率变化 / 新增 / 下架摘要） | `workbuddy/cache/wb_pricing.json`（写前自动备份） | ✅ 长期 |
| `workbuddy/workbuddy_probe_zcode.py` | 用 **ZCode 真实 body** 探测网关模型可用性，可断点续跑 | `workbuddy/cache/wb_zcode_probe.json`；`workbuddy/logs/wb_zcode_probe.log` | ✅ 长期 |
| `workbuddy/workbuddy_zcode_sync.py` | **默认统一模式**：把 WorkBuddy 模型并入 OpenCode 的五个 chat 组（组内 CN 优先、按厂商分组、主力置顶）；`--separate` 才写免代 / 低代 / 高代 / 备用四个独立 provider。倍率取价格表归一化的 `eff_rate`/`list_rate`（免费 `-f` 条目 0.0 进免代）；probe 为 blocked/unavailable 的模型移除，复通后自动加回。`--reclassify-only` 只搬备用档，`--reorder-only` 只重排（分离模式） | 备份 `provider_config.json.bak-wbproxy-<时间戳>` | ✅ 长期 |
| `workbuddy/zcode_effective_body.js` | 复刻 ZCode 引擎的规则解析顺序，算某 modelId **真实会发的请求体** | stdout JSON | ✅ 长期（`probe_zcode.py` 依赖它，必须同目录） |
| `workbuddy/zcode_gateway_watch.ps1` | 让网关 + 统一路由的寿命跟随 ZCode **主进程**：出现 → 静默拉起 `wb2api` 和 `node tools/unified-router.js`；退出 → 宽限 8 秒 + 排空（默认最多 5 秒）后停；宽限 / 排空期间 ZCode 回来会取消停止并写日志；启动时若没有 ZCode 却还有网关 / 路由在听，按遗留进程清掉（`-KeepOrphans` 跳过）。运行期间挂了自动重启，每 15 分钟写一条心跳。`-Install` / `-Uninstall` 注册 / 移除开机自启，`-Status` 看状态并校验五个 chat 组指向，`-DryRun` 只记状态迁移，`-NoRouter` 不启停路由 | `%LOCALAPPDATA%\ZCodeGateway\watchdog.log`；网关输出 `gateway.stdout.log` / `gateway.stderr.log`，路由输出 `router.stdout.log` / `router.stderr.log`（启动前轮转 `.1`） | ✅ 长期 |
| `workbuddy/zcode_gateway_watch.vbs` | 无窗口启动上面的 `.ps1`（`-Install` 注册到启动文件夹的就是它） | — | ✅ 长期 |
| `workbuddy/gateway/` | 上游 WorkBuddy2API Panel 的**独立 clone** + 运行时（`config.json` / `auths/` / `data/` / `wb2api.exe`）；整目录被 `.gitignore` 排除 | 网关自身的 `data/` 与日志 | ✅ 长期（更新：`git -C workbuddy/gateway pull --ff-only`） |
| `qoder/gateway/` | 上游 qoder2api-hub 的**独立 clone** + 运行时（`accounts/` / `usage/` / `umid/`）；整目录被 `.gitignore` 排除。默认 `127.0.0.1:8790`，`start-qoder-proxy.bat` / `stop-qoder-proxy.bat` 管理 | 网关自身的 `accounts/scheduler/state.json`、`qoder-proxy.log` / `.err.log` | ✅ 长期（更新：`git -C qoder/gateway pull --ff-only`） |
| `qoder/qoder_zcode_sync.py` | **默认合并**：拉 qoder2api-hub `/v1/models` → 排除 `Auto`/`Fast` 别名 → 按 `price_factor` 把 `qoder:` 前缀模型并入免费/低耗/高耗三个 chat 组；`--separate` 才写独立的 `qoder` provider；`--probe-file` 只保留探测 `ok`（或曾 ok 的瞬时限流），默认 `--max-price 0.8` | 备份 `provider_config.json.bak-qoder-merge-<时间戳>`（separate 模式 `.bak-qoder-<时间戳>`）；dry run 打印落组 | ✅ 长期 |
| `qoder/qoder_probe_zcode.py` | 用 **ZCode 真实 body**（复算 `zcode_effective_body.js`）探测 Qoder 模型；默认经 7871 + `qoder:` 前缀（与 ZCode 实际路径一致），`--direct` 直连 8790；候选从 8790 `/v1/models` 取；状态 ok / fallback / queued / rate_limited / blocked / unavailable / timeout / error；结果带 `ever_ok`，瞬时限流不误杀曾 ok 的模型 | `qoder/qoder_probe.json`（`.gitignore` 排除） | ✅ 长期 |
| `opencode-go/probe/probe_models.py` | 34 个模型最小 token 连通性 + 首字节延迟 | `probe_results.json`（**写到当前工作目录**，需手动归档到 `results/<日期>/`） | ❌ 一次性 |
| `opencode-go/probe/probe_protocols.py` | 判定每个模型走哪种协议 | 只打印，不落盘 | ❌ 一次性 |
| `opencode-go/probe/bench_models.py` | 吞吐 + 工具调用基准 | `bench_results.json`（同上，需手动归档） | ❌ 一次性 |
| `opencode-go/probe/bench_clean.py` | 干净串行基准，每模型 3 采样 | `bench_clean.json`（同上，需手动归档） | ❌ 一次性 |
| `opencode-go/probe/thinking-off-probe.js` | 逐模型试「关思考」参数 | 只打印 | ❌ 一次性 |
| `opencode-go/probe/archive/validate_zcode_models.py` | 校验 ZCode 已配模型与其 provider 协议是否一致 | 只打印 | ❌ 一次性（已归档） |
| `workbuddy/archive/workbuddy_probe_models.py` | 早期裸 body 探测（已被 `workbuddy_probe_zcode.py` 完全取代） | — | ❌ 已归档 |
| `workbuddy/cache/wb_pricing.json` | 网关 56 个模型的倍率 / 上下文 / 输出上限 / effort 档位快照 | 由 `workbuddy_fetch_pricing.py` 生成 | ⚠️ 活数据 |
| `workbuddy/cache/wb_zcode_probe.json` | 探测结果缓存（status / variant / http / detail / rate） | 被 `workbuddy_zcode_sync.py` 读取 | ⚠️ 活数据 |
| `qoder/qoder_probe.json` | Qoder 模型探测结果（status / variant / http / detail） | 被 `qoder/qoder_zcode_sync.py --probe-file` 读取；`.gitignore` 排除 | ⚠️ 活数据 |
| `~/.zcode/v2/model_probe.json` | 四组统一探测结果（status / http / provider / ever_ok） | 被 `tools/model_alias.py --probe-file` 读取 | ⚠️ 活数据 |
| `~/.zcode/v2/arena-leaderboard.json` | ArenaGalleri 榜单原始响应 + `_fetched_at` | 榜单接口不可用时的缓存；`--refresh` 覆盖 | ⚠️ 活数据 |
| `~/.zcode/v2/arena-main.json` | 主力候选（基准分 / 窗口规则 / 每个候选的 channel、upstream、分数、积分） | 由 `tools/arena_leaderboard.py` 生成，被 `model_alias.py` 读取 | ⚠️ 活数据 |
| `~/.zcode/v2/model-alias-map.json` | 显示名 → 上游模型/base/protocol 的映射 | 由 `tools/model_alias.py` 生成，路由按 mtime 热加载 | ⚠️ 活数据（不含凭据） |
| `evidence/wb_panel_models.json` | 网关模型目录原始快照 | 只读证据 | — |
| `third-party/zcodium/reasoning-rules.js` | 按协议算「最小且正确」的思考字段；并比对本机 ZCode 内置规则与上游切片，报漂移 | stdout | ✅ 长期 |
| `third-party/zcodium/zcode-builtin-reasoning-rules.json` | ZCodium 内置思考规则的最小切片（4 条，逐字抄录，带来源 URL + SHA + license） | 只读参考 | ✅ 长期 |

---

## 2. 统一模式与分离模式

> **2026-10-23 起**：ZCode 只有四组（主力 / 免费 / 低耗 / 高耗），由
> `tools/model_alias.py` 生成；下面的统一/分离模式是 WorkBuddy 旧数据采集口径，
> 只作历史参考。当前命名与分组见 [MODEL-ALIAS.md](MODEL-ALIAS.md)。

`workbuddy/workbuddy_zcode_sync.py` 有两种写法，**默认是统一模式**：

| 模式 | 怎么触发 | 结果 |
|---|---|---|
| 统一模式（默认） | 不带 `--separate` | WorkBuddy 模型并进 OpenCode 的五个 chat 组，五个组的 `baseUrl` 指向统一路由 `tools/unified-router.js`（`127.0.0.1:7871`） |
| 分离模式 | `--separate` | 重建四个独立的 `workbuddy-*` provider（免代 / 低代 / 高代 / 备用），`baseUrl` 直指网关 |

统一路由按 model 前缀分流：`cn:` / `global:` → WorkBuddy 网关（`127.0.0.1:7863`），
其余 → OpenCode-Go。它随 ZCode 起停（`workbuddy/zcode_gateway_watch.ps1`），
手动启动是 `node tools/unified-router.js`，健康检查 `GET /health`。

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
