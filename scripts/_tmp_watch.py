# -*- coding: utf-8 -*-
import json, sys, time, urllib.request

HOST = "http://127.0.0.1:8188"
PIDS = {
    "c02_小雪": "ed22a980-6f57-4de0-bd17-971c5ed60a5d",
    "c03_云姐": "b3298ce6-2755-437a-bc31-364caa69f1f2",
    "c04_陈姨": "5f4f3b86-d83f-408d-9e9a-6c26c6379163",
    "c05_保镖": "bc12d29a-8cae-402c-a0e9-20dcf536d9d5",
}


def get(path):
    try:
        with urllib.request.urlopen(HOST + path, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {}


def main():
    poll = 20
    timeout = 60 * 40  # 40 分钟上限
    elapsed = 0
    state = {k: "pending" for k in PIDS}
    while elapsed < timeout:
        done = True
        for name, pid in PIDS.items():
            if state[name] in ("success", "error"):
                continue
            done = False
            hist = get("/history/%s" % pid)
            if pid in hist:
                st = hist[pid].get("status", {})
                sts = st.get("status_str")
                if sts == "success":
                    state[name] = "success"
                elif sts == "error":
                    state[name] = "error"
        elapsed += poll
        if done:
            break
        # 打印一次进度
        print("  [%ss] 状态: %s" % (elapsed, {k: v for k, v in state.items() if v != "success"} or "全部完成"))
        time.sleep(poll)

    print("=== 结果 ===")
    for name, pid in PIDS.items():
        st = state[name]
        if st == "success":
            hist = get("/history/%s" % pid)
            outs = []
            for nid, out in hist[pid].get("outputs", {}).items():
                for key, lst in out.items():
                    if not isinstance(lst, list):
                        continue
                    for it in lst:
                        if isinstance(it, dict) and it.get("filename"):
                            outs.append((key, it["filename"], it.get("subfolder", "")))
            print("  [成功] %s  %s" % (name, pid))
            for key, fn, sf in outs:
                print("      %s | subfolder=%s" % (fn, sf))
        else:
            print("  [%s] %s  %s" % (st.upper(), name, pid))


if __name__ == "__main__":
    import comfy_config  # noqa: F401  —— 统一 stdout/stderr 为 UTF-8
    main()
