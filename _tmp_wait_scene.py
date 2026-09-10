# -*- coding: utf-8 -*-
"""临时后台脚本：等待 sc001 九宫格生成，完成后自动裁切 + 重建 r2v。

九宫格(0457c485)排在旧 r2v(bb2feea4)之后，需等旧视频跑完才开跑。
本脚本轮询九宫格落盘，然后依次执行：
  1) crop_scene_panels.py      —— 把九宫格裁成 panel1-9（含 inset 去网格线）
  2) build_r2v_refs.py --shots 02,04 —— 重建镜 02/04 的 r2v（补场景参考）
任务结束即可删除本脚本。不自动提交 r2v。
"""
import os
import subprocess
import sys
import time

COMFY = r"D:\Comfy-Desktop\ComfyUI-Shared"
ROOT = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow"
SCENE = "东家城堡花园广场"
GRID = os.path.join(COMFY, "output", "01_场景素材", SCENE, "%s_九宫格_00001_.png" % SCENE)

print("[wait] 等待九宫格生成:\n  %s" % GRID, flush=True)
timeout = 3600
t = 0
while not os.path.isfile(GRID) and t < timeout:
    time.sleep(15)
    t += 15
    if t % 60 == 0:
        print("  ... 已等待 %ss" % t, flush=True)

if not os.path.isfile(GRID):
    print("TIMEOUT: 九宫格未生成，终止", flush=True)
    sys.exit(2)
print("[ok] 九宫格已生成，开始裁切单格...", flush=True)

r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "crop_scene_panels.py")])
print("[crop] 返回码:", r.returncode, flush=True)

print("[rebuild] 重建 r2v 参考（镜 02,04）...", flush=True)
r2 = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_r2v_refs.py"),
                     "--shots", "02,04", "--comfy-input", COMFY])
print("[build_r2v] 返回码:", r2.returncode, flush=True)
print("DONE", flush=True)
