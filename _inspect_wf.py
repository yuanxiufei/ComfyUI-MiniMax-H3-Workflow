# -*- coding: utf-8 -*-
"""Inspect MiniMax H3 ComfyUI workflow JSONs: node types + key params."""
import json, os, io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

base = r"D:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows"
files = [
    "09_video_FL2VA_1280x736.json",
    "09_video_FL2VA_镜01_1280x736.json",
    "11_视频_Multishot_CORE_横屏_1280x736.json",
    "14_video_R2VA_镜02_1280x736.json",
]

KEY_TYPES = {
    "UNETLoader": 4, "CheckpointLoaderSimple": 4, "VAELoader": 4, "CLIPLoader": 4,
    "LoraLoader": 4, "LoraLoaderModelOnly": 4, "LoadH3Model": 4,
    "KSampler": 12, "KSamplerAdvanced": 12, "SamplerCustom": 12,
    "MiniMaxH3Sampler": 12, "CreateVideo": 12, "CreateAudioVideo": 12,
    "MiniMaxH3CreateVideo": 12, "EmptyH3Latent": 12, "EmptyLatentImage": 12,
    "MiniMaxH3TextEncode": 12, "MiniMaxH3RefVideo": 12, "MiniMaxH3FirstLastFrame": 12,
    "MiniMaxH3T5TextEncode": 12, "H3AttentionPatch": 12, "MiniMaxH3SageAttn": 12,
    "H3TurboLoRA": 12, "SageAttentionPatch": 12, "AttentionPatch": 12,
}

for fn in files:
    p = os.path.join(base, fn)
    print("=" * 78)
    print("FILE:", fn, os.path.getsize(p), "bytes")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        print("  JSON ERROR:", e)
        continue
    nodes = d.get("nodes", [])
    links = d.get("links", [])
    print("  nodes:", len(nodes), " links:", len(links))
    for n in nodes:
        t = n.get("type", "")
        wid = n.get("id")
        wv = n.get("widgets_values")
        mode = n.get("mode", 0)
        if mode == 4:
            mark = "  [MUTED]"
        else:
            mark = ""
        need = KEY_TYPES.get(t)
        if need is None:
            if "H3" in t or "MiniMax" in t or "Sage" in t or "Turbo" in t or "TeaCache" in t or "TESpeed" in t or "MotionContext" in t:
                need = 12
            elif t in ("SaveVideo", "SaveAudioVideo", "VideoOutput"):
                need = 12
        if need is None:
            continue
        extra = ""
        if isinstance(wv, list):
            extra = " | ".join(str(x) for x in wv[:need])
        print(f"  [{wid}]{mark} {t}  :: {extra}")
    print()
PY_END = None
