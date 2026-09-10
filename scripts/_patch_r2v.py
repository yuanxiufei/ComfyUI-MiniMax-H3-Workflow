# -*- coding: utf-8 -*-
"""Patch build_r2v_refs.py: add r2v turbo LoRA (0.75, 8 steps) between UNET and Director."""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

P = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\scripts\build_r2v_refs.py"
src = open(P, encoding="utf-8").read()
orig = src

def rep(old, new, must=True):
    global src
    if old not in src:
        if must:
            raise SystemExit("NOT FOUND:\n---\n" + old[:200])
        print("[warn] not found (skip):", old[:60])
        return
    src = src.replace(old, new, 1)
    print("[ok] replaced:", old.strip().splitlines()[0][:60])

# 1) constants after REF2VA_UNET
rep(
    'REF2VA_UNET = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"\n',
    'REF2VA_UNET = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"\n\n'
    '# r2v turbo LoRA：8 步 768p 版 v1.0（社区实测 v1/v4 为质量主力，lightx2v/v0.1 画质差）。\n'
    '# 强度按社区实测取 0.75：拉满 1.0 画面可能不跟提示词。\n'
    'TURBO_LORA_R2V = "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"\n'
    'TURBO_STEPS = 8\n'
    'TURBO_STRENGTH = 0.75\n',
)

# 2) build_r2v signature
rep(
    "def build_r2v(storyboards, template, char_map, scene_map, comfy_root, voice_map=None,\n"
    "              prev_tail_map=None):",
    "def build_r2v(storyboards, template, char_map, scene_map, comfy_root, voice_map=None,\n"
    "              prev_tail_map=None, use_turbo=True):",
)

# 3) UNET->Director model link: insert LoRA node when use_turbo
rep(
    """    # Director 的 model 输入：环境缺失 patch/sage 节点，改为让 unet 直接驱动 Director。
    d_model_slot = next((i for i, inp in enumerate(director["inputs"])
                         if inp["name"] == "model"), None)
    if unet is not None and d_model_slot is not None:
        mlk = next_lid
        next_lid += 1
        if unet["outputs"] and unet["outputs"][0].get("links") is not None:
            unet["outputs"][0]["links"] = [mlk]
        links.append([mlk, unet["id"], 0, director["id"], d_model_slot, "MODEL"])
        director["inputs"][d_model_slot]["link"] = mlk""",
    """    # Director 的 model 输入：unet → turbo LoRA(0.75) → Director；
    # 模板自带的 patch/sage 节点（PathchSageAttentionKJ 等）由 DROP_TYPES 移除，
    # SageAttention 走 ComfyUI 全局 --use-sage-attention（0.34.2 内置，无需节点）。
    d_model_slot = next((i for i, inp in enumerate(director["inputs"])
                         if inp["name"] == "model"), None)
    if unet is not None and d_model_slot is not None:
        if use_turbo:
            lora_id = next_nid
            next_nid += 1
            lora_node = _node(
                lora_id, "LoraLoaderModelOnly", [-500, 300], [360, 82],
                unet.get("order", 0) + 0.5,
                [
                    {"localized_name": "模型", "name": "model", "type": "MODEL", "link": None},
                    {"localized_name": "LoRA名称", "name": "lora_name", "type": "COMBO",
                     "widget": {"name": "lora_name"}, "link": None},
                    {"localized_name": "模型强度", "name": "strength_model", "type": "FLOAT",
                     "widget": {"name": "strength_model"}, "link": None},
                ],
                [{"localized_name": "模型", "name": "MODEL", "type": "MODEL", "links": []}],
                [TURBO_LORA_R2V, TURBO_STRENGTH],
                {"Node name for S&R": "LoraLoaderModelOnly"},
                "H3 Turbo LoRA (r2v 8-step, 0.75)",
            )
            nodes.append(lora_node)
            lk_unet = next_lid
            next_lid += 1
            links.append([lk_unet, unet["id"], 0, lora_id, 0, "MODEL"])
            lora_node["inputs"][0]["link"] = lk_unet
            for out in unet["outputs"]:
                if out["name"] == "MODEL":
                    out["links"] = [lk_unet]
            lk_dir = next_lid
            next_lid += 1
            links.append([lk_dir, lora_id, 0, director["id"], d_model_slot, "MODEL"])
            director["inputs"][d_model_slot]["link"] = lk_dir
            lora_node["outputs"][0]["links"] = [lk_dir]
        else:
            mlk = next_lid
            next_lid += 1
            links.append([mlk, unet["id"], 0, director["id"], d_model_slot, "MODEL"])
            director["inputs"][d_model_slot]["link"] = mlk
            for out in unet["outputs"]:
                if out["name"] == "MODEL":
                    out["links"] = [mlk]""",
)

# 4) rebuild call site: pass steps
rep(
    "    rebuild_r2v_timeline(director, group_ids)",
    "    rebuild_r2v_timeline(director, group_ids, TURBO_STEPS if use_turbo else None)",
)

# 5) rebuild_r2v_timeline signature
rep(
    "def rebuild_r2v_timeline(director, group_ids):",
    "def rebuild_r2v_timeline(director, group_ids, steps=None):",
)

# 6) rebuild tail: write steps into wv[13]
rep(
    """    wv[10] = start          # Director 的 total_frames，与 timeline_data.totalFrames 对齐
    wv[11] = json.dumps(tl, ensure_ascii=False, separators=(",", ":"))""",
    """    wv[10] = start          # Director 的 total_frames，与 timeline_data.totalFrames 对齐
    wv[11] = json.dumps(tl, ensure_ascii=False, separators=(",", ":"))
    if steps is not None:
        wv[13] = steps       # 8 步 turbo（模板默认 25 步）""",
)

# 7) docstring line about "不接 fl2v turbo LoRA" -> update
rep(
    "- 权重用 ref2va（minimax_h3_ref2va_pruned_int8_convrot），不接 fl2v turbo LoRA",
    "- 权重用 ref2va（minimax_h3_ref2va_pruned_int8_convrot）+ r2v turbo LoRA(8步/0.75)",
)

# 8) main() call explicit use_turbo
rep(
    "    wf = build_r2v(storyboards, load_template(), char_map, scene_map, comfy_root,\n"
    "                   voice_map, prev_tail_map)",
    "    wf = build_r2v(storyboards, load_template(), char_map, scene_map, comfy_root,\n"
    "                   voice_map, prev_tail_map, use_turbo=True)",
)

if src == orig:
    raise SystemExit("no change made")
open(P, "w", encoding="utf-8", newline="").write(src)
print("\n[ok] build_r2v_refs.py patched, %d -> %d bytes" % (len(orig), len(src)))
