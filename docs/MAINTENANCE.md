# 维护流程

> **一句话**：价格表怎么刷、探测多久跑一次、结果留多久、`--apply` 前怎么备份、
> 写完怎么回退 —— 这五条是本仓的日常维护动作。

模型清单与参数口径的正本在 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)；
出问题的排查在 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

---

## 1. 价格表刷新

### 1.1 OpenCode-Go —— 不用手工刷

`go_model_sync.py` 每次运行都现拉：

| 源 | 地址 | 取什么 |
|---|---|---|
| 实时模型清单 | `https://opencode.ai/zen/go/v1/models` | 模型 id（**不需要鉴权**） |
| Go 套餐文档页 | `https://opencode.ai/v2/docs/console/go/` | 模型表（端点 = 协议）、定价表（月额度） |
| 全量目录页 | `https://opencode.ai/v2/docs/console/models` | 公开价、Free 标记、弃用日期表 |
| 本地已配置 | `provider_config.json` | 有些能用的模型**不在任何清单里** |

**四源必须取并集** —— 任一源都不完整（实测：`deepseek-v4-flash-vision-exp` 不在
`/models` 清单里但三协议全 200；弃用表第一列是显示名不是 id；价格表要
「显示名去括号后归一化」再对 id）。

### 1.2 WorkBuddy —— 价格表由 `workbuddy_fetch_pricing.py` 生成

`workbuddy/cache/wb_pricing.json`（模型倍率 / 上下文 / 输出上限 / effort 档位）
由 **`workbuddy_fetch_pricing.py`** 生成：它 `GET /panel/api/models`，把上游条目
**归一化**成下表字段，写进 `cache/wb_pricing.json`（写前自动备份旧文件）。

```bash
cd workbuddy
python workbuddy_fetch_pricing.py            # 写入
python workbuddy_fetch_pricing.py --dry-run  # 只看差异，不落盘
```

它还会打印**变动摘要**：倍率变化的模型、新增的模型、下架的模型 —— 刷完一眼就能看出套餐改了什么。

| 字段 | 含义 | 取法 |
|---|---|---|
| `id` | 模型 id，带 `cn:` / `global:` 前缀 | 网关 `/panel/api/models` |
| `credits` | 牌价（如 `"x0.29"`） | 同上 |
| `promo` / `promo_label` | 促销价与标签（"限时免费"、"Free now"） | 同上 |
| `list_rate` / `eff_rate` | 牌价倍率 / 生效倍率 | `promo_credits` 优先，回落 `credits` |
| `ctx` / `out` | 上下文长度 / 输出上限 | 同上 |
| `tool` / `img` | 是否支持工具调用 / 图片输入 | 同上 |
| `efforts` / `default_effort` | 支持的 effort 档位与默认档 | 同上 |
| `can_disable` | 能否关掉思考 | 同上 |
| `only_reasoning` | 是否只能推理模式 | 同上 |

**只想看原始返回**（不生成文件）：

```bash
curl -s http://127.0.0.1:7863/panel/api/models \
  -H "Authorization: Bearer $WB_GATEWAY_KEY" | python -m json.tool | head -40
```

> ⚠️ 网关**未重启时** `/panel/api/models` 只返回 34 个 global 模型，
> 重启后返回全部 56 个（cn 22 + global 34）。取数前先确认网关状态。

**多久刷一次**：限时免费会到期（网关日志里有 `free tier ended, now 0.227 credits/1k`），
倍率也会调整。**建议每月一次**，以及**每次准备大规模探测之前**。

---

## 2. 探测的频率与限速

### 2.1 频率

| 场景 | 频率 | 命令 |
|---|---|---|
| OpenCode-Go 新模型收录 | **每天一次** | `python opencode-go/ops/go_model_sync.py --apply` |
| 已配置模型体检 | 跟上面同一次 | 同上（默认会体检；`--no-existing` 可跳过） |
| WorkBuddy 可用性复探 | **换套餐 / 换账号池后**才需要全量重探 | `python workbuddy/workbuddy_probe_zcode.py --sleep 20` |
| 某个模型单独复探 | 按需 | `python workbuddy/workbuddy_probe_zcode.py --only <前缀> --sleep 20 --force` |

**不要**把全量探测挂成高频定时任务 —— 探测会消耗额度，也会触发上游限流。

### 2.2 限速（硬约束）

| 约束 | 值 | 后果 |
|---|---|---|
| WorkBuddy 探测间隔 | **≥ 20 秒** | 4 秒间隔会把 global 全部打进 `no_healthy_account` 冷却，**首次探测即如此**；严重时**网关进程被打崩** |
| 网关账号池规模 | 4 个号（global 3 + cn 1） | 没有余量，批量并发必爆 |
| 路由侧（若同时跑别的线） | 批量探测必须**串行化** | 历史上 10 个子代理同时密集探测 → 负载冲到 2.6 → 看门狗复位 |

**探测前先确认网关活着**：`curl http://127.0.0.1:7863/status`。

### 2.3 探测必须用 ZCode 真实 body

WorkBuddy 侧**只能用** `workbuddy_probe_zcode.py`（它先调 `zcode_effective_body.js`
算出 ZCode 真实会发的 body，失败再退 slim variant）。
裸 body 探测的结果**不可信** —— 网关会把 ZCode 注入的思考字段原样转发给上游，
上游不认就 400。机制见 [PITFALLS.md](PITFALLS.md) §2。

---

## 3. 探测结果快照的保留策略

| 文件 | 内容 | 保留 | 理由 |
|---|---|---|---|
| `workbuddy/cache/wb_pricing.json` | 网关倍率快照（活数据） | 本机保留，**不随仓库分发** | 含账号池相关信息；也因为需要定期刷新 |
| `workbuddy/cache/wb_zcode_probe.json` | 探测结果缓存（活数据，断点续跑用） | 本机保留，**不随仓库分发** | 含账号池探测结果 |
| `workbuddy/logs/wb_zcode_probe.log` | 探测日志 | 本机保留，**不随仓库分发** | 一次性日志 |
| `opencode-go/probe/results/20261019/*.json` | 三份探测原始结果（34 模型 / 28 组基准 / 决赛采样） | 本机保留，**不随仓库分发** | 体积大、可重跑再生。三个探测脚本把结果写到**当前工作目录**，跑完要手动挪进 `results/<日期>/` |
| `evidence/wb_panel_models.json` | 网关模型目录快照 | **随仓库分发** | 目录结构证据，无凭据 |
| `evidence/go-model-sync/*.md` | 每次自动收录的报告 | **随仓库分发**（可挑代表性的几份） | 收录决策的证据 |

**原则**：

- **活数据随机器走，不随仓库走** —— `.gitignore` 已排除；
  凭据与活数据缓存在哪、怎么取，见 [SECRETS.md](SECRETS.md)。
- **结论随仓库走** —— 结论写进 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)，
  原始快照放 `evidence/`。
- **历史报告不要全留** —— 保留「首次写入版」与「最近一版」即可，中间版本价值低。
- 快照文件名带日期（`results/<YYYYMMDD>/`），**不要覆盖**。

---

## 4. `--apply` 前的备份与回退

### 4.1 两个脚本都会自动备份

| 脚本 | 备份文件名 | 写入方式 |
|---|---|---|
| `go_model_sync.py --apply` | `provider_config.json.bak-gosync-<时间戳>` | 写 `.tmp` → 校验 JSON → `os.replace` 原子替换 |
| `workbuddy_zcode_sync.py --apply` | `provider_config.json.bak-wbproxy-<时间戳>` | 同上（`.tmp-wbproxy` → `os.replace`） |

### 4.2 手动备份（建议在批量操作前额外做一份）

```bash
cp ~/.zcode/v2/provider_config.json \
   ~/.zcode/v2/provider_config.json.manual-$(date +%Y%m%d-%H%M%S)
```

### 4.3 回退

```bash
# 1) 看有哪些备份
ls -lt ~/.zcode/v2/provider_config.json*

# 2) 回退到指定那份
cp ~/.zcode/v2/provider_config.json.bak-wbproxy-20261020-163812 \
   ~/.zcode/v2/provider_config.json

# 3) 确认 JSON 合法
python -c "import json,os; json.load(open(os.path.expanduser('~/.zcode/v2/provider_config.json'),encoding='utf-8')); print('OK')"
```

回退后 **ZCode 约 1 秒内会热重载**回旧配置，不用重启。

### 4.4 `--apply` 的两种风险

| 脚本 | 行为 | 风险 |
|---|---|---|
| `go_model_sync.py --apply` | 只**追加**模型 + 改一个 provider 显示名（"备用"→"响应"） | 低。已有模型的**组内顺序**可能被打乱（新模型追加到组尾） |
| `workbuddy_zcode_sync.py --apply` | **整条替换** `workbuddy-free/low/high` 三个 provider 及其全部模型规则 | 中。这三个 provider 上你手工加的模型会被冲掉；其它 provider 不受影响 |

**正确姿势**：先不带 `--apply` 跑一遍，看清它要写什么，再决定。

```bash
python opencode-go/ops/go_model_sync.py            # 只出报告
python workbuddy/workbuddy_zcode_sync.py           # 只打印计划
```

---

## 5. ZCode 配置热重载的注意事项

**ZCode 约 1 秒轮询 `provider_config.json`** —— 脚本写完一般不用重启客户端。

| 注意点 | 说明 |
|---|---|
| **写配置期间不要在 ZCode 界面里改** | 界面保存时会**整份写回**，把脚本刚写的覆盖掉。这是最常见的「配置被莫名改回去」原因 |
| 写完等 1~2 秒再看列表 | 轮询不是瞬时的 |
| 仍不刷新就重启客户端 | 极少数情况下客户端没在轮询 |
| 重启客户端**不影响**配置 | 配置在磁盘上，不在客户端里 |
| `providerId` 不要随便改 | 旧会话可能引用它；改 `providerName`（显示名）才安全 |
| 脚本与界面**同一时间只有一个写入者** | 两个写入者会互相覆盖 |

---

## 6. 定期动作清单

| 周期 | 动作 |
|---|---|
| **每天** | `python opencode-go/ops/go_model_sync.py --apply`（新模型自动收录） |
| **每月** | 手工刷新 `workbuddy/cache/wb_pricing.json`；复核 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) 里的价格 / 额度 |
| **换套餐 / 换账号池后** | 全量重探 WorkBuddy（`--sleep 20`）+ 重跑同步 |
| **每次改动脚本** | 同步根 [README.md](../README.md) 的「文件清单」表 |
| **每次新增 / 删除文档** | 同步 [docs/README.md](README.md) 索引（孤儿文档零容忍） |
| **每次踩新坑** | 写进 [PITFALLS.md](PITFALLS.md)；有对应排错条目的同步 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| **每次发版** | 按 [VERSIONING.md](VERSIONING.md) §1 定版本号，写 [CHANGELOG.md](../CHANGELOG.md) + `docs/release-notes/<版本>.md` |

---

## 7. 本仓已登记的待办

| # | 事项 | 影响 | 详见 |
|---|---|---|---|
| 1 | ~~`wb_pricing.json` **没有生成脚本**~~ **已修** | 已有 `workbuddy_fetch_pricing.py`：拉网关 → 归一化 → 写 `cache/wb_pricing.json`（自动备份 + 变动摘要） | §1.2、[PITFALLS.md](PITFALLS.md) §11 |
| 2 | ~~探测脚本里**仍有明文 API key**~~ **已修** | 5 个探测脚本改为读 `OPENCODE_GO_KEY`，**未设置时明确报错退出**；凭据不再随源码分发 | [SECRETS.md](SECRETS.md)、[PITFALLS.md](PITFALLS.md) §9 |
| 3 | ~~`go_model_sync.py` 的 `REPORT_DIR` 仍硬编码旧仓库路径~~ **已修** | 拆仓时改为本仓内 `evidence/`，可用 `GO_SYNC_REPORT_DIR` 覆盖 | [PITFALLS.md](PITFALLS.md) §10 |
| 4 | ~~根 `LICENSE` 文件未创建~~ **已修** | 仓库根已有 MIT 全文（见 [LICENSE](../LICENSE)），不再只有 `README.md` 里的一句话 | [CHANGELOG.md](../CHANGELOG.md) 「待补」 |
| 5 | ~~`docs/VERSIONING.md` 未创建~~ **已修** | 版本晋升规则有独立正本 [VERSIONING.md](VERSIONING.md)，不再暂以 `CHANGELOG.md` 头部为正本 | [VERSIONING.md](VERSIONING.md) §1–§2 |

---

## 8. 相关文档

| 要查什么 | 去哪 |
|---|---|
| 发版时版本号动哪一位（版本晋升规则正本） | [VERSIONING.md](VERSIONING.md) §1–§2 |
| Release 说明怎么写 | [release-notes/README.md](release-notes/README.md) |
| 凭据（OpenCode-Go key / 网关 key / ZCode 配置路径）在哪 | [SECRETS.md](SECRETS.md) |
| provider 分组、协议类型、参数矩阵 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) |
| 排障步骤 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
