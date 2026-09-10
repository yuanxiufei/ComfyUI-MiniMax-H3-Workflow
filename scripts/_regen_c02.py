# -*- coding: utf-8 -*-
"""临时脚本：修复小雪(c02)三视图黑图 —— 换 seed 自动重跑，并按产物文件大小校验非黑。
黑图为纯黑(约13KB)，正常三视图约900KB+。成功后写 _c02_result.json。
用法: python scripts/_regen_c02.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

WF = os.path.join(ROOT, "workflows", "01_char3view_1216x832_Qwen2512_c02_Fusion.json")
OUT_ROOT = "D:/Comfy-Desktop/ComfyUI-Shared/output"
SUBDIR = "00_角色素材/小雪"
MIN_GOOD = 300 * 1024  # 300KB
MAX_TRIES = 6


def wait_done(pid, timeout=3600):
    for _ in range(timeout // 8):
        time.sleep(8)
        d = sw._get("/history/" + pid).get(pid)
        if d:
            st = d.get("status", {}).get("status_str", "running")
            if st in ("success", "error"):
                return d, st
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
    wf_path = WF
    results = []
    good = None
    for attempt in range(MAX_TRIES):
        seed = 42 + attempt * 977
        print(f"[try {attempt}] seed={seed} 提交...", flush=True)
        try:
            pid = sw.do_submit(wf_path, seed=seed)
        except SystemExit:
            print(f"[try {attempt}] 提交失败(exit)", flush=True)
            results.append({"try": attempt, "seed": seed, "ok": False, "reason": "submit_fail"})
            continue
        d, st = wait_done(pid)
        files = files_of(d) if d else []
        # 取最后一个 image 产物做校验
        chosen = None
        for f in files:
            if f.get("type") == "image" or str(f.get("filename", "")).lower().endswith((".png", ".jpg", ".jpeg")):
                chosen = f
        path = None
        size = 0
        if chosen:
            path = os.path.join(OUT_ROOT, chosen.get("subfolder", ""), chosen["filename"])
            if os.path.isfile(path):
                size = os.path.getsize(path)
        ok = (st == "success") and size >= MIN_GOOD
        info = {
            "try": attempt, "seed": seed, "pid": pid, "status": st,
            "file": chosen.get("filename") if chosen else None,
            "sizeKB": round(size / 1024), "ok": ok,
        }
        results.append(info)
        print(f"[try {attempt}] status={st} file={info['file']} size={info['sizeKB']}KB ok={ok}", flush=True)
        if ok:
            good = info
            break

    with open(os.path.join(HERE, "_c02_result.json"), "w", encoding="utf-8") as f:
        json.dump({"good": good, "results": results}, f, ensure_ascii=False, indent=2)
    print("DONE good=", json.dumps(good, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
