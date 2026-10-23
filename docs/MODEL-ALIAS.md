# 统一模型命名与四组

> **一句话**：ZCode 的模型 ID 统一为 `渠道/积分/型号`（如 `W/0.03/DeepSeek-41-Fs`），所有模型只落「主力 / 免费 / 低耗 / 高耗」四组；`tools/model_alias.py` 生成配置与 alias map，`tools/unified-router.js` 按 map 还原上游模型名。

---

## 1. 为什么需要 alias map

显示名为了可读性丢掉了原始 model id（`W/0.03/DeepSeek-41-Fs` 里没有
`global:deepseek-v4.1-flash-sg`），路由无法从缩写反推上游。因此同步脚本同时写两份：

| 文件 | 作用 |
|---|---|
| `~/.zcode/v2/provider_config.json` | ZCode 看到的四个 provider 与 36 个显示名 |
| `~/.zcode/v2/model-alias-map.json` | 显示名 → `{channel, upstream, base, protocol, main_reason}`；路由读它 |

alias map **不含凭据**；上游 key 仍由路由按渠道从 `provider_config.json` /
`workbuddy/gateway/config.json` / `qoder/.env.local` 读取。

---

## 2. 显示名格式

```
<渠道>/<积分>/<型号>
```

| 渠道 | 字母 | 内部地区（不显示） | 示例 |
|---|---|---|---|
| `WB` WorkBuddy | `W` | `CN` / `GB` | `W/0.03/DeepSeek-41-Fs`、`W/0.00/DeepSeek-41-Fs` |
| `OC` OpenCode-Go | `O` | 无 | `O/0.11/DeepSeek-41-Fs`、`O/0.09/Claude-Haiku-55` |
| `QD` Qoder | `Q` | `CN` | `Q/0.00/DeepSeek-4-Fs`（谷价）、`Q/0.69/GLM-53` |

型号用紧凑可读名：去掉版本里的 `V` 和点，`Flash` 缩写为 `Fs`。

| 原模型 | 显示名 |
|---|---|
| `deepseek-v4.1-flash` | `DeepSeek-41-Fs` |
| `deepseek-v4-flash` / `deepseek-flash` | `DeepSeek-4-Fs` |
| `qwen3.8-flash` | `Qwen-38-Fs` |
| `glm-5.3-flash` | `GLM-53-Fs` |
| `minimax-m3.1-flash` | `MiniMax-M31-Fs` |
| `mimo-v2.6-pro` | `MiMo-26-Pro` |
| `claude-haiku-5-5` | `Claude-Haiku-55` |
| `kimi-k2.8-preview` | `Kimi-K28-Pre` |

系列前缀保持可读：`DeepSeek`、`Qwen`、`GLM`、`MiniMax`、`Kimi`、`HY`、`MiMo`、
`LongCat`、`Beam`、`Claude`、`GPT`、`Muse`、`Step`、`Space`。
变体只保留模型本身有意义的：`Fs`=Flash、`Pre`=Preview、`Pro`、`Max`、`Plus`、`Vision`。
**不再编码 `-f` / `-sg` / `-free`**：免费或促销只看积分。
价格两位小数，免费 = `0.00`；三段用 `/` 分隔，不再有空格。

**WorkBuddy 的 CN/GB 已合并成一个 `W` 口子**：GB 优先，GB 全部不可用时
路由自动回退 CN。同价 CN/GB 对合并成一个条目；GB 的免费价档和付费价档各自保留
（例如 `W/0.00/DeepSeek-41-Fs` 和 `W/0.03/DeepSeek-41-Fs`）。
显示的是 GB 主价，回退 CN 时实际扣费可能更高。

---

## 3. 积分换算

WorkBuddy 的 `eff_rate` 是基准（1 积分 = 它的 1 倍率）。

| 渠道 | 公式 | 依据 |
|---|---|---|
| WB | 原样 | `wb_pricing.json` 的 `eff_rate` |
| OC | `混合 $/M ÷ 3.409` | 锚点 `deepseek-v4.1-flash` $0.15 入 / $0.60 出 ↔ 0.11，1:1 混合 |
| QD | `price_factor × 0.86` | 同名模型与 WB 比值中位数（GLM-5.3 0.862、GLM-5.3-Flash 0.80、MiniMax-M3.1-Flash 0.80、Kimi-K2.8 0.963、DeepSeek-V4-Pro 1.02） |

示例：`O/0.10/GLM-53-Fs`、`O/0.06/MiMo-26-Fs`、`O/0.09/Qwen-38-Fs`、
`Q/0.43/Qwen-38-Max`、`Q/0.69/GLM-53`。
换算值是**估算**，不是上游账单；价格变了显示名会跟着变。

---

## 4. 四组规则

| 组 | 规则 |
|---|---|
| 主力 `opencode-go-chat` | 人工精选 + 榜单扩充：`MAIN_IDS`（W/O 的 `DeepSeek-41-Fs`、O 的 `Qwen-38-Fs`、O 的 `MiMo-26-Pro`）+ `arena-main.json` 里通过「DeepSeek 基准 + 价格上限」的模型（§4.2） |
| 免费 `opencode-go-chat-free` | 积分 = 0.00（峰谷价下模型会随当前时段进出此组） |
| 低耗 `opencode-go-chat-fast` | 0 < 积分 ≤ 0.16 |
| 高耗 `opencode-go-chat-slow` | 积分 > 0.16，不设上限 |

原来的 `备用` 组按积分并入高耗；`对话` / `响应` 两个协议组已折进四组，由
`tools/protocol_bridge.js` 做 chat ↔ messages/responses 转换。

**组内排序**：渠道 `WB → OC → QD`；每个渠道内 `DeepSeek` 永远最前；
同渠道按公司（DeepSeek、Qwen、GLM、MiniMax、Kimi、HY、MiMo、LongCat、Beam、Claude、GPT、
Muse、Step、Space），最后按积分升序。

---

### 4.1 峰谷价（早晚不同）

`model_alias.py` 支持 `--slot auto|peak|offpeak`：

- `auto`：Qoder 按 `price_factor_peak` / `price_factor_valley` 和 `off_peak`
  窗口（22:00–08:00，Asia/Shanghai）取当前价；WorkBuddy 用价格表里的 `eff_rate`
  （由 `workbuddy_fetch_pricing.py` 在时段边界刷新）。
- OpenCode-Go：**只有 DeepSeek V4.1 Flash / V4 Pro** 有峰谷价。峰时是 UTC
  周一至周五 01:00–04:00、06:00–10:00（北京时间 09:00–12:00、14:00–18:00），
  其余时间（含夜间和周末）为谷价；其他 OC 模型是固定价。
- `peak` / `offpeak`：显式取峰价 / 谷价，适合手动预演。

例：Qoder 的 `DeepSeek-4-Fs` 峰价显示 `Q/0.09/DeepSeek-4-Fs`，谷价变
`Q/0.00/DeepSeek-4-Fs`；`Qwen-38-Max` 峰 `Q/0.43/Qwen-38-Max`、谷 `Q/0.17/Qwen-38-Max`。
OC：`DeepSeek-41-Fs` 峰 `O/0.22/DeepSeek-41-Fs` / 谷 `O/0.11/DeepSeek-41-Fs`；
`DeepSeek-4-Pro` 峰 `O/0.77/DeepSeek-4-Pro` / 谷 `O/0.39/DeepSeek-4-Pro`。
谷价时模型可能从低耗挪进免费组。

自动切换的做法（北京时间）：每天 **08:00 / 22:00**，外加**工作日 09:00 / 12:00 /
14:00 / 18:00**（OC 峰谷边界）各跑一次：

```bash
python workbuddy/workbuddy_fetch_pricing.py
python tools/model_alias.py --slot auto --apply
```

- 显示名里的积分会变，模型 ID 也随之变；alias map 的 `legacy` 会让旧 ID 继续可路由。
- ZCode 约 1 秒热加载新列表；已选中的旧 ID 仍能发请求，但模型选择器里要重新点一次新名字。
- 不想改名的话，也可以不做定时重写，只在需要时手动 `--slot peak|offpeak --apply`。

### 4.2 主力扩充（外部榜单）

主力有两个人选来源：

1. **人工**：`model_alias.py` 里的 `MAIN_IDS`，按厂商/额度/协议挑，不随榜单变；
2. **榜单**：`tools/arena_leaderboard.py` 拉 ArenaGalleri 实时榜，按
   「分数 ≥ DeepSeek 基准 95%、积分 ≤ 0.11、非临时、≥50 局、积分 > 0」筛出候选，
   写 `~/.zcode/v2/arena-main.json`；`model_alias.py` 默认读它，命中
   `(channel, upstream)` 就放进主力。

```bash
python tools/arena_leaderboard.py --refresh --apply   # 重拉 + 落候选 + 重写四组
python tools/arena_leaderboard.py --status            # 看当前候选
python tools/model_alias.py --no-arena --apply        # 回到纯人工主力
```

- 榜单口径、名字映射与 2026-10-23 的候选表见 [BENCHMARKS.md](BENCHMARKS.md) §8。
- **免费模型不进主力**（积分 = 0 留在免费组）；榜单掉出窗口的模型退回原积分组。
- 榜单每 10 分钟更新，但只有候选集合或规则变化才重写配置；分数波动不会引起 ID 抖动。
- 候选按谷价/eff/valley 判断，峰时切价不会改变主力成员。

## 5. 协议桥接

`tools/protocol_bridge.js` 把 chat 请求转成：

- Anthropic Messages（`/v1/messages`，`x-api-key` + `anthropic-version`）
- OpenAI Responses（`/v1/responses`，Bearer）

上游用**非流式**调用，桥接器再合成 chat SSE。工具调用会双向转换
（`tools` / `tool_calls` / `tool_use` / `function_call`）。
代价：桥接模型的首字不是逐 token 到达，而是整段返回；chat 模型仍是原生流式。

---

## 6. 生成与探测

```bash
# 0. 重拉外部榜单，更新主力候选（候选没变时不会触发重写）
python tools/arena_leaderboard.py --refresh --write

# 1. 用真实 ZCode body 探测四组模型（经 7871，按 provider 套用 optionSpecs）
python tools/model_probe.py

# 2. 生成四组 + alias map；只保留探测 ok（或曾 ok 的瞬时限流）的模型
python tools/model_alias.py --slot auto --probe-file ~/.zcode/v2/model_probe.json --apply
```

- 只预演：去掉 `--apply`。
- 备份：`provider_config.json.bak-alias-<时间戳>`。
- 旧 ID（`cn:` / `global:` / `qoder:` / bare OC）会进 alias map 的 `legacy`，
  老会话仍可路由；价格变化时旧显示名也会映射到新显示名。
- 旧的 `workbuddy_zcode_sync.py` / `go_model_sync.py` / `qoder_zcode_sync.py`
  现在只当**数据采集器**：它们写旧 ID，随后由 `model_alias.py` 归一化。不要
  在 `model_alias.py` 之后单独跑它们的 `--apply`，否则会临时把旧 ID 写回去。

---

## 7. 已知边界

- 价格写进 ID：上游调价/峰谷切换会改显示名；老会话靠 legacy map 继续可用。
- 峰谷重写按 §4.1 的时段跑；不跑则积分停在最后一次生成的时段。
- `no_healthy_account`（WorkBuddy 池冷却）按瞬时限流处理，不删模型。
- `deepseek-v4-flash-vision-exp`、`minimax-m2.7` 没有公布价格，暂不收录。
- 桥接模型非流式上游；如果以后需要逐 token，再补 SSE 增量转换。
- 别名表是本地活数据，不入库；`provider_config.json` 与备份同样不入库。
- 榜单接口不可用时用本地缓存；缓存也没有就跳过扩充，人工 `MAIN_IDS` 仍生效。
  榜单名对不上的模型（`qwen3.8-flash`、`minimax-m3.1-flash`）保持人工分组。

---

## 8. 相关

- 价格 / 协议来源：[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)
- 外部榜单与主力扩充口径：[BENCHMARKS.md](BENCHMARKS.md) §8
- 工具清单：[TOOLS.md](TOOLS.md)
- 日常维护：[MAINTENANCE.md](MAINTENANCE.md)
- Qoder 专用链路：[QODER.md](QODER.md)
