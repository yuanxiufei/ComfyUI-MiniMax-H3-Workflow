# -*- coding: utf-8 -*-
"""一条命令校验「H3 r2v 加速配置」是否真的生效（只读，不提交任务）。

检查项：
  1) turbo LoRA：是否在图上、是否真的接到 Director 的 model 口、强度是多少、文件是否存在
  2) 采样步数：转换后的 API prompt 里 Director 到底有没有带 steps。
     缺 steps = 服务端用节点默认 25 步 -> 「8 步 turbo」没生效（这是最容易被忽略的坑）
  3) 分辨率/帧数：Director 的 width/height/frame_rate/total_frames 与 timeline_data 是否自洽
  4) SageAttention：全局启动参数是否启用；图里是否还挂着 sage patch 节点
  5) 可选 --pid：读 /queue + /history，看「实际在跑/已跑完的那份 prompt」的真实参数

Usage:
  python scripts/check_speedup.py                         # 查默认整集图
  python scripts/check_speedup.py --workflow <wf.json>
  python scripts/check_speedup.py --pid <prompt_id>       # 额外核对在跑的 prompt
  python scripts/check_speedup.py --expect-steps 8 --comfy-root D:\\Comfy-Desktop\\ComfyUI-Shared

退出码：0 = 无 FAIL；1 = 有 FAIL（加速没生效 / 链路断了）
"""
import argparse
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402  复用同一套 UI->API 转换逻辑

DEF_WF = os.path.join(ROOT, "workflows", "14_video_R2VA_整集_1280x736.json")
DIRECTOR = "MiniMaxH3Director"
LORA_TURBO_HINT = "turbo"
SAGE_PATCH_TYPES = (
    "PathchSageAttentionKJ",
    "MiniMaxH3MemoryEfficientSageAttentionPatch",
    "MiniMaxH3SageAttentionPatch",
    "SageAttentionPatch",
    "MiniMaxH3SageAttention",
)
SAGE_FLAGS = ("--use-sage-attention", "--use-pp-sage-attention")

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_FAILS, _WARNS = [], []


def say(tag, msg):
    print("[%s] %s" % (tag, msg))
    if tag == FAIL:
        _FAILS.append(msg)
    elif tag == WARN:
        _WARNS.append(msg)


def safe_get(path):
    """带容错的 GET：服务端繁忙/超时只提示，不中断校验。"""
    try:
        return sw._get(path)
    except SystemExit:
        return None
    except Exception as e:  # noqa: BLE001 网络超时等
        print("  (读取 %s 失败：%s)" % (path, e))
        return None


def widget_index_map(node, obj_info):
    """复刻 submit_workflow.ui_to_api 的 widgets_values 消费顺序 -> {字段名: 下标}。

    ui_to_api 是按 /object_info 的字段顺序 + 跳过连接/动态增长口 + seed 后跟一个
    控制项 来消费 widgets_values 的，所以这里用同一套规则还原「字段 -> 下标」。
    """
    info = obj_info.get(node["type"]) or {}
    inp = info.get("input", {})
    fields = list(inp.get("required", {}).items()) + list(inp.get("optional", {}).items())
    wv = node.get("widgets_values") or []
    idx, wi = {}, 0
    for field, spec in fields:
        is_force = (isinstance(spec, list) and len(spec) >= 2
                    and isinstance(spec[1], dict) and spec[1].get("forceInput"))
        if sw._is_conn(spec) or is_force or sw._is_autogrow(spec):
            continue
        idx[field] = wi
        if wi < len(wv):
            wi += 1
            if (field == "seed" and isinstance(spec, list) and len(spec) >= 2
                    and isinstance(spec[1], dict) and spec[1].get("control_after_generate")
                    and wi < len(wv)
                    and wv[wi] in ("fixed", "increment", "decrement", "randomize")):
                wi += 1
    return idx, wv


def upstream_ids(api, node_id):
    """从某个节点出发，沿所有连接输入向上游走，返回可达节点 id 集合（不含自身）。"""
    seen, stack = set(), [str(node_id)]
    while stack:
        nid = stack.pop()
        node = api.get(nid)
        if not node:
            continue
        for v in node["inputs"].values():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in seen:
                    seen.add(v[0])
                    stack.append(v[0])
    return seen


def find_director(wf, api):
    """返回 (UI 节点, API 里的节点 id)。"""
    ui = next((n for n in wf["nodes"] if n.get("type") == DIRECTOR), None)
    if ui is None:
        return None, None
    nid = str(ui["id"])
    return ui, (nid if nid in api else None)


def check_lora(wf, api, director_id, comfy_root):
    loras = [n for n in wf["nodes"] if n.get("type") == "LoraLoaderModelOnly"]
    if not loras:
        say(FAIL, "图上没有 LoraLoaderModelOnly 节点 -> turbo 加速完全没接")
        return
    turbo = [n for n in loras if LORA_TURBO_HINT in str((n.get("widgets_values") or [""])[0]).lower()]
    if not turbo:
        names = [str((n.get("widgets_values") or [""])[0]) for n in loras]
        say(FAIL, "有 LoRA 节点但没有 turbo LoRA：%s" % ", ".join(names))
        return
    reach = upstream_ids(api, director_id) if director_id else set()
    for n in turbo:
        wv = n.get("widgets_values") or []
        name, strength = str(wv[0]), (wv[1] if len(wv) > 1 else None)
        nid = str(n["id"])
        if n.get("mode") == 4:
            say(FAIL, "turbo LoRA 节点 id=%s 被 bypass（mode=4），不生效" % nid)
        elif director_id and nid not in reach:
            say(FAIL, "turbo LoRA id=%s 存在但没接到 Director 的 model 链上 -> 不生效" % nid)
        else:
            say(OK, "turbo LoRA 已在链上：%s（强度 %s，节点 id=%s）" % (name, strength, nid))
        # 强度与文件名里的步数提示
        if strength is not None and float(strength) > 0.9:
            say(WARN, "turbo 强度 %s 偏高（社区实测建议约 0.75，拉满可能不跟提示词）" % strength)
        if comfy_root:
            p = os.path.join(comfy_root, "models", "loras", name)
            say(OK if os.path.isfile(p) else FAIL,
                "LoRA 文件%s：%s" % ("存在" if os.path.isfile(p) else "缺失", p))


def check_steps(ui_dir, api_dir, obj_info, expect_steps):
    idx, wv = widget_index_map(ui_dir, obj_info)
    # 先用 total_frames / timeline_data 自检「字段 -> 下标」映射是否可信
    trust = True
    tl_i, tf_i = idx.get("timeline_data"), idx.get("total_frames")
    try:
        tl = json.loads(wv[tl_i]) if tl_i is not None and tl_i < len(wv) else None
        if tl is None or not isinstance(tl, dict):
            trust = False
        elif tf_i is not None and wv[tf_i] != tl.get("totalFrames"):
            trust = False
    except (ValueError, TypeError, IndexError):
        trust = False

    ui_steps = wv[idx["steps"]] if "steps" in idx and idx["steps"] < len(wv) else None
    api_steps = (api_dir or {}).get("inputs", {}).get("steps")

    if api_steps is None:
        say(FAIL, "提交的 API prompt 里 Director 没有 steps 字段 -> 服务端用节点默认步数"
                  "（object_info 默认 %s），图上写的 %s 步不会生效"
            % (default_of(obj_info, "steps"), ui_steps))
        say(WARN, "图里 widgets_values 的 steps=%s%s；要让 8 步真正生效，"
                  "需让提交路径带上 steps（见 submit_workflow.ui_to_api 的可选输入处理）"
            % (ui_steps, "" if trust else "（下标映射未通过自检，仅供参考）"))
    elif int(api_steps) != int(expect_steps):
        say(FAIL, "提交的 steps=%s，期望 %s -> 加速档位不对" % (api_steps, expect_steps))
    else:
        say(OK, "提交的 steps=%s（= 期望值，turbo 8 步生效）" % api_steps)

    sampler = (api_dir or {}).get("inputs", {}).get("sampler")
    sched = (api_dir or {}).get("inputs", {}).get("scheduler")
    if sampler or sched:
        say(OK, "采样器/调度器：%s / %s" % (sampler, sched))


def default_of(obj_info, field, node_type=DIRECTOR):
    info = obj_info.get(node_type) or {}
    inp = info.get("input", {})
    for bucket in ("required", "optional"):
        spec = inp.get(bucket, {}).get(field)
        if isinstance(spec, list) and len(spec) >= 2 and isinstance(spec[1], dict):
            return spec[1].get("default")
    return None


def check_res(api_dir, ui_dir, expect_res):
    wd = (api_dir or {}).get("inputs", {})
    w, h = wd.get("width"), wd.get("height")
    if w is None or h is None:
        say(WARN, "API prompt 里拿不到 width/height，改用图上值")
        wv = ui_dir.get("widgets_values") or []
        w, h = wv[7] if len(wv) > 7 else None, wv[8] if len(wv) > 8 else None
    say(OK, "输出分辨率：%sx%s，total_frames=%s，fps=%s" % (w, h, wd.get("total_frames"), wd.get("frame_rate")))
    try:
        tl = json.loads(wd.get("timeline_data") or "{}")
        ow = (tl.get("output") or {}).get("width")
        oh = (tl.get("output") or {}).get("height")
        if ow and oh and (ow, oh) != (w, h):
            say(FAIL, "timeline_data 的 %sx%s 与节点 width/height %sx%s 不一致" % (ow, oh, w, h))
        else:
            say(OK, "timeline_data 与节点分辨率自洽（%sx%s）" % (ow, oh))
    except ValueError:
        say(WARN, "timeline_data 不是合法 JSON，无法交叉校验")
    if expect_res:
        ew, eh = expect_res
        if (w, h) == (ew, eh):
            say(OK, "命中指定分辨率 %sx%s（快档）" % (ew, eh))
        else:
            say(WARN, "分辨率 %sx%s 未命中 --res %sx%s（降档可再省一半时间）" % (w, h, ew, eh))


def check_sage(wf, object_info):
    patch = [(n["id"], n["type"]) for n in wf["nodes"] if n.get("type") in SAGE_PATCH_TYPES]
    if patch:
        say(OK, "图里有 sage patch 节点：%s" % ", ".join("%s(%s)" % p for p in patch))
    else:
        say(WARN, "图里没有 sage patch 节点（本仓库 DROP_TYPES 会删掉环境缺失的那两个），"
                  "SageAttention 只能靠启动参数全局开启")
    s = safe_get("/system_stats")
    if not s:
        return
    argv = (s.get("system") or {}).get("argv") or []
    hit = [a for a in argv if a in SAGE_FLAGS]
    if hit:
        say(OK, "启动参数已开 SageAttention：%s" % " ".join(hit))
    else:
        say(WARN, "启动参数里没有 %s -> SageAttention 未开（这是最容易白捡的一档提速）"
                  % " / ".join(SAGE_FLAGS))
    say(OK, "启动参数：%s" % (" ".join(argv) if argv else "(服务端未返回 argv)"))


def check_pid(pid, expect_steps):
    """核对「实际提交的那份 prompt」的真实参数。"""
    q = safe_get("/queue")
    if not q:
        return
    found = None
    for item in (q.get("queue_running") or []) + (q.get("queue_pending") or []):
        if len(item) >= 2 and item[1] == pid:
            found = item[2]
            break
    if found is None:
        print("[--] /queue 里没有 %s（可能已完成），改查 /history" % pid)
        hist = safe_get("/history/%s" % pid)
        if not hist:
            return
        if pid not in hist:
            say(WARN, "队列与历史里都没有 %s，无法核对在跑的参数" % pid)
            return
        found = hist[pid].get("prompt") or [None, None, {}]
        found = found[2] if isinstance(found, list) and len(found) >= 3 else {}

    d = next((n for n in found.values() if n.get("class_type") == DIRECTOR), None)
    if not d:
        say(WARN, "该 prompt 里找不到 Director 节点")
        return
    api_steps = d["inputs"].get("steps")
    if api_steps is None:
        say(FAIL, "在跑的 prompt 里 Director 没有 steps -> 实际用的是服务端默认步数，8 步 turbo 没生效")
    elif int(api_steps) != int(expect_steps):
        say(FAIL, "在跑的 prompt 里 steps=%s，期望 %s" % (api_steps, expect_steps))
    else:
        say(OK, "在跑的 prompt 里 steps=%s（turbo 8 步确实生效）" % api_steps)
    loras = [(nid, (n.get("inputs") or {}).get("lora_name"), (n.get("inputs") or {}).get("strength_model"))
             for nid, n in found.items() if n.get("class_type") == "LoraLoaderModelOnly"]
    say(OK, "在跑的 prompt 里 LoRA：%s" % (loras or "无"))
    say(OK, "在跑的 prompt 里分辨率：%sx%s" % (d["inputs"].get("width"), d["inputs"].get("height")))


def main():
    import comfy_config  # noqa: F401  —— import 即把 stdout/stderr 统一为 UTF-8
    ap = argparse.ArgumentParser(description="校验 H3 r2v 加速配置是否真的生效（只读）")
    ap.add_argument("--workflow", default=DEF_WF, help="UI-format 工作流 JSON")
    ap.add_argument("--pid", default=None, help="额外核对这个 prompt_id 的实际参数")
    ap.add_argument("--expect-steps", type=int, default=8, help="期望步数（默认 8）")
    ap.add_argument("--expect-res", default=None, help="期望分辨率，如 1280x736，用于判断是否命中降档快跑")
    ap.add_argument("--comfy-root", default=os.environ.get("COMFY_ROOT"), help="ComfyUI 根目录（校验 LoRA 文件是否存在）")
    a = ap.parse_args()

    with open(a.workflow, encoding="utf-8") as f:
        wf = json.load(f)
    print("工作流：%s" % a.workflow)
    print("ComfyUI：%s\n" % sw.HOST)

    obj_info = sw.get_object_info()
    api = sw.ui_to_api(wf, obj_info)
    ui_dir, director_id = find_director(wf, api)
    if ui_dir is None:
        say(FAIL, "图里没有 %s 节点" % DIRECTOR)
        print("\n结论：FAIL（%d 项）" % len(_FAILS))
        return 1
    api_dir = api.get(director_id) if director_id else None

    print("== 1) turbo LoRA ==")
    check_lora(wf, api, director_id, a.comfy_root)
    print("\n== 2) 采样步数（加速核心） ==")
    check_steps(ui_dir, api_dir, obj_info, a.expect_steps)
    print("\n== 3) 分辨率 / 帧数 ==")
    er = None
    if a.expect_res and "x" in a.expect_res.lower():
        p = a.expect_res.lower().split("x")
        er = (int(p[0]), int(p[1]))
    check_res(api_dir, ui_dir, er)
    print("\n== 4) SageAttention ==")
    check_sage(wf, obj_info)
    if a.pid:
        print("\n== 5) 在跑的 prompt（--pid %s） ==" % a.pid)
        check_pid(a.pid, a.expect_steps)

    print("\n结论：%s（FAIL %d / WARN %d）"
          % ("加速已生效" if not _FAILS else "加速未完全生效", len(_FAILS), len(_WARNS)))
    for m in _FAILS:
        print("  FAIL: %s" % m)
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
