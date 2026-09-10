# -*- coding: utf-8 -*-
"""Check R2V / 整集 / Multishot workflows: Director steps, LoRA presence; MiniMaxH3 node list."""
import json, io, sys, os, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

WF = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows"
files = [
    "14_video_R2VA_镜02_1280x736.json",
    "14_video_R2VA_整集_1280x736.json",
    "09_video_FL2VA_整集_1280x736.json",
    "12_视频_Multishot_Extend_横屏_1280x736.json",
]
for fn in files:
    p = os.path.join(WF, fn)
    print("=" * 70)
    print("FILE:", fn)
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("  ERR", e)
        continue
    for n in d.get("nodes", []):
        t = n.get("type", "")
        if t in ("MiniMaxH3Director", "LoraLoaderModelOnly", "UNETLoader",
                 "MiniMaxH3MemoryEfficientSageAttentionPatch", "PathchSageAttentionKJ",
                 "H3LoraStack", "H3ModelLoaderAny", "H3MultishotSampler"):
            wv = n.get("widgets_values")
            if t == "MiniMaxH3Director":
                wl = len(wv) if isinstance(wv, list) else 0
                if wl >= 16:
                    print(f"  [{t}] steps={wv[13]} sampler={wv[14]} sched={wv[15]} res={wv[7]}x{wv[8]} frames={wv[10]} cfg={wv[3]} seed={wv[4]} liveTae={str(wv[11])[:60]}")
                else:
                    print(f"  [{t}] widgets_len={wl} :: {str(wv)[:150]}")
            elif t == "UNETLoader":
                print(f"  [UNETLoader] {wv[0] if isinstance(wv,list) else wv}")
            else:
                print(f"  [{t}] {wv}")

print()
print("========== ComfyUI-MiniMaxH3 NODE_CLASS_MAPPINGS ==========")
ini = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI-MiniMaxH3\nodes\__init__.py"
print(open(ini, encoding="utf-8", errors="ignore").read()[:4000])
