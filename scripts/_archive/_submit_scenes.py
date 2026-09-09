# -*- coding: utf-8 -*-
"""临时脚本：提交场景素材九宫格工作流（sc001 + sc002），记录 pid。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw

WFS = [
    "03_scene3view_1216x832_Qwen2512_sc001.json",
    "03_scene3view_1216x832_Qwen2512_sc002.json",
]
BASE = os.path.abspath(os.path.join(HERE, "..", "workflows"))


def main():
    pids = []
    for name in WFS:
        path = os.path.join(BASE, name)
        with open(path, encoding="utf-8") as f:
            wf = json.load(f)
        obj_info = sw.get_object_info()
        api = sw.ui_to_api(wf, obj_info)
        resp = sw._post("/api/prompt", {"prompt": api, "client_id": "codebuddy"})
        if resp.get("error") or resp.get("node_errors"):
            print("FAILED", name, json.dumps(resp, ensure_ascii=False)[:500])
            continue
        pid = resp["prompt_id"]
        pids.append(pid)
        print("SUBMITTED", name, "->", pid)
    with open(os.path.join(HERE, "_scene_pids.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(pids))
    print("total:", len(pids))


if __name__ == "__main__":
    import json
    main()
