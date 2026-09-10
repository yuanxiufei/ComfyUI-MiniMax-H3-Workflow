# -*- coding: utf-8 -*-
"""Validate patched Multishot workflows: parse OK, no dangling links, key params."""
import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows"
FILES = ["11_视频_Multishot_CORE_横屏_1280x736.json",
         "12_视频_Multishot_Extend_横屏_1280x736.json",
         "13_视频_Multishot_剧本_第1集_横屏_1280x736.json"]

for fn in FILES:
    p = BASE + "\\" + fn
    d = json.load(open(p, encoding="utf-8"))
    nodes = d["nodes"]
    ids = {n["id"] for n in nodes}
    links = d["links"]
    dangling = []
    for l in links:
        lid, src, so, dst, do_, typ = l
        if src not in ids or dst not in ids:
            dangling.append(lid)
    # check model chain nodes
    types = {n["type"] for n in nodes}
    ok = all(x in types for x in ("H3LoraStack", "MiniMaxH3TeaCache"))
    steps_ok = True
    for n in nodes:
        if n["type"] == "H3StudioControls":
            steps_ok = steps_ok and n["widgets_values"][3] == 8
        if n["type"] == "H3LoraStack":
            steps_ok = steps_ok and n["widgets_values"][0] != "None"
    print("%s | dangling_links=%s teacache_node=%s steps8=%s lora_ok=%s" % (
        fn[:6], dangling, ok, steps_ok, ok and steps_ok))
