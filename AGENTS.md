# AGENTS.md — 本仓库的机器协议

> **一句话**：三条硬规矩 —— **PROGRESS 按逻辑任务分家**、**凭据只走环境变量**、
> **有 CodeGraph 就先用 CodeGraph**。其它都能从 `docs/` 里查到。

---

## 1. PROGRESS：路径由逻辑任务决定，不是物理目录

**每个逻辑任务目录内有且仅有一个 `PROGRESS.md`。** 本仓当前的逻辑任务只有一个，
所以全仓只有一个进度文件：仓库根的 `PROGRESS.md`（追加式批次日志）。

- **不要**因为「起了个子代理」或「换了个子目录」就在别处再开一个 `PROGRESS.md`。
- **不要**把多个互不相关的任务写进同一个 `PROGRESS.md`。
- **子代理只写分片**：文件名 `evidence/agent-<name>.md`，**不碰任何共享文件**
  （不碰 `PROGRESS.md`、不碰 `provider_config.json`、不碰 `docs/`）。

> **为什么**：历史上 13 个并行子代理被要求「在任务根目录维护 PROGRESS.md」，
> 结果全部往同一个物理文件写，后写覆盖先写 —— 根 `PROGRESS.md` 一度被并发写坏，
> 同一篇里同一个批次标题出现两次，且步骤清单未勾选而状态写着「已完成」。
> 根因是把「任务根目录」理解成**物理目录**，而不是**逻辑任务**。
> 合并原则见 [docs/DOC-RULES.md](docs/DOC-RULES.md)。

写 `PROGRESS.md` 时按批次追加，格式照现有内容：

```
# YYYY-MM-DD 第 N 轮：<一句话主题>

## 任务目标
## 已完成变更      （- [x] 勾选式）
## 验收            （可复现的验证方式 + 结论）
## 待解决 / 注意事项
## 状态: 已完成
```

**每完成一个关键步骤（文件改动、命令执行成功）立即更新一次** —— 写入时间即心跳。

---

## 2. 凭据一律走环境变量

**不要把 key / 口令 / token 写进源码、文档、日志、缓存文件。**

| 凭据 | 怎么取 |
|---|---|
| OpenCode-Go 的 `oc_sk_…` | `provider_config.json` 里的 `providerConfigRules.providerRules[].config.access.apiKey`（脚本自己读） |
| WorkBuddy 网关 `api_key` | 环境变量 **`WB_GATEWAY_KEY`** |
| 网关地址 | 环境变量 **`WB_GATEWAY_BASE`**（默认 `http://127.0.0.1:7863`） |
| ZCode 配置文件路径 | 环境变量 **`ZCODE_PERSONAL_PROVIDER_CONFIG_FILE`** |
| ZCode 内置规则文件 | 环境变量 **`ZCODE_BUILTIN`** |
| 代理会话头 | 环境变量 **`OPENCODE_SESSION`** |

> ⚠️ **现存违规**：`opencode-go/probe/` 下的 `probe_models.py`、`probe_protocols.py`、
> `bench_models.py`、`bench_clean.py`、`thinking-off-probe.js` 已改为读 `OPENCODE_GO_KEY` 环境变量。
> 本轮只做文档拆分、未动脚本。**在把这些仓库推到公开 GitHub 之前，必须先改成
> 环境变量读取**（改法见上面的表）。

同理，`provider_config.json` 的备份文件（`*.bak-*`）里也有 key ——
它们只留在本机，**绝不进版本库**（`.gitignore` 已排除）。

---

## 3. CodeGraph

**仓库根有 `.codegraph/` 就优先用它查符号与调用路径；没有就退回普通检索（Grep / Read / glob）。**

- 判断依据：仓库根存在 `.codegraph/` 目录才算已索引。当前工作副本已索引
  （`.codegraph/` 被 `.gitignore` 排除，不随仓库分发）。
- 有索引时优先 `codegraph_explore` / `codegraph explore "<问题>"`；
  新克隆或索引失效时直接普通检索，需要再 `codegraph init -y`。
- 无论有没有索引，**改动前后都要把 `docs/README.md` 的索引对齐**（孤儿文档零容忍）。

---

## 4. 其它约定（简）

- **文档正本**：每条规则只在一篇文档里定义，其余位置只留一句话 + 链接。
  正本映射表见 [docs/DOC-RULES.md](docs/DOC-RULES.md) §2。
- **链接**：一律相对链接 + 半角括号；锚点必须真实存在。
- **每篇文档开头**必须有 `> **一句话**：…` 引言块。
- **中文**：简体中文。务实，给结论，给证据；不确定的写「待补」并说明缺什么。
- **单篇 ≤ 800 行**。
- **不要 `git init` / `git add` / 提交**，除非明确要求。
- **不要动** `docs/模型速查表.md`、`docs/archive/`、`evidence/`、`PROGRESS.md`
  与任何脚本，除非任务明确要求改它们。
