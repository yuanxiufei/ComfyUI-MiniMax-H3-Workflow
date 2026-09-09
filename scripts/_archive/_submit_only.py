# -*- coding: utf-8 -*-
"""临时脚本：只提交镜02视频工作流，不等待返回。输出prompt_id到文件。"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw

WORKFLOW = r"d:\code\voide\ComfyUI-MiniMax-H3-Workflow\workflows\09_video_FL2VA_镜02_1280x736.json"


def main():
    with open(WORKFLOW, encoding="utf-8") as f:
        wf = json.load(f)
    obj_info = sw.get_object_info()
    api = sw.ui_to_api(wf, obj_info)
    errs = sw.validate_references(api)
    if errs:
        print("引用校验失败:")
        for e in errs:
            print("  ", e)
        return 1
    resp = sw._post("/api/prompt", {"prompt": api, "client_id": "codebuddy"})
    if resp.get("error") or resp.get("node_errors"):
        print("提交失败:", json.dumps(resp, ensure_ascii=False)[:800])
        return 1
    pid = resp["prompt_id"]
    print("SUBMITTED pid:", pid)
    with open(os.path.join(HERE, "_video_pid.txt"), "w", encoding="utf-8") as f:
        f.write(pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
