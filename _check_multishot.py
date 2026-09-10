# -*- coding: utf-8 -*-
"""Inspect ComfyUI-H3-Multishot package: node mappings, speed boosters, episode/long-video capability."""
import io, sys, re, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI-H3-Multishot.disabled"

print("===== 1) NODE_CLASS_MAPPINGS in __init__.py =====")
t = open(os.path.join(BASE, "__init__.py"), encoding="utf-8", errors="ignore").read()
m = re.search(r'NODE_CLASS_MAPPINGS\s*=\s*\{(.*?)\}', t, re.S)
if m:
    for cm in re.finditer(r'"([^"]+)"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)', m.group(1)):
        print("  ", cm.group(1), "->", cm.group(2))
else:
    print("  no mappings found; head:")
    print(t[:1500])

print()
print("===== 2) h3_speed_boosters.py classes & inputs =====")
sp = open(os.path.join(BASE, "h3_speed_boosters.py"), encoding="utf-8", errors="ignore").read()
print("  LEN", len(sp))
for m in re.finditer(r'class\s+([A-Za-z0-9_]+)\b', sp):
    print("  class:", m.group(1))
for m in re.finditer(r'class\s+(\w*[Ss]peed\w*|\w*[Tt]ea[Cc]ache\w*)\b(.*?)(?=\nclass |\Z)', sp, re.S):
    seg = m.group(2)
    ins = re.findall(r'"([a-z_]+)"\s*:\s*\(', seg)
    print("  --", m.group(1), "inputs:", ins)

print()
print("===== 3) README key capabilities (episode / chain / teacache / lora) =====")
rd = open(os.path.join(BASE, "README.md"), encoding="utf-8", errors="ignore").read()
for line in rd.splitlines():
    low = line.lower()
    if any(k in low for k in ["episode", "chain", "seamless", "teacache", "speed", "lora", "multi", "extend", "context", "连续", "剧"]):
        print("  ", line.strip()[:130])

print()
print("===== 4) h3_extend.py / h3_episode_tools.py presence of context =====")
for fn in ["h3_extend.py", "h3_episode_tools.py"]:
    p = os.path.join(BASE, fn)
    if os.path.isfile(p):
        txt = open(p, encoding="utf-8", errors="ignore").read()
        classes = re.findall(r'class\s+([A-Za-z0-9_]+)\b', txt)
        print("  ", fn, "classes:", classes[:12])
