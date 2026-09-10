# -*- coding: utf-8 -*-
"""Locate sage patch classes + TeaCache node names + Director sampling defaults."""
import io, sys, os, re, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

CN = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes"

print("===== A) search class defs & mappings for sage/teacache across custom_nodes =====")
targets = ["PathchSageAttentionKJ", "MiniMaxH3MemoryEfficientSageAttentionPatch",
           "TeaCache", "MiniMaxH3TeaCacheArgs"]
for root_dir in os.listdir(CN):
    root = os.path.join(CN, root_dir)
    if not os.path.isdir(root):
        continue
    for py in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        try:
            txt = open(py, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        hits = [t for t in targets if t in txt]
        if hits:
            print(os.path.relpath(py, CN), "contains:", hits)

print()
print("===== B) director/core_sampling.py FULL =====")
p = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\director\core_sampling.py"
print(open(p, encoding="utf-8").read())

print()
print("===== C) Director node: sampling-related widget names =====")
p2 = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\nodes\director.py"
try:
    txt = open(p2, encoding="utf-8", errors="ignore").read()
    print("LEN", len(txt))
    # print INPUT_TYPES / widget definitions around steps/sampler/cfg
    for pat in ["steps", "sampler", "scheduler", "cfg", "guidance"]:
        seen = set()
        for m in re.finditer(r'.{50}' + pat + r'.{70}', txt, re.I):
            s = m.group(0).replace("\n", " ")
            key = s[:40]
            if key in seen:
                continue
            seen.add(key)
            print("  ...", s[:150])
except Exception as e:
    print("ERR", e)
