# -*- coding: utf-8 -*-
"""临时脚本：重新提交全部角色三视图 workflow 到 ComfyUI 生成图片。
只提交并返回 pids（不阻塞盯守），结果写 _3view_pids.json 供后续跟踪。
用法: python scripts/_gen_char3view.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

BASE = os.path.abspath(os.path.join(HERE, "..", "workflows"))
ROLES = [("c01", "凌云"), ("c02", "小雪"), ("c03", "云姐"), ("c04", "陈姨"), ("c05", "保镖")]


def main():
    out = []
    for rid, name in ROLES:
        fname = ("01_char3view_1216x832_Qwen2512_Fusion.json"
                 if rid == "c01" else f"01_char3view_1216x832_Qwen2512_{rid}_Fusion.json")
        path = os.path.join(BASE, fname)
        if not os.path.isfile(path):
            print(f"[!!] 工作流不存在: {path}", flush=True)
            continue
        pid = sw.do_submit(path)
        out.append({"rid": rid, "name": name, "pid": pid, "wf": fname})
        print(f"SUBMITTED {rid} {name} -> {pid}", flush=True)
    with open(os.path.join(HERE, "_3view_pids.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("ALL_SUBMITTED", len(out), flush=True)


if __name__ == "__main__":
    main()
