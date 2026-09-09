# -*- coding: utf-8 -*-
"""把分镜库(第1集_分镜.json)组装成 MiniMax-H3 Seamless Chain(连续镜头)剧本,
写入 H3_Seamless_Chain_CORE 模板,生成可提交的「一集连续剧情视频」工作流,
并保证每个角色声音稳定、对得上。

如何做到「人物声音一致、对得上」:
  依据 H3 官方对白写法:每句台词都要带【说话人编号 (S编号) + 稳定音色描述】,并逐镜复用。
  - speaker_id 由角色库提供(S1..S11),与 voice_desc(中文音色)绑定;
  - 每镜段用英文稳定音色描述 + (S编号) 标注说话人,同一角色永远同一段声音描述 → 声音一致;
  - 台词保留中文,用 <d>[Chinese] 台词</d> 包裹;
  - 旁白(S11)以 narrator(旁白音)呈现,不与其他角色混;
  - 遵循「一镜一人说」:若某镜有多个说话人(如镜14 打手甲+乙),自动拆成多条连续段。

用法:
  python scripts/build_seamless_video.py
输出:
  workflows/13_视频_Multishot_剧本_第1集_横屏_1280x736.json
  剧本/02_分镜/第1集_无缝链剧本.txt
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
STORYBOARD = os.path.join(ROOT, "剧本", "02_分镜", "第1集_分镜.json")
ROLE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "角色.json")
SCENE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "场景.json")
TPL = os.path.join(ROOT, "workflows", "11_视频_Multishot_CORE_横屏_1280x736.json")
OUT_WF = os.path.join(ROOT, "workflows", "13_视频_Multishot_剧本_第1集_横屏_1280x736.json")
OUT_TXT = os.path.join(ROOT, "剧本", "02_分镜", "第1集_无缝链剧本.txt")

FRAMES_PER_SHOT = 192          # 24fps -> 8s/镜
SAVE_VIDEO_PFX = "02_分镜/第1集/第1集_整段_成片_剧本"
SAVE_AUDIO_PFX = "02_分镜/第1集/第1集_整段_音频_剧本"

# 音色锚(voice anchor):把一段 5-10s 干净人声(放在 ComfyUI 的 input 目录,
# 文件名如 "voice_anchor_S1.mp3")填到这里,脚本会自动注入 LoadAudio 节点并连到
# sampler 的 voice_ref 输入,用于跨集锁定音色。留空 "" = 不锚定,维持默认的
# self_anchor_voice(第一镜自定音色、整集复用)。命令行可用 --voice-anchor <文件名> 覆盖。
VOICE_ANCHOR_FILE = ""

# 每个说话编号 → 稳定英文音色描述(逐镜复用 → 声音一致)
VOICE_EN = {
    "S1":  "in a clear, steady young male voice, calm and reserved, highly distinctive as the lead",
    "S2":  "in a bright, youthful male voice with confident swagger",
    "S3":  "in a deep, husky adult male voice with a drawling, knife-beneath-smile tone, fit for the villain",
    "S4":  "in a raspy, low young male voice, stubborn yet weary",
    "S5":  "in a bright, agile young female voice, quick tempo, clever and lively",
    "S6":  "in a thin, timid young male voice, soft and faint",
    "S7":  "in a husky middle-aged male voice, strained with humiliation",
    "S8":  "in a tearful middle-aged female voice, pleading and sobbing",
    "S9":  "in a rough, fierce masculine voice",
    "S10": "in a sinister, thuggish masculine voice",
    "S11": "in a low, deep male narration voice, steady with classic storyteller cadence",
}

# 画面/场景描述里常见的「风格约束」尾巴,拼接剧本前剔除,避免逐镜重复噪音
_NOISE_TAIL = re.compile(
    r"(\s*,\s*(cinematic(scene|close-up|medium shot|wide shot)?|high quality|"
    r"consistent art style|no text|no watermark))+\s*$"
)


def _widget_index(node):
    """返回 {字段名: widgets_values 下标}。优先用 properties.h3_widget_values 的键顺序
    （H3 插件权威顺序），否则退化为按 outputs 槽位名顺序，避免硬编码下标在模板结构变化时错位。"""
    hw = (node.get("properties") or {}).get("h3_widget_values")
    if isinstance(hw, dict) and hw:
        return {k: i for i, k in enumerate(hw.keys())}
    outs = node.get("outputs") or []
    return {o.get("name"): i for i, o in enumerate(outs) if isinstance(o, dict)}


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _clean(s, default=""):
    s = (s or default).strip().rstrip(".")
    s = _NOISE_TAIL.sub("", s).strip().rstrip(",").strip()
    return s


def align_voice_gender(en, gender):
    """按角色真实性别校正音色描述里的性别词。

    VOICE_EN 是按 S 编号写死的历史静态表，性别可能与角色库错位（例：小雪/gender=女
    却命中 '…male voice'；保镖/gender=男 却命中 '…female voice'）。这里用角色库的
    gender 做唯一权威，把音色描述里的男声词/女声词校正过来，保证「女角色配女声、
    男角色配男声」，也即 H3 subject_definition 里「声音永不漂移」的语义正确。
    若 gender 缺失或无法识别，保持原样（不臆测）。
    """
    if not en or not gender:
        return en
    g = str(gender).strip()
    is_female = ("女" in g) or g.lower() in ("female", "f", "girl", "woman")
    is_male = ("男" in g) or g.lower() in ("male", "m", "boy", "man")
    res = en
    if is_female:
        res = re.sub(r"\bmale voice\b", "female voice", res)
        res = re.sub(r"\bmasculine\b", "feminine", res)
    elif is_male:
        res = re.sub(r"\bfemale voice\b", "male voice", res)
        res = re.sub(r"\bfeminine\b", "masculine", res)
    return res


def build_role_map(role_db):
    """speaker_id -> {name, gender, voice_desc, voice_en}。voice_en 按角色真实性别对齐。"""
    m = {}
    for c in role_db.get("characters", []):
        sid = c.get("speaker_id")
        if sid:
            gender = c.get("gender", "")
            en = VOICE_EN.get(sid, VOICE_EN.get("S11", ""))
            m[sid] = {
                "name": c.get("name", sid),
                "gender": gender,
                "voice_desc": c.get("voice", {}).get("voice_desc", ""),
                "voice_en": align_voice_gender(en, gender),
            }
    return m


def scene_env_en(scene):
    """同一 scene_id 的稳定环境段逐镜复用(保证建筑/道具跨镜一致)。"""
    parts = [_clean(scene.get("prompt", ""))]
    for prop in (scene.get("props") or []):
        ip = _clean(prop.get("image_prompt", ""))
        if ip:
            parts.append(ip)
    return ", ".join([p for p in parts if p]).rstrip(",")


def camera_en(sb):
    angle = {"平视": "eye-level", "俯视": "high-angle overhead", "仰视": "low angle up-shot",
             "背面": "from behind"}.get(sb.get("angle", ""), "eye-level")
    shot = {"远景": "extreme wide shot", "全景": "full establishing shot",
            "中景": "medium shot", "近景": "close-up", "特写": "extreme close-up"}.get(
        sb.get("shot_type", ""), "medium shot")
    move = {"固定": "locked-off static camera", "缓推": "slow push-in camera",
            "摇镜": "slow pan camera", "拉镜": "slow pull-back camera"}.get(
        sb.get("movement", ""), "locked-off static camera")
    return f"{shot} at {angle}, {move}"


def split_dialogue(d):
    """把 dialogue 拆成 [(speaker_name, 台词)],支持一镜多说话人(\\n 分隔)。"""
    if not d:
        return []
    d = d.replace("\\n", "\n")
    out = []
    for line in re.split(r"[\n]+", d):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(?P<spk>[^：:]{1,10}?)[：:]\s*[（(][^）)]*[）)]?\s*(?P<txt>.*)$", line)
        if m:
            out.append((m.group("spk").strip(), m.group("txt").strip()))
        else:
            out.append(("", line))
    return [(s, t) for s, t in out if t]


def build_shots(sbs, scene_db, role_map):
    """为每个分镜生成若干条 Seamless Chain 段(空镜1条;对白按说话人拆分)。"""
    result = []           # [(seg_text, meta)]
    for sb in sbs:
        sid = sb.get("shot_id")
        scene_id = sb.get("scene_id", "")
        env = scene_env_en(scene_db.get(scene_id, {}))
        # 场景素材的 prompt 常以 ", no people" 结尾（仅用于纯环境九宫格参考图），
        # 直接拼进分镜段会与在场角色（image_prompt 里的人物）冲突，组装前剔除该断言：
        # 真正无人的镜头由 subject_definition 的「空镜」限定，不由环境段声明。
        env = re.sub(r",\s*no people\b", "", env).strip()
        img = _clean(sb.get("image_prompt", ""))
        cam = camera_en(sb)
        dlg = split_dialogue(sb.get("dialogue", ""))

        if not dlg:
            # 空镜/无对白:只给画面 + 机位
            seg = f"{env}. {img}. Camera: {cam}."
            result.append((seg, {"shot": sid, "scene": scene_id, "speakers": [], "num": ""}))
            continue

        # 有对白:一镜一人说为好;若多人,拆成多条连续段
        sb_speaker = sb.get("speaker_id")
        for spk, text in dlg:
            if not spk:  # dialogue 未带角色前缀时,回退到该镜 speaker_id 的默认角色
                spk = role_map.get(sb_speaker, {}).get("name", "")
            voice = role_map.get(spk)  # spk 为中文名,需映射到编号
            if not voice:
                # 用说话人中文名反查角色库(角色库 id->name->speaker_id)
                voice = _find_role_by_name(spk, role_map) or role_map.get(sb_speaker) \
                    or role_map.get("S11", {})
            s_num = _speaker_num(role_map, voice, spk)
            is_narration = (s_num == "S11") or ("旁白" in spk)
            v_en = voice.get("voice_en", VOICE_EN.get(s_num, VOICE_EN["S11"]))
            name = voice.get("name", spk)
            if is_narration:
                text = re.sub(r"^\s*旁白\s*[：:]\s*", "", text)
                say = f"Narrator speaks {v_en} ({s_num}): <d>[Chinese] {text} </d>"
            else:
                say = f"{name} speaks {v_en} ({s_num}): <d>[Chinese] {text} </d>"
            seg = f"{env}. {img}. Camera: {cam}. {say}"
            result.append((seg, {"shot": sid, "scene": scene_id,
                                 "speakers": [spk], "num": s_num}))
    return result


def _find_role_by_name(spk, role_map):
    for v in role_map.values():
        if v.get("name") == spk:
            return v
    return None


def _speaker_num(role_map, voice, spk):
    for sid, v in role_map.items():
        if v is voice or v.get("name") == spk:
            return sid
    return "S11"


def add_voice_anchor(wf, file_name):
    """注入 LoadAudio(voice anchor) 节点,连到 sampler 的 voice_ref 输入。

    H3 的 voice_ref 输入接收一段短人声作为「音色锚」,让整段视频按该音色说话,
    用于跨集锁定角色音色(单集内靠 self_anchor_voice 已锁定)。file_name 为空则跳过。
    """
    if not file_name:
        return False
    sampler = next(n for n in wf["nodes"] if n["type"] == "H3MultishotSampler")
    idx = next(i for i, inp in enumerate(sampler["inputs"])
               if inp.get("name") == "voice_ref")
    node_id = max(n["id"] for n in wf["nodes"]) + 1
    link_id = max((l[0] for l in wf["links"]), default=0) + 1
    wf["nodes"].append({
        "id": node_id,
        "type": "LoadAudio",
        "pos": [-1000, 540],
        "size": [410, 136],
        "flags": {},
        "order": len(wf["nodes"]),
        "mode": 0,
        "inputs": [
            {"localized_name": "audio", "name": "audio", "type": "COMBO",
             "widget": {"name": "audio"}, "link": None},
            {"localized_name": "audioUI", "name": "audioUI", "type": "AUDIO_UI",
             "widget": {"name": "audioUI"}, "link": None},
            {"localized_name": "choose file to upload", "name": "upload",
             "type": "AUDIOUPLOAD", "widget": {"name": "upload"}, "link": None},
        ],
        "outputs": [
            {"localized_name": "AUDIO", "name": "AUDIO", "type": "AUDIO",
             "slot_index": 0, "links": [link_id]},
        ],
        "title": "voice anchor (音色锚)",
        "properties": {"cnr_id": "comfy-core", "ver": "0.30.0",
                       "Node name for S&R": "LoadAudio"},
        "widgets_values": [file_name, None, None],
    })
    wf["links"].append([link_id, node_id, 0, sampler["id"], idx, "AUDIO"])
    sampler["inputs"][idx]["link"] = link_id
    wf["last_node_id"] = node_id
    wf["last_link_id"] = link_id
    return True


def main():
    voice_anchor = VOICE_ANCHOR_FILE
    if "--voice-anchor" in sys.argv:
        i = sys.argv.index("--voice-anchor")
        if i + 1 < len(sys.argv):
            voice_anchor = sys.argv[i + 1]

    st = _load(STORYBOARD)
    scene_db = {s["id"]: s for s in _load(SCENE_DB).get("scenes", [])}
    role_map = build_role_map(_load(ROLE_DB))
    sbs = st.get("storyboards", [])

    shots = build_shots(sbs, scene_db, role_map)

    # 人可读核对
    txt_lines = []
    for seg, meta in shots:
        txt_lines.append(f"[镜 {meta['shot']}] 场景 {meta['scene']} | 说话: "
                         f"{'、'.join(meta['speakers']) or '无(空镜)'} {('(' + meta['num'] + ')') if meta['num'] else ''}")
        txt_lines.append(f"  {seg}")
        txt_lines.append("")

    script = "\n---\n".join(seg for seg, _ in shots)

    wf = _load(TPL)
    sampler = next(n for n in wf["nodes"] if n["type"] == "H3MultishotSampler")
    wv = sampler["widgets_values"]
    hw = sampler.get("properties", {}).get("h3_widget_values", {})
    idx = _widget_index(sampler)
    # script 是唯一剧本文本字段，按键定位写入（避免硬编码下标 0）
    if idx.get("script") is not None and idx["script"] < len(wv):
        wv[idx["script"]] = script
    hw["script"] = script
    # shot_count: 0 = 自动按 script 的 '---' 块数分镜（节点仅允许 1-8 强制模式，
    # 传 22 会触发 value_bigger_than_max 校验错误）。块数由 script 决定，故设 0。
    hw["shot_count"] = 0
    hw["frames_per_shot"] = FRAMES_PER_SHOT
    for k, v in (("shot_count", 0), ("frames_per_shot", FRAMES_PER_SHOT)):
        if k in idx and idx[k] < len(wv):
            wv[idx[k]] = v
    sampler["properties"]["h3_widget_values"] = hw

    for n in wf["nodes"]:
        if n["type"] == "SaveVideo":
            n["widgets_values"][0] = SAVE_VIDEO_PFX
        elif n["type"] == "SaveAudio":
            n["widgets_values"][0] = SAVE_AUDIO_PFX

    anchored = add_voice_anchor(wf, voice_anchor)

    os.makedirs(os.path.dirname(OUT_WF), exist_ok=True)
    with open(OUT_WF, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
    with open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write(f"# 第1集 无缝连链剧本(Seamless Chain, 带说话人/音色)\n"
                f"总段数 {len(shots)} | 每段 {FRAMES_PER_SHOT}帧 @24fps ≈ {FRAMES_PER_SHOT//24}s\n\n")
        f.write("\n".join(txt_lines))

    print(f"[ok] 工作流: {OUT_WF}")
    print(f"[ok] 核对剧本: {OUT_TXT}")
    print(f"[ok] 段数: {len(shots)} | script 长度: {len(script)} 字符")
    print(f"[ok] 音色锚: {'已注入 ' + voice_anchor if anchored else '未启用(留空,走 self_anchor_voice)'}")


if __name__ == "__main__":
    main()
