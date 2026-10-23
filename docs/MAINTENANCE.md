# 维护流程

> **一句话**：价格表怎么刷、探测多久跑一次、结果留多久、`--apply` 前怎么备份、
> 写完怎么回退 —— 这五条是本仓的日常维护动作。

模型清单与参数口径的正本在 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)；
出问题的排查在 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

> **2026-10-23 起**：ZCode 统一为四组（主力 / 免费 / 低耗 / 高耗），最终写入者是
> `tools/model_alias.py`。旧的 Go / WorkBuddy / Qoder sync 只作数据采集；日常顺序是
> `arena_leaderboard.py --refresh --write` → `model_probe.py` →
> `model_alias.py --probe-file … --apply`。命名/积分规则见
> [MODEL-ALIAS.md](MODEL-ALIAS.md)，榜单扩充口径见
> [BENCHMARKS.md](BENCHMARKS.md) §8。

---

## 1. 价格表 / 模型目录刷新

### 1.1 通用做法（换供应商照这个做）

**任何**供应商的目录接口都会变：涨价、促销到期、模型下架、新模型上架。
所以「价格表」一定会过期，**必须有一个可重跑的取数脚本**，不能手工维护 JSON。

通用三步：

| 步 | 做什么 | 要点 |
|---|---|---|
| 1 | 找到该供应商的**模型目录接口** | 通常是 OpenAI 兼容的 `/v1/models`，或带价格字段的面板接口；本仓两个实例的地址见 §1.2 / §1.3 |
| 2 | 把返回**归一化**成一张统一字段的价格表 | 字段集照 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) 的实例表：id / 单价或倍率 / 上下文 / 输出上限 / 工具调用 / 思考档位 / 能否关思考 |
| 3 | 写盘 + 打**变动摘要** | 写前自动备份；摘要要能一眼看出「倍率变了 / 新增了 / 下架了」 |

**分档是纯本地计算** —— 归一化做完之后，换档数、换阈值都不用动取数脚本。
探针部分（哪些模型真能调通）是另一条线，见 §2。

### 1.2 实例 A：OpenCode-Go —— 不用手工刷

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

> 这条「四源并集」是**通用教训**：单一目录接口几乎从不完整。
> 接新供应商时，先想清楚「有哪些源能拿到模型 id」，取并集。

### 1.3 实例 B：WorkBuddy —— 价格表由 `workbuddy_fetch_pricing.py` 生成

`providers/workbuddy/cache/wb_pricing.json`（模型倍率 / 上下文 / 输出上限 / effort 档位）
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

> **接别的供应商**：§1.1 讲的是通用做法；这里只是把「本仓实例 B 的目录接口与字段」
> 具体化了。换成你的供应商，改的是**取数那一段**（接口地址 + 字段映射），
> 归一化之后的字段集、备份与变动摘要的逻辑照抄即可。

---

## 2. 探测的频率与限速

> **通用原则**：探测会消耗额度，也会触发上游限流，**不要挂成高频定时任务**。
> 限速的具体数值取决于对方的账号池规模 —— 池子越小，越要拉长间隔。

### 2.1 频率

| 场景 | 频率 | 命令 |
|---|---|---|
| OpenCode-Go 新模型收录 | **每天一次** | `python providers/opencode-go/ops/go_model_sync.py --apply` |
| 已配置模型体检 | 跟上面同一次 | 同上（默认会体检；`--no-existing` 可跳过） |
| 外部榜单 → 主力候选 | **每天一次**（随 08:00 / 22:00 与工作日时段） | `python tools/arena_leaderboard.py --refresh --write` |
| 候选变化 → 重写四组 | 随上一步；候选没变脚本会跳过 | `python tools/model_alias.py --slot auto --probe-file ~/.zcode/v2/model_probe.json --apply` |
| WorkBuddy 可用性复探 | **换套餐 / 换账号池后**才需要全量重探 | `python providers/workbuddy/workbuddy_probe_zcode.py --sleep 20` |
| 某个模型单独复探 | 按需 | `python providers/workbuddy/workbuddy_probe_zcode.py --only <前缀> --sleep 20 --force` |

**不要**把全量探测挂成高频定时任务 —— 探测会消耗额度，也会触发上游限流。
榜单接口不消耗本仓额度，可以随时 `--refresh` 看排名；`--apply` 只在候选集合或规则
变化时才重写配置（脚本自己判断），所以不会每 10 分钟抖一次模型 ID。

### 2.2 限速（硬约束）

| 约束 | 值 | 后果 |
|---|---|---|
| WorkBuddy 探测间隔 | **≥ 20 秒** | 4 秒间隔会把 global 全部打进 `no_healthy_account` 冷却，**首次探测即如此**；严重时**网关进程被打崩** |
| 网关账号池规模 | 4 个号（global 3 + cn 1） | 没有余量，批量并发必爆 |
| 路由侧（若同时跑别的线） | 批量探测必须**串行化** | 历史上 10 个子代理同时密集探测 → 负载冲到 2.6 → 看门狗复位 |

**探测前先确认网关活着**：`curl http://127.0.0.1:7863/status`。

> **换供应商时**：上表的 20 秒与 4 个号是**实例 B 的实测值** ——
> 池子只有 4 个号、其中一个号被冷却就没号可用，所以间隔要拉到 20 秒。
> 池子大的供应商可以放宽，但**先小批量试**（比如 `--only <前缀>` 跑几个），
> 看有没有 `no_healthy_account` 这类症状再定间隔。

### 2.3 探测必须用 ZCode 真实 body

WorkBuddy 侧**只能用** `workbuddy_probe_zcode.py`（它先调 `zcode_effective_body.js`
算出 ZCode 真实会发的 body，失败再退 slim variant）。
裸 body 探测的结果**不可信** —— 网关会把 ZCode 注入的思考字段原样转发给上游，
上游不认就 400。机制见 [PITFALLS.md](PITFALLS.md) §2。

---

## 3. 探测结果快照的保留策略

| 文件 | 内容 | 保留 | 理由 |
|---|---|---|---|
| `providers/workbuddy/cache/wb_pricing.json` | 网关倍率快照（活数据） | 本机保留，**不随仓库分发** | 含账号池相关信息；也因为需要定期刷新 |
| `providers/workbuddy/cache/wb_zcode_probe.json` | 探测结果缓存（活数据，断点续跑用） | 本机保留，**不随仓库分发** | 含账号池探测结果 |
| `providers/workbuddy/logs/wb_zcode_probe.log` | 探测日志 | 本机保留，**不随仓库分发** | 一次性日志 |
| `providers/opencode-go/probe/results/20261019/*.json` | 三份探测原始结果（34 模型 / 28 组基准 / 决赛采样） | 本机保留，**不随仓库分发** | 体积大、可重跑再生。三个探测脚本把结果写到**当前工作目录**，跑完要手动挪进 `results/<日期>/` |
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

### 4.1 三个脚本都会自动备份

| 脚本 | 备份文件名 | 写入方式 |
|---|---|---|
| `go_model_sync.py --apply` | `provider_config.json.bak-gosync-<时间戳>` | 写 `.tmp` → 校验 JSON → `os.replace` 原子替换 |
| `workbuddy_zcode_sync.py --apply` | `provider_config.json.bak-wbproxy-<时间戳>` | 同上（`.tmp-wbproxy` → `os.replace`） |
| `providers/qoder/qoder_zcode_sync.py --apply` | `provider_config.json.bak-qoder-merge-<时间戳>`（`--separate` 为 `.bak-qoder-<时间戳>`） | 同上（`.tmp-qoder` → `os.replace`） |
| `tools/model_alias.py --apply` | `provider_config.json.bak-alias-<时间戳>` | 同上（`.tmp-alias` → `os.replace`） |

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

三个同步脚本各自的写入行为（默认合并 / 只追加、`--separate` 的风险、正确姿势）以
[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §1.1 为**正本**；本节只管备份与回退。

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
| **每天 12:00（定时任务 `automation-3e2f8a53-b408-4bf8-90ff-4a331a721f5c`）** | 四段顺序：① `python providers/opencode-go/ops/go_model_sync.py --apply`；② WorkBuddy（`workbuddy_fetch_pricing.py` → `workbuddy_probe_zcode.py --max-rate 0.3 --sleep 20` → `workbuddy_zcode_sync.py --max-rate 0.3 --apply`）；③ Qoder（`qoder_probe_zcode.py --timeout 90 --sleep 3` → `qoder_zcode_sync.py --probe-file providers/qoder/qoder_probe.json --apply`）；④ `python tools/model_alias.py --slot auto --apply` 归一化四组与 alias map；⑤ `python tools/sync_report.py --write --push` 生成 `docs/reports/MODEL-SYNC-<时间>.md`（写明新增 / 移除 / 分组 / 链路变化）、更新报告索引并提交推送。手动补跑也按这个顺序；**不要在 ④ 之后单独跑旧 sync 的 `--apply`** |
| **每天（可选，全量体检）** | `python tools/model_probe.py` → `python tools/model_alias.py --slot auto --probe-file ~/.zcode/v2/model_probe.json --apply`；定时任务不跑全量 probe，各 sync 自带定向探测。规则见 [MODEL-ALIAS.md](MODEL-ALIAS.md) §6 |
| **每天 08:00 / 22:00 + 工作日 09:00 / 12:00 / 14:00 / 18:00** | `python providers/workbuddy/workbuddy_fetch_pricing.py` → `python tools/model_alias.py --slot auto --apply`（峰谷价切换，见 [MODEL-ALIAS.md](MODEL-ALIAS.md) §4.1） |
| **每月** | 复核 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) 里的价格 / 额度（`wb_pricing.json` 已由每日任务自动刷新） |
| **换套餐 / 换账号池后** | 全量重探 WorkBuddy（`--sleep 20`）+ 重跑同步 |
| **每次接入新供应商** | 照 §1.1 的通用做法写一份取数脚本 + 在 [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0 的表里补一行；凭据按 [SECRETS.md](SECRETS.md) §2、§3.5 加环境变量 |
| **每次改动脚本** | 同步 [TOOLS.md](TOOLS.md) 的工具表 |
| **每次新增 / 删除文档** | 同步 [docs/README.md](README.md) 索引（孤儿文档零容忍） |
| **每次踩新坑** | 写进 [PITFALLS.md](PITFALLS.md)；有对应排错条目的同步 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| **每次发版** | 按 [VERSIONING.md](VERSIONING.md) §1 定版本号，写 [CHANGELOG.md](../CHANGELOG.md) + `docs/release-notes/<版本>.md` |

---

## 7. 本仓已登记的待办

| # | 事项 | 影响 | 详见 |
|---|---|---|---|
| 1 | ~~`wb_pricing.json` **没有生成脚本**~~ **已修** | 已有 `workbuddy_fetch_pricing.py`：拉网关 → 归一化 → 写 `cache/wb_pricing.json`（自动备份 + 变动摘要） | §1.3、[PITFALLS.md](PITFALLS.md) §11 |
| 2 | ~~探测脚本里**仍有明文 API key**~~ **已修** | 5 个探测脚本改为读 `OPENCODE_GO_KEY`，**未设置时明确报错退出**；凭据不再随源码分发 | [SECRETS.md](SECRETS.md)、[PITFALLS.md](PITFALLS.md) §9 |
| 3 | ~~`go_model_sync.py` 的 `REPORT_DIR` 仍硬编码旧仓库路径~~ **已修** | 拆仓时改为本仓内 `evidence/`，可用 `GO_SYNC_REPORT_DIR` 覆盖 | [PITFALLS.md](PITFALLS.md) §10 |
| 4 | ~~根 `LICENSE` 文件未创建~~ **已修** | 仓库根已有 MIT 全文（见 [LICENSE](../LICENSE)），不再只有 `README.md` 里的一句话 | [CHANGELOG.md](../CHANGELOG.md) 「待补」 |
| 5 | ~~`docs/VERSIONING.md` 未创建~~ **已修** | 版本晋升规则有独立正本 [VERSIONING.md](VERSIONING.md)，不再暂以 `CHANGELOG.md` 头部为正本 | [VERSIONING.md](VERSIONING.md) §1–§2 |
| 6 | ~~`go_model_sync.py` 的**体检**把全部已配置模型都探向 OpenCode-Go~~ **已修** | 体检按 id 前缀分流：`cn:*` / `global:*` 跳过（由统一路由供给），不再每天刷 18 条假异常 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) §13 |
| 7 | ~~`workbuddy_zcode_sync.py` 的 `rate_of` 认不出 `credits` 为空的免费条目~~ **已修** | 改为优先信任价格表归一化的 `eff_rate` / `list_rate`（免费 `-f` 条目为 0.0），缺失才回退原始串；`cn:hy4-preview-f` / `global:hy4-preview-f` 已收进免代档 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) §13 |
| 8 | ~~探测失败的已配置模型只打 ⚠、不清理~~ **已修** | 落实「跑不通即清、复通即加回」：Go 侧对 400/402/404/410/5xx 直接 `prune_model`（仅豁免 401/429）；WorkBuddy 侧 blocked/unavailable 亦移除 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) §13 |

---

## 8. 网关生命周期（zgate）

2026-10-23 起，三个反代由**一个进程**托管：`gateways/zgate`（Go，约 19 MB）。
它监听 `127.0.0.1:7871`，按 alias map 把四个 chat provider 的请求分流到三条上游，
并按策略拉起 / 回收两个本地上游进程：

| 上游 | 端口 | 谁在跑 | 策略 |
|---|---|---|---|
| OpenCode-Go | 远程 | — | 直连，无本地进程 |
| WorkBuddy（`wb2api`） | 7863 | zgate 的子进程 | `ondemand`：首个 WB 请求时拉起，空闲 300 秒回收 |
| Qoder（`qoder_proxy.py`） | 8790 | zgate 的子进程 | `ondemand`：同上，随用随拉 |

两个上游都**不常驻**：没人用就一个都不起，zgate 自己只占约 19 MB。
签到 / 保活这类定时任务靠 `children.*.windows` 兜底 —— 窗口内按 `always` 处理，
窗口结束后若没有请求，再按 `idleSeconds` 回收：

| 子进程 | 默认窗口（本地时间） | 对应上游任务 |
|---|---|---|
| WorkBuddy | `08:58-09:15`、`09:58-10:15`、`20:58-21:15`、`21:58-22:15` | 签到 9/21 点、活跃 10 点、token 保活 22 点 |
| Qoder | `08:58-09:15`、`20:58-21:15`、`21:58-22:15` | 签到 9/21 点、保活 22 点 |

策略与窗口写在 `gateways/zgate/zgate.json`，改完用 `zgate.exe reload` 热加载
（新增子进程、监听地址、上游 base 仍要重启）。
子进程装在 **Job Object** 里，zgate 崩溃或被结束时会一起收掉，不会留下占着 7863 / 8790 的孤儿。

### 8.1 日常命令

| 动作 | 命令（在仓库根执行） |
|---|---|
| 看状态（服务是否在跑 / 子进程 / 端口 / 凭据有无） | `gateways/zgate/zgate.exe status` |
| 前台启动（排错用；正常由登录自启拉起） | `gateways/zgate/zgate.exe serve` |
| 注册登录自启 | `gateways/zgate/zgate.exe install` |
| 移除登录自启 | `gateways/zgate/zgate.exe uninstall` |
| 热加载策略/窗口（改完 `zgate.json`） | `gateways/zgate/zgate.exe reload` |
| 健康检查 | `curl http://127.0.0.1:7871/health`（含每个子进程的 `state` / `pid` / `idle_s`） |
| 只重启 WorkBuddy 上游 | `taskkill /IM wb2api.exe /F`，下一次 WB 请求自动拉起 |
| 只重启 Qoder 上游 | `taskkill /IM python.exe /F` 后用下面的 bat 兜底，或重启 zgate |

自启方式是**启动文件夹快捷方式**（`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ZcodeAIModels zgate.lnk`）——
`schtasks /create /sc ONLOGON` 在当前权限下会被拒绝（拒绝访问），快捷方式不需要管理员。

### 8.2 配置项（`gateways/zgate/zgate.json`）

| 键 | 默认 | 说明 |
|---|---|---|
| `listen` | `127.0.0.1:7871` | 四个 chat provider 的 `baseUrl` 指向这里；环境变量 `ZGATE_LISTEN` 可覆盖 |
| `aliasMap` | `~/.zcode/v2/model-alias-map.json` | 显示名 → 上游；按 mtime 热加载，改完不用重启 |
| `providerConfig` | `~/.zcode/v2/provider_config.json` | 凭据兜底来源 |
| `children.<name>.policy` | `ondemand` | `always` 常驻 / `ondemand` 按需（默认谁都不用就不起） |
| `children.<name>.idleSeconds` | `300` | `ondemand` 的空闲回收阈值 |
| `children.<name>.windows` | 见 §8 表 | 本地时间窗口 `HH:MM-HH:MM`，可跨午夜；窗内按 `always` 处理 |
| `children.<name>.health` | — | 就绪判定；WB 用 `/panel/`（`/status` 需要鉴权，返回 401） |
| `children.<name>.startTimeoutSeconds` | 25 / 30 / 40 | 冷启动等待上限 |

### 8.3 日志

| 文件（`%LOCALAPPDATA%\ZCodeGateway\`） | 内容 |
|---|---|
| `zgate.log` | 路由日志（每个请求一行 `model=… -> 通道`）、子进程起停、错误；超过 5 MB 轮转为 `.1` |
| `workbuddy.stdout.log` / `.stderr.log` | WorkBuddy 上游输出 |
| `qoder.stdout.log` / `.stderr.log` | Qoder 上游输出（Qoder 自己还会写 `gateways/upstream/qoder/qoder-proxy.log`） |

### 8.4 上游 clone 的更新

两个上游仍是**独立 clone**，整目录被主仓 `.gitignore` 排除（含账号凭据与运行时状态）。

| 场景 | 命令 |
|---|---|
| 更新 WorkBuddy 上游 | `git -C gateways/upstream/workbuddy pull --ff-only`，再 `taskkill /IM wb2api.exe /F`（下次请求自动重启） |
| 更新 Qoder 上游 | `git -C gateways/upstream/qoder pull --ff-only`，再重启 zgate |
| 新机器重建 WorkBuddy | `git clone https://github.com/linguo2625469/workbuddy2api-panel.git gateways/upstream/workbuddy`，按 `config.example.json` 建 `config.json`、放 `auths/`，`go build -o wb2api.exe ./cmd/server` |
| 新机器重建 Qoder | 见 [QODER.md](QODER.md) §2 |

> ⚠️ **WorkBuddy 的定时任务**（签到 9 / 21 点、活跃 10 点、token 保活 22 点、夜猫子、
> 余额刷新）只在进程活着时才跑。签到 / 活跃 / 保活已由 `windows` 覆盖；
> **夜猫子（23:00–08:00）与每 5 分钟的余额刷新仍然只在有 WB 请求时跑** ——
> 要让它们常跑，把 `children.workbuddy.policy` 改成 `always`（多占约 23 MB），
> 或加 `"23:00-08:00"` 窗口（跨午夜也支持）。排查见
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md) §11。

### 8.5 Qoder（qoder2api-hub，8790）

Qoder 由 zgate 托管（默认 `ondemand`，签到/保活窗口自动唤醒），
`qoder:` 模型经 7871 分流；ZCode 侧没有独立 `qoder` provider。

| 场景 | 命令 |
|---|---|
| 看状态 | `gateways/zgate/zgate.exe status`，或 `curl http://127.0.0.1:8790/ping` |
| 手动兜底启动（zgate 不在时） | `gateways/upstream/qoder/start-qoder-proxy.bat` |
| 手动兜底停止 | `gateways/upstream/qoder/stop-qoder-proxy.bat` |
| 日志 | `gateways/upstream/qoder/qoder-proxy.log`；zgate 侧见 §8.3 |
| 签到状态 | `gateways/upstream/qoder/accounts/scheduler/state.json` |
| 每日同步 | `python tools/model_probe.py`（可加 `--group 免费`）→ `python tools/model_alias.py --slot auto --probe-file ~/.zcode/v2/model_probe.json --apply`；Qoder 显示名为 `Q/积分/型号` |

> Qoder 的专用 `qoder_probe_zcode.py` / `qoder_zcode_sync.py` 现在只作数据采集与兼容；
> 四组统一探测用 `tools/model_probe.py`，最终写入用 `tools/model_alias.py`。
> 账号、签到与模型细节见 [QODER.md](QODER.md)。

---

## 9. 相关文档

| 要查什么 | 去哪 |
|---|---|
| 发版时版本号动哪一位（版本晋升规则正本） | [VERSIONING.md](VERSIONING.md) §1–§2 |
| Release 说明怎么写 | [release-notes/README.md](release-notes/README.md) |
| 凭据（OpenCode-Go key / 网关 key / ZCode 配置路径）在哪 | [SECRETS.md](SECRETS.md) |
| provider 分组、协议类型、参数矩阵 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) |
| 统一命名、积分换算、四组、alias map 与协议桥 | [MODEL-ALIAS.md](MODEL-ALIAS.md) |
| 脚本改 ZCode 配置的哪几处、三个 `--apply` 脚本的行为差异 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §1、§1.1 |
| Qoder 的端口、账号、同步与探测 | [QODER.md](QODER.md) |
| 排障步骤 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

---

## 10. 维护记录

| 日期 | 做了什么 | 结果 |
|---|---|---|
| 2026-10-23 | 统一模型命名：四组（主力/免费/低耗/高耗）、`渠道/积分/型号`、alias map、协议桥接 | 43 个模型 / 4 个 provider；37 ok，5 个 WB GB 因池冷却暂为瞬时限流 |
| 2026-10-23 | 接入 Qoder：qoder2api-hub clone 到 `gateways/upstream/qoder`（8790）、OAuth 账号、独立 `qoder` provider、同步/探测脚本与文档 | 7 个模型探测 200；免费 `DeepSeek-Flash` 1.1s；`Qwen3.8-Flash` 因 10605 排队暂不收录 |
| 2026-10-22 | 收尾大扫除：清 `__pycache__` 与过期定价备份；对齐模型计数 / 快照日期、Release 说明反馈入口、AGENTS 的 CodeGraph 状态 | 仓库 53109K → 53053K；`python tools/check-docs.py` 通过 |
