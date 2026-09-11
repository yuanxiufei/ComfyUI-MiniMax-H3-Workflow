# -*- coding: utf-8 -*-
"""Build 横屏 Multishot（连续镜头）工作流，依据文档第九章/第十六章：
- 24GB 卡官方推荐：1280x736、192帧、14步（曲线模型未装，改用本机 fl2va int8）
- 横屏 16:9（H3 官方横屏推荐值，可导出 1920x1080），保存到 02_分镜/第1集/ 按命名规范
模板来自已安装的 ComfyUI-H3-Multishot 插件，仅复制改造，不改原模板。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_config as cc  # noqa: E402

# 模板源：与实例共用同一共享池（原来指向另一套安装 ComfyUI-Installs\ComfyUI\ComfyUI）
MS = os.path.join(cc.CUSTOM_NODES_DIR, "ComfyUI-H3-Multishot", "workflows")
OUT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workflows"))

FL2VA_INT8 = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
VW, VH, FRAMES, STEPS = 1280, 736, 192, 14  # 横屏 16:9
PFX_VIDEO = "02_分镜/第1集/第1集_整段_成片"
PFX_AUDIO = "02_分镜/第1集/第1集_整段_音频"


# 需要在控制/采样节点上覆盖的固定参数（键名与 H3 插件 h3_widget_values / outputs 槽位一致）
CTRL_FIELDS = (("width", VW), ("height", VH), ("frames_per_shot", FRAMES), ("steps", STEPS))


def _widget_index(node):
    """尽量稳健地得到 {字段名: widgets_values 下标}。
    优先用 properties.h3_widget_values 的键顺序（H3 插件权威顺序）；
    否则退化为按 outputs 槽位名顺序（ComfyUI 惯例），可供无 h3_widget_values 的节点
    （如 H3StudioControls）使用。"""
    hw = (node.get("properties") or {}).get("h3_widget_values")
    if isinstance(hw, dict) and hw:
        return {k: i for i, k in enumerate(hw.keys())}
    outs = node.get("outputs") or []
    return {o.get("name"): i for i, o in enumerate(outs) if isinstance(o, dict)}


def set_controls(wf):
    for n in wf["nodes"]:
        t = n["type"]
        wv = n.get("widgets_values")
        if not isinstance(wv, list):
            n["widgets_values"] = wv = []
        idx = _widget_index(n)
        if t == "H3StudioControls":
            # 无 h3_widget_values，按 outputs 槽位名顺序定位（width/height/frames_per_shot/steps）
            for k, v in CTRL_FIELDS:
                if k in idx and idx[k] < len(wv):
                    wv[idx[k]] = v
        elif t == "H3ModelLoaderAny":
            if wv:
                wv[0] = FL2VA_INT8
        elif t in ("H3MultishotSampler", "H3MultishotMemorySampler"):
            hw = (n.get("properties") or {}).get("h3_widget_values")
            for k, v in CTRL_FIELDS:
                if k in idx and idx[k] < len(wv):
                    wv[idx[k]] = v
                # ui_to_api 优先读 h3_widget_values，必须同步更新，否则覆盖参数会失效
                if isinstance(hw, dict) and k in hw:
                    hw[k] = v
        elif t == "SaveVideo":
            if wv:
                wv[0] = PFX_VIDEO
        elif t == "SaveAudio":
            if wv:
                wv[0] = PFX_AUDIO
    return wf


def main():
    jobs = [("H3_Seamless_Chain_CORE.json", f"11_视频_Multishot_CORE_横屏_{VW}x{VH}.json"),
            ("H3_Extend_Take.json", f"12_视频_Multishot_Extend_横屏_{VW}x{VH}.json")]
    os.makedirs(OUT, exist_ok=True)
    for src, dst in jobs:
        wf = json.load(open(os.path.join(MS, src), encoding="utf-8"))
        wf = set_controls(wf)
        json.dump(wf, open(os.path.join(OUT, dst), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("wrote", dst)


if __name__ == "__main__":
    main()
