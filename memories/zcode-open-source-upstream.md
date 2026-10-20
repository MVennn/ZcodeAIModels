---
name: zcode-open-source-upstream
description: ZCode 已开源在 zai-org/ZCode（Apache-2.0）——内置思考规则的源码依据、vendor 位置、以及几个关键坑
metadata:
  node_type: memory
  type: reference
  originSessionId: session_6db242bc883a5098369e896d6f8234cb
---

**ZCode 官方开源仓：`zai-org/ZCode`**（★8028，Apache-2.0，TypeScript，2026-09-21 智谱开源，主页 <https://zcode.z.ai/>）。
社区审计 fork：**`ZCodium-project/ZCodium`**（★238，MIT，删掉全部遥测，含完整源码）。

**最有价值的一份文件**：`config/provider/zcode-builtin.json`（180 KB，revision 33）——
ZCode 内置的 83 条 model 规则 / 73 条 model-api 规则 / 54 条 provider-site 规则 /
248 条 template 规则 / 30 条精确 provider 规则。

**本仓踩过的最大坑，在这里有源码依据**：内置通用规则（`apiTypeMatch=openai-chat-completions`、
`modelMatch: ".*"`）会**无条件**往请求体里塞 `thinking` + `enable_thinking` +
`reasoning_effort` + `reasoning` 四个字段 → 不认这些字段的供应商直接 400。
ZCodium（revision 32）的同三条规则**逐字一致**。

**规则引擎语义**（照 `packages/provider/src/config/` 三份源码读出来的，别再从闭源 bundle 反推）：
- 遍历顺序（`schema.ts` 的 `parseZCodeBuiltinModelConfigRules`）：
  `model → model-api → provider-site → template-model → provider-model`
- 匹配是**全匹配**正则 `^(?:pattern)$`，`modelMatch` 忽略大小写（`matchesRule`）
- 合并语义 `overlayValue(base,next) = next===undefined ? base : next`（后者胜、undefined 不清空、null 清空、数组整体替换）
- `apiTypeMatch` **缺省时对所有 api type 生效**（provider-site 里有 4 条这样）
- `map` 表达式的作用域只有 `reasoningLevel` 与 `maxOutputTokens` 两个自由变量

**已 vendor 进 `zcode-ai-models/third-party/zcode/`**（4 个原样文件 + Apache-2.0 LICENSE）。

**三个坑**：
1. ZCode 桌面版装在 `AppData/Local/Programs/@opencodedesktop`（**@ 前缀**），
   不是 `Programs/ZCode` —— 旧脚本的默认路径一直是坏的。
   真正的运行时规则文件在 `~/.zcode/v2/runtime/provider/<平台>/<版本>/<端点>/zcode-builtin.json`。
2. **Windows 上 `git clone` 再复制会被 `core.autocrlf` 转成 CRLF** —— vendor 的上游文件
   "看起来没改"其实每个字节都不同。要拿原始 blob 就用
   `https://codeload.github.com/<owner>/<repo>/tar.gz/<sha>`（服务端无转换），
   或 `git -c core.autocrlf=false archive`。CRLF 的上游 shell 脚本拷到路由器会直接报错。
3. `mihomo` 的许可是 **MIT**（`Copyright 2023 KT`），不是 GPL-3.0；
   `jucase/ShellCrash` **不存在**，真实上游是 `juewuy/ShellCrash`；
   `ACL4SSR` 是 **CC BY-SA 4.0**（→ GPL-3.0 单向兼容，但 share-alike 独立生效）。

参见 [[openwrt-repos-final-state]]、[[workbuddy-proxy-zcode]]、[[opencode-go-zcode-models]]。
