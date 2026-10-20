# zai-org/ZCode —— 来源凭证

> **一句话**：本目录是 ZCode 官方开源仓库的**原样文件**，用来让本仓能离线复刻
> 客户端的请求体语义 —— 不再依赖本机是否装了 ZCode。

---

## 1. 上游

| 项 | 值 |
| --- | --- |
| 仓库 | `zai-org/ZCode` |
| URL | <https://github.com/zai-org/ZCode> |
| 许可 | **Apache-2.0**（全文见本目录 `LICENSE`） |
| 钉住的 commit | 见本目录 `.upstream-sha` |
| 上游主页 | <https://zcode.z.ai/> |
| 开源时间 | 2026-09-21（智谱官方开源） |

## 2. 包含哪些文件、对应上游哪个路径

| 本地文件 | 上游路径 | 用途 |
| --- | --- | --- |
| `zcode-builtin.json` | `config/provider/zcode-builtin.json` | **规则数据**：ZCode 内置的 83 条 model 规则、73 条 model-api 规则、54 条 provider-site 规则、248 条 template 规则、30 条精确 provider 规则 |
| `model-config.ts` | `packages/provider/src/config/model-config.ts` | **规则引擎**：`ModelConfigRules.resolve()` 的遍历与匹配语义、`matchesRule()` 的全匹配正则、`overlayValue()` 的合并语义 |
| `schema.ts` | `packages/provider/src/config/schema.ts` | **规则扁平化顺序**：5 个规则数组怎么合成一条遍历列表（`model → model-api → provider-site → template-model → provider-model`） |
| `rule-data-schema.ts` | `packages/provider/src/config/rule-data-schema.ts` | 规则数据的 zod schema |

**这四个文件一个字节都没有改。**

## 3. 本仓怎么用它们

`workbuddy/zcode_effective_body.js` 靠它们把「ZCode 实际会发什么请求体」算出来：

1. 按 `schema.ts` 的顺序把 5 个规则数组合成一条遍历列表；
2. 按 `model-config.ts` 的 `resolve()` 逐条匹配并叠加（**后者胜**，`undefined` 不清空）；
3. 用 `matchesRule()` 的语义做全匹配正则 `^(?:pattern)$`（`modelMatch` 忽略大小写）；
4. 把 `optionSpecs.reasoningLevel.map` / `optionSpecs.maxOutputTokens.map` 当 JS 表达式求值，
   作用域里只有 `reasoningLevel` 与 `maxOutputTokens` 两个自由变量。

脚本的 builtin 文件查找顺序：
`ZCODE_BUILTIN` 环境变量 → **本目录的 `zcode-builtin.json`** → 本机 ZCode 运行时
（`~/.zcode/v2/runtime/provider/<平台>/<版本>/<端点>/zcode-builtin.json`，取最新）
→ 桌面版安装目录（`@opencodedesktop` / `ZCode` 的 `resources/config/provider/`）。

> **为什么把上游 vendor 进来**：本仓的核心用途是「用 ZCode 真实请求体去探测供应商哪些模型能用」。
> 如果规则语义只能从本机安装的客户端里读，那么换台机器、或者客户端升级换了规则，
> 探测结果就会和真实行为脱节。vendor 之后，**规则语义跟着仓库走**，而且每一行都能指回上游源码。

## 4. 怎么更新

```bash
SHA=$(git ls-remote https://github.com/zai-org/ZCode.git refs/heads/main | cut -f1)
BASE="https://raw.githubusercontent.com/zai-org/ZCode/$SHA"
curl -sSL "$BASE/config/provider/zcode-builtin.json"                    -o zcode-builtin.json
curl -sSL "$BASE/packages/provider/src/config/model-config.ts"           -o model-config.ts
curl -sSL "$BASE/packages/provider/src/config/schema.ts"                -o schema.ts
curl -sSL "$BASE/packages/provider/src/config/rule-data-schema.ts"      -o rule-data-schema.ts
curl -sSL "$BASE/LICENSE"                                               -o LICENSE
printf '%s\n' "$SHA" > .upstream-sha
```

**更新后必须做两件事**：
1. 跑 `node ../zcodium/reasoning-rules.js check` —— 报「存在漂移」说明内置的思考规则变了，
   按 `docs/PITFALLS.md` §2 重新实测思考参数矩阵；
2. 跑一遍 `workbuddy/workbuddy_probe_zcode.py` 的回归 —— 确认 56 个 WorkBuddy 模型的
   有效请求体没有非预期变化（`reasoning` / `enable_thinking` / `reasoning_effort` 三个字段）。

## 5. 许可与传染性

ZCode 是 **Apache-2.0**。本仓整体是 MIT —— Apache-2.0 与 MIT **兼容**（Apache-2.0 允许再分发进 MIT 项目，
但要求保留原始版权声明与 NOTICE）。本目录保留了上游的 `LICENSE` 全文与文件头版权声明，满足该条件。

> 注意对比：本仓的兄弟仓 `ShellcrashRules` 整仓是 **GPL-3.0**，因为它含 ShellCrash 的 GPL-3.0 派生件。
> 本仓没有这个问题 —— Apache-2.0 与 MIT 可共存。
