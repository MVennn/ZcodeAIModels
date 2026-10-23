# 统一模型命名与四组

> **一句话**：模型 ID 只用型号名（如 `DeepSeek-4.1-Fs`），同一型号跨渠道合并成一条
> 按价格升序的链路；四组按「免费 / 低于 DeepSeek 基准价 / 高于」划分，主力另由人工 + 榜单决定。

---

## 1. 为什么需要 alias map

显示名不再带渠道和积分，路由无法从名字反推上游（`DeepSeek-4.1-Fs` 对应四个渠道的
四个上游 id）。因此同步脚本同时写两份：

| 文件 | 作用 |
|---|---|
| `~/.zcode/v2/provider_config.json` | ZCode 看到的四个 provider 与显示名列表 |
| `~/.zcode/v2/model-alias-map.json` | 显示名 → `{protocol, price, chain:[{channel, upstream, base, price}], group}`；路由读它 |

`chain` 是**有序链路**：路由从第一跳开始试，遇到 429 / 502 / 503 / 504 或
`400 model_unavailable` 就换下一跳。每一跳自带 `base`，所以一条链路可以横跨
WorkBuddy（7863）、Qoder（8790）和 OpenCode-Go（远程）。

alias map **不含凭据**；上游 key 仍由路由按渠道从 `provider_config.json` /
`gateways/upstream/workbuddy/config.json` / `providers/qoder/.env.local` 读取。

---

## 2. 显示名格式

```
<型号>
```

例：`DeepSeek-4.1-Fs`、`GLM-5.3-Fs`、`Qwen-3.8-Max`、`Claude-Haiku-5.5`。

- **不再带渠道**（原 `W/` `O/` `Q/`）**和积分**（原 `/0.03/`）。
- 版本号保留点号（`4.1` / `3.8` / `2.6` / `5.3`），`Flash` 与 `Preview` 不再缩写（`DeepSeek-4.1-Flash`、`HY4-Pre`）。
- 系列前缀保持可读：`DeepSeek`、`Qwen`、`GLM`、`MiniMax`、`Kimi`、`HY`、`MiMo`、
  `LongCat`、`Beam`、`Claude`、`GPT`、`Muse`、`Step`、`Space`。
- 变体只保留模型本身有意义的：`Flash`、`Pre`=Preview、`Pro`、`Max`、`Plus`、`Vision`。

**同名冲突的两种处理：**

| 情况 | 做法 |
|---|---|
| 同型号既有免费档又有付费档 | 免费那条单独成条，名字加 `-Free`（如 `HY3-Free`、`HY4-Pre-Free`、`DeepSeek-4-Flash-Free`）；付费那条用原名 |
| 同名但协议不同（chat / messages / responses） | 桥接那条加 `-Msg` / `-Resp`（目前没有触发） |

`deepseek-v4.1-flash` 是唯一例外：免费档**并入**付费条目并放在链路第一跳，见 §3。

---

## 3. 跨渠道合并（chain）

同一型号、同一协议的所有渠道按**价格升序**排成一条链路；同价时 GB 优先于 CN，
CN 优先于其它渠道。以 DeepSeek 为例：

```
DeepSeek-4.1-Fs
  1. WB  global:deepseek-v4.1-flash      0.00   ← 免费，优先
  2. WB  global:deepseek-v4.1-flash-sg   0.03
  3. WB  cn:deepseek-v4.1-flash          0.11
  4. OC  deepseek-v4.1-flash             0.11
```

- 实际扣费看命中哪一跳；显示名不再体现价格。
- `MERGE_FREE_GB`（当前只有 `deepseek-v4.1-flash`）：免费档不单独成条，直接作为
  付费条目的第一跳。其它型号的免费档仍然单独成条（`-Free`）。
- 合并键是「型号 + 协议」，所以 chat 与 messages/responses 不会混在一条链路里。
- 生成器**幂等**：链路会写回 alias map 的 `chain`，下一次运行从 `chain` 还原全部跳，
  不会因为配置里只剩一个条目而丢掉其它渠道。

---

## 4. 四组规则

| 组 | 规则 |
|---|---|
| 主力 `opencode-go-chat` | `MAIN_IDS`（人工）+ `arena-main.json`（榜单）；命中任意一跳即进主力。DeepSeek 固定第一 |
| 免费 `opencode-go-chat-free` | 整条链路价格 = 0（免费档单独成条，带 `-Free`） |
| 低耗 `opencode-go-chat-fast` | `0 < 最低跳价格 ≤ 0.11`（DeepSeek 的 OC 价，即基准价） |
| 高耗 `opencode-go-chat-slow` | 最低跳价格 > 0.11，不设上限 |

- **主力优先于价格分组**：模型在 `MAIN_IDS` 或榜单候选里就进主力，不看价格。
- **组内排序**：DeepSeek 永远最前；其余按厂商（DeepSeek、Qwen、GLM、MiniMax、Kimi、
  HY、MiMo、LongCat、Beam、Claude、GPT、Muse、Step、Space），再按最低价升序。
- 分档基准是**固定常数 0.11**（`LOW_MAX`），不随峰谷价漂移。

### 4.1 峰谷价（早晚不同）

`model_alias.py` 支持 `--slot auto|peak|offpeak`：

- `auto`：Qoder 按 `price_factor_peak` / `price_factor_valley` 和 `off_peak`
  窗口（22:00–08:00，Asia/Shanghai）取当前价；WorkBuddy 用价格表里的 `eff_rate`
  （由 `workbuddy_fetch_pricing.py` 在时段边界刷新）。
- OpenCode-Go：**只有 DeepSeek V4.1 Flash / V4 Pro** 有峰谷价。峰时是 UTC
  周一至周五 01:00–04:00、06:00–10:00（北京时间 09:00–12:00、14:00–18:00），
  其余时间（含夜间和周末）为谷价；其他 OC 模型是固定价。
- `peak` / `offpeak`：显式取峰价 / 谷价，适合手动预演。

**名字不再随价格变化**：峰谷切换只会改变链路顺序、最低价和分组归属
（例如 Qoder 的 DeepSeek-Flash 谷价时进免费组、峰价时并进付费链路），
不会改显示名，老会话不受影响。

自动切换的做法（北京时间）：每天 **08:00 / 22:00**，外加**工作日 09:00 / 12:00 /
14:00 / 18:00**（OC 峰谷边界）各跑一次：

```bash
python providers/workbuddy/workbuddy_fetch_pricing.py
python tools/model_alias.py --slot auto --apply
```

### 4.2 主力扩充（外部榜单）

主力有两个人选来源：

1. **人工**：`model_alias.py` 里的 `MAIN_IDS`，按厂商/额度/协议挑，不随榜单变；
2. **榜单**：`tools/arena_leaderboard.py` 拉 ArenaGalleri 实时榜，按
   「分数 ≥ DeepSeek 基准 95%、积分 ≤ 0.11、非临时、≥50 局、积分 > 0」筛出候选，
   写 `~/.zcode/v2/arena-main.json`；`model_alias.py` 默认读它，任意一跳命中
   `(channel, upstream)` 就放进主力。

```bash
python tools/arena_leaderboard.py --refresh --apply   # 重拉 + 落候选 + 重写四组
python tools/arena_leaderboard.py --status            # 看当前候选
python tools/model_alias.py --no-arena --apply        # 回到纯人工主力
```

- 榜单口径、名字映射与 2026-10-23 的候选表见 [BENCHMARKS.md](BENCHMARKS.md) §8。
- **免费条目不进主力**（价格 = 0 留在免费组）；榜单掉出窗口的模型退回价格分组。
- 榜单每 10 分钟更新，但只有候选集合或规则变化才重写配置；分数波动不会引起 ID 抖动。
- 候选按谷价/eff/valley 判断，峰时切价不会改变主力成员。

## 5. 协议桥接

`gateways/zgate` 内置协议桥（原 `tools/protocol_bridge.js` 已退役），把 chat 请求转成：

- Anthropic Messages（`/v1/messages`，`x-api-key` + `anthropic-version`）
- OpenAI Responses（`/v1/responses`，Bearer）

上游用**非流式**调用，桥接器再合成 chat SSE。工具调用会双向转换
（`tools` / `tool_calls` / `tool_use` / `function_call`）。
代价：桥接模型的首字不是逐 token 到达，而是整段返回；chat 模型仍是原生流式。
链路里的桥接跳失败（5xx / 429 / 503）会自动换下一跳。

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
- 旧 ID（`cn:` / `global:` / `qoder:` / 裸 OC，以及旧的 `W/0.03/…` 显示名）会进
  alias map 的 `legacy`，老会话仍可路由；改名链会自动追到最终名字。
- 旧的 `workbuddy_zcode_sync.py` / `go_model_sync.py` / `qoder_zcode_sync.py`
  现在只当**数据采集器**：它们写旧 ID，随后由 `model_alias.py` 归一化。不要
  在 `model_alias.py` 之后单独跑它们的 `--apply`，否则会临时把旧 ID 写回去。

---

## 7. 已知边界

- 价格不进 ID 后，**改名只发生在型号/版本变化时**；峰谷切换只影响分组归属。
- 峰谷重写按 §4.1 的时段跑；不跑则分组停在最后一次生成的时段。
- `no_healthy_account` / `400 model_unavailable`（WorkBuddy 池冷却或模型级限流）
  会触发下一跳；没有下一跳时才报 502。
- `deepseek-v4-flash-vision-exp`、`minimax-m2.7` 没有公布价格，暂不收录。
- 桥接模型非流式上游；如果以后需要逐 token，再补 SSE 增量转换。
- 别名表是本地活数据，不入库；`provider_config.json` 与备份同样不入库。
- 榜单接口不可用时用本地缓存；缓存也没有就跳过扩充，人工 `MAIN_IDS` 仍生效。
- 同名不同协议的条目靠 `-Msg` / `-Resp` 区分；同名免费条目靠 `-Free` 区分。

---

## 8. 相关

- 价格 / 协议来源：[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md)
- 外部榜单与主力扩充口径：[BENCHMARKS.md](BENCHMARKS.md) §8
- 工具清单：[TOOLS.md](TOOLS.md)
- 日常维护：[MAINTENANCE.md](MAINTENANCE.md)
- Qoder 专用链路：[QODER.md](QODER.md)
