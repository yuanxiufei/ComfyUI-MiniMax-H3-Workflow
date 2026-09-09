# -*- coding: utf-8 -*-
"""临时脚本：批量提交首帧工作流。
用法:
    python scripts/_submit_batch_shotfirst.py all                 # 提交全部 21 镜
    python scripts/_submit_batch_shotfirst.py 01 14 21            # 只提交指定镜号
每镜只提交一次，task_type 为生图(KSampler)，返回 (workflow, prompt_id) 写入 _shotfirst_pids.txt。
"""
import json
import os
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw


def _post_raw(data):
    """提交，400 时打印 node_errors 响应体，不抛异常。"""
    req = urllib.request.Request(
        sw.HOST + "/api/prompt", data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=sw.TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("=== HTTP %s 响应体 ===" % e.code)
        try:
            print(json.dumps(json.loads(body), ensure_ascii=False, indent=2))
        except Exception:
            print(body)
        return {"error": "HTTP %s" % e.code, "body": body}

OUT = os.path.abspath(os.path.join(HERE, "..", "workflows"))
PREFIX = "05_shotfirst_1216x832_Qwen2512_Fusion_"


def shot_first_json(n):
    return os.path.join(OUT, PREFIX + n + ".json")


def main():
    args = sys.argv[1:]
    if not args:
        print("缺少参数：all 或镜号列表")
        return
    if args[0] == "all":
        shots = [f"{i:02d}" for i in range(1, 22)]
    else:
        shots = [a.zfill(2) for a in args]

    obj_info = sw.get_object_info()
    pids = []
    for n in shots:
        path = shot_first_json(n)
        if not os.path.exists(path):
            print("[缺失]", n, path)
            continue
        wf = json.load(open(path, encoding="utf-8"))
        api = sw.ui_to_api(wf, obj_info)
        resp = _post_raw({"prompt": api, "client_id": "codebuddy"})
        if resp.get("error") or resp.get("node_errors"):
            print("[FAILED]", n, json.dumps(resp, ensure_ascii=False)[:300])
            continue
        pid = resp["prompt_id"]
        pids.append((n, pid))
        print("[SUBMITTED] 镜", n, "->", pid)

    with open(os.path.join(HERE, "_shotfirst_pids.txt"), "w", encoding="utf-8") as f:
        for n, pid in pids:
            f.write(f"{n}\t{pid}\n")
    print("\n成功提交:", len(pids))


if __name__ == "__main__":
    main()
