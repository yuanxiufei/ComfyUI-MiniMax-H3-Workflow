# -*- coding: utf-8 -*-
"""Patch Multishot Extend(12) + Script(13): turbo LoRA 0.75, steps 8, insert MiniMaxH3TeaCache(total_steps=8)."""
import json, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

FL2V_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
LOK = 0.75
FILES = [
    r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\12_视频_Multishot_Extend_横屏_1280x736.json",
    r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\13_视频_Multishot_剧本_第1集_横屏_1280x736.json",
]

for P in FILES:
    d = json.load(open(P, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    print("=====", P.split("\\")[-1])

    # 1) steps -> 8
    sc = next(n for n in nodes if n["type"] == "H3StudioControls")
    if sc["widgets_values"][3] != 8:
        print("  StudioControls steps:", sc["widgets_values"][3], "-> 8")
        sc["widgets_values"][3] = 8
    for n in nodes:
        if n["type"] in ("H3MultishotSampler", "H3MultishotMemorySampler", "H3ExtendTake"):
            w = n.get("widgets_values", [])
            if len(w) > 7 and isinstance(w[7], int):
                print("  %s steps:" % n["type"], w[7], "-> 8")
                w[7] = 8

    # 2) LoraStack slot0
    ls = next(n for n in nodes if n["type"] == "H3LoraStack")
    ls_w = ls["widgets_values"]
    print("  LoraStack:", ls_w[0], "->", FL2V_LORA, "; strength", ls_w[1], "->", LOK)
    ls_w[0] = FL2V_LORA
    ls_w[1] = LOK

    # 3) insert TeaCache on LoraStack.model -> sampler hop (if not already)
    already = any(n["type"] == "MiniMaxH3TeaCache" for n in nodes)
    if already:
        print("  TeaCache already present, skip")
    else:
        sampler = next(n for n in nodes if n["type"] in ("H3MultishotSampler", "H3MultishotMemorySampler", "H3ExtendTake"))
        model_in = next(i for i in sampler["inputs"] if i["name"] == "model")
        old_link = model_in["link"]
        old_rec = next(l for l in links if l[0] == old_link)
        max_nid = max(n["id"] for n in nodes)
        max_lid = max(l[0] for l in links)
        tc_id, lk1, lk2 = max_nid + 1, max_lid + 1, max_lid + 2
        tc_node = {
            "id": tc_id, "type": "MiniMaxH3TeaCache", "pos": [-420, 460], "size": [330, 150],
            "flags": {}, "order": 8.5, "mode": 0,
            "inputs": [{"localized_name": "模型", "name": "model", "type": "MODEL", "link": lk1}],
            "outputs": [{"localized_name": "模型", "name": "MODEL", "type": "MODEL", "links": [lk2]}],
            "properties": {"Node name for S&R": "MiniMaxH3TeaCache"},
            "widgets_values": [0.15, 2, -2, 8],
            "title": "TeaCache (8步)",
        }
        nodes.append(tc_node)
        old_rec[0], old_rec[2], old_rec[3] = lk1, tc_id, 0
        ls["outputs"][0]["links"] = [lk1]
        tc_node["inputs"][0]["link"] = lk1
        links.append([lk2, tc_id, 0, sampler["id"], model_in["name"], "MODEL"])
        model_in["link"] = lk2
        d["last_node_id"] = tc_id
        d["last_link_id"] = lk2
        print("  TeaCache inserted (total_steps=8)")

    # 4) keep H3SpeedBoosters teacache OFF (manual node used instead)
    for n in nodes:
        if n["type"] == "H3SpeedBoosters":
            print("  H3SpeedBoosters teacache stays:", n["widgets_values"][1])

    json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("  [ok] saved")
