# -*- coding: utf-8 -*-
"""按章节（集）+ 镜号动态引入首帧图，生成「整集 I2V 视频工作流」。

与 build_new_workflows.py 生成的 09_video_FL2VA（导演台上传模式、图片留空手动）
不同，本脚本基于 MiniMax H3 Director 的 external_groups_i2v 模板：
  LoadImage(首帧) -> GroupImageToVideo -> GroupsCombine -> Director.i2v_groups
图片文件名按命名规范自动生成（与 05_shotfirst 固定名一一对应），
消除「出图 -> 手动选图」的断链，实现按章节动态引入。

首帧文件名约定（与 build_new_workflows.py 的 05 保存前缀一致）：
  第1集_镜{shot_id}_首帧_写实CG融合.png

LoadImage 读取 ComfyUI 的 input 目录，故首帧图需位于：
  <ComfyUI>/input/02_分镜/第1集/第1集_镜{shot_id}_首帧_写实CG融合.png
可用 --comfy-input <ComfyUI根目录> 自动把 output 下的图复制过去。

用法:
  python scripts/build_video_refs.py
  python scripts/build_video_refs.py --comfy-input D:\\Comfy-Desktop\\ComfyUI-Shared
"""
import argparse
import copy
import json
import os
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
OUT = os.path.abspath(os.path.join(ROOT, "workflows"))
EXAMPLES = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\example_workflows"
SB_DB = os.path.join(ROOT, "剧本", "02_分镜", "第1集_分镜.json")

TEMPLATE = os.path.join(EXAMPLES, "minimax_h3_director_external_groups_i2v.json")

EPISODE = "第1集"
SNAME = "写实CG融合"          # 与 05_shotfirst 保存前缀一致
IMG_SUBDIR = "02_分镜"        # output 与 input 共用的子目录
VID_W, VID_H = 1280, 736      # 与 build_new_workflows 视频横屏一致
FRAME_RATE = 24

# 8 步 turbo 加速（与 07/09 视频工作流一致）。
# 24GB 显存跑 H3 全量(fl2va int8 约 20GB) + TE(qwen3vl 32B 约 15GB) 会触发 offload，
# 每步约 200s：25 步需 ~1.2h/镜，8 步约 ~26min/镜。turbo LoRA(bf16) 与 int8 fl2va 模型兼容。
TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
TURBO_STEPS = 8

DROP_TYPES = (
    "LoadImage",
    "MiniMaxH3DirectorGroupImageToVideo",
    "MiniMaxH3DirectorGroupsCombine",
    # 可选「加速模块」节点：当前 ComfyUI 环境未注册（或已更名），
    # 移除后 UNETLoader 直连 Director.model，避免提交时报 node_errors。
    "PathchSageAttentionKJ",
    "MiniMaxH3MemoryEfficientSageAttentionPatch",
)


def clean_video_prompt(p):
    """去掉 <location>/<role> 等占位符标签，保留内容。"""
    return re.sub(r"</?[a-zA-Z_]+>", "", p or "").strip()


# ---- 分镜结构化字段 → 英文镜头语言 ----
# 让 I2V 出片带上运镜 / 时段光线 / 景别 / 视角 / 一致道具，而不只是零散中文叙述。
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
    """把分镜结构化字段拼成完整镜头提示词（英文镜头语言前缀 + 剧情正文 + 氛围）。"""
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
    prefix = ", ".join(lead) + ", " + loc + ", "
    if prop:
        prefix += prop
    tail = (" " + atmos) if atmos else ""
    return (prefix + body + tail).strip()


def first_frame_file(sid):
    # ComfyUI SaveImage 会自动追加 _00001 序号（首帧首次生成即为 00001），
    # 与 build_new_workflows.py 05_shotfirst 保存前缀去掉「!」后的实际文件名一致。
    return "%s/%s/%s_镜%s_首帧_%s_00001_.png" % (IMG_SUBDIR, EPISODE, EPISODE, sid, SNAME)


def load_storyboards():
    with open(SB_DB, encoding="utf-8") as f:
        return json.load(f).get("storyboards", [])


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


def build_i2v(storyboards, template, use_turbo=True):
    wf = copy.deepcopy(template)
    nodes = wf["nodes"]
    links = wf["links"]

    director = next(n for n in nodes if n["type"] == "MiniMaxH3Director")
    drop_ids = {n["id"] for n in nodes if n["type"] in DROP_TYPES}

    # 删除镜头相关节点 / 加速模块节点，及其涉及的 links
    nodes = [n for n in nodes if n["id"] not in drop_ids]
    links = [l for l in links if l[1] not in drop_ids and l[3] not in drop_ids]

    next_nid = max(n["id"] for n in nodes) + 1
    next_lid = max((l[0] for l in links), default=0) + 1

    # 移除 SageAttention 加速节点后，重建 UNETLoader -> [turbo LoRA] -> Director.model
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
                    [TURBO_LORA, 1.0],
                    {"Node name for S&R": "LoraLoaderModelOnly"},
                    "H3 Turbo LoRA (8-step)",
                )
                nodes.append(lora_node)
                # UNETLoader -> lora.model
                lk_unet = next_lid
                next_lid += 1
                links.append([lk_unet, unet["id"], 0, lora_id, 0, "MODEL"])
                lora_node["inputs"][0]["link"] = lk_unet
                for out in unet["outputs"]:
                    if out["name"] == "MODEL":
                        out["links"] = [lk_unet]
                # lora -> Director.model
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

        # --- LoadImage（首帧）---
        lid = next_nid
        next_nid += 1
        limg_link = next_lid
        next_lid += 1
        load_node = _node(
            lid, "LoadImage", [-1500 - (i % 5) * 300, 100 + (i // 5) * 420],
            [270, 314], order,
            [
                {"localized_name": "图像", "name": "image", "type": "COMBO",
                 "widget": {"name": "image"}, "link": None},
                {"localized_name": "选择文件上传", "name": "upload", "type": "IMAGEUPLOAD",
                 "widget": {"name": "upload"}, "link": None},
            ],
            [
                {"localized_name": "图像", "name": "IMAGE", "type": "IMAGE", "links": [limg_link]},
                {"localized_name": "遮罩", "name": "MASK", "type": "MASK", "links": None},
            ],
            [first_frame_file(sid), "image"],
            {"Node name for S&R": "LoadImage"},
            "镜%s 首帧" % sid,
        )

        # --- GroupImageToVideo ---
        gid = next_nid
        next_nid += 1
        group_node = _node(
            gid, "MiniMaxH3DirectorGroupImageToVideo", [-1100 - (i % 5) * 300, 100 + (i // 5) * 420],
            [400, 200], order,
            [
                {"localized_name": "first_frame", "name": "first_frame", "shape": 7,
                 "type": "IMAGE", "link": limg_link},
                {"localized_name": "last_frame", "name": "last_frame", "shape": 7,
                 "type": "IMAGE", "link": None},
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

        # link: LoadImage.IMAGE -> Group.first_frame
        links.append([limg_link, lid, 0, gid, 0, "IMAGE"])
        nodes.append(load_node)
        nodes.append(group_node)
        group_ids.append(gid)

    # --- GroupsCombine（按镜头顺序串接）---
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

    # Director.i2v_groups <- Combine.groups（input slot 4）
    links.append([dirlink, cid, 0, director["id"], 4, "MMX_DIR_GROUP"])
    for inp in director["inputs"]:
        if inp["name"] == "i2v_groups":
            inp["link"] = dirlink

    # 更新 Director 参数与 timeline（配 turbo 时采样步数设为 8）
    rebuild_timeline(director, storyboards, TURBO_STEPS if use_turbo else None)

    wf["nodes"] = nodes
    wf["links"] = links
    wf["last_node_id"] = next_nid - 1
    wf["last_link_id"] = next_lid - 1
    return wf


def rebuild_timeline(director, storyboards, steps=None):
    """按分镜库重建 Director 的 timeline_data，保证导演台 UI 与接线一致。

    steps 为采样步数（wv[13]）；None 则保留模板默认值（25 步）。"""
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
        segments.append({
            "id": seg_id, "start": start, "length": fc, "frameCount": fc,
            "durationSec": dur, "prompt": prompt, "negativePrompt": "bad video",
            "isStartFrame": True, "isEndFrame": False,
            "genImage": {"imageFile": first_frame_file(sid), "width": 0, "height": 0},
            "endImage": None, "taskType": "", "refs": [],
        })
        shots.append({
            "id": seg_id, "durationSec": dur, "prompt": prompt,
            "negativePrompt": "bad video",
            "startImage": {"imageFile": first_frame_file(sid), "width": 0, "height": 0},
            "endImage": None,
        })
        start += fc

    I2V_TYPE = "i2v — 图生视频(Image to Video)"
    tl["timelineMode"] = "i2v"
    if isinstance(tl.get("global"), dict):
        tl["global"]["taskType"] = I2V_TYPE

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

    # widgets_values 索引（Director object_info 字段序）：
    #   0 task_type, 1 global_prompt, 2 bd_grp_sample, 3 cfg, 4 seed,
    #   5 seed.control_after_generate, 6 frame_rate, 7 width, 8 height,
    #   9 ref_max_size, 10 total_frames, 11 timeline_data,
    #   （optional）12 bd_grp_advanced, 13 steps, 14 sampler, 15 scheduler, ...
    wv[0] = I2V_TYPE
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
        print("未找到 output 首帧目录，跳过复制：%s" % src)
        return
    dst = os.path.join(comfy_root, "input", IMG_SUBDIR, EPISODE)
    os.makedirs(dst, exist_ok=True)
    copied = 0
    for fn in os.listdir(src):
        if fn.endswith(".png"):
            shutil.copy2(os.path.join(src, fn), os.path.join(dst, fn))
            copied += 1
    print("已复制 %d 张首尾帧到 ComfyUI input：%s" % (copied, dst))


def main():
    parser = argparse.ArgumentParser(description="按章节动态引入首帧，生成整集/单镜 I2V 工作流")
    parser.add_argument("--comfy-input", default=None,
                        help="ComfyUI 根目录；提供则把 output 首尾帧复制到 input 子目录")
    parser.add_argument("--shots", default=None,
                        help="逗号分隔的镜号（如 01,02,03）；默认生成全部镜头")
    parser.add_argument("--no-turbo", action="store_true",
                        help="不插入 turbo LoRA、保持模板默认 25 步（默认插 turbo + 8 步）")
    args = parser.parse_args()

    if not os.path.isfile(TEMPLATE):
        raise SystemExit("找不到 external_groups_i2v 模板：%s" % TEMPLATE)

    storyboards = load_storyboards()
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

    wf = build_i2v(storyboards, load_template(), use_turbo=not args.no_turbo)

    # 08 = I2V 演进阶段（07 T2V / 09 FL2VA / 10 Ref2VA / 11-13 Multishot 均已占用）
    if args.shots:
        tag = "镜" + "-".join(sorted(wanted))
    else:
        tag = "整集"
    out_name = "08_video_I2V_%s_%dx%d.json" % (tag, VID_W, VID_H)
    out_path = os.path.join(OUT, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)

    print("已生成：%s（共 %d 镜，动态引入首帧）" % (out_path, len(storyboards)))
    for sb in storyboards:
        print("  镜 %s  首帧=%s  时长=%ss  %s" % (
            sb.get("shot_id"), first_frame_file(sb.get("shot_id")),
            sb.get("duration"), sb.get("title", "")))

    if args.comfy_input:
        copy_to_input(args.comfy_input)
    else:
        print("提示：LoadImage 读 ComfyUI input 目录，请确保首帧图在 "
              "input/02_分镜/第1集/ 下；可用 --comfy-input <ComfyUI根目录> 自动复制。")


if __name__ == "__main__":
    main()
