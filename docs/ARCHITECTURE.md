# 运行架构整合方案

> **一句话**：把现在的「PowerShell 守护 + Node 路由 + 两个上游进程」收敛成
> **一个 Go 入口进程 + 按需拉起的子进程**，实测常驻内存 293 MB → ~128 MB
> （ZCode 关闭时 ~20 MB），目录按「运行层 / 接入层」两轴重排。

**状态：已落地（2026-10-23）。**
运行层现在是 `gateways/`：`zgate`（Go）监听 7871 并托管两个子进程；
接入层是 `providers/`。落地差异与实测数据见 §10，日常操作见
[MAINTENANCE.md](MAINTENANCE.md) §8。

---

## 0. 结论

**可以整合，但整合的对象不是三个网关，而是我们自己写的那两层。**

三个网关里有两个是**上游 clone**：WorkBuddy2API（Go，`wb2api.exe`）和
qoder2api-hub（Python，`qoder_proxy.py`）。把它们"合进一个进程"等于重写上万个
上游代码，还会丢掉上游更新通道、自带面板、签到与额度逻辑 —— **不可行，也不该做**。

真正冗余的是**我们自己叠在上面的两层**：

| 层 | 现在是什么 | 内存 | 能不能合 |
|---|---|---|---|
| 入口路由 | `tools/unified-router.js`（Node） | 71.5 MB | ✅ 可以并入一个 Go 二进制 |
| 生命周期守护 | `workbuddy/zcode_gateway_watch.ps1`（PowerShell，常驻） | 124.2 MB | ✅ 必须换掉，PowerShell 常驻太贵 |
| WorkBuddy 上游 | `wb2api.exe` | 27.6 MB | ❌ 上游 clone，保留为子进程 |
| Qoder 上游 | `qoder_proxy.py` | 70.1 MB | ❌ 上游 clone，保留为子进程 |

另外要澄清一个前提：**对 ZCode 来说，现在其实已经只有"一路"了** ——
四个 chat 组全部指向 `http://127.0.0.1:7871/v1`。三路是三段内部实现，不是三个对外入口。
所以这次整合省的是**进程与内存**，不是端口；端口方案（7871 对外，7863 / 8790 只监听
回环）保持不变，`provider_config.json` 一个字节都不用改。

目标态：**1 个入口进程（Go，~20 MB）+ 2 个按需子进程**。

| 场景 | 今天 | 整合后 |
|---|---|---|
| ZCode 开着，三条线路都在用 | ~293 MB | ~128 MB |
| ZCode 开着，只用 OpenCode-Go | ~293 MB | ~20-48 MB（子进程按需/空闲回收） |
| ZCode 关着 | ~194 MB（守护器 + Qoder 常驻） | ~20 MB（任务窗口内 ~90 MB） |

---

## 1. 现状（2026-10-23 19:19 实测）

测量命令见 §9，数据单位 MB（WorkingSet）。

| # | 进程 | 端口 | WS | 谁管它的生命周期 | 它挂了会怎样 |
|---|---|---|---|---|---|
| 1 | `powershell.exe`（`zcode_gateway_watch.ps1`） | — | **124.2** | 启动文件夹快捷方式 → `.vbs` | 网关/路由死了没人拉起；ZCode 关掉后网关不回收 |
| 2 | `node.exe tools/unified-router.js` | 7871 | **71.5** | #1 | **四组全挂**（路由在关键路径上） |
| 3 | `python.exe qoder_proxy.py` | 8790 | **70.1** | `start-qoder-proxy.bat`（detached，24/7） | 只有 `qoder:` 模型不可用 |
| 4 | `wb2api.exe` | 7863 | **27.6** | #1 | 只有 `cn:` / `global:` 模型不可用 |
| | **合计** | | **293.4** | | |

四个进程、四条生命周期、四套日志（`watchdog.log` + `gateway.*.log` + `router.*.log` +
`qoder-proxy*.log`），三种实现语言（PowerShell / Node / Python）。

参考基线（同一台机器实测，空载 HTTP 服务）：

- 极简 Go HTTP 服务：**8.3 MB**
- 极简 Node HTTP 服务：**46.6 MB**

也就是说 Node 路由的 71.5 MB 里，约 47 MB 是运行时本身；PowerShell 守护器的
124 MB 里几乎全是运行时 —— **换实现语言的收益比优化代码大得多**。

---

## 2. 约束（决定了方案长什么样）

| 约束 | 来源 | 对方案的影响 |
|---|---|---|
| ZCode 每个 provider 只能填一个 `api.baseUrl` | 客户端机制 | 四组必须共用 7871 入口 → 路由不能去掉 |
| 四个组里混着三个渠道的模型 | [MODEL-ALIAS.md](MODEL-ALIAS.md) | 分流必须按 alias map 的 `chain` 做，不能按组做 |
| 两个上游是 git clone，更新方式是 `git pull --ff-only` | [MAINTENANCE.md](MAINTENANCE.md) §8 | 不能改上游源码；只能当子进程管 |
| Qoder 自带调度器（09:00 / 21:00 签到、22:00 保活） | [QODER.md](QODER.md)、`qoder_scheduler.py` | 停掉即漏任务，除非由外部在窗口内拉起 |
| WorkBuddy 自带签到/活跃/夜猫子/额度刷新，且**只在进程活着时跑** | [MAINTENANCE.md](MAINTENANCE.md) §8 副作用 | 现状已经因为跟 ZCode 起停而漏跑；整合时可以顺手修 |
| 协议桥要处理 Anthropic Messages / OpenAI Responses / 思考字段 / 工具调用 / SSE 合成 | `tools/protocol_bridge.js`（375 行） | 重写必须做等价性回归，不能"看着差不多" |

---

## 3. 方案：`zgate`（一个 Go 二进制）

### 3.1 职责

一个可执行文件，四个子命令：

| 子命令 | 做什么 |
|---|---|
| `zgate serve` | 常驻：监听 7871，做 alias 分流 + 协议桥 + 子进程守护 |
| `zgate status` | 打印各通道/子进程/alias 条数/最近错误（`--json` 给脚本用） |
| `zgate install` / `uninstall` | 注册 / 移除"登录时启动"的计划任务（替代 `.vbs` + 启动文件夹） |
| `zgate replay` | 拿录制的黄金样本回放，和 JS 路由的结果做逐字段比对（见 §6.1） |

### 3.2 进程模型

```
ZCode ──▶ 127.0.0.1:7871  zgate (Go, ~20 MB)
             │
             ├─ alias 未命中/OC 通道 ──▶ https://opencode.ai/zen/go/v1（远程，无本地进程）
             ├─ WB 通道 ──▶ 子进程 wb2api.exe :7863   （按需拉起 / 空闲回收）
             └─ QD 通道 ──▶ 子进程 python qoder_proxy.py :8790（按需拉起 / 空闲回收）
```

- **监听面不变**：仍然只有 7871 对 ZCode 暴露；7863 / 8790 继续只绑 `127.0.0.1`。
- **子进程用 Windows Job Object 托管**：`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，
  zgate 崩了/被结束，子进程一起收掉，不会留孤儿（现在靠 PowerShell 启动时对账清理）。
- **单飞（single-flight）拉起**：同一通道并发首请求只触发一次启动，其余请求排队等
  健康检查就绪（上限可配，默认 15 s，超时返回 503 而不是挂死）。
- **崩溃重启**：带指数退避（1s → 2s → 4s，上限 30s），连续失败 5 次后标记通道降级，
  `/health` 里可见，但**不影响其他通道**。

### 3.3 子进程回收策略（三档，可配置）

| 档 | 行为 | 适用 |
|---|---|---|
| `always` | 常驻，等同今天 | 保守起步；Qoder 签到时唯一安全档 |
| `on-demand` | 首次请求拉起，空闲 N 分钟（默认 10）后停 | WorkBuddy 默认；ZCode 不在时自动归零 |
| `scheduled` | 只在时间段内常驻（如 08:55–09:10、20:55–21:10、21:55–22:10），其余按需 | Qoder 第二阶段评估用 |

`scheduled` 档要落地的关键事实（已核实）：

- Qoder 的签到、保活都有 HTTP 入口：`POST /accounts/checkin`、`POST /tasks/run`
  （`qoder_proxy.py:9392`、`:9304`），面板 token 在 `qoder/.panel-token`。
- Qoder 启动时会做一次"启动巡检"，对 `can_checkin()` 为真的账号补签
  （`qoder_scheduler.py:365` `_allow_complement_checkin`）—— 所以按窗口拉起
  **有机会**补上漏掉的签到，但必须实测确认，不能直接当成前提。
- WorkBuddy 侧同理：进程不在，签到/夜猫子/额度刷新都不跑。整成 `scheduled` 档
  可以顺手修掉这个既有缺陷（现在跟 ZCode 起停，ZCode 关着就漏）。

**推荐先 `always` + `on-demand`，`scheduled` 放最后一档单独验证。**

### 3.4 代码结构

```
gateways/zgate/
├─ main.go                 # 子命令分发
├─ config.json             # 端口 / 超时 / 回收阈值 / 子进程命令（不含凭据）
├─ internal/alias/         # 读 ~/.zcode/v2/model-alias-map.json，按 mtime 热加载
├─ internal/bridge/        # chat ↔ messages/responses + SSE 合成（protocol_bridge.js 的等价物）
├─ internal/router/        # 7871 入口、上游选择、超时、错误归一
├─ internal/supervisor/    # 子进程起停、健康检查、空闲回收、退避、窗口调度
├─ internal/winproc/       # Job Object、进程树终止、端口就绪探测
└─ internal/probe/         # 可选：把 model_probe.py 的探测请求也搬进来
```

规模估计：alias ~200 行、bridge ~450 行（对等 JS 375 行）、router ~350 行、
supervisor ~400 行、windows ~150 行，合计 **~1500 行 Go**，加测试 ~2000 行。
对照要替换的两份 JS + 一份 PS1 合计 946 行 —— **维护面积不会变大**。

### 3.5 顺手合并的三件小事

1. `opencode-go/ops/opencode-header-proxy.js`（8787，给第三方客户端补
   `x-opencode-session`）→ zgate 的第二个监听器，`config.json` 里 `profiles.client-headers`。
   它现在根本没在跑，但迟早要跑，别再多一个 Node 进程。
2. `/health` 从"三家各自回显"升级为统一视图：每个通道的 `state`
   （`up` / `starting` / `down` / `degraded`）、最后一次错误、子进程 PID、alias 条数。
3. 日志合并：`zgate.log`（按大小轮转）+ 子进程 stdout/stderr 各一份，
   目录统一到 `%LOCALAPPDATA%\ZCodeGateway\`。今天的四套日志名保留一版兼容。

---

## 4. 目录重构：按「运行层 / 接入层」两轴

### 4.1 现在的问题

| 问题 | 证据 |
|---|---|
| 同一家供应商的"要跑的进程"和"要跑的脚本"混在一个目录 | `workbuddy/gateway/`（clone，235 文件 48 MB）与 `workbuddy/*.py`（采集脚本）同级 |
| 运行层没有统一的家 | 路由在 `tools/`，守护器在 `workbuddy/`，Qoder 启动脚本在 `qoder/gateway/` |
| 上游 clone 嵌两层 | `qoder/gateway/` 里再套 `docs/`、`scripts/`、`accounts/`，进入仓库后很难判断"哪些是上游、哪些是我们的" |

全仓 tracked 文件只有 97 个，但两个 clone 带进来 439 个文件 / 63 MB ——
**目录混乱主要是 clone 位置造成的，不是文档造成的**。

### 4.2 目标结构

```
ZcodeAIModels/
├─ gateways/                    # 【运行层】唯一会产出进程的目录
│  ├─ zgate/                    #   我们的 Go 入口（源码 + config.json）
│  ├─ upstream/
│  │  ├─ workbuddy/             #   ← workbuddy/gateway（clone，gitignored）
│  │  └─ qoder/                 #   ← qoder/gateway（clone，gitignored）
│  └─ runtime/                  #   日志 / pid / 状态（gitignored）
├─ providers/                   # 【接入层】只会被手动执行，不常驻
│  ├─ opencode-go/              #   ← opencode-go/{ops,probe}
│  ├─ workbuddy/                #   ← workbuddy/*.py、cache/、logs/
│  └─ qoder/                    #   ← qoder/*.py、.env.local、qoder_probe.json
├─ tools/                       # 跨供应商工具：model_alias / arena / model_probe / check-*
├─ third-party/                 # 不变（随仓分发的上游切片）
├─ docs/  evidence/  memories/  # 不变
└─ README.md  AGENTS.md  CHANGELOG.md  PROGRESS.md
```

判断规则一句话：**会被启动的东西进 `gateways/`，被手动执行的东西进 `providers/`，
跨供应商复用的进 `tools/`。**

### 4.3 路径映射表（迁移必改）

| 现在 | 之后 |
|---|---|
| `workbuddy/gateway/` | `gateways/upstream/workbuddy/` |
| `qoder/gateway/` | `gateways/upstream/qoder/` |
| `tools/unified-router.js`、`tools/protocol_bridge.js` | 迁入 `gateways/zgate/` 并重写为 Go；JS 版留在 `gateways/legacy-router/` 作回退 |
| `opencode-go/ops/opencode-header-proxy.js` | 先留在 `providers/opencode-go/ops/`，P3 后由 zgate profile 取代 |
| `opencode-go/{ops,probe}/` | `providers/opencode-go/` |
| `workbuddy/*.py`、`workbuddy/cache/`、`workbuddy/logs/` | `providers/workbuddy/` |
| `workbuddy/zcode_gateway_watch.ps1` / `.vbs` | 退役 → `zgate install`（P2 后删除） |
| `qoder/*.py`、`qoder/.env.local` | `providers/qoder/` |
| `tools/*.py`、`third-party/`、`docs/`、`evidence/` | 不动 |

### 4.4 迁移步骤（一次性，半天）

1. 关 ZCode；停守护器、停路由；`workbuddy/gateway/stop-gateway.bat`；
   `qoder/gateway/stop-qoder-proxy.bat`（**Qoder 必须停，它的 cwd 就在被移动的目录里**）。
2. tracked 文件用 `git mv`；两个 clone 是独立 `.git`，用普通 `mv`（保留 `.git`，
   上游更新命令随之改为 `git -C gateways/upstream/qoder pull --ff-only`）。
3. 改 `.gitignore`：`/workbuddy/gateway/` → `/gateways/upstream/workbuddy/`，
   `/qoder/gateway/` → `/gateways/upstream/qoder/`，`/workbuddy/cache/*.json` →
   `/providers/workbuddy/cache/*.json`，另加 `/gateways/runtime/`、`*.exe`。
4. 改代码里的硬编码路径（**已定位，共 4 个文件**）：
   - `tools/model_alias.py:60-61`（`WB_PRICING`、`QD_ENV`）
   - `tools/model_probe.py:39`（`EFFECTIVE`）
   - `tools/check-docs.py:26`、`tools/check-secrets.py:30`（`SKIP_REL_PREFIXES`）
5. 改文档引用：16 篇文档 + `README.md` / `AGENTS.md` / `CONTRIBUTING.md` /
   `.github/ISSUE_TEMPLATE/bug_report.yml` 里共有 130 处路径。
   做法：`git grep -l 'workbuddy/gateway\|qoder/gateway\|opencode-go/\|tools/unified-router'`
   一次改完，再用同一命令确认归零。
6. 重建启动入口：`qoder` 的 `start-*.bat` 用 `%~dp0` 自推导，移动后仍可用；
   WorkBuddy 的 `run.bat` / `stop-gateway.bat` 同理。P2 之后统一收归 `zgate`。
7. CI 跑一遍：`python tools/check-docs.py`、`python tools/check-secrets.py`、
   `node --check`、`go build ./...`。

> **要不要搬？** 建议搬，而且现在搬 —— tracked 文件才 97 个，越晚成本越高。
> 若不想承担 130 处引用的改动，最小替代方案是只新建 `gateways/`，
> 把两个 clone 搬进去、`zgate` 放进去，`providers/` 暂缓 —— 省一半改动，结构仍改善。

---

## 5. 分阶段实施

每个阶段都能独立交付、独立回退，**不要求一次做完**。

### P0 · 目录重构（0.5 天，零行为变化）

- 做 §4.3 的移动 + 引用修正。
- 验收：`check-docs` / `check-secrets` 通过；ZCode 四组模型列表不变；三个网关重启后可用。

### P1 · Go 守护器顶掉 PowerShell（1 天，省 ~114 MB）

- 只写 `internal/supervisor` + `internal/winproc` + `install/status`；路由仍是 Node。
- 行为对齐今天：跟随 ZCode 主进程、8 s 宽限、5 s 排空、崩溃重启、心跳、孤儿清理。
- 验收：见 §7 的 1–6 项。

> 若不想引入 Go：把守护逻辑并进 `unified-router.js` 也能省掉这 114 MB（仍是一个
> Node 进程 71.5 MB），代码量约 300 行。这是**方案乙**，见 §8 选项 A。

### P2 · Go 路由 + 协议桥（2–3 天，再省 ~51 MB，去 Node 依赖）

- `internal/alias`、`internal/bridge`、`internal/router`；`zgate replay` 黄金回归先绿再接。
- 端口、路径、错误码、SSE 分片节奏保持兼容。
- 验收：§7 的 7–10 项。

### P3 · 子进程按需回收 + 定时窗口（1–2 天，再省 28–70 MB 空闲）

- WorkBuddy 先上 `on-demand`（ZCode 关闭即归零）；
- Qoder 先保持 `always`，验证补签行为后再切 `scheduled`。
- 验收：§7 的 11–13 项。

累计（实测口径）：

| 阶段 | 常驻进程 | ZCode 开着 | ZCode 关着 |
|---|---|---|---|
| 今天 | 4 | 293 MB | 194 MB |
| P1 | 3 | 179 MB | 90 MB |
| P2 | 2（+1 子进程） | 128 MB | 90 MB |
| P3（推荐档） | 1–3 | 118 MB / 48 MB（按需） | 90 MB |
| P3（Qoder 也切 scheduled） | 1 | 118 MB / 48 MB | **~20 MB** |

---

## 6. 风险与回退

### 6.1 协议桥重写的等价性风险（最高）

`protocol_bridge.js` 处理的是"看着差不多、实际差很多"的细节：思考字段、
工具调用结构、非流式上游伪造成 SSE。**靠肉眼 review 一定会漏。**

对策 —— 黄金样本回归，P2 开工前先做：

1. 在 7871 前置一个录制代理（或直接给 JS 路由加 `--record`），
   录下每个通道 × 每种协议的请求体、响应体、状态码、关键响应头（**不含 key**）。
2. 样本存 `evidence/golden/`（脱敏后可用）。
3. `zgate replay --golden evidence/golden/` 逐条比对：状态码相等、JSON 归一后深比较
   相等、SSE 事件序列（`event` 类型 + `[DONE]`）相等。
4. 不相等即视为回归，必须先修。

### 6.2 其他风险

| 风险 | 影响 | 对策 |
|---|---|---|
| 子进程杀不干净（端口占用） | 重启失败 / 端口冲突 | Job Object + 端口就绪探测 + 启动前按 PID/端口对账 |
| 按需拉起引入首字延迟（1–3 s） | 体验下降 | 默认 `always` 起步；`on-demand` 只对 WB 开；健康检查预热 |
| 防护软件拦新 exe | 起不来 | 本地构建、不随仓库发 exe；首次运行加白 |
| 单点：zgate 崩了四组全挂 | 全渠道不可用 | 计划任务"失败即重启"；`/health` 里暴露自身存活；子进程独立进程仍可直连兜底 |
| 迁移期间 JS 路由和 Go 路由抢 7871 | 启动失败 | 迁移只在 ZCode 关闭时做；端口占用时 `zgate` 拒绝启动并明确报错 |
| 目录搬迁漏改引用 | 脚本静默失败 | `git grep` 归零检查 + CI 里加一条路径存在性断言 |

### 6.3 回退

- P0：`git revert` 一个提交（clone 是 untracked，搬回即可）。
- P1：`zgate uninstall` → 重新 `zcode_gateway_watch.ps1 -Install`。
- P2：`config.json` 里 `router.impl = "node"`，仍可回落 JS 版（保留一个版本）。
- P3：`config.json` 里把通道改回 `always`，重启即恢复今天行为。

---

## 7. 验收

| # | 项目 | 怎么验 |
|---|---|---|
| 1 | 内存 | 同一张 `Get-Process` 表（§9）复测，记录各阶段数值 |
| 2 | ZCode 起停联动 | 开 ZCode → 子进程在 2 s 内就绪；关 ZCode → 宽限期后回收，端口释放 |
| 3 | 崩溃重启 | `Stop-Process` 掉子进程 → 5 s 内自动回来；`/health` 反映状态变化 |
| 4 | 孤儿清理 | 强杀 zgate → 子进程随之退出（Job Object 生效） |
| 5 | 心跳/日志 | 15 min 一条心跳；日志轮转正常，UTF-8 不乱码 |
| 6 | 不回归 | 四组共 36 个模型的列表、`baseUrl` 与今天完全一致 |
| 7 | 黄金回归 | `zgate replay` 全绿（§6.1） |
| 8 | 流式 | 三个渠道各挑一个流式请求，首字时间与今天同量级，SSE 无截断 |
| 9 | 工具调用 | 各渠道一个工具调用样本，参数 JSON 完整 |
| 10 | 思考字段 | 按 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) 的矩阵抽样：会 400 的模型不再 400 |
| 11 | 按需回收 | 空闲阈值到点后子进程消失，下次请求自动拉起 |
| 12 | 定时窗口 | 临时把窗口设到 2 分钟后，确认按时拉起、按时回收 |
| 13 | 签到 | 至少观察一个真实签到窗口（09:00 或 21:00），确认 `scheduled` 档不漏 |

---

## 8. 待确认（每项都给了推荐）

> **2026-10-23 已按推荐项落地**：A 选 ①、B 选 ①、C 选 ①（Qoder 保持常驻）、
> D 留作配置项、E 选 ②（JS 保留一个版本）。落地差异见 §10。

| # | 问题 | 选项 | 推荐 |
|---|---|---|---|
| A | 入口换成 Go，还是保守地把守护并进现有 Node 路由？ | ① Go 一体（293→128，去 Node 依赖）② Node 一体（293→169，改动最小） | **①**：Go 1.26 已装，桥+路由共 ~1500 行，换掉 946 行 JS/PS1，维护面积不增；②可作为第一步 |
| B | 目录一次搬完（`gateways/` + `providers/`），还是只搬 clone？ | ① 全搬（130 处引用）② 只搬 clone | **①**：tracked 仅 97 个文件，现在搬最便宜 |
| C | Qoder 允许按需停吗（会影响 09:00 / 21:00 签到）？ | ① 保持 24/7 ② 切 `scheduled` 窗口 | **②但要先实测**：窗口拉起后 `_allow_complement_checkin` 是否真补签；不成立就退回 ① |
| D | WorkBuddy 的签到/夜猫子/额度刷新要不要顺手修好（现在是"ZCode 关着就不跑"）？ | ① 维持现状 ② 交给 zgate 定时窗口 | **②**：反正要写调度器，顺手补上，等于免费修一个既有缺陷 |
| E | JS 路由保留多久？ | ① P2 后立即删 ② 留一个版本作回退 | **②**：留到 P3 验收通过再删 |

---

## 9. 附录

### 9.1 本文数据的测量命令

```powershell
# 各进程常驻内存
Get-CimInstance Win32_Process -Filter "Name='node.exe' or Name='python.exe' or Name='wb2api.exe' or Name='powershell.exe'" |
  Select-Object ProcessId,Name,CommandLine,
    @{n='WS_MB';e={[math]::Round($_.WorkingSetSize/1MB,1)}}

# 端口归属
foreach ($p in 7863,7871,8790,8787) {
  $c = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  if ($c) { "{0} -> pid {1} ({2})" -f $p,$c.OwningProcess,(Get-Process -Id $c.OwningProcess).ProcessName }
  else { "$p 未监听" }
}
```

### 9.2 被否掉的方案

| 方案 | 为什么不做 |
|---|---|
| **去路由化**：四组拆成"每家 × 四档"共 12 个 provider，ZCode 直连各网关 | 省 71 MB 路由，但 UI 从 4 组变 12 组；协议/思考参数要按上游各配一遍；改名与排序规则全部重做。**用体验和维护量换内存，不划算** |
| **换现成聚合器**（CLIProxyAPI / OmniRoute / Agent2API / LiteLLM） | 能替 Node 路由，但要重接 alias map、协议桥、思考参数矩阵；WB/QD 的面板、签到、额度都在上游进程里，聚合器替不掉。等于用黑盒换 50 MB，回归风险高于自研 |
| **把两个上游重写成 Go 或嵌进本进程** | wb2api（Go 上游，含 panel/auths/定时任务）与 qoder_proxy（Python 1.1 万行，含 OAuth/签名/风控/调度/看板）重写成本以月计，且放弃 `git pull` 更新通道。**不可行** |
| **加一层 Nginx/Caddy 统一反代** | 只是把两段跳转变三段，多一个进程，内存反而涨 |
| **`node --snapshot-blob` / Bun 单文件** | Bun 单文件体积与内存都不比 Node 好；snapshot 省的是启动时间不是常驻内存 |

---

## 10. 落地记录（2026-10-23）

### 10.1 实际做了什么

| 阶段 | 结果 |
|---|---|
| P0 目录重构 | 完成。`gateways/{zgate,legacy-router,upstream/{workbuddy,qoder}}` + `providers/{opencode-go,workbuddy,qoder}`；4 个脚本的硬编码路径、`.gitignore`、19 篇文档/模板的路径全部改齐，`check-docs` / `check-secrets` 通过 |
| P1 守护器 | 完成，但**没有**按原计划跟随 ZCode 主进程 —— 见 §10.2 |
| P2 路由 + 协议桥 | 完成。Go 实现约 2000 行（含测试），替换 857 行 JS |
| P3 子进程回收 | 两个上游都用 `ondemand`（空闲 300 秒回收）；签到/保活用 `windows` 定时窗口兜底 |

### 10.2 与提案的差异

1. **去掉了「跟随 ZCode 主进程」**。在 Go 里判 ZCode 主进程要读 PEB 命令行（`--type=` 过滤），
   实现成本高且脆弱。改成 **zgate 常驻 + 子进程策略**：zgate 约 19 MB，常驻代价远小于原来的
   PowerShell 守护器（124 MB），还顺手解决了「ZCode 关着时 WorkBuddy 定时任务不跑」的老问题 ——
   把 `children.workbuddy.policy` 设成 `always` 即可让它 24/7 跑。
2. **自启用启动文件夹快捷方式**，不是 `schtasks /create /sc ONLOGON`（当前权限下返回「拒绝访问」）。
3. ~~`scheduled` 窗口档没有实现~~ —— 2026-10-23 晚补上（见 §10.6）：它不是第三种 policy，
   而是给任意 child 加的 `windows` 列表，窗内按 `always` 处理。
4. **旧 JS 路由保留**在 `gateways/legacy-router/`，作为回退；P3 验收通过后可删。

### 10.3 等价性验证

旧路由（7871）与新入口（7971）并排跑同一批请求，9 个用例逐项比对状态码、响应形态、
SSE 事件序列：OC chat / WB chat（含 fallback chain）/ QD chat / messages 桥 / responses 桥 /
三种流式 / 未知模型，**9/9 一致**。之后切到 7871，四条通道各打一发真实请求全部 200；
WB 冷启动 1.6 秒，Qoder 由 zgate 启动后 `/ping` 200。

### 10.4 实测内存

| 状态 | 改造前 | 改造后 |
|---|---|---|
| 三路都在用 | 293.4 MB（4 进程） | **99.3 MB**（zgate 18.7 + Qoder 57.4 + wb2api 23.2） |
| WB 空闲 15 分钟回收后 | — | **76.1 MB**（zgate + Qoder） |
| 全部停掉只剩 zgate | — | **18.7 MB** |

省下来的主要是 PowerShell（124.2 MB）与 Node（71.5 MB）两个运行时，
与 §1 的基线测量一致：Go 空载 8.3 MB、Node 空载 46.6 MB。

### 10.5 已知取舍

- WB 首次请求多 1–2 秒冷启动（旧守护器在 ZCode 启动时就常驻了）。
  不能接受就把 `children.workbuddy.policy` 改成 `always`。
- 路由与桥的行为靠 §10.3 的样本兜底；后续改 `model-alias-map.json` 或思考参数矩阵时，
  仍需按 [MAINTENANCE.md](MAINTENANCE.md) §3 先探测再同步。

### 10.6 追加：全部按需 + 定时窗口（2026-10-23 晚）

用户要求「没被调用就不要拉起任何一个网关」。落地为：

| 变化 | 说明 |
|---|---|
| 两个 child 都改 `ondemand` | ZCode 启动后不再自动起 Qoder；7863 / 8790 平时都是空的 |
| 新增 `children.*.windows` | 本地时间 `HH:MM-HH:MM`，支持跨午夜；窗内等同 `always`，窗口结束再按 `idleSeconds` 回收 |
| 默认窗口 | WB：`08:58-09:15`、`09:58-10:15`、`20:58-21:15`、`21:58-22:15`；Qoder：三档（9 / 21 / 22 点） |
| 空闲阈值降到 300 秒 | 一次对话结束后 5 分钟内回收 |
| 新增 `zgate reload` + `POST /admin/reload` | 改策略/窗口/阈值不用重启；新增 child、监听地址、上游 base 仍需重启 |

顺带修掉的问题：

- 协议桥加 120 秒超时（旧 JS 有，Go 版最初漏了）；
- `Process.Release` 改为 `sync.Once`，消除监控 goroutine 与主动停止的 double CloseHandle；
- 接管的 `external` 实例每 5 秒做一次健康检查，死了会转回 zgate 管理并自动重启；
- 重启退避改成 1s→2s→4s→…→60s（与 §3.2 一致）；
- 日志在运行期按 5 MB 轮转（常驻进程原来只有启动时轮转）；`zgate status` 不再打开写句柄；
- **回退链补齐**：WB 的 `400 model_unavailable`（上游 6004 模型级限流）原来不触发 region fallback，
  现在按池故障处理（普通 400 不重试）；
- `qoder:` 前缀改成大小写不敏感；清理了若干死代码（`WaitExit`、`Missing`/`Redacted`、无用的 log 字段）。

实测（新二进制，旁路 7971 验证）：

- 启动时不带窗口的子进程保持 `stopped`；窗口内的子进程自动 `running`；
- `POST /admin/reload` 去掉窗口并把 `idleSeconds` 设 1 后，一个 tick 内回到 `stopped`；
- 单元测试新增：窗口解析/跨午夜、`ApplyConfig`、退避序列、桥超时、`/admin/reload`，共 24 个用例。
