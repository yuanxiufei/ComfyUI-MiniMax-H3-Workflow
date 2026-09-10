# -*- coding: utf-8 -*-
"""临时脚本：提交 r2v 镜02 视频工作流并等待落盘，产物路径写 _video_result.json。
用法: python scripts/_submit_video.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

WF = "workflows/14_video_R2VA_镜02_1280x736.json"
WF = os.path.abspath(os.path.join(HERE, "..", WF))
MIN_GOOD = 200 * 1024  # 200KB 视频


def wait_done(pid, timeout=1800):
    for _ in range(timeout // 8):
        time.sleep(8)
        d = sw._get("/history/" + pid).get(pid)
        if d:
            st = d.get("status", {}).get("status_str", "running")
            if st in ("success", "error"):
                return d, st
        else:
            # history 尚空，继续等
            pass
    return None, "timeout"


def files_of(d):
    out = []
    for nid, o in (d.get("outputs") or {}).items():
        for kind, lst in o.items():
            for x in (lst if isinstance(lst, list) else []):
                if isinstance(x, dict) and x.get("filename"):
                    out.append(x)
    return out


def main():
    print("提交:", WF, flush=True)
    try:
        pid = sw.do_submit(WF)
    except SystemExit as e:
        print("提交失败", e, flush=True)
        return
    print("pid=", pid, flush=True)
    d, st = wait_done(pid)
    files = files_of(d) if d else []
    vids = [f for f in files if str(f.get("filename", "")).lower().endswith((".mp4", ".webm", ".mov"))]
    chosen = vids[-1] if vids else None
    size = 0
    path = None
    if chosen:
        path = os.path.join("D:/Comfy-Desktop/ComfyUI-Shared/output",
                            chosen.get("subfolder", ""), chosen["filename"])
        if os.path.isfile(path):
            size = os.path.getsize(path)
    result = {"status": st, "pid": pid,
              "file": chosen.get("filename") if chosen else None,
              "subdir": chosen.get("subfolder") if chosen else None,
              "sizeKB": round(size / 1024), "ok": (st == "success" and size >= MIN_GOOD)}
    with open(os.path.join(HERE, "_video_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("DONE", json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
