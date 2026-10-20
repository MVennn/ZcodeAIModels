<div align="center">

<img src="https://gitlab.com/M.Venn/ZcodeAIModels/-/raw/main/assets/logo.png" width="128" alt="ZcodeAIModels">

# ZcodeAIModels

**把模型供应商接进 ZCode 客户端的脚本与文档**（以 WorkBuddy2API 网关与 OpenCode-Go 套餐为例）

不改 ZCode 的代码，只写它的配置文件。

![流水线](https://gitlab.com/M.Venn/ZcodeAIModels/badges/main/pipeline.svg) ![源码仓库](https://img.shields.io/badge/源码仓库-GitLab-FC6D26?logo=gitlab&logoColor=white) ![问题反馈](https://img.shields.io/badge/问题反馈-Issues-FC6D26?logo=gitlab&logoColor=white) ![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white) ![Node.js](https://img.shields.io/badge/Node.js-18%2B-339933?logo=node.js&logoColor=white) ![License](https://img.shields.io/badge/License-MIT-blue)

</div>

---

## 这是什么

一个**工具仓库**，不是一个应用。它做三件事：

1. **探测** —— 逐个模型试：能不能连、走哪种协议、工具调用能不能用、
   思考参数怎么关、还剩多少额度；
2. **同步** —— 把探测结论整理成 provider 分组（按成本档 / 积分倍率），
   写进 ZCode 客户端的 `provider_config.json`，让 ZCode 的模型列表里出现它们；
3. **记录** —— 把踩过的坑、模型的协议归属、关思考的参数矩阵固化成文档，
   下次换套餐、改网关、调规则时不用重新试一遍。

**方法与供应商无关**：仓里的 `opencode-go/` 与 `workbuddy/` 是两个跑通的**完整示例**，
也是照「[接一个新的模型供应商](#接一个新的模型供应商)」那套结构写的参照实现。
文档里的结论分两类 ——「通用能力」（换供应商也成立）与「本次实例」（随服务商变动的数据快照），
分类与正本见 [docs/MODEL-PROVIDERS.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/MODEL-PROVIDERS.md)。

## 适用环境

| 项 | 值 |
|---|---|
| 客户端 | ZCode（Windows 桌面端） |
| 配置文件 | `~/.zcode/v2/provider_config.json`（Windows：`C:\Users\<你的用户名>\.zcode\v2\provider_config.json`）；可用环境变量 `ZCODE_PERSONAL_PROVIDER_CONFIG_FILE` 覆盖 |
| 运行时 | Python 3（**只用标准库**，无第三方依赖）+ Node.js（跑 `.js` 脚本） |
| 网络 | 能直连你的供应商。示例：直连 `opencode.ai`；WorkBuddy 侧需要本地网关 `wb2api` 在 `127.0.0.1:7863` 在跑（`WB_GATEWAY_BASE` 可覆盖） |
| 凭据 | **一律走环境变量**：`OPENCODE_GO_KEY`（OpenCode-Go）、`WB_GATEWAY_KEY`（网关）。位置口径见 [docs/SECRETS.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/SECRETS.md) |

## 快速开始

顺序不能乱：**先刷价格表 → 再探测 → 最后同步**。探测要慢（≥ 20 秒一个模型，
太密会把对方的账号池打爆），同步是秒级。

### 0. 准备环境变量

```bash
export OPENCODE_GO_KEY='<OpenCode-Go api_key>'        # 跑 opencode-go/probe/ 下的脚本必填
export WB_GATEWAY_KEY='<网关 api_key>'                 # 仅 WorkBuddy 侧需要
export ZCODE_PERSONAL_PROVIDER_CONFIG_FILE="$HOME/.zcode/v2/provider_config.json"
```

### 1. 刷价格表（只有 WorkBuddy 侧需要）

```bash
cd workbuddy
python workbuddy_fetch_pricing.py            # 抓网关价格表 → workbuddy/cache/wb_pricing.json（自动备份旧文件）
python workbuddy_fetch_pricing.py --dry-run  # 只看会变成什么样
```

OpenCode-Go 侧不需要这一步：`go_model_sync.py` 每次运行都会现拉模型目录与官方价格表。

### 2. 探测

```bash
# --- WorkBuddy：用 ZCode 真实请求体探测，间隔必须 >= 20 秒 ---
python workbuddy/workbuddy_probe_zcode.py --sleep 20

# --- OpenCode-Go：连通性 + 首字节延迟（结果写到当前目录，跑完手动归档）---
cd opencode-go/probe
python probe_models.py
node thinking-off-probe.js        # 只打印，不落盘
```

> 探测**必须用 ZCode 真实请求体**，不能拿裸 body 试 —— ZCode 会注入思考字段，
> 裸 body 能通不代表 ZCode 能通。

### 3. 同步进 ZCode

```bash
# 先不带 --apply 跑一遍，只出报告，看清楚要写什么
python opencode-go/ops/go_model_sync.py
python workbuddy/workbuddy_zcode_sync.py

# 确认无误再写
python opencode-go/ops/go_model_sync.py --apply
python workbuddy/workbuddy_zcode_sync.py --apply
```

两个脚本都会**先备份再原子替换** `provider_config.json`；ZCode 约 1 秒轮询该文件，
写完一般**不用重启客户端**。

每个脚本的产物与保留标记见 [docs/TOOLS.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/TOOLS.md)；
模型为什么会 400 / 503、免费池 429 是不是故障，见
[docs/PITFALLS.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/PITFALLS.md)
与 [docs/TROUBLESHOOTING.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/TROUBLESHOOTING.md)。

## 接一个新的模型供应商

四步，与具体供应商无关（正本见
[docs/MODEL-PROVIDERS.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/MODEL-PROVIDERS.md) §0）：

1. **摸清接口面** —— 模型目录从哪个接口拿、每个模型走哪种协议、怎么计价；
2. **取目录与价格**，归一化成一张价格表 —— 归一化之后，分档就是纯本地计算；
3. **探测** —— 用 ZCode 真实请求体 + 限速；
4. **分档并写配置** —— 按成本档切，档内按单价（或倍率）升序，只碰
   `provider_config.json` 的三个位置（见下一节）。

换供应商只改「取数 + 归一化」与分档口径；写配置的方式、思考参数覆盖机制、
探测必须用真实 body 这几件事完全不用改。

## 与 ZCode 的关系

本仓库**不含 ZCode 客户端**，只读写它的配置文件。脚本只碰三个位置：

| JSON 路径 | 内容 |
|---|---|
| `config.providerConfigRules.providerRules[]` | provider：显示名、协议 `api.type`、`api.baseUrl`、`personalModelIds`、`modelOrder` |
| `config.modelConfigRules.providerModelRules[]` | 模型级规则：`enabled`、`properties`、`optionSpecs`（思考覆盖、最大输出） |
| `config.providerOrder[]` | provider 在界面里的先后顺序 |

写配置期间**不要**在 ZCode 的 provider 设置界面里同时改 —— 界面保存时会整份写回，
把脚本刚写进去的东西覆盖掉。两个 `--apply` 脚本分别会「只追加新模型」（低风险）与
「整条替换三个 workbuddy provider」（你手工加的模型会被冲掉），都会先做 `.bak-*` 备份；
回退方式见 [docs/MAINTENANCE.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/MAINTENANCE.md) §4。

## 反馈

接不上某个供应商、探测结果对不上、想要新的判定手法，都可以到
[Issues](https://gitlab.com/M.Venn/ZcodeAIModels/-/issues) 反馈。请尽量带上：

- 哪个脚本、执行的哪一步、报错原文
- 涉及的模型与 provider、ZCode 版本
- 对应环境变量是否已设置（**不要**把 key 贴出来）

想参与贡献（含怎么接一个新供应商的完整流程），见
[CONTRIBUTING](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/CONTRIBUTING.md)；
安全问题按 [SECURITY](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/SECURITY.md) 报告。

## 免责声明

本项目仅供学习与个人使用。

- 本仓库**不上传、不收集任何数据**；所有脚本只与你自己机器上的配置和你自己的
  模型网关交互。
- 脚本会修改**你自己的** ZCode 配置文件。写之前请备份（脚本也会自动备份）。
- 本仓示例涉及的 `opencode.ai` 与 WorkBuddy2API，以及**你自行接入的其它供应商**，
  都是**第三方服务**，本项目与它们不存在任何隶属、合作、授权或认可关系。
  模型价格、额度、可用性、隐私策略（部分模型会用请求数据训练）
  **一律以服务商当时的说明为准**，本仓库的文档只是某一时刻的快照。
- 本仓库的模型清单与分组是**按成本档 / 积分倍率**排的，是主观取舍，不是推荐。
- 使用本项目产生的任何后果由使用者自行承担。

## 开源鸣谢

本仓库建立在这些项目与服务之上（详见 [NOTICE](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/NOTICE)）：

| 项目 / 服务 | 用途 |
|---|---|
| [**WorkBuddy2API Panel**](https://github.com/linguo2625469/workbuddy2api-panel)（上游 [Sliverkiss/workbuddy2api](https://github.com/Sliverkiss/workbuddy2api)） | 腾讯 CodeBuddy 多账号网关，WorkBuddy 侧全部请求都发给它（MIT；本仓不含其源码，只通过 HTTP 调用） |
| **OpenCode Zen / Go**（opencode.ai） | 模型套餐与 API 网关，OpenCode-Go 侧全部请求都发给它（商业服务） |
| [**ZCode**](https://github.com/zai-org/ZCode) | 目标客户端，本仓改它的配置并复刻它的请求体语义（Apache-2.0；`third-party/zcode/` 随仓分发它的 4 个原样文件） |
| [**ZCodium**](https://github.com/ZCodium-project/ZCodium) | ZCode 的 MIT 授权独立审计 fork，思考规则切片的来源（MIT） |
| **Python 3** / **Node.js** | 脚本运行时 |

调研过的 14 个同类型开源项目（借鉴了什么、为什么没有 vendor）见
[docs/UPSTREAM.md](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/docs/UPSTREAM.md)。
本仓**实际复制**的只有三处：ZCodium 的规则切片（逐字）、`third-party/zcode/` 的
4 个原样文件（Apache-2.0），以及本仓自写的规则实现；来源凭证都在
[third-party/](https://gitlab.com/M.Venn/ZcodeAIModels/-/tree/main/third-party/README.md)。

## 许可证

本项目以 [MIT License](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/LICENSE) 发布。
第三方组件与服务的版权与条款声明见 [NOTICE](https://gitlab.com/M.Venn/ZcodeAIModels/-/blob/main/NOTICE)。
