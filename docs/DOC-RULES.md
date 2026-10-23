# 文档规则

> **一句话**：docs/ 下的文档怎么分类、怎么互相引用、改动时连带改哪些 ——
> 本篇只管「怎么写、怎么保持一致」，不承载任何具体技术规则。

---

## 1. 分类与定位

docs/ 分四类（索引见 [README.md](README.md)）：

| 类别 | 收什么 | 现有成员 |
|---|---|---|
| 模型与 Provider | 有哪些 provider、模型归哪组、走什么协议、参数怎么写 | MODEL-PROVIDERS、MODEL-QUICK-REF、archive/OPENCODE-GO-ANALYSIS |
| 流程与规范 | 怎么写文档、怎么维护、版本怎么晋升、凭据放在哪、工具清单怎么记、发版说明 | DOC-RULES、MAINTENANCE、TOOLS、VERSIONING、SECRETS、release-notes/README |
| 排错与踩坑 | 出问题了怎么查、为什么会这样 | PITFALLS、TROUBLESHOOTING |
| 参考资料 | 面向使用者的 Release 说明、证据快照、许可证、外部榜单、上游调研 | release-notes/、根 README / AGENTS / CHANGELOG / NOTICE / PROGRESS / LICENSE、evidence/、BENCHMARKS、UPSTREAM、third-party/ |

每篇文档开头必须有一个 **「一句话」引言块**（`> **一句话**：…` 或一行定位语），
让读者不用往下翻就知道这篇管什么。新文档没有它不算写完。

「一句话」块要能独立成立 —— 读者只看这三行就该知道这篇能不能解决他的问题。

### 文件命名：**全大写 + 连字符**

`docs/` 下的文件一律 `ALL-CAPS-WITH-HYPHENS.md`（如 `MODEL-PROVIDERS.md`、
`MODEL-QUICK-REF.md`），`docs/archive/` 与 `docs/release-notes/` 同样适用
（例外：`release-notes/` 下的说明文件名 = `versionName`，如 `0.1.0.md`）。

- **禁止中文文件名、中英混排文件名**（历史遗留的 `模型速查表.md`、
  `OPENCODE-GO-模型与订阅优化分析.md` 已按此规则改名）。
- 改名一律 `git mv`，改完**全仓 grep 旧名**，把引用方逐个改到新位置（见 §4）。
- 降级为历史快照的文档，名字也要守住这条 —— 定位写在文档里，不写在文件名里。

---

## 2. 单一正本原则

**每条规则只在一篇文档里定义；其余位置只允许一句话概述 + 指向正本的链接。**
两处都写全文，迟早各改各的。

权威正本映射表：

| 规则 | 正本 |
|---|---|
| provider 分组 / 协议类型 / 工具调用 / 关思考参数矩阵 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) |
| 接一个新供应商的四步方法 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §0 |
| 脚本改 ZCode 配置的哪几处、两个 `--apply` 脚本的行为差异 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §1、§1.1 |
| `--apply` 的备份文件名与回退步骤 | [MAINTENANCE.md](MAINTENANCE.md) §4 |
| 写配置期间与 ZCode 界面的互斥、热重载注意事项 | [MAINTENANCE.md](MAINTENANCE.md) §5（机制解释见 [PITFALLS.md](PITFALLS.md) §8） |
| 文档怎么写、怎么分类、怎么互链、文件怎么命名 | [DOC-RULES.md](DOC-RULES.md)（本篇 §1） |
| 维护流程（价格表刷新 / 探测限速 / 快照保留 / 备份回退 / 热重载） | [MAINTENANCE.md](MAINTENANCE.md) |
| 排错步骤（现象 → 排查 → 原因 / 解法） | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 为什么会出这个坑（机制解释） | [PITFALLS.md](PITFALLS.md) |
| Release 说明格式（含动词四选一、覆盖率红线） | [release-notes/README.md](release-notes/README.md) |
| **版本晋升规则**（有功能更新 +0.1.0，没有 +0.0.1） | [VERSIONING.md](VERSIONING.md) §1–§2 |
| **交付 / 发版规则**（版本号在哪维护 / 什么时候不动版本号 / 打 tag） | [VERSIONING.md](VERSIONING.md) §3、§5 + [release-notes/README.md](release-notes/README.md) |
| 脚本清单、产物与去留标记、运行环境 | [TOOLS.md](TOOLS.md) |
| 凭据存放位置与取值方法 | [SECRETS.md](SECRETS.md) |
| 许可证 | 仓库根 [LICENSE](../LICENSE)（MIT 全文） |
| PROGRESS 的路径规则、凭据规则 | 仓库根 [AGENTS.md](../AGENTS.md) |
| 第三方组件与服务的声明 | 仓库根 [NOTICE](../NOTICE) |
| 同类项目调研与随仓分发的上游文件来源 | [UPSTREAM.md](UPSTREAM.md) + [../third-party/README.md](../third-party/README.md) |
| 外部榜单的入口、口径与分数快照 | [BENCHMARKS.md](BENCHMARKS.md) |

### 禁止重复清单（本次建仓发现的反例，勿重蹈）

1. **`docs/MODEL-QUICK-REF.md` ↔ `docs/MODEL-PROVIDERS.md`**：前者是 2026-10-20 的速查快照，
   后者是新建的正本。两边都有 provider 分组与关思考写法。本轮的处理是
   **MODEL-PROVIDERS 为正本、速查表降级为历史快照**（已在速查表顶部加
   「结论已并入 MODEL-PROVIDERS.md，本篇保留作历史快照」声明，内容保留原状）；
   后续若继续维护速查表，**只允许补实测数据**，分组与参数口径一律回 MODEL-PROVIDERS。
2. **`docs/archive/OPENCODE-GO-ANALYSIS.md` ↔ MODEL-PROVIDERS**：
   分析报告里的协议归属表、价格带表与正本重叠。归档件**只读**，不改、不删；
   要引用结论去正本。
3. **`evidence/PROGRESS.workbuddy.md` ↔ 根 `PROGRESS.md`**：前者是 WorkBuddy 接入线
   的历史台账（拆仓前就是独立文件），后者是本仓的总台账。历史台账**只读**，
   新的批次一律写进根 `PROGRESS.md`。
4. **[TOOLS.md](TOOLS.md) 的工具表 ↔ 任何脚本目录的 README**：本仓**不设**脚本级
   README（脚本少且都带 docstring），工具清单只在 TOOLS.md 维护一份。
5. **版本规则 ↔ `CHANGELOG.md` 头部**：版本**号本身**（当前是哪个版本）只在
   [CHANGELOG.md](../CHANGELOG.md) 的版本标题里；**进位规则**只在
   [VERSIONING.md](VERSIONING.md) §1–§2。两处都写规则，迟早各改各的。
6. **凭据明文 ↔ 任何其它文档**：明文值不写进代码与文档；**只写位置**的清单在
   [SECRETS.md](SECRETS.md)，脚本从环境变量读。

---

## 3. 结论与证据的分工

- **文档写结论，不写推理过程。** 「为什么会这样」放 PITFALLS，
  「怎么办」放 TROUBLESHOOTING，「是什么」放 MODEL-PROVIDERS。
- **数值要标口径与时点。** 价格、额度、倍率、延迟都是会变的，
  必须写明来源（哪个接口 / 哪个面板）与快照日期；没写时点的数值一律视为不可信。
- **不确定就写「待补」**，并写清缺什么证据（哪个接口没通、哪个文件不存在），
  不要用「大概」「应该」蒙混过去。
- **不引用报告的行号。** 结论要能被复现，不能靠「见某报告第 N 行」。

---

## 4. 链接纪律

- 统一用**相对链接 + 锚点**（形如 `[标题](文档名.md#锚点)`，写时用半角括号），
  不用绝对路径、不用本地盘符路径。
- 链接到**仓库外的第三方**用完整 URL；链接到**本仓的文件**一律相对链接。
- **改动 / 删除 / 合并文档后必须双向点验**：
  - 出链：新文档里指向别处的链接目标还存在、锚点没变；
  - 入链：全仓搜旧文件名（Grep），把指向它的链接改成新位置 ——
    **禁止只删文档不改引用方**。
- 判断某段「重复」是否该收敛时，先看它被谁引用；收敛后引用方必须同步改。
- 历史记录里的旧文件名可保留原样 —— 那是当时的事实；
  但**正文中指向现役文档的链接**必须始终指向现役文档。

---

## 5. 变更触发矩阵

改了什么，就必须连带改什么：

| 变更 | 必须同步 |
|---|---|
| **修一个缺陷**（行为变化 / 判据修正 / 安全加固） | 对应正本补一条 **现象 → 根因 → 怎么避**：[PITFALLS.md](PITFALLS.md)；CHANGELOG 只是变更记录，**不算补文档** |
| 新增 / 删除 provider，或某个模型的归属档位变了 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) 对应表、[PITFALLS.md](PITFALLS.md) 如有涉及 |
| 某个模型的协议类型变了（chat / messages / responses） | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) 的协议列 + [PITFALLS.md](PITFALLS.md) §2 |
| 关思考参数矩阵变化 | [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §5 |
| 新踩一个坑 | [PITFALLS.md](PITFALLS.md)；若已有对应排错条目，同步 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| 改了脚本的入参 / 输出路径 | [TOOLS.md](TOOLS.md) + [MAINTENANCE.md](MAINTENANCE.md) |
| 改了价格表 / 倍率的刷新方式 | [MAINTENANCE.md](MAINTENANCE.md) §1 + [CHANGELOG.md](../CHANGELOG.md) 的「待补」 |
| 改了 Release 说明格式 | [release-notes/README.md](release-notes/README.md)（正本）+ 本篇 §2 映射表 |
| 改了凭据的存放位置或新增了凭据 | [SECRETS.md](SECRETS.md)（位置清单）、`.gitignore` 的排除项 |
| 改了版本晋升 / 发版规则 | [VERSIONING.md](VERSIONING.md)；根 [CHANGELOG.md](../CHANGELOG.md)（版本号本身） |
| 改了许可证 | 根 [LICENSE](../LICENSE)、[NOTICE](../NOTICE)、根 [README.md](../README.md) 的许可证段 |
| 新增 / 删除 / 改名文档 | [README.md](README.md) 索引（见 §7）+ 全仓 grep 旧文件名改引用方（见 §4） |
| 文件改名（含中文名改全大写连字符） | `git mv` + 全仓 grep 旧名逐个改引用；**不要动 git tag** |
| 改了版本号规则 | [VERSIONING.md](VERSIONING.md) + 本篇 §2 映射表 |
| 改了 Release 说明文件名口径（`versionName`，无 `v` 前缀） | [release-notes/README.md](release-notes/README.md) + [VERSIONING.md](VERSIONING.md) §3 |

---

## 6. 体量预算与样例时效

- **单篇 ≤ 800 行。** 超了就按「正文档 + 历史篇」拆：正文档留结论与约束，
  历史 / 根因分析移到 archive/。范例：[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)（正文档）
  + [MODEL-QUICK-REF.md](MODEL-QUICK-REF.md) 与 [archive/](archive/)（历史快照）。
- **索引行 = 定位，不是摘要**：[README.md](README.md) 里每篇的一句话定位压到
  30~60 字一行读完，详细内容留在文档里 —— 索引只负责「该翻哪篇」。
- **样例时效**：带日期标注的样例（「2026-10-19 实测」「月额度 $60」）可容忍过时 ——
  它们是历史记录；但**分组结构、provider 数量、模型归属**这类清单类内容
  必须随配置变更同步，不允许停留在旧状态。
- **归档件只读**：`docs/archive/` 与 `evidence/` 里的文件**不再修改**。
  发现其中有错也不要就地改 —— 在正本里写清更正，并把归档件在索引里标注为「历史」。

---

## 7. 索引维护与孤儿零容忍

- [README.md](README.md) 是 docs/ 的**唯一索引**，
  **新增 / 删除 / 改名文档必须同步更新**。
- **孤儿文档零容忍**：任何新文档必须至少被一处既有文档引用（或进索引并有明确入口），
  否则等于没写。
- 根目录的 [README.md](../README.md)、[AGENTS.md](../AGENTS.md)、
  [CHANGELOG.md](../CHANGELOG.md)、[NOTICE](../NOTICE)、[PROGRESS.md](../PROGRESS.md)、
  [LICENSE](../LICENSE)
  **不在 docs/ 索引的管辖范围内**，但改动它们时同样要检查是否有指向它们的链接需要更新。
