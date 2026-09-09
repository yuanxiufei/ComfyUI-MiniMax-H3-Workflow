# -*- coding: utf-8 -*-
import glob, json, os, sys, urllib.request

base = os.path.join(os.path.dirname(__file__), "..", "workflows")
print("=== char3view 工作流 -> 输出角色 ===")
for p in sorted(glob.glob(os.path.join(base, "*char3view*.json"))):
    wf = json.load(open(p, encoding="utf-8"))
    prefix = None
    for n in wf.get("nodes", []):
        if n.get("type") == "SaveImage":
            wv = n.get("widgets_values") or []
            if wv:
                prefix = wv[0]
    print("  %s -> %s" % (os.path.basename(p), prefix))

print("=== ComfyUI 服务检测 ===")
try:
    with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=6) as r:
        print("  HTTP", r.status, "OK")
except Exception as e:
    print("  NOT_UP:", e)
