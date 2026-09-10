# -*- coding: utf-8 -*-
"""临时脚本：用服装签名重建后的 workflow 重新生成全部角色的三视图，
并按产物文件大小校验非黑，结果写 _all_result.json。
用法: python scripts/_regen_all.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

ROLE = [
    ("c01", "凌云", "01_char3view_1216x832_Qwen2512_Fusion.json"),
    ("c02", "小雪", "01_char3view_1216x832_Qwen2512_c02_Fusion.json"),
    ("c03", "云姐", "01_char3view_1216x832_Qwen2512_c03_Fusion.json"),
    ("c04", "陈姨", "01_char3view_1216x832_Qwen2512_c04_Fusion.json"),
    ("c05", "保镖", "01_char3view_1216x832_Qwen2512_c05_Fusion.json"),
]
OUT_ROOT = "D:/Comfy-Desktop/ComfyUI-Shared/output"
MIN_GOOD = 300 * 1024  # 300KB
MAX_TRIES = 4


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
    wf_dir = os.path.join(ROOT, "workflows")
    all_result = []
    for cid, name, wfname in ROLE:
        wf_path = os.path.join(wf_dir, wfname)
        subdir = f"00_角色素材/{name}"
        chosen = None
        info = None
        for attempt in range(MAX_TRIES):
            seed = 42 + attempt * 977
            print(f"[{cid}{name} try {attempt}] seed={seed} 提交...", flush=True)
            try:
                pid = sw.do_submit(wf_path, seed=seed)
            except SystemExit:
                print(f"[{cid}{name} try {attempt}] 提交失败", flush=True)
                continue
            d, st = wait_done(pid)
            files = files_of(d) if d else []
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
            info = {"cid": cid, "name": name, "try": attempt, "seed": seed, "pid": pid,
                    "status": st, "subdir": chosen.get("subfolder") if chosen else subdir,
                    "file": chosen.get("filename") if chosen else None,
                    "sizeKB": round(size / 1024), "ok": ok}
            print(f"[{cid}{name} try {attempt}] status={st} file={info['file']} size={info['sizeKB']}KB ok={ok}", flush=True)
            if ok:
                chosen = info
                break
        all_result.append(info)
    with open(os.path.join(HERE, "_all_result.json"), "w", encoding="utf-8") as f:
        json.dump(all_result, f, ensure_ascii=False, indent=2)
    print("DONE", json.dumps(all_result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
