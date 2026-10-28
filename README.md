<div align="center">

<img src="https://raw.githubusercontent.com/MVennn/ZcodeAIModels/main/assets/logo.png" width="128" alt="ZcodeAIModels">

# ZcodeAIModels

**把模型供应商接进 ZCode 客户端的脚本与文档**

不改 ZCode 的代码，只写它的配置文件。

![CI](https://github.com/MVennn/ZcodeAIModels/actions/workflows/ci.yml/badge.svg) ![源码仓库](https://img.shields.io/badge/源码仓库-GitHub-181717?logo=github&logoColor=white) ![问题反馈](https://img.shields.io/badge/问题反馈-Issues-181717?logo=github&logoColor=white) ![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white) ![Node.js](https://img.shields.io/badge/Node.js-18%2B-339933?logo=node.js&logoColor=white) ![License](https://img.shields.io/badge/License-MIT-blue)

</div>

---

## 这是什么

一个**工具仓库**，不是一个应用。它做三件事：

- **探测** —— 逐个模型试：能不能连、走哪种协议、工具调用能不能用、思考参数怎么关；
- **同步** —— 把探测结论整理成 provider 分组，按成本档 / 积分倍率写进 ZCode 的模型列表；
- **记录** —— 把踩过的坑、协议归属、参数矩阵固化成文档，换套餐时不用重试一遍。

仓里的 `providers/opencode-go/`、`providers/workbuddy/` 与 `providers/qoder/` 是三个跑通的**完整示例**（OpenCode-Go 套餐、
WorkBuddy2API 网关、qoder2api-hub 网关）；现在统一成**三组**（主力 / 免费 / 省钱），
模型 ID 只用型号名（如 `DeepSeek-4.1-Fs`），同型号跨渠道合并成一条按价格升序的链路，由 `tools/model_alias.py` 生成、`gateways/zgate`（Go，单进程）按 alias map 分流并托管两个本地网关。方法本身与供应商无关，接一个新供应商要做的四步见
[docs/MODEL-PROVIDERS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/MODEL-PROVIDERS.md) §0。

**边界**：本仓库**不含 ZCode 客户端**，只读写它的配置文件 `provider_config.json`，
脚本只碰里面的三个位置 —— 落点与写法见
[docs/MODEL-PROVIDERS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/MODEL-PROVIDERS.md) §1。

## 环境要求

| 项 | 要求 |
|---|---|
| 客户端 | ZCode 桌面端（Windows） |
| 运行时 | Python 3（只用标准库）、Node.js 18+（跑探测/旧版路由）；统一入口 `gateways/zgate` 是**单个 Go 二进制**，日常运行不需要 Go（只有自行构建时需要 Go 1.22+，见 [docs/TOOLS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/TOOLS.md) §0） |
| 配置与凭据 | ZCode 的 `provider_config.json`（默认在 `~/.zcode/v2/`）；凭据只走环境变量，变量名与取值见 [docs/SECRETS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/SECRETS.md) |
| 网络 | 能直连你的供应商；四个 chat 组统一指向 `127.0.0.1:7871`（`zgate`），由它按需拉起 WorkBuddy 网关（`7863`）与 Qoder hub（`8790`）。生命周期与自启见 [docs/MAINTENANCE.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/MAINTENANCE.md) §8 |

## 使用

顺序不能乱：**先刷价格表 → 再探测 → 最后同步**。探测要慢 —— 一个模型间隔至少 20 秒，
太密会把对方的账号池打爆；同步是秒级的。

1. **准备环境变量** —— `OPENCODE_GO_KEY`（OpenCode-Go）、`WB_GATEWAY_KEY`（WorkBuddy 网关）、`QD_API_KEY`（Qoder 网关；也可用 git-ignored 的 `providers/qoder/.env.local`）。
2. **刷价格表** —— WorkBuddy 侧先跑 `providers/workbuddy/workbuddy_fetch_pricing.py`；
   OpenCode-Go 侧不用刷，同步脚本每次现拉目录与价格；Qoder 侧也不用刷，`qoder_zcode_sync.py` 每次现拉 `/v1/models`。
3. **探测** —— `providers/workbuddy/workbuddy_probe_zcode.py --sleep 20`、`providers/opencode-go/probe/probe_models.py`、
   `providers/qoder/qoder_probe_zcode.py`。必须用 ZCode 的真实请求体：裸 body 能通不代表 ZCode 能通。
4. **探测并归一化** —— 先更新主力候选（可选），再跑统一探测，最后由 `model_alias.py`
   生成三组 + alias map：

```bash
python tools/arena_leaderboard.py --refresh --write   # 可选：外部榜单 → 主力候选
python tools/model_probe.py
python tools/model_alias.py --slot auto --probe-file ~/.zcode/v2/model_probe.json --apply
```

主力由两部分组成：人工 `MAIN_IDS` + 榜单候选（分数接近 DeepSeek 且积分 ≤ 0.11 的
已配置模型）。榜单口径与 2026-10-23 的候选见
[docs/BENCHMARKS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/BENCHMARKS.md) §8。

旧的 `go_model_sync.py` / `workbuddy_zcode_sync.py` / `qoder_zcode_sync.py` 现在只作
**数据采集**；它们的旧 ID 会由 `model_alias.py` 归一化成统一的型号名。命名、
积分换算与桥接规则见
[docs/MODEL-ALIAS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/MODEL-ALIAS.md)。

`model_alias.py` 会**先备份再原子替换** `provider_config.json`；ZCode 约 1 秒轮询该文件，
写完一般不用重启客户端。统一入口（`gateways/zgate`）、alias map、协议桥与各脚本产物见
[docs/TOOLS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/TOOLS.md)，
命名与积分规则见
[docs/MODEL-ALIAS.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/MODEL-ALIAS.md)，
日常刷新、限速与回退见
[docs/MAINTENANCE.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/MAINTENANCE.md)。

## 反馈

接不上某个供应商、探测结果对不上、想要新的判定手法，都可以到
[Issues](https://github.com/MVennn/ZcodeAIModels/issues) 反馈；想参与贡献见
[CONTRIBUTING](https://github.com/MVennn/ZcodeAIModels/blob/main/CONTRIBUTING.md)，
安全问题按 [SECURITY](https://github.com/MVennn/ZcodeAIModels/blob/main/SECURITY.md) 报告。反馈时请带上：

- 跑的是哪个脚本、卡在哪一步、报错原文
- 涉及的模型与 provider、ZCode 版本
- 对应的环境变量是否已设置（**不要**把 key 贴出来）
- 探测的输出文件（`providers/workbuddy/cache/` 下那两份，发之前先扫一眼有没有凭据）

## 免责声明

本项目仅供学习与个人使用。

- 本仓库**不上传、不收集任何数据**；脚本只与你自己机器上的配置和你自己的模型网关交互
- 脚本会修改**你自己的** ZCode 配置文件，写之前会自动备份，仍建议自己再备份一份
- 示例涉及的 `opencode.ai`、WorkBuddy2API、Qoder 与**你自行接入的其它供应商**都是**第三方服务**，
  本项目与它们不存在任何隶属、合作、授权或认可关系
- 模型价格、额度、可用性与隐私策略**一律以服务商当时的说明为准**，本仓文档只是某一时刻的快照；
  仓里的模型清单与分组按成本档 / 积分倍率排，是主观取舍，不是推荐
- 使用本项目产生的任何后果由使用者自行承担

「ZCode」「OpenCode Zen / Go」等商标、标识的权利均归其权利人所有。本项目与之不存在任何隶属、合作、授权、认可或支持关系。

## 开源鸣谢

本仓库建立在这些项目与服务之上（逐项声明见 [NOTICE](https://github.com/MVennn/ZcodeAIModels/blob/main/NOTICE)）：

| 项目 | 用途 |
|---|---|
| [**WorkBuddy2API Panel**](https://github.com/misakano7545/workbuddy2api-panel)（链路：`Sliverkiss/workbuddy2api` 已删库 → `linguo2625469/workbuddy2api-panel` 2026-10-21 停更 → 本仓现跟踪此分支） | 腾讯 CodeBuddy 多账号网关，WorkBuddy 侧全部请求都发给它（MIT；本仓不含其源码，只通过 HTTP 调用） |
| [**qoder2api-hub**](https://github.com/shuishuipingan/qoder2api-hub) | Qoder 账号网关，Qoder 侧全部请求都发给它（MIT；本仓不含其源码，只通过 HTTP 调用） |
| **Qoder**（qoder.com.cn / qoder.com） | Qoder 侧的模型服务与账号（商业服务） |
| **OpenCode Zen / Go**（opencode.ai） | 模型套餐与 API 网关，OpenCode-Go 侧全部请求都发给它（商业服务） |
| [**ZCode**](https://github.com/zai-org/ZCode) | 目标客户端，本仓改它的配置并复刻它的请求体语义（Apache-2.0） |
| [**ZCodium**](https://github.com/ZCodium-project/ZCodium) | ZCode 的 MIT 授权独立审计 fork，思考规则切片的来源（MIT） |
| **Python 3** / **Node.js** | 脚本运行时 |

调研过的 14 个同类型项目，以及本仓实际复制的上游文件与来源凭证，见 [docs/UPSTREAM.md](https://github.com/MVennn/ZcodeAIModels/blob/main/docs/UPSTREAM.md)。

## 许可证

本项目以 [MIT License](https://github.com/MVennn/ZcodeAIModels/blob/main/LICENSE) 发布。第三方组件与服务的版权与条款声明见 [NOTICE](https://github.com/MVennn/ZcodeAIModels/blob/main/NOTICE)。
