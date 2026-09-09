# -*- coding: utf-8 -*-
"""临时脚本：把镜02首尾帧复制到共享池 input/02_分镜/第1集，供LoadImage校验读取。"""
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

SRC1 = r"D:\Comfy-Desktop\ComfyUI-Shared\output\02_分镜\第1集"      # 无!目录（含复制的镜02首尾帧）
SRC2 = r"D:\Comfy-Desktop\ComfyUI-Shared\output\!02_分镜\第1集"     # 有!目录（原始）
DST = r"D:\Comfy-Desktop\ComfyUI-Shared\input\02_分镜\第1集"
FILES = [
    "第1集_镜02_首帧_写实CG融合_00001_.png",
    "第1集_镜02_尾帧_写实CG融合_00001_.png",
]


def main():
    os.makedirs(DST, exist_ok=True)
    for f in FILES:
        dst = os.path.join(DST, f)
        if os.path.exists(dst):
            print("[已存在] %s" % f)
            continue
        # 先从 无! 目录找，再从 有! 目录找
        src = os.path.join(SRC1, f)
        if not os.path.exists(src):
            src = os.path.join(SRC2, f)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print("复制: %s -> %s" % (f, DST))
        else:
            print("源不存在: %s" % f)
    print("完成。目标目录当前文件:")
    for f in sorted(os.listdir(DST)):
        print("   ", f)


if __name__ == "__main__":
    main()
