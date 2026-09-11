# -*- coding: utf-8 -*-
"""临时编排（用完即删）：等镜01 首/尾帧落入 ComfyUI output 后，自动接 FL2VA 视频链。

前半段由 gen_shots_images.py 01 负责（提交 05 首帧 -> 06 尾帧 -> 复制进 input）；
本脚本只做「等尾帧就绪 -> 调 pipeline_video.py --mode fl2va --shots 01 --submit-real」。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
COMFY = r"D:\Comfy-Desktop\ComfyUI-Shared"
OUT_DIR = os.path.join(COMFY, "output", "02_分镜", "第1集")
LAST_PREFIX = "第1集_镜01_尾帧_写实CG融合"
DEADLINE_H = 4          # 等图上限（小时）
FRESH_TOL_S = 300       # 产物 mtime 需晚于本次启动前 5 分钟，避免误判旧图


def find_last_frame(start_ts):
    if not os.path.isdir(OUT_DIR):
        return None
    for f in sorted(os.listdir(OUT_DIR)):
        if f.startswith(LAST_PREFIX) and f.endswith(".png"):
            p = os.path.join(OUT_DIR, f)
            if os.path.getmtime(p) >= start_ts - FRESH_TOL_S:
                return p
    return None


def main():
    t0 = time.time()
    print("[chain] 等待镜01 尾帧生成（output/02_分镜/第1集/%s*.png）..." % LAST_PREFIX, flush=True)
    while time.time() - t0 < DEADLINE_H * 3600:
        p = find_last_frame(t0)
        if p:
            print("[chain] 尾帧就绪：%s" % p, flush=True)
            break
        time.sleep(15)
    else:
        print("[chain] 超时未等到尾帧，终止", flush=True)
        return 1

    print("[chain] 启动 FL2VA 视频链（镜01）", flush=True)
    rc = subprocess.call(
        [sys.executable, os.path.join(HERE, "pipeline_video.py"),
         "--mode", "fl2va", "--shots", "01", "--submit-real", "--timeout", "7200"],
        cwd=ROOT,
    )
    print("[chain] pipeline_video 结束 rc=%s" % rc, flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
