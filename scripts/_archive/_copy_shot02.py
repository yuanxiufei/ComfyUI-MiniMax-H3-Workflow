# -*- coding: utf-8 -*-
"""临时脚本：把镜02首尾帧从 !02_分镜 复制到 02_分镜（去掉!前缀），供LoadImage读取。"""
import os
import shutil
import sys

sys.stdout.reconfigure(encoding="utf-8")

SHARED = r"D:\Comfy-Desktop\ComfyUI-Shared\output"
SRC_DIR = os.path.join(SHARED, "!02_分镜", "第1集")
DST_DIR = os.path.join(SHARED, "02_分镜", "第1集")
FILES = [
    "第1集_镜02_首帧_写实CG融合_00001_.png",
    "第1集_镜02_尾帧_写实CG融合_00001_.png",
]


def main():
    os.makedirs(DST_DIR, exist_ok=True)
    for f in FILES:
        src = os.path.join(SRC_DIR, f)
        dst = os.path.join(DST_DIR, f)
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print("复制: %s -> %s" % (f, DST_DIR))
        else:
            print("源不存在: %s" % src)
    print("完成。")


if __name__ == "__main__":
    main()
