# -*- coding: utf-8 -*-
"""临时脚本：盯守已提交的角色三视图任务，完成后落盘产物到项目 output/00_角色素材/<角色名>/。
用法: python scripts/_watch_char3view.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

PIDS = os.path.join(HERE, "_3view_pids.json")


def main():
    items = json.load(open(PIDS, encoding="utf-8"))
    ok = fail = 0
    for it in items:
        name = it["name"]
        pid = it["pid"]
        collect_dir = os.path.join(ROOT, "output", "00_角色素材", name)
        print(f"\n===== {name} ({it['rid']}) pid={pid} =====", flush=True)
        rc = sw.do_watch(pid, poll=10, timeout=3600, collect_dir=collect_dir)
        print(
            f"[{name}] rc={rc} => {'成功' if rc == 0 else ('失败' if rc == 1 else '超时')}",
            flush=True,
        )
        if rc == 0:
            ok += 1
        else:
            fail += 1
    print(f"\nDONE 成功 {ok} / 失败 {fail} / 总 {len(items)}", flush=True)


if __name__ == "__main__":
    main()
