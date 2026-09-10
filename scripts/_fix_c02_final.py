# -*- coding: utf-8 -*-
"""临时收尾脚本：确保小雪(c02)三视图为非黑图。
1) 若有正在跑的 c02 任务，先等它完成并校验；
2) 若仍黑，则自动换新 seed 重跑直到出非黑图(>=300KB)；
3) 结果写 _fix_c02_result.json。
用法: python scripts/_fix_c02_final.py
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
START_SEED = 9000
STEP = 977
MAX_TRIES = 10


def _get(path):
    return sw._get(path)


def queue():
    return _get("/queue")


def is_c02(pm):
    try:
        s = json.dumps(pm, ensure_ascii=False)
        return s and ("小雪" in s) and ("三视图" in s)
    except Exception:
        return False


def hist(pid):
    return _get("/history/" + pid).get(pid)


def wait_pid(pid, timeout=2400):
    for _ in range(timeout // 8):
        time.sleep(8)
        d = hist(pid)
        if d:
            st = d.get("status", {}).get("status_str", "running")
            if st in ("success", "error"):
                return d, st
    return None, "timeout"


def file_size_of(d):
    """返回最后一张 image 产物的绝对路径与大小。"""
    best = None
    for nid, o in (d.get("outputs") or {}).items():
        for kind, lst in o.items():
            if not isinstance(lst, list):
                continue
            for x in lst:
                if isinstance(x, dict) and x.get("filename"):
                    best = x
    if not best:
        return None, 0
    p = os.path.join(OUT_ROOT, best.get("subfolder", ""), best["filename"])
    size = os.path.getsize(p) if os.path.isfile(p) else 0
    return p, size


def latest_c02_file():
    """扫描小雪目录，返回最新的 c02 png 及其大小。"""
    d = os.path.join(OUT_ROOT, SUBDIR)
    best = None
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.lower().startswith("c02") and f.lower().endswith(".png"):
                p = os.path.join(d, f)
                if best is None or os.path.getmtime(p) > os.path.getmtime(best):
                    best = p
    return best, (os.path.getsize(best) if best else 0)


def main():
    # phase 1: 等在跑的 c02 任务完成
    print("[phase1] 检查是否有正在运行的 c02 任务", flush=True)
    while True:
        q = queue()
        running = [i for i in q.get("queue_running", []) if len(i) > 2 and is_c02(i[2])]
        if not running:
            break
        pid = str(running[0][1])
        print("  c02 正在运行 pid=%s，等待完成..." % pid, flush=True)
        d, st = wait_pid(pid)
        print("  pid=%s -> %s" % (pid, st), flush=True)
        break

    # phase 2: 校验当前最新 c02 文件
    p, sz = latest_c02_file()
    print("[phase2] 当前最新 c02: %s  %sKB" % (os.path.basename(p or ""), round(sz / 1024)), flush=True)
    if sz >= MIN_GOOD:
        key = {"good": True, "file": p, "sizeKB": round(sz / 1024), "from": "existing"}
        with open(os.path.join(HERE, "_fix_c02_result.json"), "w", encoding="utf-8") as f:
            json.dump(key, f, ensure_ascii=False, indent=2)
        print("DONE already-good", json.dumps(key, ensure_ascii=False), flush=True)
        return

    # phase 3: 循环换 seed 重跑
    results = []
    for k in range(MAX_TRIES):
        seed = START_SEED + k * STEP
        print("[phase3 try %d] seed=%s 提交..." % (k, seed), flush=True)
        try:
            pid = sw.do_submit(WF, seed=seed)
        except SystemExit:
            print("  提交失败(exit)", flush=True)
            results.append({"try": k, "seed": seed, "ok": False})
            continue
        d, st = wait_pid(pid)
        p, sz = file_size_of(d) if d else (None, 0)
        ok = (st == "success") and sz >= MIN_GOOD
        info = {"try": k, "seed": seed, "pid": pid, "status": st,
                "file": p, "sizeKB": round(sz / 1024), "ok": ok}
        results.append(info)
        print("  pid=%s %s -> %sKB ok=%s" % (pid, st, info["sizeKB"], ok), flush=True)
        if ok:
            good = info
            with open(os.path.join(HERE, "_fix_c02_result.json"), "w", encoding="utf-8") as f:
                json.dump({"good": good, "results": results}, f, ensure_ascii=False, indent=2)
            print("DONE good", json.dumps(good, ensure_ascii=False), flush=True)
            return

    with open(os.path.join(HERE, "_fix_c02_result.json"), "w", encoding="utf-8") as f:
        json.dump({"good": None, "results": results}, f, ensure_ascii=False, indent=2)
    print("DONE all-failed", flush=True)


if __name__ == "__main__":
    main()
