# -*- coding: utf-8 -*-
"""Dump Multishot CORE workflow graph structure around model chain."""
import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

P = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\11_视频_Multishot_CORE_横屏_1280x736.json"
d = json.load(open(P, encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"]}

print("=== nodes of interest ===")
for n in d["nodes"]:
    t = n["type"]
    if t in ("H3StudioControls", "H3ModelLoaderAny", "H3ClipLoaderAny", "H3LoraStack",
             "H3MultishotSampler", "CreateVideo", "SaveVideo", "VAELoader"):
        print("\n## [%d] %s widgets=%s" % (n["id"], t, n.get("widgets_values")))
        print("   inputs:")
        for i, inp in enumerate(n.get("inputs", [])):
            print("     %d: name=%s type=%s link=%s" % (i, inp.get("name"), inp.get("type"), inp.get("link")))
        print("   outputs:")
        for o in n.get("outputs", []):
            print("     name=%s type=%s links=%s" % (o.get("name"), o.get("type"), o.get("links")))

print("\n=== links touching these nodes ===")
interest = {n["id"] for n in d["nodes"] if n["type"] in (
    "H3StudioControls", "H3ModelLoaderAny", "H3ClipLoaderAny", "H3LoraStack", "H3MultishotSampler")}
for l in d["links"]:
    lid, src, s_off, dst, d_off, typ = l
    if src in interest or dst in interest:
        sn = nodes.get(src, {}).get("type", "?")
        dn = nodes.get(dst, {}).get("type", "?")
        print("  L%d: %s[%d](%s) -> %s[%d](%s)" % (lid, sn, src, s_off, dn, dst, d_off))
