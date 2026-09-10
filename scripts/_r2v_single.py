# -*- coding: utf-8 -*-
"""临时：提交「镜02 R2V 单镜视频」到 ComfyUI，盯守至完成，记录状态到 artifacts/。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import submit_workflow as sw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, "workflows", "14_video_R2VA_镜02_1280x736.json")
QUE = os.path.join(ROOT, "artifacts", "r2v_queue.json")
STAT = os.path.join(ROOT, "artifacts", "r2v_status.json")


def main():
    obj_info = sw.get_object_info()
    with open(WF, encoding="utf-8") as f:
        wf = json.load(f)
    api = sw.ui_to_api(wf, obj_info)
    resp = sw._post("/api/prompt", {"prompt": api, "client_id": "codebuddy"})
    pid = resp.get("prompt_id")
    with open(QUE, "w", encoding="utf-8") as f:
        json.dump(
            {"prompt_id": pid, "error": resp.get("error"),
             "node_errors": resp.get("node_errors")},
            f, ensure_ascii=False, indent=2,
        )
    print("pid=", pid, flush=True)
    rc = sw.do_watch(pid, poll=15, timeout=7200)
    with open(STAT, "w", encoding="utf-8") as f:
        json.dump({"prompt_id": pid, "rc": rc}, f, ensure_ascii=False, indent=2)
    print("rc=", rc, flush=True)


if __name__ == "__main__":
    main()
