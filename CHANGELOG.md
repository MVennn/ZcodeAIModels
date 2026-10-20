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

## [未发布] — 2026-10-20

本仓**首次建仓**：从同级的「OpenWrt 工作目录」里把
**AI 模型接入**这一条线整体拆出来，成为独立仓库 `ZcodeAIModels`。

拆分只做两件事：**搬文件** 与 **补文档**。**没有改动任何脚本逻辑**，
**没有改动 ZCode 的 `provider_config.json`**，也没有动原目录里的其它线
（路由器运维、ShellCrash、前端控制台等仍留在 OpenWrt 工作目录）。

### 调整

- 调整 仓库 —— 从 OpenWrt 工作目录拆出独立仓库 `ZcodeAIModels`，可独立上传 GitLab。
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
