# ZcodeAIModels —— 记忆索引

> **一句话**：把 AI 模型供应商接进 ZCode（OpenCode-Go 探测与同步 / WorkBuddy2API 网关 / 思考参数矩阵）。
>
> 仓库路径：本仓库根目录（`ZcodeAIModels/`，实际路径以 git remote 为准）
> 记忆文件一条一件事，**只记非看代码/读文档就能知道的结论**；
> 交叉引用用 `[[记忆名]]`。

- [answer-first-preference](answer-first-preference.md) — 用户提问时直接给结论/表格即可，不要为了“更稳”继续跑探测或做多余操作
- [beam-free-daily-quota](beam-free-daily-quota.md) — beam-free 2026-10-20 报 429 是上游免费池日配额打满（每日 00:00 UTC 重置），不是配置/弃用/地区问题
- [beam-free-thinking-param-fix](beam-free-thinking-param-fix.md) — beam-free 在 ZCode 里 400 的根因是内置通用 reasoningLevel map 无条件发 thinking
- [opencode-go-zcode-models](opencode-go-zcode-models.md) — OpenCode Go 订阅的模型价格/额度、协议归属（chat/messages/responses）、ZCode provider
- [workbuddy-proxy-zcode](workbuddy-proxy-zcode.md) — WorkBuddy2API 反代接入 ZCode：免代/低代/高代 三组按积分倍率分层，含账号类型限制与 ZCode 真实 body 探测法
- [zcode-open-source-upstream](zcode-open-source-upstream.md) — ZCode 已开源在 zai-org/ZCode（Apache-2.0）——内置思考规则的源码依据、vendor 位置、以及几个关键坑
- [zcode-ui-ordering-preferences](zcode-ui-ordering-preferences.md) — 用户对模型/策略组列表的命名与排序偏好：自建标签用两字中文、不加 emoji、常用的排最前、模型按厂商分组
- [zgate-windowless-build](zgate-windowless-build.md) — zgate 必须按 GUI 子系统编译（PE `Subsystem`=2）；构建入口只有 `gateways/zgate/build.py`，别裸跑单包 `go build .`（会覆盖成控制台版）；agent 会话里起 zgate 只有 explorer 拉起能活

共 8 条。新增记忆时：一条一文件，文件名用 kebab-case；
写完把上面索引补一行。
