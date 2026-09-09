# -*- coding: utf-8 -*-
"""按章节（集）+ 镜号动态引入【角色三视图 + 场景九宫格】参考图，生成「整集 r2v 参考生视频工作流」。

核心思路（H3 官方 Reference-to-Video，参考锁一致性）：
- 每个镜段用 MiniMaxH3DirectorGroupReferenceToVideo，
  把「该镜角色三视图 + 场景九宫格」通过 ref_images.ref_image_N 连进去，
  提示词用 <Picture N> 引用参考图 → 角色身份 + 场景环境被参考图硬锁。
- 跨集时同一角色用同一张三视图、同一场景(scene_id)用同一张九宫格 →
  角色与场景跨集保持一致（不再靠分镜文字复现，杜绝漂移）。

参考图产物命名（与 build_new_workflows.py 的保存前缀一致，取 _00001_ 首张）：
  角色三视图: 00_角色素材/{角色名}/{角色id}_三视图_{风格}_00001_.png
  场景九宫格: 01_场景素材/{场景名}/{场景名}_九宫格_00001_.png

差异（相对 build_fl2va_refs.py 首尾帧版）：
- 模板用 external_groups_r2v（Director 走 r2v_groups，而非 i2v_groups）
- 节点类型 GroupImageToVideo → GroupReferenceToVideo（接 ref_image_N）
- 权重用 ref2va（minimax_h3_ref2va_pruned_int8_convrot），不接 fl2v turbo LoRA
- 参考图来自角色/场景素材（output），而非分镜首尾帧

用法:
  python scripts/build_r2v_refs.py --comfy-input D:\\Comfy-Desktop\\ComfyUI-Shared
  python scripts/build_r2v_refs.py --shots 02
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
CHAR_DB = os.path.join(ROOT, "剧本", "03_角色场景", "角色.json")
SCENE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "场景.json")
VOICE_DB = os.path.join(ROOT, "剧本", "04_音色", "音色库.json")

TEMPLATE = os.path.join(EXAMPLES, "minimax_h3_director_external_groups_r2v.json")

EPISODE = "第1集"
SNAME = "写实CG融合"                       # 与 01_char3view 保存前缀一致
CHAR_PREFIX = "00_角色素材"                # output 与 input 共用子目录
SCENE_PREFIX = "01_场景素材"
VID_W, VID_H = 1280, 736
FRAME_RATE = 24

# r2v 专用权重（不同于 fl2va / fl2v turbo）
REF2VA_UNET = "minimax_h3_ref2va_pruned_int8_convrot.safetensors"

R2V_TYPE = "r2v — 参考主体生视频(Reference to Video)"

# 删除"按镜重建"的图/组节点 + 模板自带的模型链路里当前环境缺失的节点。
# 注：外部模板用 unet→patch(PathchSageAttentionKJ)→sage(MemoryEfficientSageAttentionPatch)→director，
# 但当前 ComfyUI 未安装这两个节点，director.model 若引用它们会断链，故删掉并让 unet 直连 director。
DROP_TYPES = (
    "LoadImage",
    "MiniMaxH3DirectorGroupReferenceToVideo",
    "MiniMaxH3DirectorGroupsCombine",
    "PathchSageAttentionKJ",                      # 环境缺失的 attention patch
    "MiniMaxH3MemoryEfficientSageAttentionPatch",  # 环境缺失的 sage patch
    "VHS_LoadVideo",                              # 模板残留参考视频，未使用
)


def clean_video_prompt(p):
    """去掉 <xxx>...</xxx> 内部标签，保留内容文本（<role>梁八斗</role> → 梁八斗）。"""
    return re.sub(r"</?[a-zA-Z_]+>", "", p or "").strip()


def _load_json(path, key, default=None):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key, default) if isinstance(data, dict) else data


def load_storyboards():
    return _load_json(SB_DB, "storyboards", [])


def load_id_name(db_path, key, id_prefix):
    """返回 {id: name} 映射，id 形如 c01 / sc001。key 为顶层数组字段名（characters/scenes）。"""
    items = _load_json(db_path, key, []) or []
    if isinstance(items, dict):
        items = list(items.values())
    out = {}
    for it in items:
        cid = it.get("id", "")
        if str(cid).startswith(id_prefix):
            out[cid] = it.get("name", "")
    return out


def load_template():
    with open(TEMPLATE, encoding="utf-8") as f:
        return json.load(f)


def load_voice_map():
    """返回 {姓名: voice}，用于给台词标注说话人音色（让 H3 拟声更准）。"""
    voices = _load_json(VOICE_DB, "voices", []) or []
    if isinstance(voices, dict):
        voices = list(voices.values())
    return {v.get("name"): v for v in voices if v.get("name")}


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


# ---------- 上一镜成片尾帧（跨镜锁船/锁构图） ----------

def extract_tail_frame(video_path, out_png):
    """用 opencv 读取视频最后一帧，存为 PNG。返回 True/False。"""
    try:
        import cv2
    except Exception:
        print("  [!] 未安装 opencv(cv2)，无法提取上一镜尾帧，跳过")
        return False
    if not os.path.isfile(video_path):
        return False
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False
    try:
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if n <= 0:
            return False
        cap.set(cv2.CAP_PROP_POS_FRAMES, n - 1)
        ok, frame = cap.read()
        if ok and frame is not None:
            os.makedirs(os.path.dirname(out_png), exist_ok=True)
            # 用 imwrite 的 Unicode 安全写法：cv2 对中文路径需用 np 数组 + 手动编码，
            # 这里直接用 imencode+tofile 兼容中文目录。
            ret, buf = cv2.imencode(".png", frame)
            if not ret:
                return False
            buf.tofile(out_png)
            return True
        return False
    finally:
        cap.release()


# ---------- 参考图路径 ----------

def char_ref_file(cid, name):
    return "%s/%s/%s_三视图_%s_00001_.png" % (CHAR_PREFIX, name, cid, SNAME)


def scene_ref_file(sid, name, panel=1):
    """场景参考改为「单一机位」单格（panel1..9），而非整张九宫格拼图。"""
    return "%s/%s/%s_panel%d_00001_.png" % (SCENE_PREFIX, name, name, panel)


def panel_for_shot(sb):
    """按镜头的 景别/角度/运镜 从场景九宫格中选对应机位单格。

    九宫格机位约定（build_new_workflows.SCENE_GRID_PANELS）：
      panel1 大远景定场 / 2 远景全景 / 3 广角地面 /
      4 前景边缘中景 / 5 平视中景 / 6 仰视 /
      7 俯视鸟瞰 / 8 关键道具特写 / 9 暮色变体
    """
    st = (sb.get("shot_type") or "").strip()     # 景别
    ang = (sb.get("angle") or "").strip()        # 角度
    mv = (sb.get("movement") or "").strip()      # 运镜
    # 角度优先
    if "俯视" in ang or "俯拍" in ang or "鸟瞰" in ang:
        return 7
    if "仰视" in ang or "仰拍" in ang or "低角度" in ang:
        return 6
    if "背面" in ang or "背影" in ang:
        return 2
    # 景别
    if "特写" in st or "近景" in st:
        # 大远景/广角转场时仍可能需要俯视，但近景归特写道具前一层
        return 8 if "道具" in (sb.get("action") or "") else 4
    if "中景" in st:
        return 5
    if "远景" in st:
        return 2
    if "全景" in st:
        return 1
    if "广角" in st:
        return 3
    # 无景别信息：按运镜兜底
    if "拉" in mv:
        return 2
    if "推" in mv:
        return 4
    return 1


def ref_exists(comfy_root, rel):
    """参考图是否已生成（output 目录）。"""
    return os.path.isfile(os.path.join(comfy_root, "output", rel))


# ---------- 参考图收集（每镜） ----------

def collect_refs(sb, char_map, scene_map, comfy_root):
    """返回 (ref_items, ref_image_files, refs_slots)。

    ref_items: [(kind,cid_or_sid,name)] , kind in ('char','scene')
    ref_image_files: 该镜引用到的参考图相对路径列表（<Picture 1..N> 顺序，角色在前，场景在后）
    refs_slots: 参考图文件（含存在的），用于 timeline segments[].refs
    """
    # 角色：该镜 character_ids（无角色如空镜则为空）
    char_items = []
    for cid in sb.get("character_ids", []) or []:
        name = char_map.get(cid)
        if not name:
            print("  [!] 未知角色 id %s，跳过" % cid)
            continue
        char_items.append(("char", cid, name))

    # 场景：该镜 scene_id，按机位选对应单格
    scene_items = []
    sid = sb.get("scene_id", "")
    sname = scene_map.get(sid)
    spanel = panel_for_shot(sb)
    if sname:
        scene_items.append(("scene", sid, sname, spanel))
    else:
        print("  [!] 未知场景 id %s，跳过场景参考" % sid)

    # 角色 ref_items 保持 (kind,cid,name)；场景多一个 panel 字段
    ref_items = char_items + [("scene", sid, sname, spanel)]
    ref_image_files = []
    refs_slots = []
    missing = False
    for item in ref_items:
        kind = item[0]
        cid = item[1]
        name = item[2]
        if kind == "char":
            rel = char_ref_file(cid, name)
        else:
            rel = scene_ref_file(sid, name, item[3])
        if ref_exists(comfy_root, rel):
            ref_image_files.append(rel)
            # timeline 里 refs 的 imageFile 用相对 input 的路径（LoadImage 同名读取）
            refs_slots.append({"index": len(refs_slots), "imageFile": rel,
                               "fileName": "", "type": "input", "subfolder": ""})
        else:
            print("  [!] 参考图未生成，跳过：%s" % rel)
            missing = True
    return ref_items, ref_image_files, refs_slots, missing


# ---------- 提示词：带 <Picture N> 引用 ----------

def _voice_of(name, voice_map):
    """按说话人姓名匹配音色描述。"""
    v = voice_map.get(name or "")
    if not v:
        return ""
    return v.get("voice_desc", "") or ""


# ---------- 道具锁定：r2v 场景参考权重低于角色三视图，船/道具最易漂移 ----------
# 从 location/description 里识别"本场景关键道具"，在主体定义中显式声明其必须与参考图一致。
PROP_LOCK = (
    ("银色手枪", "银色手枪（精致小巧的银色手枪，枪身泛着金属冷光，剧情关键道具）"),
    ("佩剑", "佩剑（入鞘的古剑，剑鞘古朴暗沉）"),
    ("三尺青锋", "三尺青锋（剑鞘古朴暗沉，透着凛冽剑意）"),
    ("剑鞘", "古剑的剑鞘（古朴暗沉，剑身锈死难以拔出）"),
)
# 道具词 → 用于锁定句子中的称呼（避免重复短词）
_PROP_SEEN = set()
_prop_desc_cache = {}


def prop_lock_phrase(sb):
    """从分镜 location/description 提取关键道具，返回中文锁定描述；无敏感道具返回 ""。"""
    text = "%s %s" % ((sb.get("location") or ""), (sb.get("description") or ""))
    seen, parts = set(), []
    for kw, cn in PROP_LOCK:
        if kw in text and kw not in seen:
            parts.append(cn)
            seen.add(kw)
    if not parts:
        return ""
    return "本镜及后续所有镜头中，%s 必须与参考图完全一致（形状、破损程度、位置均不得改变或漂移）。" % (
        "、".join(parts))


def build_ref_prompt(sb, ref_items, base_prompt, voice_map=None, extra_refs=None):
    """构造 r2v 提示词：主体定义（<Picture N> 锁角色/场景 + 上一镜尾帧 + 道具锁定）
    + 详细描述（分镜动作/对白/音效）。

    ref_items 元素：角色为 ('char',cid,name)，场景为 ('scene',sid,name,panel)。
    角色参考提供三视图锁定形象；场景参考提供单一机位单格锁定该镜构图。
    extra_refs：额外参考图（如上一镜成片尾帧），元素为 (rel_path, 中文说明)，
        会拼到主体定义末尾，要求本镜起始画面与该帧完全延续（锁船/锁构图）。
    """
    voice_map = voice_map or {}
    pic_no = 1
    lines = []
    # 是否含人物：人物对话镜（近景/中景、有角色）应让【人物】成为画面主体，场景仅作背景陪衬。
    has_char = any(it[0] == "char" for it in ref_items)
    for item in ref_items:
        kind, name = item[0], item[2]
        if kind == "char":
            lines.append("<Picture %d> 是角色《%s》的三视图参考：锁定该角色的面容、发型、"
                         "体态、服装与随身道具，本镜及后续所有镜头中该角色形象须与此完全一致。"
                         % (pic_no, name))
        else:
            if has_char:
                # 对话镜：场景只取环境色调/光线/背景，画面主体是人（不能画成纯粹的空景/船景）。
                lines.append(
                    "<Picture %d> 是场景《%s》的参考：仅取其环境地貌、建筑与道具、光线色调，"
                    "作为本镜【背景与前景道具】的陪衬。本镜是人物对话镜头，画面主体必须是人物"
                    "（该镜 <role> 所指的角色占画面中心，近景/中景，正面或半侧对镜头），"
                    "城堡、喷泉、庭院、树木、轿车等环境元素只作为人物周围的背景与前景，"
                    "不得抢占画面中心、不得以空无一人的空场景开场。"
                    % (pic_no, name))
            else:
                lines.append("<Picture %d> 是场景《%s》的单机位参考：仅取其环境地貌、建筑与道具、"
                             "光线色调与构图，锁定本镜该机位的空间与氛围，禁止出现参考图之外的地标或道具。"
                             % (pic_no, name))
        pic_no += 1
    # 上一镜尾帧：作为起始画面参考，强制本镜起点与之延续（锁船/锁构图）。
    for rel, note in (extra_refs or []):
        lines.append("<Picture %d> 是上一镜头结尾画面（%s）：本镜画面必须从该帧无缝延续，"
                     "其中的人物、道具、光线、人物位置须与原帧完全一致，禁止出现不同形状或位置的人物与道具。"
                     % (pic_no, note))
        pic_no += 1
    # 道具锁定：r2v 里场景参考权重低，船/道具易漂，显式点名须与参考一致。
    plock = prop_lock_phrase(sb)
    if plock:
        lines.append(plock)
    head = "主体定义:\n" + "\n".join(lines)

    detail = clean_video_prompt(base_prompt)
    parts = [head, "详细描述:\n" + detail]

    # 台词：H3 对白由文字驱动，缺台词则只能瞎编，声音必乱。
    # 说话人在 dialogue 内标注（如「梁八斗：（叹气）xxx」），据此补音色描述。
    dia = (sb.get("dialogue") or "").strip()
    if dia:
        spoke = re.match(r"^\s*([^：:（(]+)[：:]", dia)
        sname = spoke.group(1).strip() if spoke else (sb.get("speaker", "") or "")
        vdesc = _voice_of(sname, voice_map) or ""
        line_dia = ("（说话人：%s%s）\n%s" % (sname, ("；%s" % vdesc) if vdesc else "", dia)
                    if sname else dia)
        parts.append("台词:\n" + line_dia)
    # BGM 与音效：引导生成贴合氛围的环境声。
    bgm = (sb.get("bgm_prompt") or "").strip()
    sfx = (sb.get("sound_effect") or "").strip()
    if bgm:
        parts.append("背景音乐:\n" + bgm)
    if sfx:
        parts.append("音效:\n" + sfx)
    return "\n\n".join(parts)


# ---------- 工作流构建 ----------

def extract_prev_tail_ref(prev_sid, prev_video, comfy_root, rel):
    """从上一镜成片提取尾帧，直接写入 ComfyUI input/rel 供本镜 LoadImage/refs 使用。

    返回 (rel_path, note) 供 <Picture> 引用；失败返回 None。
    """
    dst_png = os.path.join(comfy_root, "input", rel)
    ok = extract_tail_frame(prev_video, dst_png)
    if not ok:
        print("  [!] 提取上一镜(%s)尾帧失败，跳过尾帧参考" % prev_sid)
        return None
    print("  [ok] 复用上一镜(%s)尾帧 → %s" % (prev_sid, rel))
    return (rel, "上一镜" + prev_sid + "结尾画面")


def build_r2v(storyboards, template, char_map, scene_map, comfy_root, voice_map=None,
              prev_tail_map=None):
    wf = copy.deepcopy(template)
    nodes = wf["nodes"]
    links = wf["links"]

    director = next(n for n in nodes if n["type"] == "MiniMaxH3Director")
    drop_ids = {n["id"] for n in nodes if n["type"] in DROP_TYPES}
    nodes = [n for n in nodes if n["id"] not in drop_ids]
    links = [l for l in links if l[1] not in drop_ids and l[3] not in drop_ids]

    next_nid = max(n["id"] for n in nodes) + 1
    next_lid = max((l[0] for l in links), default=0) + 1

    # 权重切换：fl2va → ref2va（r2v 参考生视频必须用 ref2va，非 fl2v turbo）
    unet = next((n for n in nodes if n["type"] == "UNETLoader"), None)
    if unet is not None:
        unet["widgets_values"] = [REF2VA_UNET, unet["widgets_values"][-1] if unet["widgets_values"] else "default"]
        unet["title"] = "MiniMax H3 UNET (r2v ref2va)"
        unet.setdefault("properties", {})["models"] = [
            {"name": REF2VA_UNET, "directory": "diffusion_models"}]

    # Director 的 model 输入：环境缺失 patch/sage 节点，改为让 unet 直接驱动 Director。
    d_model_slot = next((i for i, inp in enumerate(director["inputs"])
                         if inp["name"] == "model"), None)
    if unet is not None and d_model_slot is not None:
        mlk = next_lid
        next_lid += 1
        if unet["outputs"] and unet["outputs"][0].get("links") is not None:
            unet["outputs"][0]["links"] = [mlk]
        links.append([mlk, unet["id"], 0, director["id"], d_model_slot, "MODEL"])
        director["inputs"][d_model_slot]["link"] = mlk

    # Director 的 r2v_groups 输入槽
    r2v_slot = next((i for i, inp in enumerate(director["inputs"])
                     if inp["name"] == "r2v_groups"), None)
    if r2v_slot is None:
        raise SystemExit("模板中未找到 Director 的 r2v_groups 输入槽")

    group_ids = []
    for i, sb in enumerate(storyboards):
        sid = sb.get("shot_id")
        dur = float(sb.get("duration") or 5)
        stitle = (sb.get("title") or "").strip()
        order = 10 + i
        pos_x = -1600 - (i % 4) * 640
        pos_y = 60 + (i // 4) * 400

        ref_items, ref_files, refs_slots, missing = collect_refs(sb, char_map, scene_map, comfy_root)
        # 上一镜尾帧参考（跨镜锁船/锁构图）：按 prev_tail_map 找到上一镜成片，提取尾帧作为额外参考图。
        extra_refs = []
        if prev_tail_map and sid in prev_tail_map:
            prev_sid, prev_video = prev_tail_map[sid]
            ref_rel = "01_场景素材/%s/prev_tail_%s_00001_.png" % (
                scene_map.get(sb.get("scene_id", ""), ""), prev_sid)
            er = extract_prev_tail_ref(prev_sid, prev_video, comfy_root, ref_rel)
            if er:
                extra_refs.append(er)
                ref_files = ref_files + [er[0]]
                refs_slots = refs_slots + [{"index": len(refs_slots),
                                            "imageFile": er[0], "fileName": "",
                                            "type": "input", "subfolder": ""}]
        # 分镜衔接：衔接上一镜结尾（若有上一镜，则继承其人物/机位/氛围延续）
        prev_tail = ''
        if i > 0:
            ph = (storyboards[i - 1].get("result") or "").strip()
            if ph:
                prev_tail = ("\n本镜承接上一镜结尾（%s），保持人物位置、光线明暗与氛围连贯，"
                             "避免突兀跳切。" % ph)
        prompt = build_ref_prompt(sb, ref_items,
                                  (sb.get("video_prompt") or sb.get("image_prompt")) + prev_tail,
                                  voice_map, extra_refs)

        # 参考图 LoadImage（每个 <Picture> 一张）
        load_ids, load_links = [], []
        for idx, rel in enumerate(ref_files):
            lid = next_nid
            next_nid += 1
            lk = next_lid
            next_lid += 1
            load = _load_img_node(lid, order, [pos_x + idx * 300, pos_y],
                                  rel, "参考图%d %s" % (idx + 1, os.path.basename(rel)))
            load["outputs"][0]["links"] = [lk]
            nodes.append(load)
            load_ids.append(lid)
            load_links.append(lk)

        # GroupReferenceToVideo 节点（ref_images.ref_image_0..N）
        group_inputs = []
        for idx in range(len(ref_files)):
            group_inputs.append({
                "label": "ref_image_%d" % idx,
                "localized_name": "ref_images.ref_image_%d" % idx,
                "name": "ref_images.ref_image_%d" % idx,
                "shape": 7, "type": "IMAGE", "link": load_links[idx],
            })
        group_inputs.append({"localized_name": "prompt", "name": "prompt",
                             "type": "STRING", "widget": {"name": "prompt"}, "link": None})
        group_inputs.append({"localized_name": "duration_sec", "name": "duration_sec",
                             "type": "FLOAT", "widget": {"name": "duration_sec"}, "link": None})

        gid = next_nid
        next_nid += 1
        group_node = _node(
            gid, "MiniMaxH3DirectorGroupReferenceToVideo",
            [pos_x + 200, pos_y + 320], [420, 200], order,
            group_inputs,
            [{"localized_name": "group", "name": "group", "type": "MMX_DIR_GROUP", "links": None}],
            [prompt, dur],
            {"Node name for S&R": "MiniMaxH3DirectorGroupReferenceToVideo"},
            (("镜%s %s %ss" % (sid, stitle, ("%g" % dur))) if stitle
             else ("镜%s %ss" % (sid, ("%g" % dur)))),
        )
        for idx, lk in enumerate(load_links):
            links.append([lk, load_ids[idx], 0, gid, idx, "IMAGE"])
        nodes.append(group_node)
        group_ids.append((gid, sid, refs_slots, prompt, missing, dur))

    # GroupsCombine（按镜头顺序串接）
    cid = next_nid
    next_nid += 1
    combine_inputs, combine_links = [], []
    for i, (gid, _, _, _, _, _) in enumerate(group_ids):
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
        cid, "MiniMaxH3DirectorGroupsCombine", [-760, 40], [290, 126], 5,
        combine_inputs,
        [{"localized_name": "groups", "name": "groups", "type": "MMX_DIR_GROUP", "links": [dirlink]}],
        [], {"Node name for S&R": "MiniMaxH3DirectorGroupsCombine"},
    )
    nodes.append(combine_node)
    links.append([dirlink, cid, 0, director["id"], r2v_slot, "MMX_DIR_GROUP"])
    director["inputs"][r2v_slot]["link"] = dirlink

    rebuild_r2v_timeline(director, group_ids)

    wf["nodes"] = nodes
    wf["links"] = links
    wf["last_node_id"] = next_nid - 1
    wf["last_link_id"] = next_lid - 1
    return wf


def rebuild_r2v_timeline(director, group_ids):
    wv = director["widgets_values"]
    tl = json.loads(wv[11])
    segments, shots = [], []
    start = 0
    for i, (gid, sid, refs_slots, prompt, missing, dur) in enumerate(group_ids):
        fc = max(1, round(float(dur) * FRAME_RATE))
        segments.append({
            "id": "shot%d" % i, "start": start, "length": fc, "frameCount": fc,
            "durationSec": float(dur), "prompt": prompt, "negativePrompt": "bad video",
            "taskType": "", "refs": refs_slots, "refAudios": [], "refVideos": [],
            "genImage": {"imageFile": "", "fileName": ""},
            # 段间引导：每段(除首段 index0 自动不 pin)引用上一段尾帧作为本段开头，
            # H3 会在批内把上一段尾帧 pin 进本段 conditioning 并裁掉前缀 → 跨镜无缝衔接。
            "continuityFromPrev": True,
        })
        shots.append({
            "id": "shot%d" % i, "durationSec": float(dur), "prompt": prompt,
            "negativePrompt": "bad video",
            "startImage": None, "endImage": None,
        })
        start += fc

    tl["timelineMode"] = "prompt_batch"
    if isinstance(tl.get("global"), dict):
        tl["global"]["taskType"] = R2V_TYPE
        tl["global"]["prompt"] = ""
        tl["global"]["refs"] = []
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
    # 段间引导主开关：多镜同批时 H3 自动做「上一段尾帧 → 下一段」无缝衔接
    tl.setdefault("output", {})["continuityEnabled"] = True
    tl.setdefault("output", {})["continuityOverlapFrames"] = 22   # 官方默认 motion-context 窗口

    wv[0] = R2V_TYPE
    wv[6] = FRAME_RATE
    wv[7] = VID_W
    wv[8] = VID_H
    wv[9] = max(VID_W, VID_H)
    wv[10] = start          # Director 的 total_frames，与 timeline_data.totalFrames 对齐
    wv[11] = json.dumps(tl, ensure_ascii=False, separators=(",", ":"))


def copy_refs_to_input(comfy_root, ref_files):
    """把参考图从 output/<子目录> 复制到 input/<子目录>（LoadImage 读 input）。"""
    copied = 0
    for rel in ref_files:
        src = os.path.join(comfy_root, "output", rel)
        dst = os.path.join(comfy_root, "input", rel)
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.abspath(src) != os.path.abspath(dst):
                shutil.copy2(src, dst)
            copied += 1
    print("已复制 %d 张参考图到 ComfyUI input" % copied)
    return copied


def main():
    parser = argparse.ArgumentParser(description="按章节动态引入角色三视图+场景九宫格，生成整集/单镜 r2v 工作流")
    parser.add_argument("--comfy-input", default=None)
    parser.add_argument("--shots", default=None)
    parser.add_argument("--prev-tail", default=None,
                        help="为某镜注入上一镜尾帧，格式：<当前镜>:<上一镜成片.mp4绝对路径>，可多个用逗号分隔。"
                             "如：--prev-tail 03:D:\\...\\MiniMaxH3_Director_external_r2v_00002_.mp4")
    args = parser.parse_args()

    if not os.path.isfile(TEMPLATE):
        raise SystemExit("找不到 external_groups_r2v 模板：%s" % TEMPLATE)

    comfy_root = args.comfy_input or r"D:\Comfy-Desktop\ComfyUI-Shared"
    char_map = load_id_name(CHAR_DB, "characters", "c")
    scene_map = load_id_name(SCENE_DB, "scenes", "sc")
    voice_map = load_voice_map()

    storyboards = load_storyboards()
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

    # 解析 --prev-tail：{当前镜: 上一镜成片绝对路径}
    prev_tail_map = {}
    if args.prev_tail:
        for tok in args.prev_tail.split(","):
            tok = tok.strip()
            if ":" not in tok:
                print("  [!] --prev-tail 项缺少冒号，跳过：%s" % tok)
                continue
            cur, vid = tok.split(":", 1)
            cur = cur.strip()
            vid = vid.strip()
            imported = os.path.expandvars(vid)
            if not os.path.isfile(imported):
                print("  [!] 找不到上一镜成片，跳过：%s" % imported)
                continue
            # 上一镜 shot_id = 当前镜 - 1（数字递增）
            prev_sid = "%02d" % (int(cur) - 1) if cur.isdigit() else cur
            prev_tail_map[cur] = (prev_sid, imported)
            print("  [ok] 镜%s 复用上一镜(%s)尾帧：%s" % (cur, prev_sid, os.path.basename(imported)))

    wf = build_r2v(storyboards, load_template(), char_map, scene_map, comfy_root,
                   voice_map, prev_tail_map)

    if wanted:
        tag = "镜" + "-".join(sorted(wanted))
    else:
        tag = "整集"
    out_name = "14_video_R2VA_%s_%dx%d.json" % (tag, VID_W, VID_H)
    out_path = os.path.join(OUT, out_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)

    print("已生成：%s（共 %d 镜，参考图驱动 r2v）" % (out_path, len(storyboards)))
    for sb in storyboards:
        sid = sb.get("shot_id")
        ref_items, _, _, missing = collect_refs(sb, char_map, scene_map, comfy_root)
        kinds = "、".join(("%s:%s" % ("角色", it[2])) if it[0] == "char" else ("场景:%s" % it[2])
                          for it in ref_items)
        pl = "  [含上一镜尾帧]" if (prev_tail_map and sid in prev_tail_map) else ""
        print("  镜 %s  时长=%ss  参考=[%s]%s%s" % (
            sid, sb.get("duration"), kinds, ("  ⚠缺参考图" if missing else ""), pl))

    if args.comfy_input:
        all_refs = set()
        for sb in storyboards:
            _, rfiles, _, _ = collect_refs(sb, char_map, scene_map, comfy_root)
            all_refs.update(rfiles)
        copy_refs_to_input(comfy_root, sorted(all_refs))
    else:
        print("提示：LoadImage 读 ComfyUI input 目录，请确保参考图已复制到 "
              "input/00_角色素材/ 与 input/01_场景素材/；可用 --comfy-input <ComfyUI根目录> 自动复制。")


if __name__ == "__main__":
    main()
