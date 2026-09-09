# -*- coding: utf-8 -*-
"""临时脚本：基于镜01特制工作流，生成镜02视频工作流（替换首尾帧路径）。"""
import copy
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

SRC = r"d:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\09_video_FL2VA_镜01_1280x736.json"
DST = r"d:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\09_video_FL2VA_镜02_1280x736.json"

# 源路径 -> 目标路径
MAP = {
    "02_分镜/第1集/第1集_镜01_首帧_写实CG融合_00001_.png":
        "02_分镜/第1集/第1集_镜02_首帧_写实CG融合_00001_.png",
    "02_分镜/第1集/第1集_镜01_尾帧_写实CG融合_00001_.png":
        "02_分镜/第1集/第1集_镜02_尾帧_写实CG融合_00001_.png",
}


def main():
    with open(SRC, encoding="utf-8") as f:
        wf = json.load(f)

    # 适用 UI 或 API 两种格式
    replaced = 0
    if isinstance(wf, dict) and "nodes" in wf:
        nodes = wf["nodes"]
        for node in nodes:
            if node.get("type") == "LoadImage" and isinstance(node.get("widgets_values"), list):
                for i, v in enumerate(node["widgets_values"]):
                    if isinstance(v, str) and v in MAP:
                        node["widgets_values"][i] = MAP[v]
                        replaced += 1
                        print("替换: %s -> %s" % (v, MAP[v]))
    else:
        print("未知工作流格式")
        return 1

    print("共替换 %d 处" % replaced)
    if replaced < 2:
        print("警告: 未找到预期的两张首尾帧路径，请检查")
        return 1

    with open(DST, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    print("已写入:", DST)
    return 0


if __name__ == "__main__":
    sys.exit(main())
