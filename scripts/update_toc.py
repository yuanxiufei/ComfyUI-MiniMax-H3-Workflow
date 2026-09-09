# -*- coding: utf-8 -*-
"""按章节动态生成目录：扫描 Markdown 文件里的所有「## 二级标题」，
自动重写「## 目录」区块，让目录始终与章节同步，无需手写维护。

锚点规则复刻 GitHub 风格：
  - 标题整体转小写（ASCII 部分）；
  - 去掉所有标点（、 ： （ ） / 等，中文字符保留）；
  - 空格替换为「-」。

用法:
  python scripts/update_toc.py            # 直接重写方案文档目录
  python scripts/update_toc.py --check    # 只对比，不写文件
  python scripts/update_toc.py --file 路径/某.md
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DEFAULT_MD = os.path.join(ROOT, "小说转短剧视频生产方案（H3固定方案）.md")


def slugify(title: str) -> str:
    """生成 GitHub 风格锚点。"""
    s = title.lower()
    kept = "".join(ch for ch in s if ch.isalnum() or ch in (" ", "-"))
    return kept.replace(" ", "-")


def collect_headings(text: str):
    """按出现顺序返回所有二级标题文本（排除「目录」本身）。"""
    headings = []
    for line in text.splitlines():
        if line.startswith("## "):
            title = line[3:].strip()
            if title == "目录":
                continue
            headings.append(title)
    return headings


def build_toc_lines(headings):
    """生成目录区块的行列表（含「## 目录」标题与首尾空行）。"""
    out = ["## 目录", ""]
    for title in headings:
        out.append("- [%s](#%s)" % (title, slugify(title)))
    out.append("")
    return out


def extract_current_toc(lines):
    """定位现有目录区块：从「## 目录」到其后第一个「---」，返回 (start, end)。"""
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "## 目录":
            start = i
            break
    if start is None:
        raise SystemExit("未找到「## 目录」标题，无法定位目录区块")
    end = None
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == "---":
            end = j
            break
    if end is None:
        raise SystemExit("「## 目录」之后未找到 --- 分隔线")
    return start, end


def update(text: str) -> str:
    headings = collect_headings(text)
    lines = text.split("\n")
    start, end = extract_current_toc(lines)
    new_lines = lines[:start] + build_toc_lines(headings) + lines[end:]
    return "\n".join(new_lines)


def main():
    parser = argparse.ArgumentParser(description="按章节动态生成目录")
    parser.add_argument("--file", default=DEFAULT_MD, help="目标 Markdown 文件")
    parser.add_argument("--check", action="store_true", help="只对比不写入")
    args = parser.parse_args()

    path = args.file
    if not os.path.isfile(path):
        raise SystemExit("文件不存在: %s" % path)

    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    headings = collect_headings(text)
    new_text = update(text)

    if args.check:
        if new_text == text:
            print("目录已是最新，共 %d 个章节。" % len(headings))
        else:
            print("目录与章节不同步，共 %d 个章节，需要运行脚本重写。" % len(headings))
        return

    if new_text == text:
        print("目录已是最新，共 %d 个章节，无需改动。" % len(headings))
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)
    print("已重写目录，共 %d 个章节。" % len(headings))


if __name__ == "__main__":
    main()
