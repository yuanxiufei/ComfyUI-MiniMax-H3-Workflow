# -*- coding: utf-8 -*-
"""Submit a UI-format workflow JSON to the local ComfyUI (/api/prompt).

Usage:
    python scripts/submit_workflow.py --submit <workflow.json> [seed]  # 快速提交，返回 prompt_id
    python scripts/submit_workflow.py --check <prompt_id>              # 查询任务结果（完成/失败/图片URL）
    python scripts/submit_workflow.py --dryrun <workflow.json>         # 只离线转换并打印 API prompt，不消耗算力

Converts the UI-format JSON (nodes/links/widgets_values) into the API prompt format.

Conversion strategy (robust vs. H3 template workflows):
  - Fetch /object_info once to know every node type's declared inputs (required + optional).
  - Connection-typed inputs (MODEL/CLIP/VAE/IMAGE/AUDIO/VIDEO/...) -> use the link target.
  - Widget inputs:
      * if the node carries properties.h3_widget_values  -> use that packed value (authoritative);
      * otherwise consume the next entry of widgets_values (in object_info field order);
      * fall back to the field's declared default.
"""
import json
import os
import shutil
import sys
import time
import urllib.request
from urllib.parse import quote

# 进度行带中文：编码统一交给 import 时的 comfy_config.setup_stdio()，
# 这里不再各写一份（避免同一份日志里 GBK/UTF-8 混杂）。
# ComfyUI 地址：统一取自 comfy_config（唯一配置源），仍可用环境变量 COMFY_HOST 覆盖。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_config as _cc  # noqa: E402

HOST = _cc.HOST

# ComfyUI "connection" input types (spec[0] is a bare uppercase string).
CONNECTION_TYPES = {
    "MODEL", "CLIP", "VAE", "IMAGE", "AUDIO", "VIDEO", "CONDITIONING",
    "LATENT", "CONTROL_NET", "STYLE_MODEL", "UPSCALE_MODEL", "SIGMAS",
    "MASK", "GUIDER", "CLIP_VISION", "TRANSFORMS", "CARLO",
    # H3 Director 自定义连接类型
    "MMX_DIR_GROUP", "MMX_DIR_REFINE",
}

# Node types that are purely cosmetic and never executed.
SKIP_TYPES = {"Note", "MarkdownNote"}


TIMEOUT = 30  # 秒；服务未启动或卡死时避免脚本长时间挂起

def _post(path, data):
    req = urllib.request.Request(
        HOST + path, data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("HTTP %s 响应内容: %s" % (e.code, body))
        raise
    except urllib.error.URLError as e:
        print("无法连接 ComfyUI (%s): %s" % (HOST, e.reason))
        print("请确认服务已启动、端口可用，且未被防火墙拦截。")
        print("  拉起桌面端实例：python scripts/comfy_config.py --ensure（或 scripts\\_start_comfyui.bat）")
        raise SystemExit(1)


def _get(path):
    try:
        with urllib.request.urlopen(HOST + path, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print("HTTP %s 响应内容: %s" % (e.code, e.read().decode("utf-8", "replace")))
        raise
    except urllib.error.URLError as e:
        print("无法连接 ComfyUI (%s): %s" % (HOST, e.reason))
        print("请确认服务已启动、端口可用，且未被防火墙拦截。")
        raise SystemExit(1)


def get_object_info():
    return _get("/object_info")


def _is_conn(spec):
    """True if the input spec is a connection slot (spec[0] is an uppercase type or '*' wildcard)."""
    if isinstance(spec, list) and isinstance(spec[0], str):
        return spec[0] in CONNECTION_TYPES or spec[0] == "*"
    return False


def _is_autogrow(spec):
    """True if the input spec is a COMFY_AUTOGROW_V3 dynamic-grow list."""
    return isinstance(spec, list) and spec and spec[0] == "COMFY_AUTOGROW_V3"


def _default(spec):
    """Best-effort default value from a widget input spec."""
    if isinstance(spec, list) and len(spec) >= 2 and isinstance(spec[1], dict):
        d = spec[1].get("default")
        if d is not None and not isinstance(d, dict):
            return d
    if isinstance(spec, list) and spec:
        c0 = spec[0]
        if isinstance(c0, list) and c0:  # combo -> first option
            return c0[0]
        if isinstance(c0, str):
            return {"INT": 0, "FLOAT": 0.0, "STRING": "", "BOOLEAN": False}.get(c0)
    return None


def _norm_num(v, t):
    """把表单值归一成 ComfyUI 能校验接受的标量类型; 无法归一返回 None."""
    if v is None:
        return None
    if isinstance(v, bool):                     # bool 是 int 子类, 需先判定
        return v
    if t == "INT":
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    if t == "FLOAT":
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    if t == "BOOLEAN":
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        try:
            return str(v).strip().lower() in ("1", "true", "yes", "on")
        except Exception:
            return None
    if t == "STRING":
        return v if isinstance(v, str) else str(v)
    return v


def _sanitize_inputs(prompt, obj_info):
    """提交前归一: 空值/类型异常的数字、布尔、字符串, 否则服务端会报节点校验错误."""
    base = {"INT": 0, "FLOAT": 0.0, "BOOLEAN": False, "STRING": ""}
    for node in prompt.values():
        nfo = obj_info.get(node["class_type"])
        if not nfo:
            continue
        fields = (list(nfo["input"].get("required", {}).items())
                  + list(nfo["input"].get("optional", {}).items()))
        for fname, spec in fields:
            if fname not in node["inputs"]:
                continue
            t = spec[0] if isinstance(spec, list) else None
            v = node["inputs"][fname]
            norm = _norm_num(v, t if isinstance(t, str) else None)
            if norm is None:                     # 仍非法 -> 用声明默认, 再不行用基础默认
                norm = _default(spec)
                if norm is None and isinstance(t, str):
                    norm = base.get(t)
            if norm is not None:
                node["inputs"][fname] = norm
    return prompt


def ui_to_api(wf, obj_info):
    """UI-format graph -> API prompt dict, guided by /object_info."""
    nodes = {n["id"]: n for n in wf["nodes"]}
    src = {}
    for link in wf["links"]:  # [link_id, src_id, src_slot, dst_id, dst_slot, type]
        src[link[0]] = (link[1], link[2])
    prompt = {}
    for nid, node in nodes.items():
        if node.get("mode") == 4:  # bypassed
            continue
        if node.get("type") in SKIP_TYPES:  # 注释节点不参与执行
            continue
        if "inputs" not in node:  # 无输入槽位的辅助节点,不参与 API prompt
            continue
        ct = node["type"]
        node_info = obj_info.get(ct)
        if not node_info:
            print("跳过未知节点类型: %s (id=%s)" % (ct, nid))
            continue
        fields = (list(node_info["input"].get("required", {}).items())
                  + list(node_info["input"].get("optional", {}).items()))
        name_map = {inp["name"]: inp for inp in node.get("inputs", []) or []}
        hv = (node.get("properties") or {}).get("h3_widget_values") or {}
        wv = node.get("widgets_values") or []
        wi = 0
        inputs = {}
        for field, spec in fields:
            entry = name_map.get(field)
            # forceInput 字段（可被 link 驱动的 widget）与连接输入同理：未连接则留空
            is_force = (isinstance(spec, list) and len(spec) >= 2
                        and isinstance(spec[1], dict) and spec[1].get("forceInput"))
            if _is_conn(spec) or is_force:
                if entry and entry.get("link") is not None:
                    s_id, s_slot = src[entry["link"]]
                    inputs[field] = [str(s_id), s_slot]
                # 无 link 的连接/强制输入 -> 不填，用节点默认
                continue
            # COMFY_AUTOGROW_V3 动态增长输入：UI 里展开为 groups.group_0/1/...
            # API 格式需扁平展开 key（如 "groups.group_0" -> [node, slot]）
            if _is_autogrow(spec):
                template = spec[1].get("template", {}) if isinstance(spec[1], dict) else {}
                prefix = template.get("prefix", "")
                for inp in node.get("inputs", []) or []:
                    nm = inp.get("name", "")
                    if prefix and nm.startswith(field + "." + prefix) and inp.get("link") is not None:
                        s_id, s_slot = src[inp["link"]]
                        inputs[nm] = [str(s_id), s_slot]
                continue
            # widget 类型输入
            if field in hv:
                inputs[field] = hv[field]
                continue
            if wi < len(wv):
                inputs[field] = wv[wi]
                wi += 1
                # seed 带 control_after_generate 时，UI 序列额外跟一个控制选项
                # (如 "randomize"/"fixed")，需多跳一位，否则后续字段全部错位。
                # 仅当下一个 widget 值确为合法控制选项字符串时才跳位，兼容未写占位的工作流。
                if (field == "seed" and isinstance(spec, list) and len(spec) >= 2
                        and isinstance(spec[1], dict)
                        and spec[1].get("control_after_generate")
                        and wi < len(wv)
                        and wv[wi] in ("fixed", "increment", "decrement", "randomize")):
                    wi += 1
            else:
                d = _default(spec)
                if d is not None:
                    inputs[field] = d
        prompt[str(nid)] = {"class_type": ct, "inputs": inputs}
    return _sanitize_inputs(prompt, obj_info)


def validate_references(api):
    """静态图校验（零算力、不触网）：检查每个 connection 输入引用的目标节点 id 均存在。
    能提前发现「转换后引用了被跳过/缺失节点」这类会导致服务端报错的错误。
    返回错误列表，空列表表示通过。"""
    ids = set(api.keys())
    errs = []
    for nid, node in api.items():
        for field, v in node["inputs"].items():
            # connection 输入形如 [str(target_id), slot]
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str):
                if v[0] not in ids:
                    errs.append(f"节点 {nid}({node['class_type']}) 的 {field} 引用了缺失节点 {v[0]}")
    return errs


def do_submit(path, seed=None):
    with open(path, encoding="utf-8") as f:
        wf = json.load(f)
    obj_info = get_object_info()
    api = ui_to_api(wf, obj_info)
    if seed is not None:
        for n in api.values():
            for k, v in n["inputs"].items():
                if k == "seed" and isinstance(v, (int, float)):
                    n["inputs"][k] = int(seed)
    resp = _post("/api/prompt", {"prompt": api, "client_id": "codebuddy"})
    if resp.get("error") or resp.get("node_errors"):
        print("提交失败:", json.dumps(resp, ensure_ascii=False))
        sys.exit(1)
    pid = resp["prompt_id"]
    print("已提交 prompt_id: %s" % pid)
    print("生成约需 1-3 分钟，稍后用 --check 查询。")
    return pid


def do_dryrun(path):
    with open(path, encoding="utf-8") as f:
        wf = json.load(f)
    obj_info = get_object_info()
    api = ui_to_api(wf, obj_info)
    out = json.dumps(api, ensure_ascii=False, indent=2)
    print(out)   # 编码已由 comfy_config.setup_stdio() 统一，无需再次 reconfigure


_EXT_KIND = {
    ".mp4": "video", ".webm": "video", ".mov": "video", ".mkv": "video", ".m4v": "video",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
    ".gif": "gif",
    ".wav": "audio", ".mp3": "audio", ".flac": "audio", ".aac": "audio",
    ".m4a": "audio", ".ogg": "audio", ".wma": "audio",
}


def _kind_of(key, filename):
    """按文件扩展名判断产物类型。

    之前用 key.rstrip("s")，但 H3 视频会挂在 outputs["images"] 名下，
    导致 mp4 被标成 "image"，下游按 kind=="video" 定位成片时落空。"""
    ext = os.path.splitext(filename)[1].lower()
    return _EXT_KIND.get(ext, key.rstrip("s"))


def _view_url(filename, subfolder="", ftype="output"):
    """构造 /view 下载地址：查询串按 UTF-8 百分号编码。

    产物名/子目录带中文时（如 02_分镜/第1集/第1集_镜01_成片_fl2v_00001_.mp4），
    原样拼进 URL 会让 http.client 按 ascii 编码请求行而抛
    "'ascii' codec can't encode character ..."，产物就永远下载不回来。
    """
    return "%s/view?filename=%s&subfolder=%s&type=%s" % (
        HOST, quote(filename, safe=""), quote(subfolder or "", safe=""), quote(ftype or "output", safe=""))


def _collect_outputs(item):
    """从 history 条目收集产物（images/videos/gifs/audio 等），返回列表。"""
    outs = []
    for nid, out in item.get("outputs", {}).items():
        for key, lst in out.items():
            if not isinstance(lst, list):
                continue
            for it in lst:
                if isinstance(it, dict) and it.get("filename"):
                    sub = it.get("subfolder", "") or ""
                    ftype = it.get("type", "output") or "output"
                    outs.append({"kind": _kind_of(key, it["filename"]), "node": nid,
                                 "filename": it["filename"], "subfolder": sub, "type": ftype,
                                 "url": _view_url(it["filename"], sub, ftype)})
    return outs


def do_check(pid):
    hist = _get("/history/%s" % pid)
    if pid not in hist:
        print("排队中或尚未开始，当前无结果。")
        return
    item = hist[pid]
    st = item.get("status", {})
    sts = st.get("status_str")
    if sts == "success":
        outs = _collect_outputs(item)
        print("完成。输出文件:")
        for o in outs:
            print("  [%s] %s" % (o["kind"], o["filename"]))
            print("  %s" % o["url"])
        if not outs:
            print("  （无产物条目，请检查输出节点）")
    elif sts == "error":
        print("生成失败:", json.dumps(st, ensure_ascii=False))
    else:
        print("状态: %s" % sts)


def _download(url, dest, fallback_rel=None):
    """下载产物到本地文件（供盯守成功后自动落盘使用）。返回是否落盘成功。

    失败时若给了 fallback_rel（= <subfolder>/<filename>），回退到共享池
    COMFY_ROOT/output 下直接拷贝：服务与共享池同机（comfy_config 的约定），
    HTTP 这条路走不通时仍然能把成片拿回来。必须返回真实结果——曾出现下载异常
    被吞掉、清单照写、还打印"已收集 1 个产物"的假成功，下游以为成片已就位。
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "codebuddy"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            f.write(r.read())
        return True
    except Exception as e:  # noqa: BLE001 网络/IO 失败只提示不中断
        print("  下载失败 %s -> %s" % (url, e))
    if not fallback_rel:
        return False
    src = os.path.join(_cc.OUTPUT_DIR, fallback_rel)
    if not os.path.isfile(src):
        print("  本地回退源不存在：%s" % src)
        return False
    try:
        shutil.copy2(src, dest)
        print("  已回退本地拷贝：%s" % src)
        return True
    except OSError as e:
        print("  本地拷贝失败 %s -> %s" % (src, e))
        return False


def _collect_to_dir(outs, collect_dir):
    """把盯守得到的产物落盘到 collect_dir，并写 collect_manifest.json。

    返回 (成功数, 失败文件名列表)；manifest 每条带 downloaded 标记。
    """
    os.makedirs(collect_dir, exist_ok=True)
    manifest, failed = [], []
    for o in outs:
        fn = o["filename"]
        sub = o.get("subfolder", "") or ""
        dest = os.path.join(collect_dir, fn)
        ok = _download(o["url"], dest, fallback_rel=os.path.join(sub, fn) if sub else fn)
        if not ok:
            failed.append(fn)
        manifest.append({"filename": fn, "subfolder": sub, "kind": o["kind"],
                         "url": o["url"], "saved": dest, "downloaded": ok})
    mf = os.path.join(collect_dir, "collect_manifest.json")
    with open(mf, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    if failed:
        print("已收集 %d/%d 个产物到 %s；失败：%s（清单 %s）"
              % (len(manifest) - len(failed), len(manifest), collect_dir, "、".join(failed), mf))
    else:
        print("已收集 %d 个产物到 %s（清单 %s）" % (len(manifest), collect_dir, mf))
    return len(manifest) - len(failed), failed


def _fmt_sec(sec):
    """秒 → h:mm:ss / m:ss，长任务（整集可达数小时）读起来更直观。"""
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return ("%d:%02d:%02d" % (h, m, s)) if h else ("%d:%02d" % (m, s))


def _queue_state(pid):
    """盯守中的队列状态：'运行中' / '排队中（前方还有 N 个任务）'；不在队列返回 None。

    运行中的 prompt 不在 /history 里，只查 history 会误报"尚未入队"。
    """
    q = _get("/queue")
    if not isinstance(q, dict):
        return None

    def _hit(it):
        if isinstance(it, (list, tuple)) and len(it) > 1:
            return it[1] == pid
        return pid in json.dumps(it, ensure_ascii=False)

    for it in q.get("queue_running") or []:
        if _hit(it):
            return "运行中"
    for i, it in enumerate(q.get("queue_pending") or []):
        if _hit(it):
            return "排队中（前方还有 %d 个任务）" % i
    return None


def do_watch(pid, poll=10, timeout=3600, collect_dir=None):
    """盯守一个 prompt_id 直到完成/失败/超时，成功返回 0、失败返回 1、超时返回 2。

    poll: 轮询间隔秒；timeout: 最大等待秒（默认 1h，H3 多镜较慢可加大）。
    collect_dir: 若给定，盯守成功后把产物下载落盘到该目录，并写 collect_manifest.json。
    """
    elapsed = 0
    print("盯守 prompt_id: %s（每 %ss 查一次，超时 %ss）" % (pid, poll, timeout))
    while elapsed < timeout:
        hist = _get("/history/%s" % pid)
        if pid in hist:
            item = hist[pid]
            st = item.get("status", {})
            sts = st.get("status_str")
            if sts == "success":
                outs = _collect_outputs(item)
                print("完成（耗时约 %ss）。产物:" % elapsed)
                for o in outs:
                    print("  [%s] %s" % (o["kind"], o["filename"]))
                    print("  %s" % o["url"])
                if not outs:
                    print("  （无产物条目，请检查输出节点）")
                if collect_dir:
                    _, failed = _collect_to_dir(outs, collect_dir)
                    if failed:
                        print("  [!] %d 个产物未落盘（生成本身是成功的，文件仍在 ComfyUI output；"
                              "清单里对应 downloaded=false）" % len(failed))
                return 0
            if sts == "error":
                errmsg = st.get("messages") or st
                print("生成失败:", json.dumps(errmsg, ensure_ascii=False))
                print("  建议：失败多为素材缺失/显存不足/模板改动。可 --no-turbo 降规格，或换 seed 重试。")
                return 1
            # 运行中/排队：打印进度（若有）
            prog = st.get("progress")
            if prog is not None:
                print("  运行中 ... %s%%（%s）" % (prog, _fmt_sec(elapsed)))
            else:
                print("  运行中/排队 ... %s" % _fmt_sec(elapsed))
        else:
            print("  %s ... %s" % (_queue_state(pid) or "尚未入队", _fmt_sec(elapsed)))
        time.sleep(poll)
        elapsed += poll
    print("超时（%ss）任务仍未完成。" % timeout)
    print("  提示：可加 --timeout 延长；或 --no-turbo 降耗时；已完成产物仍保留在 ComfyUI output。")
    return 2


def main():
    import argparse
    p = argparse.ArgumentParser(description="提交 / 查询 / 盯守 ComfyUI 工作流")
    p.add_argument("--submit", metavar="WF", help="提交 UI-format 工作流 JSON 到 /api/prompt")
    p.add_argument("--check", metavar="PID", help="查询一个 prompt_id 的结果")
    p.add_argument("--dryrun", metavar="WF", help="只离线转换为 API prompt 并打印，不消耗算力")
    p.add_argument("--watch", metavar="PID", nargs="?", const="__submit__", default=None,
                   help="盯守：配 --submit 提交后即盯，或单独 --watch <PID>")
    p.add_argument("--collect-dir", default=None,
                   help="盯守成功后把产物下载落盘到该目录，并写 collect_manifest.json（默认不落盘）")
    p.add_argument("--poll", type=int, default=10, help="盯守轮询间隔秒（默认 10）")
    p.add_argument("--timeout", type=int, default=3600, help="盯守超时秒（默认 3600）")
    p.add_argument("seed", nargs="?", metavar="SEED", help="提交时固定随机种子（可选）")
    a = p.parse_args()

    if a.submit:
        pid = do_submit(a.submit, a.seed)
        if a.watch is not None:
            return do_watch(pid, a.poll, a.timeout, a.collect_dir)
        return 0
    if a.watch is not None and a.watch != "__submit__":
        return do_watch(a.watch, a.poll, a.timeout, a.collect_dir)
    if a.check:
        do_check(a.check)
        return 0
    if a.dryrun:
        do_dryrun(a.dryrun)
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
