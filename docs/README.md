# docs/ 索引

> **一句话**：这里只有索引与定位，不放正文 —— 每篇文档一句话说明「它管什么」，
> 规则本身按 [DOC-RULES.md](DOC-RULES.md) 的单一正本原则只在对应文档里定义。

文档分四类。每篇开头都有一个「一句话」引言块，先看它再决定要不要往下读。

---

## 一、模型与 Provider

| 文档 | 一句话定位 |
|---|---|
| [MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) | **provider 与模型参数正本**：接供应商的四步方法、ZCode 配置落点、三组 provider（OpenCode-Go / WorkBuddy / Qoder）的分组 / 协议 / 工具调用 / 关思考参数 |
| [MODEL-ALIAS.md](MODEL-ALIAS.md) | **统一命名与四组正本**：`渠道/积分/型号`、三家积分换算、主力（人工 + 榜单扩充）/免费/低耗/高耗、alias map 与协议桥接 |
| [QODER.md](QODER.md) | **Qoder 接入正本**：qoder2api-hub 的 8790 进程、OAuth/签到、`qoder` provider 的模型与同步/探测命令、边界与故障处理 |
| [MODEL-QUICK-REF.md](MODEL-QUICK-REF.md) | 早期速查（2026-10-20）：价格、额度与实测首字。**结论已并入 MODEL-PROVIDERS.md**，本篇保留作历史快照 |
| [archive/OPENCODE-GO-ANALYSIS.md](archive/OPENCODE-GO-ANALYSIS.md) | 2026-10-19 的阶段性分析（归档只读）：协议归属实测、价格带筛选、出口方案 |

## 二、流程与规范

| 文档 | 一句话定位 |
|---|---|
| [DOC-RULES.md](DOC-RULES.md) | **文档规则正本**：文件命名（全大写连字符）、分类定位、单一正本映射表、链接纪律、变更触发矩阵、体量预算 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | **运行架构整合提案（待确认）**：四个常驻进程 293 MB 的实测拆解、`zgate` 单入口 + 按需子进程方案、`gateways/` 与 `providers/` 两轴目录重构、分阶段验收与回退 |
| [MAINTENANCE.md](MAINTENANCE.md) | 日常维护：刷价格表、探测限速、快照保留、`--apply` 备份与回退、热重载注意事项 |
| [TOOLS.md](TOOLS.md) | **工具清单正本**：运行环境、每个脚本的产物与去留标记、统一模式与 `--separate` 的区别 |
| [VERSIONING.md](VERSIONING.md) | **版本晋升正本**：三段式进位、仓库发布号在哪维护、什么时候不动版本号。发版规则并入本篇 |
| [SECRETS.md](SECRETS.md) | **凭据位置正本**：一律走环境变量，**只写位置不写值**；上传公开仓库前必读 |
| [release-notes/README.md](release-notes/README.md) | **Release 说明格式正本**：形状、动词四选一、覆盖率红线、固定尾巴 |

## 三、排错与踩坑

| 文档 | 一句话定位 |
|---|---|
| [PITFALLS.md](PITFALLS.md) | **为什么会出这个坑**：机制解释，每条标 **【通用】/【实例 A】/【实例 B】** |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | **怎么查**：现象 → 排查步骤 → 原因 / 解法，标题即检索词 |

## 四、参考资料

| 位置 | 一句话定位 |
|---|---|
| 仓库根 [README.md](../README.md) | 门面（面向使用者）：这是什么、环境要求、使用、反馈、免责声明、许可证 |
| 仓库根 [AGENTS.md](../AGENTS.md) | 机器协议：PROGRESS 按逻辑任务分家、凭据走环境变量、CodeGraph |
| 仓库根 [CHANGELOG.md](../CHANGELOG.md) | 开发者记录：**版本号本身**在它的版本标题里，**进位规则**见 [VERSIONING.md](VERSIONING.md) |
| 仓库根 [PROGRESS.md](../PROGRESS.md) | 本仓唯一进度台账（追加式批次日志） |
| 仓库根 [NOTICE](../NOTICE) | 第三方声明：WorkBuddy2API Panel（MIT）、qoder2api-hub（MIT）、OpenCode Go（商业）、ZCode（Apache-2.0）等 |
| [UPSTREAM.md](UPSTREAM.md) | **上游调研正本**：同类型项目清单、深读结论、借鉴落地、随仓分发的上游文件与来源凭证 |
| [BENCHMARKS.md](BENCHMARKS.md) | **外部跑分参考**：AI 能力专项测试（2026-09-11 快照）+ ArenaGalleri 实时榜；主力自动扩充的基准、窗口与候选表 |
| 仓库根 [third-party/](../third-party/README.md) | 随仓分发的上游文件：ZCode 规则数据与引擎源码、ZCodium 规则切片，各带来源凭证 |
| 仓库根 [LICENSE](../LICENSE) | 许可证全文（**MIT**），与 [NOTICE](../NOTICE) 配套 |
| [release-notes/](release-notes/README.md) | 面向使用者的 Release 说明，文件名 = `versionName`；格式规范在它的 README。已发布：[0.2.0.md](release-notes/0.2.0.md) / [0.1.0.md](release-notes/0.1.0.md) |
| `../evidence/` | 证据快照：网关模型目录、自动收录报告、WorkBuddy 接入线历史台账（只读） |

---

> 新增 / 删除文档后**必须同步更新本索引**（规则见 [DOC-RULES.md](DOC-RULES.md)）；
> 新文档至少要被一处既有文档引用，不允许孤儿。
