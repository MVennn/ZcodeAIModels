# Qoder（qoder2api-hub）

> **一句话**：Qoder 由 qoder2api-hub 反代（`127.0.0.1:8790`）接入，模型以 `Q/积分/型号` 显示并并入四组（主力/免费/低耗/高耗），经 `127.0.0.1:7871` 的 alias map 分流；WorkBuddy2API 与 OpenCode-Go 不动。
>
> **2026-10-23 起**：下文 §4 的 `qoder:` 前缀与独立 provider 是上一版合并模式；
> 当前命名/分组以 [MODEL-ALIAS.md](MODEL-ALIAS.md) 为准。统一探测/写入用
> `tools/model_probe.py` + `tools/model_alias.py`；`qoder_probe_zcode.py` /
> `qoder_zcode_sync.py` 仅作数据采集与兼容。

---

## 1. 为什么是独立适配器

本仓的接法是「每个上游一个专用反代 + ZCode provider」：

| 上游 | 适配器 | 端口 | 在 ZCode 里的形态 |
|---|---|---|---|
| OpenCode-Go | 直连 / 统一路由 | — / 7871 | 四组（主力/免费/低耗/高耗） |
| WorkBuddy | WorkBuddy2API Panel | 7863 | 模型并入四组（经 7871） |
| Qoder | **qoder2api-hub** | **8790** | 并入四组（`Q/积分/型号`，alias map） |

Qoder 走 7871：显示名是 `Q/积分/型号`，alias map 还原上游模型并转给 8790；
旧的 `qoder:` 前缀只作为 legacy 回退。ZCode 的 provider 列表是四组，Qoder 只作为
模型出现在主力/免费/低耗/高耗里。Agent2API 也评估过（多合一网关，功能更全），但它的
`/v1/models` 只吐 `credits`、不吐 Qoder 的 `price_factor` / 思考档位，且会把
组合层吃进一个大项目里，与「加一个上游 = 加一个适配器」的目标相反。

上游项目：[shuishuipingan/qoder2api-hub](https://github.com/shuishuipingan/qoder2api-hub)
（MIT，Python 3.9+，零第三方依赖）。本机 clone 在 `qoder/gateway/`，整目录被
`.gitignore` 排除（与 `workbuddy/gateway/` 同一模式）。

---

## 2. 进程、端口与数据

| 项 | 值 |
|---|---|
| 网关 | `http://127.0.0.1:8790/v1`（OpenAI Chat Completions） |
| 看板 | `http://127.0.0.1:8790/` |
| 面板密码 | 存在 `qoder/gateway/accounts/settings.json`（PBKDF2 摘要） |
| API Key | 存在同一份 `settings.json`；合并模式下由 7871 路由从 `qoder/.env.local` 的 `QD_API_KEY` 读 |
| 账号 | `qoder/gateway/accounts/*.json`（含 token，绝不入库） |
| 用量 | `qoder/gateway/usage/` |
| 日志 | `qoder/gateway/qoder-proxy.log` / `qoder-proxy.err.log` |
| 启动 | `qoder/gateway/start-qoder-proxy.bat`（detached，关窗口不退出） |
| 停止 | `qoder/gateway/stop-qoder-proxy.bat`（按 PID，只停 `qoder_proxy.py`） |
| 健康 | `GET http://127.0.0.1:8790/ping`、`GET /health` |

API Key 与面板密码已持久化到 `accounts/settings.json`，所以 `.bat` 不需要
额外参数即可用同一把 Key 重启。`qoder/.env.local` 只给同步/探测脚本读，
也在 `.gitignore` 里。

当前没有把 Qoder 接进 `workbuddy/zcode_gateway_watch.ps1`：它是常驻进程，
不随 ZCode 起停。这样 09:00 / 21:00 的签到在 ZCode 没开时也会跑；如果以后
想让它跟随 ZCode，再把 `start-qoder-proxy.bat` 加进守护器即可。

---

## 3. 账号与签到

- 当前已入库一个 **CN 账号**（`qoder.com.cn`，`personal_professional_trial`），
  通过看板「添加账号 (OAuth)」的设备授权流程加入。
- 新增账号：看板 → 账号 → `+ 添加账号 (OAuth)`；国内版/国际版各自一张卡片。
  接口是 `POST /accounts/login/start`（`realm=cn|intl`）→ 浏览器授权 →
  `GET /accounts/login/poll?state=…`。
- 账号的 OAuth 设备流凭据 30 天有效，到期前网关会自动续期；续不动时看板会
  标 `session dead`，重新授权一次即可。
- 签到排程默认 **09:00 / 21:00**，Token 保活 **22:00**，状态在
  `qoder/gateway/accounts/scheduler/state.json`。
- 签到所需的 UMID 组件已用 `python _install_umid.py` 提取到
  `qoder/gateway/umid/`（`runtime-info.exe` + `sgsdk.dll`）。2026-10-23 16:56
  的启动巡检已成功领取 **+100 Credits**，余额 399。
- 国际版签到按设备去重（每台机器每天只有一个国际版账号能领）；国内版按账号。

---

## 4. ZCode provider

`qoder/qoder_zcode_sync.py` 默认是**合并模式**：不创建独立 provider，把模型加
`qoder:` 前缀后写入现有三个 chat 组：

| `price_factor` | 目标 provider | 显示组 |
|---|---|---|
| `0` | `opencode-go-chat-free` | 免费 |
| `0 < x ≤ 0.2` | `opencode-go-chat-fast` | 低耗 |
| `> 0.2` | `opencode-go-chat-slow` | 高耗 |

`--separate` 才写独立的 `qoder` provider（旧模式，bare model id）。

当前收录 7 个模型（按 `price_factor` 从免费到贵排序）：

| 模型（旧 `qoder:` / 现 `Q/积分/型号`） | price_factor | 落到 | 思考档位 | 备注 |
|---|---:|---|---|---|
| `DeepSeek-Flash` | 0.0 | 免费 | low/high/max | 免费；平时 1.1s，排队时 64s 后 200，也可能 90s+ 后 502（10605） |
| `GLM-5.3-Flash` | 0.1 | 低耗 | high/max | |
| `MiniMax-M3.1-Flash` | 0.1 | 低耗 | — | |
| `DeepSeek-V4-Pro` | 0.5 | 高耗 | high/max | |
| `Qwen3.8-Max` | 0.5 | 高耗 | low/medium/xhigh | 错峰 4 折 |
| `GLM-5.3` | 0.8 | 高耗 | low/high/max | |
| `Kimi-K2.8-Preview` | 0.8 | 高耗 | low/high/max | |

排除项：

- `Auto` / `Fast`：Qoder 的路由别名，没有自身价格（同 WorkBuddy 的 `cn:auto` 规则）。
- `Kimi-K3`：price_factor 1.4，超过同步脚本默认上限 0.8。
- `Qwen3.8-Flash`：免费，但 2026-10-23 探测时上游 **10605 排队**
  （queueCount ≈ 19k，p3），75s 超时，按「跑不通即清」暂时移出。等它复通后，
  重新探测 + 同步会自动加回。

**排队/超时不误杀已跑通的模型**：探测结果带 `ever_ok`。一个曾经返回 200 的模型
遇到 `queued` / `timeout` / `rate_limited` 时，`--probe-file` 仍保留它；只有
**从未成功过**的模型（如当前的 Qwen3.8-Flash）才会因为排队被挡在配置外。免费
`DeepSeek-Flash` 也会排队（实测 64s 后 200，也可能 90s+ 后 502），交互场景可以先用
付费的低价档（`GLM-5.3-Flash` / `MiniMax-M3.1-Flash`，1–2s）。

**思考参数**：7 个模型用 ZCode 原生四件套（`thinking` + `enable_thinking` +
`reasoning_effort` + `reasoning`）探测全部 HTTP 200，因此**没有配任何
`optionSpecs.reasoningLevel.map` 覆写**。思考字段矩阵见
[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4.9、§5.2。

---

## 5. 日常维护

> 统一四组的日常维护是 `tools/model_probe.py` → `tools/model_alias.py --probe-file … --apply`
> （见 [MODEL-ALIAS.md](MODEL-ALIAS.md) §6）。下面的 Qoder 专用命令只用于采集/兼容。

```bash
# 1. 看当前目录与价格（dry run，不写）
python qoder/qoder_zcode_sync.py

# 2. 用 ZCode 真实 body 探测（写入 qoder/qoder_probe.json）
python qoder/qoder_probe_zcode.py

# 3. 只保留探测 ok 的模型并写入（先备份）
python qoder/qoder_zcode_sync.py --probe-file qoder/qoder_probe.json --apply

# 单独重试排队的免费模型（例如晚上队列空了）
python qoder/qoder_probe_zcode.py --only Qwen3.8-Flash --timeout 180
python qoder/qoder_zcode_sync.py --probe-file qoder/qoder_probe.json --apply
```

默认是合并模式：写入现有四组，不建独立 provider；`--separate` 才写
独立的 `qoder` provider。probe 默认经 7871 + `qoder:` 前缀（与 ZCode 实际路径
一致），`--direct` 才直连 8790。

- `--apply` 前会生成 `provider_config.json.bak-qoder-merge-<时间戳>`（separate
  模式是 `.bak-qoder-<时间戳>`）；回退步骤见
  [MAINTENANCE.md](MAINTENANCE.md) §4。
- 同步脚本默认 `--max-price 0.8`；要收 Kimi-K3 用 `--max-price 1.4`，要全收用
  `--max-price 0`。
- 写配置期间不要在 ZCode 的 provider 设置界面同时保存（界面会整份写回，
  覆盖脚本结果；机制见 [PITFALLS.md](PITFALLS.md) §8）。
- ZCode 约 1 秒热加载 `provider_config.json`，写完用 `ListModels` 或模型选择器
  确认即可，不需要重启。

升级 qoder2api-hub：

```bash
git -C qoder/gateway pull --ff-only
# 然后 stop-qoder-proxy.bat → start-qoder-proxy.bat
```

升级后先看 `/health`（版本、账号数、`identity_cached`），再跑一轮探测/同步；
上游改了模型目录时，`/v1/models` 会自动反映，同步脚本会按新清单重写 provider。

---

## 6. 边界与风险

- Qoder 没有面向第三方客户端的通用 OpenAI 兼容 API；本仓用的是 qoder2api-hub
  对官方客户端 OAuth 设备流的复用。账号风控/条款风险自担，只接自己的账号。
- 国内版与国际版是两套账号、两套目录，凭证不通用；当前只接了 CN。
- Qoder 的模型目录是**动态**的，还会出现 `Auto` / `Fast` 这类别名；不要把
  「目录里出现」当成「可以收录」，一律先过 `qoder_probe_zcode.py`。
- Qoder 与 WorkBuddy 是两套账号池，不要用同一个 Qoder 账号再起第二个网关；
  也不要把 Qoder 的 token 塞进 WorkBuddy2API。
- 合并模式下 Qoder 模型在四组里，必须保证 7871 路由在跑；Qoder hub
  常驻、router 随 ZCode 起停（见 [MAINTENANCE.md](MAINTENANCE.md) §8.1）。
- 本仓不把 `qoder/gateway/`、`qoder/.env.local`、`qoder/qoder_probe.json`、
  `accounts/` 下的任何文件入库。

---

## 7. 相关

- Provider/模型矩阵：[MODEL-PROVIDERS.md](MODEL-PROVIDERS.md) §4.9、§5.2
- 脚本清单：[TOOLS.md](TOOLS.md)
- 凭据位置：[SECRETS.md](SECRETS.md)
- 排错：[TROUBLESHOOTING.md](TROUBLESHOOTING.md) 的 Qoder 段
- 进度：[../PROGRESS.md](../PROGRESS.md) 2026-10-23 批次
