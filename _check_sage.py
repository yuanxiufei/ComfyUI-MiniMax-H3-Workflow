# -*- coding: utf-8 -*-
"""Check: (1) Director example workflows node composition; (2) whether sage patch nodes exist in installed custom nodes; (3) Director sampling config."""
import json, io, sys, os, re, glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("========== 1) Director example workflows ==========")
d = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\example_workflows"
for fn in sorted(os.listdir(d)):
    if not fn.endswith(".json"):
        continue
    p = os.path.join(d, fn)
    try:
        wf = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print(fn, "ERR", e)
        continue
    types = [n.get("type", "") for n in wf.get("nodes", [])]
    print(fn, "->", types)

print()
print("========== 2) Sage attention node classes in installed custom nodes ==========")
roots = [
    r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI-MiniMaxH3",
    r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director",
]
for root in roots:
    print("### root:", root)
    for py in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
        try:
            txt = open(py, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for m in re.finditer(r'NODE_CLASS_MAPPINGS\s*=\s*\{(.*?)\}', txt, re.S):
            for cm in re.finditer(r'"([^"]+)":\s*([A-Za-z_][A-Za-z0-9_]*)', m.group(1)):
                name, cls = cm.group(1), cm.group(2)
                if re.search(r'[Ss]age|Attention|Turbo|TeaCache|TESpeed', name):
                    print("  ", os.path.basename(py), "::", name, "->", cls)
        # also class definitions
        for cm in re.finditer(r'class\s+([A-Za-z0-9_]*[Ss]age[A-Za-z0-9_]*)\b', txt):
            print("   class def:", cm.group(1), "@", os.path.basename(py))
        for cm in re.finditer(r'class\s+([A-Za-z0-9_]*Attention[A-Za-z0-9_]*)\b', txt):
            print("   class def:", cm.group(1), "@", os.path.basename(py))

print()
print("========== 3) Director core_sampling.py key params ==========")
p = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\director\core_sampling.py"
try:
    txt = open(p, encoding="utf-8").read()
    print("LEN", len(txt))
    for pat in ["steps", "sampler", "scheduler", "cfg", "guidance", "shift", "denoise"]:
        for i, m in enumerate(re.finditer(r'.{60}' + pat + r'.{80}', txt, re.I)):
            if i >= 3:
                break
            print("  ...", m.group(0).replace("\n", " ")[:160])
except Exception as e:
    print("ERR", e)
