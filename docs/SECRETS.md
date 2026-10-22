# 凭据与安全须知

> **一句话**：本仓涉及哪些凭据、**分别从哪儿读**、活数据缓存在哪儿、上传公开仓库前该怎么处理 ——
> 本篇**只写位置，不写值**。
>
> **通用规则**：**任何**供应商的凭据都**只走环境变量** —— 读环境变量、缺失就明确报错退出。
> 本仓只列两个示例供应商（OpenCode-Go / WorkBuddy）的具体变量名；接别的供应商照同一模式加一行即可。

---

## 1. 为什么单独立一篇

本仓的两个示例凭据（OpenCode-Go API key、WorkBuddy 网关 key）原先**明文写在探测脚本里**，
会随仓库一起走；拆仓时已改为从**环境变量**读（见 §2）。
但「改成环境变量」只解决了一半 —— 还剩下这些容易被忽略的敞口：

- **ZCode 的 `provider_config.json` 本身就带 `apiKey`** —— 它是本机文件，不该入库；
- **脚本自己产生的 `.bak-*` 备份**里同样带 key；
- **`workbuddy/cache/` 与 `workbuddy/logs/` 是活数据缓存**（含账号池探测结果），随机器走，不随仓库走。

统一列一次位置，比到处找强；也比「顺手把值删掉」安全 —— **值该轮换，而不是该被藏起来**。

---

## 2. 凭据位置清单

| 凭据 | 真源（值在这儿） | 本仓里**不出现值**的对应物 | 处置 |
|---|---|---|---|
| **OpenCode-Go API key**（`oc_sk_…`） | ZCode 的 `provider_config.json` 里的 `apiKey` 字段；也可从 OpenCode 控制台重新签发 | 5 个探测脚本从环境变量 **`OPENCODE_GO_KEY`** 读；**未设置时明确报错退出**，不会带着空 key 去请求 | **不入库**。轮换后重新 `export` |
| **WorkBuddy 网关 key** | 本机 `wb2api` 网关自己的 `api_key`（网关面板 / 配置里） | 2 个 WorkBuddy 脚本从环境变量 **`WB_GATEWAY_KEY`** 读 | **不入库**。网关换账号池时一并轮换 |
| **统一路由的上游 key** | 不新增凭据文件：OpenCode key 从 `provider_config.json` / `OPENCODE_GO_KEY` 读，WorkBuddy key 从 `workbuddy/gateway/config.json` / `WB_GATEWAY_KEY` 读 | `tools/unified-router.js` 启动时读取；只监听 `127.0.0.1`；`/health` 只返回 key 是否存在，不返回值 | **不入库**。轮换上游 key 后重启路由 |
| **网关账号池凭据**（`auths/`，4 个号） | 本机 `workbuddy/gateway/auths/`（上游 clone 的运行目录）；`config.json` 里还有网关自己的 `api_key` | 整个 `workbuddy/gateway/` 被 `.gitignore` 排除；仓库里只出现 `WB_GATEWAY_KEY` 这个变量名 | **不入库**。换账号池时整目录一起换 |
| **其它供应商的凭据**（你自己接的） | 该服务商自己的控制台 / 账号设置 | **一律走环境变量**，不落进源码、文档、缓存、日志。命名建议 `<供应商>_KEY` / `<供应商>_BASE`，与 §3.5 的表同格式 | **不入库**。加变量时同步补 §3.5 的表 |
| **ZCode provider 配置**（含各 provider 的 `apiKey`） | 本机 `~/.zcode/v2/provider_config.json` | 不在本仓；`--apply` 产生的 `provider_config.json.bak-*` 备份同样含 key，已被 `.gitignore` 排除 | **不入库**。回退步骤见 [MAINTENANCE.md](MAINTENANCE.md) §4 |
| **网关模型目录快照** | 网关 `/panel/api/models` | `evidence/wb_panel_models.json` —— 目录结构证据，**不含凭据**，随仓库分发 | 可入库 |
| **探测原始结果 / 账号池探测结果** | 本机探测输出 | `workbuddy/cache/wb_zcode_probe.json`、`opencode-go/probe/results/` —— `.gitignore` 已排除 | **不入库**（体积大 + 含账号池信息） |

> **加新供应商时的完整清单**（三件事，缺一不可）：
> ① 脚本读 `os.environ.get("<供应商>_KEY")`，**不设就报错退出**；
> ② 在 §3.5 的环境变量表里补一行（谁在读、默认值、缺失时什么表现）；
> ③ 在本表补一行（真源在哪儿、值不进仓）。

---

## 3. 凭据怎么取

> **本文档只写位置，不写值；值在真源取，或在真源轮换之后再取。**
> 仓库里的一切凭据都是环境变量名或占位符，
> **拿占位符去请求一定失败** —— 那不是 bug，是设计。

### 3.1 OpenCode-Go API key

- **环境变量**：**`OPENCODE_GO_KEY`**。
- **谁在读**：`opencode-go/probe/` 下的 5 个脚本 ——
  `probe_models.py`、`probe_protocols.py`、`bench_models.py`、`bench_clean.py`、
  `thinking-off-probe.js`。
- **缺失时**：Python 脚本抛 `RuntimeError`、Node 脚本打印错误并退出，
  **绝不带着空 key 去请求**（省得收到一个含义不明的 401 再回头查）。

```sh
export OPENCODE_GO_KEY='<OpenCode-Go api_key>'
```

**当前值从哪取**：ZCode 的 `provider_config.json`（脚本自己读同一份配置）——
见 §3.4。

### 3.2 WorkBuddy 网关 key

- **环境变量**：**`WB_GATEWAY_KEY`**。
- **谁在读**：`workbuddy/workbuddy_probe_zcode.py`、`workbuddy/workbuddy_zcode_sync.py`
  （历史脚本 `workbuddy/archive/workbuddy_probe_models.py` 同样读它）。
- **缺失时**：**本地不会报错** —— 脚本照常发请求，只是 `Authorization` 头带空值，
  网关回 **401**。这是本仓与 OpenCode-Go 侧的一个**行为差异**，排查时注意区分：
  「OpenCode-Go 侧立刻抛 `RuntimeError`」与「WorkBuddy 侧表现为 401」是两种症状。

```sh
export WB_GATEWAY_KEY='<网关 api_key>'
```

### 3.3 网关地址

- **环境变量**：**`WB_GATEWAY_BASE`**，默认 `http://127.0.0.1:7863`。
- **谁在读**：`workbuddy/workbuddy_probe_zcode.py`、`workbuddy/workbuddy_zcode_sync.py`。
- 换成远端网关时用环境变量覆盖，不必改代码。

### 3.4 ZCode 配置文件路径

| 项 | 值 |
|---|---|
| 默认路径 | `~/.zcode/v2/provider_config.json`（Windows：`C:\Users\<用户名>\.zcode\v2\provider_config.json`） |
| 覆盖方式 | 环境变量 **`ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`** |
| 谁在读 | `workbuddy/workbuddy_zcode_sync.py` |

> **已知缺口**：`opencode-go/ops/go_model_sync.py` **不读**这个环境变量 ——
> 它用 `--config` 参数，默认值按**当前用户主目录**推导
> （`~/.zcode/v2/provider_config.json`）。换机器时要么带 `--config`，要么改脚本让它也认
> `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`。
> 缺什么：脚本侧的环境变量兜底。

### 3.5 环境变量 → 谁在读

| 环境变量 | 谁在读 | 默认值 | 缺失时 |
|---|---|---|---|
| **`OPENCODE_GO_KEY`** | `opencode-go/probe/` 下 5 个脚本 + `tools/unified-router.js`（缺省回退到 `provider_config.json`） | 无 | 明确报错退出（不静默）；路由对应上游 502 |
| **`WB_GATEWAY_KEY`** | `workbuddy/` 下 2 个现役脚本 + 1 个归档脚本 + `tools/unified-router.js`（缺省回退到网关 `config.json`） | 无（空串） | 不本地报错，表现为网关 **401**；路由对应上游 502 |
| **`WB_GATEWAY_BASE`** | 同上 + `tools/unified-router.js` | `http://127.0.0.1:7863` | 用默认值 |
| **`UNIFIED_ROUTER_PORT`** | `tools/unified-router.js` | `7871` | 用默认值；改了要同步改五个 chat 组的 `baseUrl` |
| **`ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`** | `workbuddy/workbuddy_zcode_sync.py` | `~/.zcode/v2/provider_config.json` | 用默认值 |
| `WB_PRICING_FILE` | `workbuddy/` 下 2 个脚本 | `workbuddy/cache/wb_pricing.json` | 用默认值 |
| `WB_ZCODE_PROBE_FILE` | 同上 | `workbuddy/cache/wb_zcode_probe.json` | 用默认值 |
| `GO_SYNC_REPORT_DIR` | `opencode-go/ops/go_model_sync.py` | 本仓 `evidence/` | 用默认值 |
| `ZCODE_BUILTIN` / `ZCODE_API_TYPE` | `workbuddy/zcode_effective_body.js` | 见脚本 | 用默认值 —— **不是凭据**，是协议开关 |
| `OPENCODE_SESSION` | `opencode-go/ops/opencode-header-proxy.js` | `local-client-session` | 用默认值 —— **不是凭据**，是会话标识 |

> **接新供应商**：照这张表的格式加自己的行 ——
> `<供应商>_KEY`（必填、无默认、缺失即报错）、`<供应商>_BASE`（有默认地址）、
> 必要时 `<供应商>_PRICING_FILE` / `<供应商>_PROBE_FILE`（活数据落盘位置）。

---

## 4. 活数据缓存：随机器走，不随仓库走

| 位置 | 是什么 | 为什么不入库 |
|---|---|---|
| `workbuddy/cache/` | 网关倍率快照（`wb_pricing.json`）、探测结果缓存（`wb_zcode_probe.json`） | 活数据，含账号池相关信息；且需要定期刷新（见 [MAINTENANCE.md](MAINTENANCE.md) §1、§3） |
| `workbuddy/logs/` | 探测日志（`wb_zcode_probe.log`） | 一次性日志 |
| `opencode-go/probe/results/<日期>/` | 探测原始结果 | 体积大、可重跑再生 |
| `provider_config.json.bak-*` | 脚本 `--apply` 前自动备份 | **含 apiKey** |

`.gitignore` 里对应的排除项：`/workbuddy/cache/*.json`、`/workbuddy/logs/`、
`/workbuddy/cache/*.log`、`/opencode-go/probe/results/`、`*.bak-*`。

> **结论随仓库走，原始快照放 `evidence/`** —— `evidence/` 下的模型目录快照与
> 自动收录报告不含凭据，可以放心分发。

---

## 5. 上传公开仓库前的检查清单

```sh
# 1) 确认没有把凭据文件带进去
git ls-files | grep -E 'provider_config\.json|\.bak-|workbuddy/cache/|\.env$|\.key$'

# 2) 确认忽略规则生效
git status --ignored --short | grep -E '^!!' | head -20

# 3) 扫一遍将要提交的内容里有没有裸密钥特征
git diff --cached | grep -nE 'oc_sk_|apiKey|api_key|Bearer [A-Za-z0-9]'
```

**逐条确认清单**：

- [ ] 5 个探测脚本源码里**没有**明文 `oc_sk_…`（应只有 `os.environ.get("OPENCODE_GO_KEY", ...)` /
      `process.env.OPENCODE_GO_KEY`）；
- [ ] `provider_config.json` 及其 `.bak-*` 备份**不在** `git ls-files` 里；
- [ ] `workbuddy/cache/`、`workbuddy/logs/`、`opencode-go/probe/results/` 不在库里；
- [ ] `evidence/` 下的文件不含 `apiKey` / `oc_sk_…`；
- [ ] 轮换过 `OPENCODE_GO_KEY` 与网关 key 的话，**重新 export** 一遍；
      换了 key 之后旧值就失效，不必再从仓库里清理。

> **本仓当前的实情（2026-10-20）**：5 个探测脚本已改为环境变量读取（未设置即报错退出）；
> `.gitignore` 已排除缓存、日志、备份与各类密钥文件。
> 但**占位符不等于凭据已失效** —— 本机配置里的值仍然有效，
> **上传到公开远端前仍须轮换**；要公开，先轮换。

---

## 6. 几条硬规矩

1. **新脚本不许把 key 写死在文件里** —— 读环境变量；
   缺失时**明确报错退出**，绝不用空值去请求。
2. **文档里出现值只允许出现在历史记录里** —— 新的说明一律指向真源；
   需要举例时用 `<OpenCode-Go api_key>` / `<网关 api_key>` 这类占位符。
3. **`provider_config.json` 及其备份都是凭据文件** —— 不入库、不贴进 issue 或截图。
4. **日志里不要打印凭据** —— `Authorization` 头打印前先打码。
5. **凭据变更必须连带改依赖方** —— 换了 key 要重新 `export`，
   并同步改 ZCode 配置里对应的 `apiKey`（否则界面里选到旧 key 的模型会 401）。

---

## 7. 相关文档

| 要查什么 | 去哪 |
|---|---|
| 凭据相关的坑（明文随仓库走、硬编码路径） | [PITFALLS.md](PITFALLS.md) §9、§10 |
| 探测限速、活数据快照的保留策略 | [MAINTENANCE.md](MAINTENANCE.md) §2、§3 |
| `--apply` 的备份与回退 | [MAINTENANCE.md](MAINTENANCE.md) §4 |
| 鉴权失败（401）与协议用错（400）怎么区分 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) §2、§4 |
| provider 分组、协议类型、参数矩阵 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) |
| 忽略规则 | 仓库根 `.gitignore` |
| 许可证 | 仓库根 [LICENSE](../LICENSE) |

---

# 推送前脱敏规则（通用）

> **一句话**：推送前跑一次 `python tools/check-secrets.py`；它拦的是三类东西 ——
> 可用凭据、本机用户目录、真实邮箱。规则对 8 个仓完全一致，一处改全局同步。

---

## 1. 为什么需要这一条

历史教训：本系列仓的脱敏一度靠人记，结果漏过两次 ——

1. **同步脚本把 `--config` 的绝对路径回显进报告**，报告又作为 evidence 提交，
   本机用户目录就这样进了版本库。脚本默认值是按主目录推导的，本身没问题，
   问题出在那两行 `log("已写入 %s" % args.config)`。
2. **没有守卫的仓全靠自觉**。8 个仓里原本只有 2 个有 `tools/check-secrets.py`，
   规则里还不含本机路径。

所以规则固化成本篇 + 一个脚本 + 一个 CI 步骤。脚本是规则的**可执行版本**。

---

## 2. 三类拦截面

| 类别 | 例子 | 为什么拦 |
|---|---|---|
| **P0 可用凭据** | `gh[pousr]_…`、`sk-…`、`oc_sk_…`、`AIza…`、`glpat-…`、`-----BEGIN … PRIVATE KEY`、`AKIA…`、shadow 哈希、订阅 URL 的 token 段、代理节点 URI | 任何人拿到就能直接用 |
| **P1 本机用户目录** | `C:\Users\<名字>\…`（正反斜杠都拦） | 暴露用户名与软件安装布局，是社工的素材 |
| **P1 真实邮箱** | `…@qq.com` / `@163.com` / `@gmail.com` 等 | 暴露个人身份；GitHub noreply 邮箱不含这些域名，不会误伤 |

> **域名清单**：qq / 163 / 126 / gmail / outlook / hotmail / foxmail / sina / sohu。
> 只列国内常用与 Google / Microsoft 系 —— 加更多域名只会增加误报。

---

## 3. 三条放行规则（避免误报）

守卫不是越严越好，误报多了人就学会跳过它。所以明确放行三种情形：

### 3.1 占位符与示例值不算命中

行内含 `REDACTED` / `YOUR-` / `REPLACE-` / `<…>` / `example.com` / `placeholder`
/ `<用户名>` 等字样时，整行跳过。所以写文档时**优先用占位符**，能省掉很多例外。

### 3.2 文档类文件允许「截断形式」的描述性引用

变更说明里需要引用泄漏原文，否则读者不知道该改什么。形如下面的写法放行：

- 用户名位置就是省略号：`C:\Users\...\provider_config.json`
- 用户名用尖括号占位：`C:\Users\<名字>\...`
- 用户名后紧跟 `\...` 截断：`C:\Users\SansK\...`

**完整路径一律不放行。** 这条只对文档类文件生效
（`CHANGELOG.md` / `PROGRESS.md` / `SECURITY.md` / `CONTRIBUTING.md` / `docs/` /
`evidence/` / `memories/`）。

### 3.3 占位用户名不算命中

示例文件里的 `C:/Users/You/...`、`C:/Users/User/...`、`C:/Users/你的用户名/...`
是给用户照着改的模板，不是本机路径。

---

## 4. 白名单：只放「有意为之」

逐行白名单（`LINE_ALLOWLIST`）只放两类情形，**每条必须写清理由**：

- **机制上就该出现** —— 如 `.mailmap` 里的邮箱映射，那是 git 官方的作者身份
  归属机制，邮箱本来就该在里面。
- **确定不是敏感信息** —— 如 Kotlin 协程符号 `$scaleDone$1` 被 shadow 哈希
  正则误判。

加白名单前先问：能不能改用占位符绕开？能的话优先改内容，不要加白名单。

---

## 5. 推送前怎么做

```sh
# 1) 扫已跟踪文件（CI 跑的就是这个，退出码 0 才能推）
python tools/check-secrets.py

# 2) 扫工作树，含未跟踪文件（提交前自查用）
python tools/check-secrets.py --all
```

`--all` 模式**遵循 `.gitignore`** —— 本机配置（如 `config.local.json`）设计上
就不入库，报出来只是噪音。但它仍会扫**未跟踪且未被忽略**的新文件，所以能抓住
「新建了个文件忘了加 .gitignore」这种情况。

**CI 里有「敏感信息扫描」步骤**，推上去会自动跑。本地先跑一遍，别等 CI 报错。

---

## 6. 踩过的坑（写规则/脚本时注意）

1. **Python 单元素元组**：`SKIP_PREFIXES = ("tools/preview/")` 少了尾逗号，
   它不是元组而是字符串，`any(base.startswith(p) for p in "…")` 会逐字符迭代，
   导致所有以首字符开头的路径都被跳过 —— 守卫静默失效，扫描显示"通过"但实际
   什么都没查。必须写 `("tools/preview/",)`。
2. **`printf` 吞转义**：Git Bash 里 `printf 'C:\Users\...'` 把 `\U` 当 unicode
   转义，写出的测试文件内容是坏的，注入测试假通过。写含反斜杠的测试内容要用
   Python 的 `chr(92)`。
3. **replace-text 只匹配字面量**：重写历史时，文档里引用泄漏原文的写法
   （如 `git grep Users.SansK`，没有 `C:\` 前缀）匹配不到，要单独列规则。
4. **模板多行块替换**：按单行字符串替换跨多行的配置块会留下孤儿行导致
   IndentationError；先在源里 `assert` 锚点存在再替换，失败即中止。
5. **守卫脚本自己的注释会被自己的规则拦到** —— 注释里别出现完整路径字面量。

---

## 7. 相关文档

| 要查什么 | 去哪 |
|---|---|
| 凭据从哪读、怎么轮换 | 本篇其余章节 |
| 上报安全问题 | [../SECURITY.md](../SECURITY.md) |
| 提交前自检 | [../CONTRIBUTING.md](../CONTRIBUTING.md) |
| 文档怎么写 | [DOC-RULES.md](DOC-RULES.md) |
