# -*- coding: utf-8 -*-
"""按章节（集）+ 镜号动态引入【首帧+尾帧】，生成「整集 FL2VA 视频工作流」。

与 build_video_refs.py（I2V，只用首帧）同源，本脚本把每个镜的尾帧 LoadImage
也连进 GroupImageToVideo.last_frame：
  LoadImage(首帧) ──> GroupImageToVideo.first_frame
  LoadImage(尾帧) ──> GroupImageToVideo.last_frame
pack_i2v_group(first,last) 会因 first+last 同时存在而判 kind="fl2v"，Director 走
「首尾帧硬锁定」，task_type 设为 fl2v。

文件名约定（与 05_shotfirst / 06_shotlast 保存前缀去掉「!」后一致）：
  第1集_镜{shot_id}_首帧_写实CG融合{_00001_}.png
  第1集_镜{shot_id}_尾帧_写实CG融合{_00001_}.png
LoadImage 读取 ComfyUI 的 input 目录，故首尾帧图需位于：
  <ComfyUI>/input/02_分镜/第1集/

用法:
  python scripts/build_fl2va_refs.py --comfy-input D:\\Comfy-Desktop\\ComfyUI-Shared
  python scripts/build_fl2va_refs.py --shots 01,02
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys

import build_seamless_video as bsv

import comfy_config  # noqa: F401  —— import 即把 stdout/stderr 统一为 UTF-8

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.abspath(os.path.join(ROOT, "workflows"))
EXAMPLES = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\example_workflows"
SB_DB = os.path.join(ROOT, "剧本", "02_分镜", "第1集_分镜.json")
ROLE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "角色.json")

TEMPLATE = os.path.join(EXAMPLES, "minimax_h3_director_external_groups_i2v.json")

# 角色映射（speaker_id -> {name, gender, voice_en …}），由 main 加载。
# H3 对白是文字驱动：缺台词段模型会瞎编、人声漂移。compose_video_prompt 会据此注入对白。
_ROLE_MAP = None

EPISODE = "第1集"
SNAME = "写实CG融合"          # 与 05_shotfirst / 06_shotlast 保存前缀一致
IMG_SUBDIR = "02_分镜"        # output 与 input 共用的子目录
VID_W, VID_H = 1280, 736
FRAME_RATE = 24

# 与 build_video_refs.py / 09 视频工作流一致：8 步 turbo 加速。
TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
TURBO_STRENGTH = 0.75   # 社区实测：拉满 1.0 可能不跟提示词
TURBO_STEPS = 8

FL2V_TYPE = "fl2v — 首尾帧生视频(First-Last Frame)"

DROP_TYPES = (
    "LoadImage",
    "MiniMaxH3DirectorGroupImageToVideo",
    "MiniMaxH3DirectorGroupsCombine",
    "PathchSageAttentionKJ",
    "MiniMaxH3MemoryEfficientSageAttentionPatch",
)


def clean_video_prompt(p):
    # 去掉 <role>/<location> 之类角标标签；再剥离"0-3秒："这类时间窗前缀，
    # 避免被当成字面时间标记塞进 prompt（H3 Director 不解此标记）。
    text = re.sub(r"</?[a-zA-Z_]+>", "", p or "").strip()
    text = re.sub(r"\d+[\-~至]\d+\s*秒[：:]\s*", "", text)
    return text.strip()


# ---- 分镜结构化字段 → 英文镜头语言 ----
# 把分镜里中文的 movement / shot_type / angle / time 转成视频模型可识别的镜头术语，
# 让 FL2V 出片真正带"运镜 + 时段光线"，而不只是零散中文叙述。
CAM_MOVE = {
    "固定": "static locked-off shot",
    "缓推": "slow dolly-in",
    "推": "dolly-in",
    "拉镜": "slow dolly-out",
    "拉": "dolly-out",
    "摇镜": "pan across the scene",
    "摇": "pan",
    "移": "tracking shot",
    "跟": "follow shot",
    "环绕": "orbit around",
}
SHOT_TYPE_EN = {
    "远景": "wide establishing shot",
    "全景": "full shot",
    "中景": "medium shot",
    "近景": "close shot",
    "特写": "extreme close-up",
}
ANGLE_EN = {
    "平视": "eye-level angle",
    "俯视": "high angle looking down",
    "仰视": "low angle looking up",
    "背面": "viewed from behind",
}
_TIME_ASSOC = {
    "黄昏": "golden-hour dusk, warm low orange sunset light",
    "夕照": "low setting-sun afterglow, warm amber light",
    "傍晚": "evening, fading dim light, dusky",
    "天色渐暗": "sky gradually darkening, dusk deepening",
    "夜幕": "nightfall, darkening sky, deepening dusk",
    "夜色": "darkening night, dim low light",
    "白天": "daytime, bright clear natural light",
    "正午": "midday, harsh overhead sunlight",
}
# 道具一致性：FL2V 动态阶段最容易让"道具"漂移，这里显式锁定"同一批道具"。
PROP_ASSOCIATIONS = (
    ("银色手枪", "the same delicate silver pistol with a metallic glint"),
    ("佩剑", "the same sheathed ancient sword with a dark, understated scabbard"),
    ("三尺青锋", "the same three-foot green blade with a dark, understated scabbard"),
    ("剑鞘", "the same ancient sword scabbard, dark and understated"),
)


def _time_en(t):
    for key, en in _TIME_ASSOC.items():
        if key in (t or ""):
            return en
    return ""


def _prop_en(loc):
    seen, parts = set(), []
    for key, en in PROP_ASSOCIATIONS:
        if key in (loc or "") and key not in seen:
            parts.append(en)
            seen.add(key)
    if parts:
        return "consistent props, " + ", ".join(parts) + ", "
    return ""


def compose_video_prompt(sb):
    """把分镜的结构化字段拼成完整的镜头提示词（英文镜头语言前缀 + 剧情正文 + 氛围）。

    相比直接用 clean_video_prompt，补齐了：
      运镜(camera movement) / 时段光线(time of day) / 景别(shot type) / 视角(angle)
      一致道具(consistent props...) / 氛围(atmosphere)。
    剧情正文仍是分镜 video_prompt 的中文叙述，保留具体动作。
    注：video_prompt 不含台词（台词在分镜的 dialogue 字段），故末尾单独注入 H3 官方对白段，
      否则模型只能瞎编台词、人声漂移。空镜（无对白）不追加。
    """
    body = clean_video_prompt(sb.get("video_prompt") or sb.get("image_prompt"))
    cam = CAM_MOVE.get((sb.get("movement") or "").strip(), "static locked-off shot")
    st = SHOT_TYPE_EN.get((sb.get("shot_type") or "").strip(), "medium shot")
    ang = ANGLE_EN.get((sb.get("angle") or "").strip(), "eye-level angle")
    tod = _time_en(sb.get("time"))
    loc = re.sub(r"（sc\d+）", "", (sb.get("location") or "")).strip()
    prop = _prop_en(sb.get("location"))
    atmos = (sb.get("atmosphere") or "").strip()

    lead = [st, ang, cam]
    if tod:
        lead.append(tod)
    prefix = ", ".join(lead)
    # loc 可能为空（分镜 strip 缺 location 字段）：空时不要拼出多余空逗号
    if loc:
        prefix += ", " + loc
    prefix += ", "
    if prop:
        prefix += prop
    tail = (" " + atmos) if atmos else ""
    text = (prefix + body + tail).strip()

    # 注入 H3 官方对白段（缺台词则模型瞎编、人声漂移；有对白才追加）
    if _ROLE_MAP:
        dia = bsv.dialogue_segment(sb, _ROLE_MAP)
        if dia:
            text = text + "\n台词:\n" + dia
    return text


def first_frame_file(sid):
    return "%s/%s/%s_镜%s_首帧_%s_00001_.png" % (IMG_SUBDIR, EPISODE, EPISODE, sid, SNAME)


def last_frame_file(sid):
    return "%s/%s/%s_镜%s_尾帧_%s_00001_.png" % (IMG_SUBDIR, EPISODE, EPISODE, sid, SNAME)


def load_storyboards():
    with open(SB_DB, encoding="utf-8") as f:
        return json.load(f).get("storyboards", [])


def load_role_map():
    """读取角色库，生成 speaker_id -> {name, gender, voice_en …} 映射，供对白注入。"""
    global _ROLE_MAP
    if os.path.isfile(ROLE_DB):
        with open(ROLE_DB, encoding="utf-8") as f:
            _ROLE_MAP = bsv.build_role_map(json.load(f))
    return _ROLE_MAP


def load_template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return json.load(f)


def _node(nid, ntype, pos, size, order, inputs, outputs, widgets_values, props, title=None):
    node = {
        "id": nid, "type": ntype, "pos": pos, "size": size, "flags": {},
        "order": order, "mode": 0, "inputs": inputs, "outputs": outputs,
        "properties": props, "widgets_values": widgets_values,
    }
    if title:
        node["title"] = title
    return node


def _load_img_node(nid, order, pos, image_widget, title):
    return _node(
        nid, "LoadImage", pos, [270, 314], order,
        [
            {"localized_name": "图像", "name": "image", "type": "COMBO",
             "widget": {"name": "image"}, "link": None},
            {"localized_name": "选择文件上传", "name": "upload", "type": "IMAGEUPLOAD",
             "widget": {"name": "upload"}, "link": None},
        ],
        [
            {"localized_name": "图像", "name": "IMAGE", "type": "IMAGE", "links": []},
            {"localized_name": "遮罩", "name": "MASK", "type": "MASK", "links": None},
        ],
        [image_widget, "image"],
        {"Node name for S&R": "LoadImage"},
        title,
    )


def build_fl2va(storyboards, template, use_turbo=True, save_pfx=None):
    wf = copy.deepcopy(template)
    nodes = wf["nodes"]
    links = wf["links"]

    director = next(n for n in nodes if n["type"] == "MiniMaxH3Director")
    drop_ids = {n["id"] for n in nodes if n["type"] in DROP_TYPES}
    nodes = [n for n in nodes if n["id"] not in drop_ids]
    links = [l for l in links if l[1] not in drop_ids and l[3] not in drop_ids]

    next_nid = max(n["id"] for n in nodes) + 1
    next_lid = max((l[0] for l in links), default=0) + 1

    unet = next((n for n in nodes if n["type"] == "UNETLoader"), None)
    if unet is not None:
        model_slot = next((i for i, inp in enumerate(director["inputs"])
                           if inp["name"] == "model"), None)
        if model_slot is not None:
            if use_turbo:
                lora_id = next_nid
                next_nid += 1
                lora_node = _node(
                    lora_id, "LoraLoaderModelOnly", [-500, 300], [360, 82],
                    unet.get("order", 0) + 0.5,
                    [
                        {"localized_name": "模型", "name": "model", "type": "MODEL", "link": None},
                        {"localized_name": "LoRA名称", "name": "lora_name", "type": "COMBO",
                         "widget": {"name": "lora_name"}, "link": None},
                        {"localized_name": "模型强度", "name": "strength_model", "type": "FLOAT",
                         "widget": {"name": "strength_model"}, "link": None},
                    ],
                    [{"localized_name": "模型", "name": "MODEL", "type": "MODEL", "links": []}],
                    [TURBO_LORA, TURBO_STRENGTH],
                    {"Node name for S&R": "LoraLoaderModelOnly"},
                    "H3 Turbo LoRA (8-step)",
                )
                nodes.append(lora_node)
                lk_unet = next_lid
                next_lid += 1
                links.append([lk_unet, unet["id"], 0, lora_id, 0, "MODEL"])
                lora_node["inputs"][0]["link"] = lk_unet
                for out in unet["outputs"]:
                    if out["name"] == "MODEL":
                        out["links"] = [lk_unet]
                lk_dir = next_lid
                next_lid += 1
                links.append([lk_dir, lora_id, 0, director["id"], model_slot, "MODEL"])
                director["inputs"][model_slot]["link"] = lk_dir
                lora_node["outputs"][0]["links"] = [lk_dir]
            else:
                mlink = next_lid
                next_lid += 1
                links.append([mlink, unet["id"], 0, director["id"], model_slot, "MODEL"])
                director["inputs"][model_slot]["link"] = mlink
                for out in unet["outputs"]:
                    if out["name"] == "MODEL":
                        out["links"] = [mlink]

    group_ids = []
    for i, sb in enumerate(storyboards):
        sid = sb.get("shot_id")
        prompt = compose_video_prompt(sb)
        dur = float(sb.get("duration") or 5)
        stitle = (sb.get("title") or "").strip()
        order = 10 + i
        pos_x = -1500 - (i % 5) * 620
        pos_y = 100 + (i // 5) * 420

        # 首帧 LoadImage
        lid = next_nid
        next_nid += 1
        limg_link = next_lid
        next_lid += 1
        first_load = _load_img_node(
            lid, order, [pos_x, pos_y], first_frame_file(sid), "镜%s 首帧" % sid)
        first_load["outputs"][0]["links"] = [limg_link]

        # 尾帧 LoadImage
        leid = next_nid
        next_nid += 1
        leimg_link = next_lid
        next_lid += 1
        last_load = _load_img_node(
            leid, order, [pos_x + 300, pos_y], last_frame_file(sid), "镜%s 尾帧" % sid)
        last_load["outputs"][0]["links"] = [leimg_link]

        # GroupImageToVideo（first + last）
        gid = next_nid
        next_nid += 1
        group_node = _node(
            gid, "MiniMaxH3DirectorGroupImageToVideo",
            [pos_x + 620, pos_y], [400, 200], order,
            [
                {"localized_name": "first_frame", "name": "first_frame", "shape": 7,
                 "type": "IMAGE", "link": limg_link},
                {"localized_name": "last_frame", "name": "last_frame", "shape": 7,
                 "type": "IMAGE", "link": leimg_link},
                {"localized_name": "prompt", "name": "prompt", "type": "STRING",
                 "widget": {"name": "prompt"}, "link": None},
                {"localized_name": "duration_sec", "name": "duration_sec", "type": "FLOAT",
                 "widget": {"name": "duration_sec"}, "link": None},
            ],
            [{"localized_name": "group", "name": "group", "type": "MMX_DIR_GROUP", "links": None}],
            [prompt, dur],
            {"Node name for S&R": "MiniMaxH3DirectorGroupImageToVideo"},
            ("镜%s %s %ss" % (sid, stitle, ("%g" % dur))) if stitle else ("镜%s %ss" % (sid, ("%g" % dur))),
        )
        links.append([limg_link, lid, 0, gid, 0, "IMAGE"])
        links.append([leimg_link, leid, 0, gid, 1, "IMAGE"])
        nodes.append(first_load)
        nodes.append(last_load)
        nodes.append(group_node)
        group_ids.append(gid)

    # GroupsCombine（按镜头顺序串接）
    cid = next_nid
    next_nid += 1
    combine_inputs = []
    combine_links = []
    for i, gid in enumerate(group_ids):
        lk = next_lid
        next_lid += 1
        combine_inputs.append({
            "label": "group_%d" % i,
            "localized_name": "groups.group_%d" % i,
            "name": "groups.group_%d" % i,
            "shape": 7, "type": "MMX_DIR_GROUP", "link": lk,
        })
        combine_links.append(lk)
        links.append([lk, gid, 0, cid, i, "MMX_DIR_GROUP"])

    dirlink = next_lid
    next_lid += 1
    combine_node = _node(
        cid, "MiniMaxH3DirectorGroupsCombine", [-700, 300], [290, 126], 5,
        combine_inputs,
        [{"localized_name": "groups", "name": "groups", "type": "MMX_DIR_GROUP",
          "links": [dirlink]}],
        [], {"Node name for S&R": "MiniMaxH3DirectorGroupsCombine"},
    )
    nodes.append(combine_node)
    links.append([dirlink, cid, 0, director["id"], 4, "MMX_DIR_GROUP"])
    for inp in director["inputs"]:
        if inp["name"] == "i2v_groups":
            inp["link"] = dirlink

    rebuild_fl2v_timeline(director, storyboards, TURBO_STEPS if use_turbo else None)

    # 按镜号/整集重命名 SaveVideo 前缀，避免多镜共用模板默认前缀
    if save_pfx:
        for n in nodes:
            if n["type"] == "SaveVideo":
                wv = n.get("widgets_values")
                if isinstance(wv, list) and wv:
                    wv[0] = save_pfx

    wf["nodes"] = nodes
    wf["links"] = links
    wf["last_node_id"] = next_nid - 1
    wf["last_link_id"] = next_lid - 1
    return wf


def rebuild_fl2v_timeline(director, storyboards, steps=None):
    wv = director["widgets_values"]
    tl = json.loads(wv[11])
    segments, shots = [], []
    start = 0
    for i, sb in enumerate(storyboards):
        dur = float(sb.get("duration") or 5)
        fc = max(1, round(dur * FRAME_RATE))
        prompt = compose_video_prompt(sb)
        sid = sb.get("shot_id")
        seg_id = "shot%d" % i
        fimg = {"imageFile": first_frame_file(sid), "width": 0, "height": 0}
        eimg = {"imageFile": last_frame_file(sid), "width": 0, "height": 0}
        segments.append({
            "id": seg_id, "start": start, "length": fc, "frameCount": fc,
            "durationSec": dur, "prompt": prompt, "negativePrompt": "bad video",
            "isStartFrame": True, "isEndFrame": True,
            "genImage": fimg, "endImage": eimg, "taskType": "", "refs": [],
        })
        shots.append({
            "id": seg_id, "durationSec": dur, "prompt": prompt,
            "negativePrompt": "bad video",
            "startImage": fimg, "endImage": eimg,
        })
        start += fc

    tl["timelineMode"] = "fl2v"
    if isinstance(tl.get("global"), dict):
        tl["global"]["taskType"] = FL2V_TYPE
    tl["segments"] = segments
    tl["shots"] = shots
    tl["keyframes"] = []
    tl["totalFrames"] = start
    tl["durationSec"] = round(start / FRAME_RATE, 2)
    tl["frameRate"] = FRAME_RATE
    tl["width"] = VID_W
    tl["height"] = VID_H
    tl["refMaxSize"] = max(VID_W, VID_H)
    tl.setdefault("output", {})["width"] = VID_W
    tl.setdefault("output", {})["height"] = VID_H
    tl.setdefault("output", {})["longEdge"] = max(VID_W, VID_H)

    wv[0] = FL2V_TYPE
    wv[6] = FRAME_RATE
    wv[7] = VID_W
    wv[8] = VID_H
    wv[9] = max(VID_W, VID_H)
    wv[10] = start
    wv[11] = json.dumps(tl, ensure_ascii=False, separators=(",", ":"))
    if steps is not None:
        wv[13] = steps


def copy_to_input(comfy_root):
    src = os.path.join(comfy_root, "output", IMG_SUBDIR, EPISODE)
    if not os.path.isdir(src):
        print("未找到 output 首尾帧目录，跳过复制：%s" % src)
        return
    dst = os.path.join(comfy_root, "input", IMG_SUBDIR, EPISODE)
    os.makedirs(dst, exist_ok=True)
    copied = skipped = 0
    for fn in os.listdir(src):
        if not fn.endswith(".png"):
            continue
        s = os.path.join(src, fn)
        d = os.path.join(dst, fn)
        # 不拿 output 里的小文件覆盖 input 的大文件：Qwen 单镜偶发纯黑坏图（~7-13KB，
        # 正常帧 ~1.2MB），黑图一旦回灌 input 就会让成片首尾黑屏（镜01 就是这么中招的）。
        # 体积是这里唯一可用的廉价判据，且合法首尾帧尺寸恒定，降级覆盖没有正当场景。
        if os.path.isfile(d) and os.path.getsize(d) >= os.path.getsize(s):
            skipped += 1
            continue
        shutil.copy2(s, d)
        copied += 1
    print("已复制 %d 张首尾帧到 ComfyUI input：%s（跳过 %d 张不优于已有素材）" % (copied, dst, skipped))


def main():
    global VID_W, VID_H
    parser = argparse.ArgumentParser(description="按章节动态引入首尾帧，生成整集/单镜 FL2VA 工作流")
    parser.add_argument("--comfy-input", default=None)
    parser.add_argument("--shots", default=None)
    parser.add_argument("--res", default=None,
                        help="出片分辨率 WxH（默认 %dx%d）；快档用 864x480 出片后再本地超分" % (VID_W, VID_H))
    parser.add_argument("--no-turbo", action="store_true")
    args = parser.parse_args()

    if args.res:
        try:
            VID_W, VID_H = (int(x) for x in args.res.lower().replace("*", "x").split("x"))
        except ValueError:
            raise SystemExit("--res 需要形如 864x480 的分辨率，收到：%s" % args.res)

    if not os.path.isfile(TEMPLATE):
        raise SystemExit("找不到 external_groups_i2v 模板：%s" % TEMPLATE)

    storyboards = load_storyboards()
    load_role_map()  # 加载角色映射，保证 compose_video_prompt 能注入对白
    wanted = None
    if args.shots:
        # 兼容整数 shot_id(1) 与补零字符串("04")：统一归一化为 %02d，便于匹配与命名
        wanted = set()
        for s in args.shots.split(","):
            s = s.strip()
            if not s:
                continue
            wanted.add("%02d" % int(s) if s.isdigit() else s)
        storyboards = [sb for sb in storyboards
                       if "%02d" % int(sb.get("shot_id", 0)) in wanted]

    if wanted:
        tag = "镜" + "-".join(sorted(wanted))
    else:
        tag = "整集"
    save_pfx = "02_分镜/%s/%s_%s_成片_fl2v" % (EPISODE, EPISODE, tag)
    wf = build_fl2va(storyboards, load_template(), use_turbo=not args.no_turbo, save_pfx=save_pfx)

    out_name = "09_video_FL2VA_%s_%dx%d.json" % (tag, VID_W, VID_H)
    out_path = os.path.join(OUT, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)

    print("已生成：%s（共 %d 镜，动态引入首帧+尾帧）" % (out_path, len(storyboards)))
    for sb in storyboards:
        print("  镜 %s  首帧=%s  尾帧=%s  时长=%ss  %s" % (
            sb.get("shot_id"), first_frame_file(sb.get("shot_id")),
            last_frame_file(sb.get("shot_id")), sb.get("duration"), sb.get("title", "")))

    if args.comfy_input:
        copy_to_input(args.comfy_input)
    else:
        print("提示：LoadImage 读 ComfyUI input 目录，请确保首尾帧图在 "
              "input/02_分镜/第1集/ 下；可用 --comfy-input <ComfyUI根目录> 自动复制。")


if __name__ == "__main__":
    main()
