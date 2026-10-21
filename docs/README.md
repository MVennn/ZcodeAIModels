# docs/ 索引

> **一句话**：这里只有索引与定位，不放正文 —— 每篇文档一句话说明「它管什么」，
> 规则本身按 [DOC-RULES.md](DOC-RULES.md) 的单一正本原则只在对应文档里定义。

文档分四类。每篇开头都有一个「一句话」引言块，先看它再决定要不要往下读。

---

## 一、模型与 Provider

| 文档 | 一句话定位 |
|---|---|
| [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) | **provider 与模型参数矩阵正本**：§0 是「接一个新供应商」的通用方法（四步 + 通用概念对照表）；§2 / §4 是本仓已配置的两组 provider 数据（OpenCode-Go 七个分组；五个 chat 组经统一路由同时装 WorkBuddy 模型）、协议类型、工具调用支持、关思考参数怎么写、global 号 `personal_free_user` 的 503 限制 |
| [模型速查表.md](模型速查表.md) | 早期速查（2026-10-20）：价格、额度与实测首字。**结论已并入 MODEL-PROVIDERS.md**，本篇保留作历史快照 |
| [archive/OPENCODE-GO-模型与订阅优化分析.md](archive/OPENCODE-GO-模型与订阅优化分析.md) | 2026-10-19 的阶段性分析：协议归属实测、价格带筛选、路由器侧出口方案。结论已被上两篇取代 |

## 二、流程与规范

| 文档 | 一句话定位 |
|---|---|
| [DOC-RULES.md](DOC-RULES.md) | **文档规则正本**：分类定位、单一正本映射表、链接纪律、变更触发矩阵、体量预算 |
| [MAINTENANCE.md](MAINTENANCE.md) | 维护流程：§1.1 刷价格表的**通用做法**（换供应商照这个做）+ §1.2 / §1.3 两个实例、探测频率与限速、结果快照保留、`--apply` 备份与回退、ZCode 热重载注意事项、§8 网关随 ZCode 自动起停 |
| [TOOLS.md](TOOLS.md) | 工具清单（**正本**）：每个脚本的产物与去留标记（长期 / 一次性 / 活数据） |
| [VERSIONING.md](VERSIONING.md) | **版本晋升规则正本**：三段式进位（有功能更新 +0.1.0 / 没有 +0.0.1）、版本号在哪维护、什么时候不动版本号；**发版与交付规则并入本篇**，不另立 `RELEASE.md` |
| [SECRETS.md](SECRETS.md) | **凭据位置正本**：**任何供应商的凭据都只走环境变量**；OpenCode-Go API key、WorkBuddy 网关 key、ZCode 配置路径、活数据缓存在哪儿 —— **只写位置，不写值**；上传公开仓库前必读 |
| [release-notes/README.md](release-notes/README.md) | **Release 说明格式正本**：形状、动词、覆盖率红线、别写这些 |

## 三、排错与踩坑

| 文档 | 一句话定位 |
|---|---|
| [PITFALLS.md](PITFALLS.md) | 踩坑总汇：为什么 ZCode 里某个模型会 400 / 503、探测为什么会打爆账号池、免费池 429 到底是不是故障；每条标 **【通用】/【实例 A】/【实例 B】** |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 排错手册：按「现象 → 排查步骤 → 原因 / 解法」组织，标题即检索词；每条标 **【通用】/【实例 A】/【实例 B】** |

## 四、参考资料

| 位置 | 一句话定位 |
|---|---|
| 仓库根 [README.md](../README.md) | 门面：这是什么、适用环境、快速开始、接一个新的模型供应商（四步）、与 ZCode 的关系、反馈、免责声明、开源鸣谢、许可证 |
| 仓库根 [AGENTS.md](../AGENTS.md) | 机器协议：PROGRESS 按逻辑任务分家、凭据走环境变量、CodeGraph |
| 仓库根 [CHANGELOG.md](../CHANGELOG.md) | 更新日志；首段记录本次拆分建仓。**版本号本身**在它的版本标题里，**进位规则**见 [VERSIONING.md](VERSIONING.md) |
| 仓库根 [PROGRESS.md](../PROGRESS.md) | 本仓唯一进度台账（追加式批次日志） |
| 仓库根 [NOTICE](../NOTICE) | 第三方声明：WorkBuddy2API Panel（MIT）、OpenCode Go（商业）、**ZCode（Apache-2.0，已开源）**、ZCodium（MIT）等 |
| [UPSTREAM.md](UPSTREAM.md) | **上游调研正本**：同类型项目清单（14 个，含 URL/SHA/license/本仓关系）、深读结论、借鉴落地、没 vendor 的理由 |
| [BENCHMARKS.md](BENCHMARKS.md) | **外部跑分参考**：第三方榜「AI 能力专项测试」（7 题 · 4 方向 · 总分 400）的入口、口径与 2026-09-11 总分榜快照；数据非本仓实测，引用须带日期 |
| 仓库根 [third-party/](../third-party/README.md) | **随仓分发的上游文件**：zai-org/ZCode 的规则数据与引擎源码（Apache-2.0）、ZCodium 的规则切片（MIT）；每个子目录一份来源凭证 |
| 仓库根 [LICENSE](../LICENSE) | 许可证全文（**MIT**）—— 与 [NOTICE](../NOTICE) 的第三方声明配套 |
| [release-notes/](release-notes/README.md) | 面向使用者的 Release 说明，文件名 = 版本号；格式规范在它的 README。已发布：[v0.1.0.md](release-notes/v0.1.0.md) |
| `../evidence/` | 证据快照：网关模型目录（`wb_panel_models.json`）、自动收录报告（`go-model-sync/`）、WorkBuddy 接入线历史台账 |

---

> 新增 / 删除文档后**必须同步更新本索引**（规则见 [DOC-RULES.md](DOC-RULES.md) §7）；
> 新文档至少要被一处既有文档引用，不允许孤儿。
