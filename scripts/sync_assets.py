# -*- coding: utf-8 -*-
"""资产回拷同步器 —— 把 ComfyUI output/ 里生成好的素材/成片回拷到项目 output/ 统一管理。

背景：视频链（pipeline_video.py）提交到 ComfyUI 后，成片与素材默认落在
`<ComfyUI根>/output/<子目录>/`（00_角色素材 / 01_场景素材 / 02_分镜 / 视频）。
本脚本按增量方式回拷到项目 `output/`，用作备份与统一归档，补齐"生成→回拷"这段
原本靠人工的操作。

用法:
  python scripts/sync_assets.py --comfy-root D:\\Comfy-Desktop\\ComfyUI-Shared --dry-run   # 只列出待拷
  python scripts/sync_assets.py --comfy-root D:\\Comfy-Desktop\\ComfyUI-Shared             # 增量回拷
  python scripts/sync_assets.py --comfy-root ... --only 00_角色素材,02_分镜                  # 只同步这些子目录
"""
import argparse
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PROJ_OUT = os.path.join(ROOT, "output")

DEFAULT_COMFY_ROOT = r"D:\Comfy-Desktop\ComfyUI-Shared"
# 需要回拷的子目录（与 pipeline_video / episode_status 的落盘约定一致）
SUBDIRS = ["00_角色素材", "01_场景素材", "02_分镜", "视频"]


def _mirror(src, dst, dry):
    """递归镜像 src -> dst，仅复制 缺失或大小不一致 的文件（增量）。返回 (copied, skipped)。"""
    copied = skipped = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = os.path.join(dst, rel) if rel != "." else dst
        for f in files:
            s = os.path.join(root, f)
            t = os.path.join(target_root, f)
            if os.path.isfile(t) and os.path.getsize(t) == os.path.getsize(s):
                skipped += 1
                continue
            copied += 1
            if not dry:
                os.makedirs(target_root, exist_ok=True)
                shutil.copy2(s, t)
    return copied, skipped


def main(argv=None):
    p = argparse.ArgumentParser(description="ComfyUI output -> 项目 output 资产增量回拷")
    p.add_argument("--comfy-root", default=DEFAULT_COMFY_ROOT, help="ComfyUI 根目录")
    p.add_argument("--dry-run", action="store_true", help="只列出待同步文件，不实际拷贝")
    p.add_argument("--only", default=None, help="逗号分隔子目录（默认全部 SUBDIRS）")
    args = p.parse_args(argv)

    src_root = os.path.join(args.comfy_root, "output")
    if not os.path.isdir(src_root):
        print(f"[!] 找不到 ComfyUI output: {src_root}")
        return 1

    subs = [s.strip() for s in (args.only or ",".join(SUBDIRS)).split(",") if s.strip()]
    total_c = total_s = 0
    for sub in subs:
        src = os.path.join(src_root, sub)
        if not os.path.isdir(src):
            print(f"  [skip] {sub}: 源目录不存在 {src}")
            continue
        dst = os.path.join(PROJ_OUT, sub)
        c, s = _mirror(src, dst, args.dry_run)
        total_c += c
        total_s += s
        state = "预览" if args.dry_run else "回拷"
        print(f"  [{state}] {sub}: 待同步/已同步 {c}，跳过(一致) {s}")
    print(f"\n合计: {'将同步' if args.dry_run else '已回拷'} {total_c} 个文件，跳过 {total_s} 个。"
          f"目标 {PROJ_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
