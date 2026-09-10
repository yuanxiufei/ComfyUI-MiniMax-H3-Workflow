# -*- coding: utf-8 -*-
"""Patch Multishot CORE workflow: LoraStack turbo(0.75) + steps 8 + insert MiniMaxH3TeaCache(total_steps=8)."""
import json, io, sys, copy
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

P = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\11_视频_Multishot_CORE_横屏_1280x736.json"
d = json.load(open(P, encoding="utf-8"))
nodes = d["nodes"]
links = d["links"]

FL2V_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
LOK = 0.75

def find(t):
    return next(n for n in nodes if n["type"] == t)

# 1) steps 14 -> 8 in StudioControls and Sampler
sc = find("H3StudioControls")
smp = find("H3MultishotSampler")
sc_w, smp_w = sc["widgets_values"], smp["widgets_values"]
print("StudioControls steps:", sc_w[3], "-> 8")
sc_w[3] = 8
print("Sampler steps:", smp_w[7], "-> 8")
smp_w[7] = 8

# 2) LoraStack first slot: None -> turbo LoRA @0.75
ls = find("H3LoraStack")
ls_w = ls["widgets_values"]
print("LoraStack slot0:", ls_w[0], "->", FL2V_LORA, "strength:", ls_w[1], "->", LOK)
ls_w[0] = FL2V_LORA
ls_w[1] = LOK

# 3) insert MiniMaxH3TeaCache between LoraStack.model and Sampler.model (link L2)
lora_out = ls["outputs"][0]
sampler_in = smp["inputs"][0]
old_link = sampler_in["link"]  # link id from LoraStack->Sampler
# find the link record
old_rec = next(l for l in links if l[0] == old_link)
print("replace link L%d (%s->%s) with TeaCache hop" % (old_link, "LoraStack", "Sampler"))

max_nid = max(n["id"] for n in nodes)
max_lid = max(l[0] for l in links)
tc_id = max_nid + 1
lk1 = max_lid + 1
lk2 = max_lid + 2

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

# retarget old link: LoraStack -> TeaCache (new lk1), TeaCache -> Sampler (lk2)
old_rec[0] = lk1
old_rec[2] = tc_id          # target node = TeaCache
old_rec[3] = 0              # target input 0
lora_out["links"] = [lk1]
tc_node["inputs"][0]["link"] = lk1
links.append([lk2, tc_id, 0, smp["id"], 0, "MODEL"])
sampler_in["link"] = lk2

d["last_node_id"] = tc_id
d["last_link_id"] = lk2
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("[ok] patched 11 CORE: turbo LoRA 0.75 + 8 steps + TeaCache(8)")

# sanity re-parse
d2 = json.load(open(P, encoding="utf-8"))
for n in d2["nodes"]:
    if n["type"] in ("H3StudioControls", "H3LoraStack", "MiniMaxH3TeaCache", "H3MultishotSampler"):
        print("  ", n["type"], "->", (n["widgets_values"][:5] if n["type"] != "H3MultishotSampler" else [n["widgets_values"][7]]))
