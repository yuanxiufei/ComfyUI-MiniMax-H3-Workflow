# -*- coding: utf-8 -*-
"""临时脚本：批量提交图片生成任务（角色三视图 + 场景图 + 镜01首尾帧），记录 pids。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw

BASE = os.path.abspath(os.path.join(HERE, "..", "workflows"))

# 角色三视图（10个）
CHARS = ["01_char3view_1216x832_Qwen2512_Fusion.json"] + [
    f"01_char3view_1216x832_Qwen2512_c{v:02d}_Fusion.json" for v in range(2, 11)]
# 场景图（2个）
SCENES = ["03_scene3view_1216x832_Qwen2512_sc001.json",
          "03_scene3view_1216x832_Qwen2512_sc002.json"]
# 镜01 首帧/尾帧（空镜）
FRAMES = ["05_shotfirst_1216x832_Qwen2512_Fusion_01.json",
          "06_shotlast_1216x832_Qwen2512_Fusion_01.json"]


def main():
    WFS = CHARS + SCENES + FRAMES
    obj_info = sw.get_object_info()
    pids = []
    for name in WFS:
        path = os.path.join(BASE, name)
        with open(path, encoding="utf-8") as f:
            wf = json.load(f)
        api = sw.ui_to_api(wf, obj_info)
        resp = sw._post("/api/prompt", {"prompt": api, "client_id": "codebuddy"})
        if resp.get("error") or resp.get("node_errors"):
            print("FAILED", name, json.dumps(resp, ensure_ascii=False)[:400])
            continue
        pid = resp["prompt_id"]
        pids.append(pid)
        print("SUBMITTED", name, "->", pid)
    with open(os.path.join(HERE, "_imgs_pids.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(pids))
    print("total:", len(pids))


if __name__ == "__main__":
    import json
    main()
