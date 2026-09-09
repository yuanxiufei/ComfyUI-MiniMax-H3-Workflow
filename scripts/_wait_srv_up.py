# -*- coding: utf-8 -*-
"""轮询等待 ComfyUI 服务就绪，并打印监听进程/GPU/输出日志。"""
import json
import os
import time
import urllib.request

log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_comfyui.log")


def up():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


for i in range(40):
    d = up()
    if d:
        for dev in d.get("devices", []):
            print("就绪! GPU:", dev.get("name"), "VRAM:", round(dev.get("vram_total", 0) / 1048576), "MB")
        break
    time.sleep(3)
else:
    print("40 次轮询后仍未就绪。查看日志尾部:")
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="replace") as f:
            print("\n".join(f.read().splitlines()[-15:]))
    raise SystemExit(1)

print("=== 输出目录设置 ===")
if os.path.exists(log):
    with open(log, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "output directory" in line.lower() or "Starting server" in line.lower() or "To see the GUI" in line:
                print(line.rstrip())
