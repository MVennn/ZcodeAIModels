# 参与贡献

> **一句话**：怎么跑、改代码守什么规矩、提交前跑什么。

## 跑起来

```bash
python3 providers/opencode-go/ops/go_model_sync.py            # 干跑（默认不写配置）
python3 providers/opencode-go/ops/go_model_sync.py --apply     # 真写
node providers/opencode-go/ops/opencode-header-proxy.js       # 常驻的请求头注入代理
```

统一入口 `gateways/zgate` 是 Go 代码，改完这样验：

```bash
cd gateways/zgate
gofmt -l . && go vet ./... && go test ./...   # 单元测试（不联网）
go build -o zgate.exe .
./zgate.exe status                             # 看服务/子进程/端口
python smoke_test.py                           # 四条通道各打一发（会花少量额度）
```

凭据一律走环境变量：

| 变量 | 用途 |
|---|---|
| `OPENCODE_GO_KEY` | OpenCode-Go 的 API key |
| `WB_GATEWAY_KEY` | WorkBuddy 网关的 api_key |
| `WB_GATEWAY_BASE` | 网关地址（默认 `http://127.0.0.1:7863`） |
| `WB_PRICING_FILE` / `WB_ZCODE_PROBE_FILE` | 价格表 / 探测缓存路径 |
| `ZCODE_BUILTIN` | ZCode 内置规则文件路径 |
| `GO_SYNC_REPORT_DIR` | 同步报告输出目录 |

## 加一个新供应商

**不要**把新供应商的代码塞进 `providers/workbuddy/` 或 `providers/opencode-go/`。照着现有结构新建一份，
四步（详见 [docs/MODEL-PROVIDERS.md](docs/MODEL-PROVIDERS.md) §0）：

1. 摸清它的**接口面** —— 模型清单在哪、价格怎么取、鉴权怎么带；
2. **归一化**成统一的字段（`id` / `eff_rate` / `ctx` / `out` / `tool` / `img` / `efforts`）；
3. 用 **ZCode 的真实请求体**探测哪些模型真能用（两条铁律见 `docs/PITFALLS.md`）；
4. 按成本档写进 `provider_config.json`。

**不用改**的是 ZCode 侧的三处落点与 `reasoningLevel.map` 的覆盖机制。

## 硬规矩

- **凭据只走环境变量。** 代码、文档、日志、缓存里都不许出现明文 key。
- **探测要有间隔。** 详见 `docs/MAINTENANCE.md`。
- 改 `providers/workbuddy/zcode_effective_body.js` 时要**对着上游源码**核对语义 ——
  ZCode 已开源（Apache-2.0），vendored 副本在 `third-party/zcode/`，
  规则遍历顺序与合并语义见 `third-party/zcode/UPSTREAM.md`。
- 不要改 `third-party/`（vendored 上游）。

## 文档

规则见 [docs/DOC-RULES.md](docs/DOC-RULES.md)。改完跑：

```bash
python3 tools/check-docs.py
```

## 提交前自检

```bash
python3 -c "import ast,glob; [ast.parse(open(f,encoding='utf-8').read(), f) for f in glob.glob('**/*.py', recursive=True)]"
for f in $(find . -name '*.js' -not -path './third-party/*'); do node --check "$f"; done
python3 tools/check-docs.py
```

## 提交信息

Conventional Commits；**按对象拆行**，不要打包成"代码整理"。
