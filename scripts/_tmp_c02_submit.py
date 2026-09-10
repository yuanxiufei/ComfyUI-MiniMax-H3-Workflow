# -*- coding: utf-8 -*-
"""一次性：把 c02 三视图降分辨率(1216x832 -> 1024x640)以削减采样激活显存，单次提交并盯守。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

SRC = os.path.join(ROOT, "workflows", "01_char3view_1216x832_Qwen2512_c02_Fusion.json")
TMP_WF = os.path.join(HERE, "_tmp_c02_lowres.json")
PID_FILE = os.path.join(HERE, "_tmp_c02_pid.txt")
SEED = 15777


def main():
    wf = json.load(open(SRC, encoding="utf-8"))
    changed = 0
    for n in wf["nodes"]:
        if n.get("type") == "EmptySD3LatentImage":
            n["widgets_values"] = [1024, 640, 1]
            changed += 1
    if changed == 0:
        print("ERR: 未找到 EmptySD3LatentImage 节点")
        sys.exit(1)
    json.dump(wf, open(TMP_WF, "w", encoding="utf-8"), ensure_ascii=False)
    print("低分辨率副本已写: %s (改 %d 节点)" % (TMP_WF, changed), flush=True)

    pid = sw.do_submit(TMP_WF, seed=SEED)
    open(PID_FILE, "w").write(pid)
    print("PID=%s" % pid, flush=True)

    rc = sw.do_watch(pid, poll=8, timeout=900)
    # 若盯守成功，把结果摘要写文件
    h = sw._get("/history/" + pid)
    item = h.get(pid, {})
    st = item.get("status", {}).get("status_str", "unknown")
    outs = []
    for nid, o in (item.get("outputs") or {}).items():
        for k, lst in o.items():
            if isinstance(lst, list):
                for x in lst:
                    if isinstance(x, dict) and x.get("filename"):
                        p = os.path.join("D:/Comfy-Desktop/ComfyUI-Shared/output",
                                         x.get("subfolder", ""), x["filename"])
                        sz = os.path.getsize(p) if os.path.isfile(p) else 0
                        outs.append({"node": nid, "file": x["filename"], "KB": round(sz / 1024)})
    res = {"status": st, "rc": rc, "outputs": outs}
    with open(os.path.join(HERE, "_tmp_c02_result.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("RESULT=" + json.dumps(res, ensure_ascii=False), flush=True)
    sys.exit(0 if rc == 0 else 1)


if __name__ == "__main__":
    main()
