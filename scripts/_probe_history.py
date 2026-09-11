# -*- coding: utf-8 -*-
"""临时探针：拉取 ComfyUI /history，还原黑图那几次运行实际提交的内容。用完即删。"""
import hashlib
import json
import urllib.request

BASE = "http://127.0.0.1:8188"


def load(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


hist = load("/history")
print("history entries:", len(hist))
rows = []
for pid, item in hist.items():
    ts = ""
    for m in item.get("status", {}).get("messages", []) or []:
        if isinstance(m, list) and m[0] == "execution_start":
            ts = str(m[1].get("timestamp", ""))
    pr = item.get("prompt")
    text = seed = save = ""
    if pr:
        for nid, node in sorted(pr[2].items(), key=lambda kv: int(kv[0])):
            ct = node.get("class_type")
            ins = node.get("inputs", {})
            if ct == "CLIPTextEncode":
                t = ins.get("text", "")
                text += "[%s len=%d md5=%s] " % (
                    nid, len(t), hashlib.md5(t.encode("utf-8")).hexdigest()[:8])
            elif ct in ("KSampler", "KSamplerAdvanced"):
                seed = ins.get("seed", ins.get("noise_seed"))
            elif ct == "SaveImage":
                save = ins.get("filename_prefix")
    outs = []
    for o in (item.get("outputs") or {}).values():
        for im in o.get("images", []):
            outs.append(im.get("filename"))
    rows.append((ts, pid, seed, save, text, outs))

for ts, pid, seed, save, text, outs in sorted(rows):
    print("-" * 70)
    print("ts=%s  pid=%s  seed=%s" % (ts, pid[:8], seed))
    print("   save:", save)
    print("   text:", text)
    print("   out :", outs)
