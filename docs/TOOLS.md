# 工具清单

> **一句话**：本仓全部脚本的产物与去留标记 —— 哪些是长期工具、哪些是一次性探测、哪些是活数据；根 README 只留「快速开始」速览。

下表列的是**两个示例接入器**的脚本。换供应商时照同样的结构加一份
（通用方法见 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0）。

| 脚本 | 作用 | 输出产物 | 长期 |
|---|---|---|---|
| `opencode-go/ops/go_model_sync.py` | 四源并集检测 Go 套餐新模型 → 三协议探测 → 按成本档分组 → 写 `provider_config.json` | 报告 `go-model-sync-<时间戳>.md`；备份 `provider_config.json.bak-gosync-<时间戳>` | ✅ 长期 |
| `opencode-go/ops/opencode-header-proxy.js` | 给不支持自定义头的客户端（ChatBox / Open WebUI 等）补 `x-opencode-session` | 常驻 HTTP 代理，默认 `127.0.0.1:8787` | ✅ 长期 |
| `workbuddy/workbuddy_fetch_pricing.py` | 拉网关目录接口 → 归一化 → 写价格表（打印倍率变化 / 新增 / 下架摘要） | `workbuddy/cache/wb_pricing.json`（写前自动备份） | ✅ 长期 |
| `workbuddy/workbuddy_probe_zcode.py` | 用 **ZCode 真实 body** 探测网关模型可用性，可断点续跑 | `workbuddy/cache/wb_zcode_probe.json`；`workbuddy/logs/wb_zcode_probe.log` | ✅ 长期 |
| `workbuddy/workbuddy_zcode_sync.py` | 按积分倍率分免代 / 低代 / 高代三档写 provider（上限 0.30 = 主力价位，超过的"贵不加"）；组内 CN 优先、按厂商分组、主力置顶（`--reorder-only` 只重排） | 备份 `provider_config.json.bak-wbproxy-<时间戳>` | ✅ 长期 |
| `workbuddy/zcode_effective_body.js` | 复刻 ZCode 引擎的规则解析顺序，算某 modelId **真实会发的请求体** | stdout JSON | ✅ 长期（`probe_zcode.py` 依赖它，必须同目录） |
| `workbuddy/zcode_gateway_watch.ps1` | 让网关寿命跟随 ZCode **主进程**：出现 → 静默拉起 `wb2api`（`/panel/` 200 才算就绪）；退出 → 宽限 8 秒 + 在途连接排空后停；运行期间网关挂了自动重启。`-Install` / `-Uninstall` 注册 / 移除开机自启，`-Status` 看状态并校验 `workbuddy-*` provider 指向，`-DryRun` 只记状态迁移 | `%LOCALAPPDATA%\ZCodeGateway\watchdog.log`；网关输出 `gateway.stdout.log` / `gateway.stderr.log`（启动前轮转 `.1`） | ✅ 长期 |
| `workbuddy/zcode_gateway_watch.vbs` | 无窗口启动上面的 `.ps1`（`-Install` 注册到启动文件夹的就是它） | — | ✅ 长期 |
| `workbuddy/gateway/` | 上游 WorkBuddy2API Panel 的**独立 clone** + 运行时（`config.json` / `auths/` / `data/` / `wb2api.exe`）；整目录被 `.gitignore` 排除 | 网关自身的 `data/` 与日志 | ✅ 长期（更新：`git -C workbuddy/gateway pull --ff-only`） |
| `opencode-go/probe/probe_models.py` | 34 个模型最小 token 连通性 + 首字节延迟 | `probe_results.json`（**写到当前工作目录**，需手动归档到 `results/<日期>/`） | ❌ 一次性 |
| `opencode-go/probe/probe_protocols.py` | 判定每个模型走哪种协议 | 只打印，不落盘 | ❌ 一次性 |
| `opencode-go/probe/bench_models.py` | 吞吐 + 工具调用基准 | `bench_results.json`（同上，需手动归档） | ❌ 一次性 |
| `opencode-go/probe/bench_clean.py` | 干净串行基准，每模型 3 采样 | `bench_clean.json`（同上，需手动归档） | ❌ 一次性 |
| `opencode-go/probe/thinking-off-probe.js` | 逐模型试「关思考」参数 | 只打印 | ❌ 一次性 |
| `opencode-go/probe/archive/validate_zcode_models.py` | 校验 ZCode 已配模型与其 provider 协议是否一致 | 只打印 | ❌ 一次性（已归档） |
| `workbuddy/archive/workbuddy_probe_models.py` | 早期裸 body 探测（已被 `workbuddy_probe_zcode.py` 完全取代） | — | ❌ 已归档 |
| `workbuddy/cache/wb_pricing.json` | 网关 56 个模型的倍率 / 上下文 / 输出上限 / effort 档位快照 | 由 `workbuddy_fetch_pricing.py` 生成 | ⚠️ 活数据 |
| `workbuddy/cache/wb_zcode_probe.json` | 探测结果缓存（status / variant / http / detail / rate） | 被 `workbuddy_zcode_sync.py` 读取 | ⚠️ 活数据 |
| `evidence/wb_panel_models.json` | 网关模型目录原始快照 | 只读证据 | — |
| `third-party/zcodium/reasoning-rules.js` | 按协议算「最小且正确」的思考字段；并比对本机 ZCode 内置规则与上游切片，报漂移 | stdout | ✅ 长期 |
| `third-party/zcodium/zcode-builtin-reasoning-rules.json` | ZCodium 内置思考规则的最小切片（4 条，逐字抄录，带来源 URL + SHA + license） | 只读参考 | ✅ 长期 |

一次性脚本的结论已固化进 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)，**不用重跑**；
要重跑先改源码里的模型清单。凭据与环境变量口径见 [SECRETS.md](SECRETS.md)；
`--apply` 的备份与回退见 [MAINTENANCE.md](MAINTENANCE.md) §4。
