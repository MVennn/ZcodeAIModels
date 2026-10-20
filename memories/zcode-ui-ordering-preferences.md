---
name: zcode-ui-ordering-preferences
description: 用户对模型/策略组列表的命名与排序偏好：自建标签用两字中文、不加 emoji、常用的排最前、模型按厂商分组
metadata:
  node_type: memory
  type: feedback
  originSessionId: sess_45231509-4e0a-42d5-b258-b22ab0e27a40
---

用户在整理 ZCode 模型列表和 ShellCrash 策略组时明确要求：

- **自建标签用两字中文、不要 emoji**，例如 `主力`、`速度`、`经济`、`对话`、`备用`。模板自带的组名（🚀 节点选择、♻️ 自动选择等）保持原样。
- **常用的排最前**：订阅策略组第一个必须是 `🚀 节点选择`，第二个 `♻️ 自动选择`。
- **模型按公司/厂商分组**连续排列（DeepSeek、智谱、MiniMax、小米 MiMo、美团 LongCat、腾讯混元……），不要按协议或字母打散。
- ZCode 没有模型备注字段，所以用"按用途拆 provider、把 providerName 当标签"的方式提供可读性。
- **2026-10-19 追加**：chat 组从"按用途"改为**按成本档**（`主力` / `免费` / `低耗` / `高耗`），因为每个模型额度独立，"这个模型能烧多少"比"快不快"更值得写进组名；对话、备用仍按协议。以后加模型先算「月额度 ÷ 输出单价」再决定放哪档。

**Why:** 用户要在一眼扫过的列表里判断"哪个快、适合什么"。长名称、emoji 和杂乱顺序都会增加噪音；两字标签最省认知成本。

**How to apply:** 以后新增模型或策略组时，沿用两字中文标签和"常用优先"顺序，不要加 emoji 或长描述；模型列表先按厂商分组，组内把常用/便宜的放前面。相关：[[opencode-go-zcode-models]]、[[shellcrash-ai-routing-fix]]
