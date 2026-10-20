# third-party/ —— 引入的上游开源项目

> **一句话**：本目录放**随仓分发的上游文件**，每个子目录一份 `UPSTREAM.md` 写清
> 来源 URL、钉住的 commit、许可与本仓怎么用它。

---

## 索引

| 子目录 | 上游项目 | 许可 | 内容 | 本仓怎么用 |
| --- | --- | --- | --- | --- |
| [`zcode/`](zcode/UPSTREAM.md) | [`zai-org/ZCode`](https://github.com/zai-org/ZCode) | Apache-2.0 | ZCode 内置规则数据 `zcode-builtin.json` + 规则引擎源码 `model-config.ts` / `schema.ts` / `rule-data-schema.ts`（**原样，未改一个字节**） | `workbuddy/zcode_effective_body.js` 靠它复刻客户端的请求体语义；让探测不依赖本机是否装了 ZCode |
| [`zcodium/`](zcodium/UPSTREAM.md) | [`ZCodium-project/ZCodium`](https://github.com/ZCodium-project/ZCodium) | MIT | ZCodium 内置思考规则的**最小切片**（4 条，逐字抄录）+ 一个本仓自己写的漂移检查脚本 | 给「思考参数矩阵」提供**可引用的源码依据**，并能检测本机 ZCode 内置规则是否变了 |

---

## 约定

1. **不改上游代码一个字节。** 本仓对上游的改动一律是「打补丁派生件」，放在各自的正经目录里
   （例如 `workbuddy/zcode_effective_body.js` 是本仓**自己写**的实现，只是对齐上游语义）。
2. **每个子目录必须有 `UPSTREAM.md`**，写清：上游 URL、clone 时间、commit SHA、license、
   包含哪些文件对应上游哪个路径、本仓怎么用、怎么更新。
3. **commit SHA 写死在 `.upstream-sha`**（或 `UPSTREAM.md` 的表格里），更新时一并改。
4. **不允许再分发的不 vendor**：AGPL 项目、无 LICENSE 的项目、只做参考但体积巨大的
   （如 `MetaCubeX/mihomo`）。理由逐条写在 [../docs/UPSTREAM.md](../docs/UPSTREAM.md)。

---

## 许可兼容性

| 仓库 | 自身许可 | 引入的上游 | 是否兼容 |
| --- | --- | --- | --- |
| `ZcodeAIModels` | MIT | Apache-2.0（ZCode）、MIT（ZCodium） | ✅ 兼容 —— Apache-2.0 允许再分发进 MIT 项目，要求保留版权声明与 NOTICE（本目录保留了上游 LICENSE 全文） |

> 对比：兄弟仓 `ShellcrashRules` 整仓是 **GPL-3.0**，因为它含 ShellCrash 的 GPL-3.0 派生件，
> 无法用「自研 MIT + 派生 GPL」拆开。**本仓没有这个问题。**

---

## 没 vendor 但值得知道的项目

完整的调研清单（14 个项目，含 URL / SHA / license / 本仓关系）见
[../docs/UPSTREAM.md](../docs/UPSTREAM.md)。
