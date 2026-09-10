import json, os, io, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
import submit_workflow as sw
HOST = sw.HOST

WF = [
    "workflows/01_char3view_1216x832_Qwen2512_Fusion.json",
    "workflows/01_char3view_1216x832_Qwen2512_c02_Fusion.json",
    "workflows/01_char3view_1216x832_Qwen2512_c03_Fusion.json",
    "workflows/01_char3view_1216x832_Qwen2512_c04_Fusion.json",
    "workflows/01_char3view_1216x832_Qwen2512_c05_Fusion.json",
]

def status(pid):
    try:
        with urllib.request.urlopen(HOST + "/history/%s" % pid, timeout=20) as r:
            hist = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return "queryskip", ""
    if pid not in hist:
        return "queued", ""
    item = hist[pid]
    st = item.get("status", {})
    s = st.get("status_str")
    outs = []
    for nid, o in item.get("outputs", {}).items():
        for k, lst in o.items():
            if isinstance(lst, list):
                for it in lst:
                    if isinstance(it, dict) and it.get("filename"):
                        outs.append(it["filename"])
    return s, outs

# 1) 全部提交
pids = []
print("=== 提交 ===")
for wf in WF:
    pid = sw.do_submit(wf)
    pids.append((wf.split("/")[-1], pid))
    print("  queue:", wf.split("/")[-1], "->", pid)

# 2) 盯守全部分支完成
print("\n=== 盯守（每 15s 轮询，总超时 1800s）===")
start = time.time()
target = {name: "queued" for name, pid in pids}
result = {name: "pending" for name, pid in pids}
while True:
    all_done = True
    for name, pid in pids:
        if result[name] in ("success", "error", "timeout"):
            continue
        s, outs = status(pid)
        if s == "success":
            result[name] = "success"
            print("  [%s] 完成: %s" % (name, outs))
        elif s == "error":
            result[name] = "error"
            print("  [%s] 失败" % name)
        else:
            all_done = False
    if all_done:
        break
    if time.time() - start > 1800:
        for name in result:
            if result[name] == "pending":
                result[name] = "timeout"
        break
    time.sleep(15)
    el = int(time.time() - start)
    print("  ... %ss（待完成: %s）" % (el, [n for n in result if result[n] == "pending"]))

print("\n=== 汇总 ===")
for name in result:
    print("  %-45s -> %s" % (name, result[name]))
