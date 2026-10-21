# 更新日志

> **一句话**：本仓每次改动记在这里 —— 改了什么、为什么、怎么回退；
> 首个版本段落记录本仓从原工作目录拆分建仓的全过程。

版本命名遵循三段式进位：**有功能更新进次版本（+0.1.0），没有就进补丁版本（+0.0.1）**；
破坏性变更同样走次版本，并在版本段落里显式标注。进位规则正本见
[docs/VERSIONING.md](docs/VERSIONING.md) §1 与 §2。

- 「功能更新」= 新增了脚本 / 新增了 provider 分组 / 现有脚本的行为变了。
- 只修 bug、改文档、调参数 → **+0.0.1**。
- 本仓库**没有编译产物**，版本号以本文件的段落标题为准
  （与 `docs/release-notes/v<version>.md` 的文件名必须一致）。

---

## [未发布] — 2026-10-21

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
- 调整 文档 —— 新增 `docs/release-notes/README.md`（Release 说明格式正本）与 `docs/release-notes/v0.1.0.md`（首版说明）。
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


