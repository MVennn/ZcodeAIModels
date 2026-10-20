# ZCodium-project/ZCodium —— 来源凭证

> **一句话**：本目录是 ZCodium（ZCode 的 **MIT 授权**独立审计 fork）内置思考规则的
> **最小切片**，外加一个本仓自己写的漂移检查脚本。

---

## 1. 上游

| 项 | 值 |
| --- | --- |
| 仓库 | `ZCodium-project/ZCodium` |
| URL | <https://github.com/ZCodium-project/ZCodium> |
| 许可 | **MIT** |
| 抄录时的 commit | `192f9b8c7b7b61c694920203f1b5c7524bdc7d09` |
| 上游路径 | `config/provider/zcode-builtin.json` |
| 上游 revision | 32 |

**ZCodium 是什么**：ZCode 的独立安全审计 fork —— 删掉了全部监控与遥测、把厂商服务默认关闭，
并从公开源码重建。**它带的是 ZCode 的完整开源代码**，所以 `config/provider/zcode-builtin.json`
是 MIT 授权的、可自由再分发的同源文件。

## 2. 包含哪些文件

| 本地文件 | 性质 | 说明 |
| --- | --- | --- |
| `zcode-builtin-reasoning-rules.json` | **逐字抄录**（上游原件） | ZCodium 内置规则里与「思考参数」有关的 4 条最小切片，文件头带 `_source`（URL + SHA + license + 版权声明）与 `_cross_check`（与官方仓的交叉验证） |
| `reasoning-rules.js` | **本仓自己写** | 两个子命令：`map`（按协议只发该协议认的思考字段）、`check`（把本机 ZCode 内置规则与上面那份切片逐条比对，报漂移） |

> `reasoning-rules.js` 借鉴的是**思路**，代码是本仓原创；文件头已注明来源与借鉴对象
> （协议→字段映射借鉴 `soulvon/AnyBridge`，表达式写法对齐 ZCode 内置规则）。

## 3. 为什么留这份切片

本仓踩过的最大一个坑是：**ZCode 内置的通用规则会无条件往请求体里塞思考字段**
（`thinking` + `enable_thinking` + `reasoning_effort` + `reasoning` 四个一起发），
导致不支持这些字段的供应商返回 400。

在那之前，这个结论只是"实测反推"出来的；有了这份切片，它变成了**可引用的源码依据** ——
文件里直接能看到那三条通用规则的表达式原文。

**交叉验证**：切片来自 ZCodium（revision 32），而官方 `zai-org/ZCode`（revision 33）的
**同三条通用规则逐字一致** —— 也就是说这份切片对官方客户端同样成立。
（本次已实测确认，见 `_cross_check` 字段。）

## 4. 怎么用

```bash
# 按协议算「最小且正确」的思考字段
node third-party/zcodium/reasoning-rules.js map --api-type=openai-chat-completions --effort=high

# 检测本机 ZCode 的内置规则是否与上游切片漂移
node third-party/zcodium/reasoning-rules.js check
```

`check` 的 builtin 查找顺序：`ZCODE_BUILTIN` 环境变量 → 本机 ZCode 运行时
（`~/.zcode/v2/runtime/provider/<平台>/<版本>/<端点>/zcode-builtin.json`，取最新）
→ 桌面版安装目录 → 仓内 vendor 的官方版本（`../zcode/zcode-builtin.json`）。

**`check` 报「存在漂移」时**：内置的思考规则变了，按
[../../docs/PITFALLS.md](../../docs/PITFALLS.md) §2 重新实测思考参数矩阵。

## 5. 怎么更新

```bash
SHA=192f9b8c7b7b61c694920203f1b5c7524bdc7d09   # 换成新的 commit
curl -sSL "https://raw.githubusercontent.com/ZCodium-project/ZCodium/$SHA/config/provider/zcode-builtin.json" \
  -o /tmp/zcodium-builtin.json
# 从中重新摘出思考参数相关的切片，并更新 _source.sha / _source.sourceRevision
```

## 6. 许可

MIT —— 可自由再分发，只需保留版权声明与许可全文。本目录的切片文件头已带
`Copyright (c) 2026 ZCodium contributors` 与 `_source.license`。
