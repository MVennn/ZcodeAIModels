#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同步报告：对比上一次快照，写出本次模型清单的变化，并可选提交推送。

用法：
    python tools/sync_report.py                      # 只打印摘要（dry run）
    python tools/sync_report.py --write              # 写报告 + 更新索引 + 存快照
    python tools/sync_report.py --write --push       # 再 git add/commit/push

状态文件默认 `~/.zcode/v2/model-sync-state.json`，记录上一轮的
「显示名 → 分组 / 最低价 / 链路」。第一次运行没有状态时写一份基线报告。

自动化里放在最后一步（model_alias.py --apply 之后）：
    python tools/sync_report.py --write --push
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "docs" / "reports"
INDEX_NAME = "README.md"
REPO_URL = "https://github.com/MVennn/ZcodeAIModels/blob/main/docs/reports"


def config_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("ZCODE_PERSONAL_PROVIDER_CONFIG_FILE")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "provider_config.json"


def alias_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("UNIFIED_MODEL_MAP")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zcode" / "v2" / "model-alias-map.json"


def state_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / ".zcode" / "v2" / "model-sync-state.json"


def load_groups(cfg_path: Path) -> dict[str, str]:
    """显示名 → 组名（主力 / 免费 / 低耗 / 高耗）。"""
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    rules = (((cfg.get("config") or {}).get("providerConfigRules") or {}).get("providerRules") or [])
    for rule in rules:
        name = str(rule.get("providerName") or "")
        for model in (rule.get("config") or {}).get("personalModelIds") or []:
            out[str(model)] = name
    return out


def snapshot(alias_file: Path, cfg_path: Path) -> dict:
    data = json.loads(alias_file.read_text(encoding="utf-8"))
    groups = load_groups(cfg_path)
    models: dict[str, dict] = {}
    for name, entry in (data.get("models") or {}).items():
        chain = entry.get("chain") or []
        if chain:
            hops = [f"{h.get('channel')}:{h.get('upstream')}@{h.get('price')}" for h in chain]
        else:
            hops = [f"{entry.get('channel')}:{entry.get('upstream')}@{entry.get('price')}"]
        models[name] = {
            "group": groups.get(name, entry.get("group") or ""),
            "price": entry.get("price"),
            "chain": hops,
        }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "alias_generated_at": data.get("generated_at"),
        "models": models,
    }


def diff(previous: dict, current: dict) -> dict:
    old = previous.get("models") or {}
    new = current.get("models") or {}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    group_changed = []
    chain_changed = []
    for name in sorted(set(new) & set(old)):
        if new[name].get("group") != old[name].get("group"):
            group_changed.append((name, old[name].get("group"), new[name].get("group")))
        if new[name].get("chain") != old[name].get("chain"):
            chain_changed.append((name, old[name].get("chain"), new[name].get("chain")))
    return {
        "added": added,
        "removed": removed,
        "group_changed": group_changed,
        "chain_changed": chain_changed,
    }


def render_report(current: dict, changes: dict, baseline: bool) -> str:
    models = current["models"]
    groups = ("主力", "免费", "低耗", "高耗")
    counts = {g: sum(1 for m in models.values() if m.get("group") == g) for g in groups}
    stamp = current["generated_at"]
    added = 0 if baseline else len(changes["added"])
    removed = 0 if baseline else len(changes["removed"])

    lines = [
        f"# 模型同步报告 {stamp[:16]}",
        "",
        f"> **一句话**：本次自动化后的模型清单 —— 共 {len(models)} 个，"
        f"新增 {added}、移除 {removed}、"
        f"分组变化 {len(changes['group_changed'])}、链路变化 {len(changes['chain_changed'])}"
        + ("（首次运行，作为基线）" if baseline else "") + "。",
        "",
        "## 概览",
        "",
        "| 组 | 数量 |",
        "|---|---|",
    ]
    for group in groups:
        lines.append(f"| {group} | {counts[group]} |")
    lines += ["", f"生成时间：{stamp}；alias map：{current.get('alias_generated_at') or '-'}", ""]

    if baseline:
        lines += ["## 基线", "", "首次生成，没有上一轮快照可比；当前清单见文末。", ""]
    else:
        lines += ["## 新增", ""]
        if changes["added"]:
            lines += ["| 名称 | 组 | 最低价 |", "|---|---|---|"]
            for name in changes["added"]:
                entry = models[name]
                lines.append(f"| `{name}` | {entry.get('group')} | {entry.get('price')} |")
        else:
            lines.append("（无）")
        lines += ["", "## 移除", ""]
        lines += [f"- `{name}`" for name in changes["removed"]] or ["（无）"]
        lines += ["", "## 分组变化", ""]
        if changes["group_changed"]:
            lines += ["| 名称 | 原分组 | 新分组 |", "|---|---|---|"]
            for name, before, after in changes["group_changed"]:
                lines.append(f"| `{name}` | {before} | {after} |")
        else:
            lines.append("（无）")
        lines += ["", "## 链路变化", ""]
        if changes["chain_changed"]:
            for name, before, after in changes["chain_changed"]:
                lines.append(f"- `{name}`")
                lines.append(f"  - 原：{' → '.join(before or ['-'])}")
                lines.append(f"  - 新：{' → '.join(after or ['-'])}")
        else:
            lines.append("（无）")
        lines.append("")

    lines += ["## 当前清单", "", "| 名称 | 组 | 最低价 | 链路（按尝试顺序） |", "|---|---|---|---|"]
    for name in sorted(models):
        entry = models[name]
        chain = " → ".join(entry.get("chain") or [])
        lines.append(f"| `{name}` | {entry.get('group')} | {entry.get('price')} | {chain} |")
    lines.append("")
    return "\n".join(lines)


def update_index(report_name: str, current: dict, changes: dict, baseline: bool) -> None:
    index = REPORT_DIR / INDEX_NAME
    if index.exists():
        text = index.read_text(encoding="utf-8")
    else:
        text = (
            "# 模型同步报告索引\n\n"
            "> **一句话**：每次自动化结束后的模型清单快照与变化记录，最新的在最上面。\n\n"
            "| 时间 | 报告 | 总数 | 新增 | 移除 |\n|---|---|---|---|---|\n"
        )
    row = (
        f"| {current['generated_at'][:16]} | [{report_name}]({report_name}) | "
        f"{len(current['models'])} | {0 if baseline else len(changes['added'])} | "
        f"{0 if baseline else len(changes['removed'])} |\n"
    )
    header, _, rest = text.partition("|---|---|---|---|---|\n")
    if not rest:
        text = text.rstrip() + "\n" + row
    else:
        text = header + "|---|---|---|---|---|\n" + row + rest
    index.write_text(text, encoding="utf-8")


def git_push(report_name: str, out_dir: Path = REPORT_DIR) -> int:
    def run(args: list[str]) -> int:
        proc = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip(), file=sys.stderr)
        return proc.returncode

    # Commit the directory the report was actually written to: with
    # --out-dir the fixed "docs/reports" add staged nothing and git reported
    # "nothing to commit" as success.
    try:
        rel_dir = out_dir.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        print(f"报告目录 {out_dir} 不在仓库内，无法自动提交", file=sys.stderr)
        return 1
    if run(["git", "add", rel_dir]) != 0:
        return 1
    if run(["git", "commit", "-m", f"docs(reports): 模型同步报告 {report_name}"]) != 0:
        # Nothing to commit is not a failure for the automation.
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True)
        if status.stdout.strip():
            return 1
        print("没有需要提交的变更")
        return 0
    return run(["git", "push", "origin", "HEAD"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="写报告、更新索引并保存快照")
    parser.add_argument("--push", action="store_true", help="写完以后 git add/commit/push（需要 --write）")
    parser.add_argument("--config", help="provider_config.json 路径")
    parser.add_argument("--alias-map", help="model-alias-map.json 路径")
    parser.add_argument("--state", help="上一轮快照路径（默认 ~/.zcode/v2/model-sync-state.json）")
    parser.add_argument("--out-dir", help="报告目录（默认 docs/reports）")
    args = parser.parse_args()

    current = snapshot(alias_path(args.alias_map), config_path(args.config))
    spath = state_path(args.state)
    baseline = not spath.exists()
    previous = {} if baseline else json.loads(spath.read_text(encoding="utf-8"))
    changes = diff(previous, current)

    print(f"模型 {len(current['models'])} 个"
          f"（主力 {sum(1 for m in current['models'].values() if m['group'] == '主力')} / "
          f"免费 {sum(1 for m in current['models'].values() if m['group'] == '免费')} / "
          f"低耗 {sum(1 for m in current['models'].values() if m['group'] == '低耗')} / "
          f"高耗 {sum(1 for m in current['models'].values() if m['group'] == '高耗')}）")
    if baseline:
        print("首次运行：本次作为基线，没有可比的变化")
    else:
        print(f"新增 {len(changes['added'])}：{', '.join(changes['added']) or '无'}")
        print(f"移除 {len(changes['removed'])}：{', '.join(changes['removed']) or '无'}")
        for name, before, after in changes["group_changed"]:
            print(f"分组变化：{name} {before} → {after}")
        print(f"链路变化 {len(changes['chain_changed'])}：{', '.join(n for n, _, _ in changes['chain_changed']) or '无'}")

    if not args.write:
        print("dry run；加 --write 生成报告并保存快照")
        return 0

    out_dir = Path(args.out_dir).expanduser() if args.out_dir else REPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"MODEL-SYNC-{datetime.now().strftime('%Y%m%d-%H%M')}.md"
    (out_dir / name).write_text(render_report(current, changes, baseline), encoding="utf-8")
    if out_dir == REPORT_DIR:
        update_index(name, current, changes, baseline)
    spath.parent.mkdir(parents=True, exist_ok=True)
    spath.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {out_dir / name}")

    if args.push:
        code = git_push(name, out_dir)
        print("已推送" if code == 0 else "推送失败（见上面的 git 输出）")
        return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
