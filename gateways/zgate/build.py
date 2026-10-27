#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建 zgate，并校验产物是 GUI 子系统（Windows 上零窗口）。

用法：
    python gateways/zgate/build.py              # 构建（Windows: 产物 zgate.exe）+ 校验 PE 子系统
    python gateways/zgate/build.py --check      # 只校验现有 gateways/zgate/zgate.exe，不编译
    python gateways/zgate/build.py --cross-check# 交叉编译一份 windows/amd64 到临时目录并校验（CI 用，可在 Linux 上跑）

为什么需要这个脚本：
    `go build ./...` 会把 main 包的可执行文件**写到当前目录**，静默覆盖掉
    按 GUI 子系统编译的 zgate.exe —— 登录自启就会弹出一个 cmd 控制台窗口，
    关掉那个窗口等于杀掉网关。`-H windowsgui` 只在链接期生效，事后无法从
    源码判断，只能校验产物的 PE 头。所以：编译入口收口到这里，并强制校验。

    仓库里的等价物：
      - 正本构建命令：docs/MAINTENANCE.md §8.1
      - 机制解释：    docs/PITFALLS.md §20
      - 排错步骤：    docs/TROUBLESHOOTING.md §13

退出码：0 通过 / 1 失败。
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile

# 本脚本位于 <repo>/gateways/zgate/，仓库根要上溯两层
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZDIR = os.path.join(ROOT, "gateways", "zgate")
EXE = os.path.join(ZDIR, "zgate.exe")

# PE Subsystem 取值
SUBSYSTEM_CONSOLE = 3
SUBSYSTEM_WINDOWS_GUI = 2
SUBSYSTEM_NAMES = {
    2: "WINDOWS_GUI（无窗）",
    3: "CONSOLE（控制台，会弹窗）",
}

# 链接期 flag：把产物切成 GUI 子系统，Windows 启动时不分配控制台窗口
WINDOWSGUI_LDFLAGS = "-H windowsgui"


def read_subsystem(path: str) -> int:
    """读 PE 头的 Subsystem 字段。返回 2=GUI / 3=CONSOLE。"""
    with open(path, "rb") as fh:
        head = fh.read(0x1000)
    if head[:2] != b"MZ":
        raise ValueError(f"不是合法的 PE 文件：{path}")
    pe_off = struct.unpack_from("<I", head, 0x3C)[0]
    if head[pe_off:pe_off + 4] != b"PE\x00\x00":
        raise ValueError(f"PE 签名缺失：{path}")
    # Optional Header 从 PE+24 开始，Subsystem 在其中偏移 0x44
    return struct.unpack_from("<H", head, pe_off + 24 + 0x44)[0]


def check_subsystem(path: str) -> int:
    """校验产物是 GUI 子系统。不合格返回 1。"""
    try:
        sub = read_subsystem(path)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    name = SUBSYSTEM_NAMES.get(sub, f"未知({sub})")
    if sub == SUBSYSTEM_WINDOWS_GUI:
        print(f"[ OK ] Subsystem = {sub} → {name}    {path}")
        return 0
    print(f"[FAIL] Subsystem = {sub} → {name}    {path}")
    print(f"       这个产物一启动就会分配控制台窗口。"
          f"用 `python gateways/zgate/build.py` 重新构建，"
          f"别裸跑 `go build ./...`。")
    return 1


def run(cmd: list[str], cwd: str, env: dict | None = None) -> int:
    print("  $ " + " ".join(cmd))
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(cmd, cwd=cwd, env=full_env)
    return proc.returncode


def build_native() -> int:
    """在 Windows 上构建 zgate.exe（带 windowsgui flag）并校验。"""
    if sys.platform != "win32":
        print("[SKIP] 本机不是 Windows，跳过原生构建（CI 用 --cross-check）。")
        return 0
    if os.path.exists(EXE):
        print(f"[INFO] 目标已存在：{EXE}")
        print("       若 zgate 正在运行，Windows 会锁住文件导致覆盖失败 ——")
        print("       先停掉 zgate（zgate 没有 stop 子命令：Stop-Process -Id <pid> -Force），")
        print("       或直接用 --check 只校验不编译。")
    rc = run(["go", "build", "-C", "gateways/zgate", "-ldflags", WINDOWSGUI_LDFLAGS,
              "-o", "zgate.exe", "."], cwd=ROOT)
    if rc != 0:
        print(f"[FAIL] go build 退出码 {rc}")
        return 1
    return check_subsystem(EXE)


def build_cross_check() -> int:
    """交叉编译 windows/amd64 到临时目录并校验 PE 子系统。

    `-H windowsgui` 是 windows 链接器的 flag，交叉编译到 windows 目标时同样生效，
    所以这套校验在 Linux CI 上也能真跑起来（而不是只在本机生效）。
    """
    with tempfile.TemporaryDirectory(prefix="zgate-cross-") as tmp:
        out = os.path.join(tmp, "zgate.exe")
        rc = run(["go", "build", "-C", "gateways/zgate", "-ldflags", WINDOWSGUI_LDFLAGS,
                  "-o", out, "."], cwd=ROOT,
                 env={"GOOS": "windows", "GOARCH": "amd64"})
        if rc != 0:
            print(f"[FAIL] 交叉编译退出码 {rc}")
            return 1
        return check_subsystem(out)


def main() -> int:
    if not os.path.isdir(ZDIR):
        print(f"[FAIL] 找不到 {ZDIR}")
        return 1
    if "--cross-check" in sys.argv:
        print("== 交叉编译 windows/amd64 并校验 PE 子系统 ==")
        return build_cross_check()
    if "--check" in sys.argv:
        print("== 校验现有产物 ==")
        if not os.path.exists(EXE):
            print(f"[FAIL] 不存在 {EXE}")
            return 1
        return check_subsystem(EXE)
    print("== 构建 zgate ==")
    return build_native()


if __name__ == "__main__":
    sys.exit(main())
