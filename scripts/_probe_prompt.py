# -*- coding: utf-8 -*-
"""临时对照实验：定位镜02 首帧纯黑的成因。

对照组（全部走同一台 ComfyUI）：
  T1 = 镜02 工作流 + 镜03 的提示词   -> 若正常，则「文本内容」是黑图的触发因素
  T2 = 镜02 工作流原样（复现 baseline）-> 预期黑图
  T3 = 镜03 工作流原样（正常 baseline）-> 预期正常
产物写到 ComfyUI output/_probe/，不碰既有素材。用完即删。
"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402
import comfy_config as cc  # noqa: E402

SINGLES = os.path.join(ROOT, "workflows", "singles")
PROBE = os.path.join(ROOT, "workflows", "_probe")


def load(sid):
    p = os.path.join(SINGLES, "05_shotfirst_1216x832_Qwen2512_Fusion_%s.json" % sid)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def node(d, nid):
    return next(n for n in d["nodes"] if n["id"] == nid)


def main():
    os.makedirs(PROBE, exist_ok=True)
    wf02, wf03 = load("02"), load("03")

    t1 = copy.deepcopy(wf02)
    node(t1, 5)["widgets_values"] = [node(wf03, 5)["widgets_values"][0]]
    cases = [("T1_prompt03", t1), ("T2_base02", copy.deepcopy(wf02)),
             ("T3_base03", copy.deepcopy(wf03))]

    submitted = []
    for name, wf in cases:
        node(wf, 10)["widgets_values"] = ["_probe/" + name]
        p = os.path.join(PROBE, name + ".json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=1)
        pid = sw.do_submit(p)
        print("submit %-12s pid=%s" % (name, pid), flush=True)
        submitted.append((name, pid))

    for name, pid in submitted:
        rc = sw.do_watch(pid, poll=10, timeout=1800)
        print("watch  %-12s rc=%s" % (name, rc), flush=True)

    print("\n=== 结果亮度 ===", flush=True)
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        Image = None
    od = os.path.join(cc.OUTPUT_DIR, "_probe")
    if os.path.isdir(od):
        for fn in sorted(os.listdir(od)):
            if not fn.endswith(".png"):
                continue
            p = os.path.join(od, fn)
            kb = os.path.getsize(p) / 1024
            mean = -1
            if Image:
                g = Image.open(p).convert("L").resize((32, 32))
                mean = sum(g.getdata()) / 1024
            print("  %-46s %8.1fKB mean=%6.1f" % (fn, kb, mean))
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
