# zgate 无窗产物的构建与守护

> **一句话**：zgate 必须按 GUI 子系统编译（`-H windowsgui`），构建入口只有
> `gateways/zgate/build.py`；别在 `gateways/zgate/` 里裸跑单包 `go build .` ——
> 它会把无窗版原地覆盖成控制台版，开机弹 cmd 窗口。

## 结论

| 事实 | 说明 |
|---|---|
| 无窗与否取决于 PE 头的 `Subsystem` | `2` = WINDOWS_GUI（无窗，设计要求）；`3` = CONSOLE（一启动就分配控制台窗口） |
| `-H windowsgui` 只在链接期生效 | 事后无法从源码判断，只能读产物 PE 头 → 所以编译后必须当场校验 |
| 回退真凶是**单包** `go build .` | 实测：`go build ./...`（多包）只编译不落盘、**不会**覆盖；`go build .`（单包）会原地覆盖 |
| 产物在 `.gitignore` 里 | `/gateways/zgate/*.exe` → 被覆盖后 **`git checkout` 救不回来**，只能带 flag 重编 |
| 快捷方式 `WindowStyle = 7` 不管用 | 「最小化」只对有窗口的程序有效，对控制台子系统程序**不等于隐藏** |
| 唯一构建入口 | `python gateways/zgate/build.py`（带 flag + 强制校验）；`--check` 只校验；`--cross-check` 交叉编译校验（Linux CI 上也生效，因为 `-H` 是 windows 链接器 flag） |

## agent 会话里起 zgate：只有 explorer 拉起能活

Windows **Job Object 会在 agent 会话结束时回收整棵进程树**。
实测 `nohup` / `setsid` / `Start-Process` 起的 zgate 都会随会话消失；
日志里表现为 `已启动` 之后**连「已退出」都没有**（被强杀，不是自己退的）。

活下来的办法：**用 explorer 拉起启动文件夹快捷方式**，父进程是 `explorer.exe`，
与登录自启同一条路径：

```
Start-Process explorer.exe -ArgumentList '"<启动文件夹>\ZcodeAIModels zgate.lnk"'
```

长期驻留靠**登录自启快捷方式**（`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`），
不要靠 agent 起的进程。

## 排错速查

```bash
# 产物是不是无窗版
python gateways/zgate/build.py --check

# 服务在不在
curl -s http://127.0.0.1:7871/health
gateways/zgate/zgate.exe status

# 有没有多余的控制台窗口
Get-Process conhost | Where-Object { $_.MainWindowTitle }
```

机制见 `docs/PITFALLS.md` §20，排错步骤见 `docs/TROUBLESHOOTING.md` §16，
构建命令正本见 `docs/MAINTENANCE.md` §8.1。
