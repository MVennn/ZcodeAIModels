#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档自检：相对链接、锚点、孤文档、一句话引言块。

用法：
    python tools/check-docs.py            # 检查全仓（跳过 third-party/、gateways/upstream/ 等不入库目录）
    python tools/check-docs.py docs/      # 只检查指定子目录

退出码：0 全部通过 / 1 有问题。
这是本仓 docs/DOC-RULES.md 里那几条规则的**可执行版本** —— 规则写在文档里，
但要在 CI 里真能拦住人，就得有个脚本。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", "third-party", "memories", "evidence",
            # .work/ 是本地工作区（.gitignore 排除），里面的草稿不参与版本库文档检查
            ".work", ".codegraph",
            # .workbuddy/ 是 IDE 本地 agent 工作区（.gitignore 排除），不是版本库文档
            ".workbuddy",
            # vault/ 被 .gitignore 排除，不属于版本库里的文档
            "vault"}
# 整目录被 .gitignore 排除的上游 clone（运行时含凭据与二进制，不套活文档规则）
SKIP_REL_PREFIXES = ("gateways/upstream/",)
# 冻结目录：归档 / 拆分记录是**历史**，不套用活文档的规则（引言块、孤儿判定）
FROZEN_DIRS = ("docs/archive/", "docs/split/", "archive/")
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".mrs", ".gz", ".pyc", ".woff", ".woff2"}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HAS_ONE_LINER = re.compile(r"一句话")
EXAMPLE = re.compile(r"^文档名\.md#")


def slugify(title: str) -> str:
    s = title.strip().lower()
    s = re.sub(r"[^\w\s一-鿿-]", "", s)
    return re.sub(r"\s+", "-", s)


def collect(dirs):
    mds = []
    for d in dirs:
        base = os.path.normpath(os.path.join(ROOT, d)) if not os.path.isabs(d) else os.path.normpath(d)
        if os.path.isfile(base):
            mds.append(os.path.normpath(base))
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [x for x in dn if x not in SKIP_DIRS]
            for f in fn:
                if not f.endswith(".md"):
                    continue
                norm = os.path.normpath(os.path.join(dp, f))
                rel = os.path.relpath(norm, ROOT).replace(os.sep, "/")
                if rel.startswith(SKIP_REL_PREFIXES):
                    continue
                if any(rel.startswith(fd) or fd in rel for fd in FROZEN_DIRS):
                    continue
                mds.append(norm)
    return sorted(set(mds))


def anchors_of(path: str) -> set[str]:
    try:
        s = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return set()
    a = set(re.findall(r'<a\s+id="([^"]+)"', s))
    a |= {slugify(t) for t in re.findall(r"^#{1,6}\s+(.*)$", s, re.M)}
    return a


def main() -> int:
    targets = sys.argv[1:] or ["."]
    mds = collect(targets)
    if not mds:
        print("没有找到 .md 文件")
        return 1
    anchor_map = {m: anchors_of(m) for m in mds}
    problems: list[str] = []
    linked: set[str] = set()

    for m in mds:
        try:
            s = open(m, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        rel = os.path.relpath(m, ROOT).replace(os.sep, "/")
        for link in LINK.findall(s):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            if link.startswith("#"):
                if link[1:] and link[1:] not in anchor_map[m]:
                    problems.append(f"{rel}: 锚点不存在 → {link}")
                continue
            if EXAMPLE.match(link):
                continue  # 文档规则里的格式示例（形如 文档名.md#锚点）
            path, _, frag = link.partition("#")
            target = os.path.normpath(os.path.join(os.path.dirname(m), path))
            if not os.path.exists(target):
                problems.append(f"{rel}: 链接目标不存在 → {link}")
                continue
            linked.add(os.path.abspath(target))
            # 链接指向**目录**时，目录下的文档也算被引用（索引里常见 `archive/` 这种写法）
            if os.path.isdir(target):
                for dp2, dn2, fn2 in os.walk(target):
                    for f2 in fn2:
                        if f2.endswith(".md"):
                            linked.add(os.path.abspath(os.path.join(dp2, f2)))
            # 目标文件存在但没被收集（被 SKIP/FROZEN 排除，或只检查了子目录）时
            # anchor_map 里没有它，不能据此判"锚点不存在"。
            if (frag and target.endswith(".md")
                    and target in anchor_map
                    and frag not in anchor_map[target]):
                problems.append(f"{rel}: 目标锚点不存在 → {link}")
        # 根 README 是面向用户的门面（对齐系列仓 gsauxiliary 的格式），不套文档引言块规则
        if (not HAS_ONE_LINER.search(s)
                and rel != "README.md"
                and rel != "docs/DOC-RULES.md"
                and not rel.startswith("docs/release-notes/")):
            problems.append(f"{rel}: 开头缺少「一句话」引言块")

    for m in mds:
        rel = os.path.relpath(m, ROOT).replace(os.sep, "/")
        if rel.startswith("docs/") and os.path.abspath(m) not in linked and rel != "docs/README.md":
            problems.append(f"{rel}: 孤儿文档 —— 没有被任何文档引用（也未进 docs/README.md 索引）")

    if problems:
        print(f"✗ {len(problems)} 个问题：")
        for p in problems:
            print("   ", p)
        return 1
    print(f"✓ {len(mds)} 篇文档全部通过（链接 / 锚点 / 引言块 / 孤儿）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
