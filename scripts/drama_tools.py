# -*- coding: utf-8 -*-
"""剧本/ 数据工具库 —— 给 skills/ 的 5 个 SKILL.md 提供「真实 backend」。

这些函数对应 SKILL.md 前置条件里引用的工具接口，把抽象接口落到本地产物：

  - script_rewriter   : read_episode_script / read_formatted_script / write_formatted_script
  - extractor         : read_script_for_extraction / load_characters / save_characters /
                        add_character / update_character / find_character /
                        load_scenes / save_scenes / load_props / save_props
  - storyboard_breaker: read_storyboard_context / load_storyboards / save_storyboards
  - voice_assigner    : list_voices / get_characters / assign_voice / auto_assign_voices
  - grid_prompt_gen   : ensure_image_prompt / validate_characters

所有函数都是确定性的（不调用 LLM），只读写 剧本/ 下的 JSON/文本，方便 pipeline 按序编排。

用法（自检脚本）:
    python scripts/drama_tools.py            # 打印各库状态并从角色 voice_desc 初始化音色库
    python scripts/drama_tools.py --voice    # 执行音色自动分配（确定性，不覆盖已锁定的）
"""

import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JU = os.path.join(ROOT, "剧本")
NOVEL_RAW = os.path.join(JU, "00_小说原文")
SCRIPT_DIR = os.path.join(JU, "01_剧本")
BOARD_DIR = os.path.join(JU, "02_分镜")
ASSET_DIR = os.path.join(JU, "03_角色场景")
VOICE_DIR = os.path.join(JU, "04_音色")

CHAR_DB = os.path.join(ASSET_DIR, "角色.json")
SCENE_DB = os.path.join(ASSET_DIR, "场景.json")
PROP_DB = os.path.join(ASSET_DIR, "道具.json")
VOICE_DB = os.path.join(VOICE_DIR, "音色库.json")

# 占位符：角色.json 的 voice.voice_id 未绑定真实音色时用的标记
PENDING_VOICE = "voice_id_待音色库绑定"

# ---- 风格/颜值常量（与 scripts/build_new_workflows.py 保持一致，供 grid 环节校验/兜底）----
FUSION_STYLE_MARK = "stylized 3D Chinese anime character"
STYLE_FUSION = ("stylized 3D Chinese anime character, perfect fusion of realistic rendering "
                "and CG animation, premium 3D animated film quality, "
                "very realistic textured human skin, fine visible skin pores, natural skin grain "
                "and subtle realistic skin details, natural skin tones, "
                "realistic non-plastic non-waxy skin material with soft natural highlights, "
                "subsurface scattering, "
                "expressive detailed anime eyes with realistic iris depth, "
                "subtle natural facial micro-expressions, "
                "电影感氛围, 电影级布光, 浅景深, 4K高清纹理, 高精度3D模型, PBR材质, "
                "Chinese Guoman 3D style, East Asian anime face")
ATTRACTIVE_MALE = "handsome and clean-cut facial features, a well-proportioned attractive face"
ATTRACTIVE_FEMALE = "pretty and lovely facial features, a well-proportioned attractive face"


# =====================================================================
# 基础读写
# =====================================================================
def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        # 防止 JSON 损坏/权限问题直接裸抛炸掉整条 pipeline
        print(f"[drama_tools] 警告: 读取失败 {os.path.basename(path)}: {e} -> 按空返回")
        return None


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# 文本解码候选顺序：utf-8-sig 兼容带/不带 BOM 的 utf-8；GBK/GB18030 兜中文编码；
# latin-1 任意字节都能解码(永不抛错,仅作最后兜底)——保证任一编码都绝不裸抛炸掉 pipeline。
_TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1")


def _read_text(path):
    if not os.path.exists(path):
        return ""
    for enc in _TEXT_ENCODINGS:
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, OSError):
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _cn_to_int(s):
    """中文数字/数字串 -> int（用于章节、集号）。"""
    s = str(s).strip()
    nums = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9}
    if s.isdigit():
        return int(s)
    if s in nums:
        return nums[s]
    if s.startswith("十"):
        return 10 + (nums.get(s[1], 0) if len(s) > 1 else 0)
    if "十" in s:
        a, b = s.split("十", 1)
        return nums.get(a, 1) * 10 + nums.get(b, 0)
    if "百" in s:
        a, b = s.split("百", 1)
        return nums.get(a, 1) * 100 + nums.get(b, 0)
    try:
        return int(re.sub(r"\D", "", s) or 0)
    except ValueError:
        return 0


def _norm_episode(episode):
    """把『第1集』/『1』/『第1集』归一成集号 int。"""
    if isinstance(episode, int):
        return episode
    return _cn_to_int(str(episode).replace("第", "").replace("集", ""))


def episode_tag(episode):
    """集号 -> 『第N集』。"""
    return f"第{_norm_episode(episode)}集"


def board_filename(episode):
    """集号 -> 分镜文件名（与 02_分镜/第1集_分镜.json 对齐）。"""
    return f"{episode_tag(episode)}_分镜.json"


# =====================================================================
# 小说原文 / 剧本
# =====================================================================
def list_novel_files():
    """00_小说原文 下的原始文本文件列表。"""
    if not os.path.isdir(NOVEL_RAW):
        return []
    return [f for f in os.listdir(NOVEL_RAW) if f.endswith(".txt")]


_CHAPTER_RE = re.compile(r"^\s*(第[零一二三四五六七八九十百千0-9]+[章节回篇])[\.\s、]*(.*)$", re.M)


def _split_chapters(text):
    """把整册小说切分成 [{'num':int,'title':str,'start':int,'end':int}]，按标题行切。"""
    matches = list(_CHAPTER_RE.finditer(text))
    chapters = []
    for i, m in enumerate(matches):
        num = _cn_to_int(re.search(r"[零一二三四五六七八九十百千0-9]+", m.group(1)).group(0))
        chapters.append({
            "num": num,
            "title": m.group(0).strip(),
            "start": m.start(),
            "end": matches[i + 1].start() if i + 1 < len(matches) else len(text),
        })
    return chapters


def read_episode_script(episode="第1集", chapter=None):
    """script_rewriter 用的原始小说：返回当前集对应的原著章节正文。

    chapter 可显式传章节号；否则用分镜库 source（原著第N章）推断，再退回『第N集≈第N章』。
    返回 (chapter_title, body)；定位不到则返回整册前 3000 字并提示。
    """
    files = list_novel_files()
    if not files:
        return ("", "")
    raw = "".join(_read_text(os.path.join(NOVEL_RAW, f)) for f in files)
    chapters = _split_chapters(raw)

    target = chapter
    if target is None:
        # 从分镜库 source 推断（如 原著第1章）
        boards = load_storyboards(episode)
        src = ""
        if boards:
            pass
        meta = _load_json(_board_path(episode)) or {}
        src = meta.get("source", "")
        m = re.search(r"第\s*([零一二三四五六七八九十百千0-9]+)\s*[章节篇]", src)
        if m:
            target = _cn_to_int(m.group(1))

    if target is not None:
        for ch in chapters:
            if ch["num"] == target:
                return (ch["title"], raw[ch["start"]:ch["end"]].strip())

    # 退回：第N集 ≈ 第N章；索引越界则给整册前段
    n = _norm_episode(episode)
    for ch in chapters:
        if ch["num"] == n:
            return (ch["title"], raw[ch["start"]:ch["end"]].strip())
    return ("定位失败", raw[:3000])


def script_path(episode="第1集"):
    """01_剧本 下对应集的剧本文件路径。"""
    return os.path.join(SCRIPT_DIR, f"{episode_tag(episode)}_剧本.md")


def read_formatted_script(episode="第1集"):
    """读 01_剧本/第N集_剧本.md 的格式化剧本正文。"""
    return _read_text(script_path(episode))


def write_formatted_script(episode="第1集", text=""):
    """把格式化剧本写入 01_剧本/第N集_剧本.md。"""
    if not text.endswith("\n"):
        text += "\n"
    _write_text(script_path(episode), text)
    return script_path(episode)


def read_script_for_extraction(episode="第1集"):
    """extractor 用的格式化剧本（与 read_formatted_script 同，语义化别名）。"""
    return read_formatted_script(episode)


# =====================================================================
# 角色
# =====================================================================
def load_characters():
    data = _load_json(CHAR_DB)
    return (data.get("characters", []) if data else [])


def save_characters(characters, project=None):
    data = _load_json(CHAR_DB) or {}
    data["project"] = project or data.get("project", "")
    data["generated_by"] = "character-scene-extractor + voice-assigner + grid-image-generator"
    data["characters"] = characters
    _save_json(CHAR_DB, data)
    return len(characters)


def get_characters():
    """voice_assigner 用：返回带 voice 状态的角色（current_voice=voice_id）。"""
    chars = load_characters()
    for c in chars:
        v = c.get("voice") or {}
        c["current_voice"] = v.get("voice_id", PENDING_VOICE)
        c["speaker_id"] = c.get("speaker_id", "")
    return chars


def _next_char_id():
    chars = load_characters()
    ids = [c.get("id", "") for c in chars]
    for i in range(1, 100):
        if f"c{i:02d}" not in ids:
            return f"c{i:02d}"
    return f"c{len(ids) + 1:02d}"


def add_character(char):
    """新增角色：自动补 id / speaker_id。"""
    chars = load_characters()
    char.setdefault("id", _next_char_id())
    if not char.get("speaker_id"):
        used = {c.get("speaker_id", "") for c in chars}
        n = 1
        while f"S{n}" in used:
            n += 1
        char["speaker_id"] = f"S{n}"
    char.setdefault("pose_props", [])
    char.setdefault("voice", {"voice_id": PENDING_VOICE, "voice_desc": "", "role_tag": ""})
    chars.append(char)
    save_characters(chars)
    return char


def find_character(name=None, char_id=None):
    for c in load_characters():
        if char_id and c.get("id") == char_id:
            return c
        if name and c.get("name") == name:
            return c
    return None


def update_character(char_id, **kw):
    chars = load_characters()
    for c in chars:
        if c.get("id") == char_id:
            for k, v in kw.items():
                c[k] = v
            save_characters(chars)
            return c
    return None


# =====================================================================
# 场景 / 道具
# =====================================================================
def load_scenes():
    data = _load_json(SCENE_DB)
    return (data.get("scenes", []) if data else [])


def save_scenes(scenes, project=None):
    data = _load_json(SCENE_DB) or {}
    data["project"] = project or data.get("project", "")
    data["generated_by"] = "character-scene-extractor + grid-image-generator"
    data["scenes"] = scenes
    _save_json(SCENE_DB, data)
    return len(scenes)


def _next_scene_id():
    ids = [s.get("id", "") for s in load_scenes()]
    for i in range(1, 100):
        if f"sc{i:03d}" not in ids:
            return f"sc{i:03d}"
    return f"sc{len(ids) + 1:03d}"


def add_scene(scene):
    scenes = load_scenes()
    scene.setdefault("id", _next_scene_id())
    scenes.append(scene)
    save_scenes(scenes)
    return scene


def load_props():
    data = _load_json(PROP_DB)
    return (data.get("props", []) if data else [])


def save_props(props, project=None):
    data = _load_json(PROP_DB) or {}
    data["project"] = project or data.get("project", "")
    data["props"] = props
    _save_json(PROP_DB, data)
    return len(props)


# =====================================================================
# 分镜
# =====================================================================
def _board_path(episode="第1集"):
    return os.path.join(BOARD_DIR, board_filename(episode))


def load_storyboards(episode="第1集"):
    data = _load_json(_board_path(episode))
    return (data.get("storyboards", []) if data else [])


def save_storyboards(episode="第1集", boards=None, meta=None):
    path = _board_path(episode)
    data = meta or {}
    data.setdefault("project", "")
    data.setdefault("episode", episode_tag(episode))
    data.setdefault("generated_by", "storyboard-breaker")
    data.setdefault("storyboards", boards if boards is not None else [])
    _save_json(path, data)
    return len(data["storyboards"])


def read_storyboard_context(episode="第1集"):
    """storyboard_breaker 用：把本集剧本、已提取的角色/场景/道具、现有分镜聚合成一份上下文。"""
    meta = _load_json(_board_path(episode)) or {}
    return {
        "episode": episode_tag(episode),
        "source": meta.get("source", ""),
        "script": read_formatted_script(episode),
        "characters": load_characters(),
        "scenes": load_scenes(),
        "props": load_props(),
        "storyboards": load_storyboards(episode),
    }


# =====================================================================
# 音色库（voice-assigner 的 backend）
# =====================================================================
def _load_voices():
    data = _load_json(VOICE_DB)
    return (data.get("voices", []) if data else [])


def _save_voices(voices):
    data = _load_json(VOICE_DB) or {}
    data.setdefault("note", "MiniMax H3 TTS 音色库（占位；接入云端 TTS 时把 voice_id 替换为真实 ID）")
    data["voices"] = voices
    _save_json(VOICE_DB, data)


def init_voice_library():
    """为每个需配音角色生成一条独立音色（voice_id 全剧唯一），保证一角色一音色。"""
    if _load_voices():
        return _load_voices()
    voices = []
    idx = 0
    for c in load_characters():
        idx += 1
        v = c.get("voice") or {}
        tag = v.get("role_tag") or "配角"
        gender = c.get("gender", "男")
        voices.append({
            "voice_id": f"voice_{tag}_{gender}_{idx:02d}",
            "name": c.get("name", f"{tag}音色"),
            "gender": gender,
            "role_tags": [tag],
            "voice_desc": v.get("voice_desc", ""),
        })
    if not voices:
        voices.append({"voice_id": "voice_narrator_01", "name": "旁白", "gender": "男",
                       "role_tags": ["旁白"], "voice_desc": "沉稳旁白男声"})
    _save_voices(voices)
    return voices


def list_voices(role_tag=None):
    """voice_assigner 用：列出可用音色，可按 role_tag（主角/反派/配角/旁白）过滤。"""
    voices = _load_voices() or init_voice_library()
    if role_tag:
        return [v for v in voices if role_tag in v.get("role_tags", [])]
    return voices


def get_voice(voice_id):
    for v in (_load_voices() or init_voice_library()):
        if v.get("voice_id") == voice_id:
            return v
    return None


def assign_voice(char_id, voice_id=None, speaker_id=None):
    """把一个角色与音色绑定（一角色一音色 + speaker_id 全局唯一），写回角色.json。"""
    chars = load_characters()
    target = None
    for c in chars:
        if c.get("id") == char_id:
            target = c
            break
    if target is None:
        raise ValueError(f"角色不存在: {char_id}")

    # 一角色一音色：已锁定且仍在音色库、未显式换绑 -> 跳过（跨集锁定）
    vids = {v["voice_id"] for v in (_load_voices() or init_voice_library())}
    existing = (target.get("voice") or {}).get("voice_id")
    if existing and existing in vids and voice_id is None:
        return target

    # speaker_id 全局唯一：若传来的号已被其他角色占用，则拒绝/自动改号
    if speaker_id:
        for c in chars:
            if c.get("id") != char_id and c.get("speaker_id") == speaker_id:
                raise ValueError(f"speaker_id {speaker_id} 已被 {c.get('name')} 占用")

    if voice_id is None:
        # 挑一条 role_tag/gender 匹配且未被其他人占用的音色，保证一角色一音色
        used = {c.get("voice", {}).get("voice_id")
                for c in chars if c.get("id") != char_id}
        cand = [v for v in (_load_voices() or init_voice_library())
                if v["voice_id"] not in used]
        if not cand:
            # 全占用：追加一条唯一音色
            nid = f"voice_{target.get('gender', '男')}_{len(used) + 1:02d}"
            cand = [{"voice_id": nid, "name": target.get("name"),
                     "gender": target.get("gender", "男"),
                     "role_tags": [(target.get("voice") or {}).get("role_tag") or "配角"],
                     "voice_desc": (target.get("voice") or {}).get("voice_desc", "")}]
            _save_voices((_load_voices() or []) + cand)
        tag = (target.get("voice") or {}).get("role_tag") or "配角"
        gender = target.get("gender", "男")
        cand.sort(key=lambda v: (0 if (gender == v["gender"] and tag in v.get("role_tags", []))
                                 else (1 if gender == v["gender"] else 2)))
        voice_id = cand[0]["voice_id"]

    target.setdefault("voice", {})
    target["voice"]["voice_id"] = voice_id
    if speaker_id:
        target["speaker_id"] = speaker_id
    if not target.get("speaker_id"):
        used = {c.get("speaker_id", "") for c in chars}
        n = 1
        while f"S{n}" in used:
            n += 1
        target["speaker_id"] = f"S{n}"

    save_characters(chars)
    return target


def auto_assign_voices():
    """批量：把所有仍是占位 voice_id 的角色绑定到音色库，speaker_id 缺失则补，已有则跳过（跨集锁定）。"""
    if not (_load_voices() or init_voice_library()):
        init_voice_library()
    ids = {v["voice_id"] for v in _load_voices()}
    cnt = {}
    for c in get_characters():
        vid = c.get("current_voice")
        if vid and vid != PENDING_VOICE:
            cnt[vid] = cnt.get(vid, 0) + 1
    assigned = []
    for c in get_characters():
        before = c.get("current_voice")
        # 独占且在库的非占位音色 -> 锁定跳过；共用/占位/失效 -> 重新分配
        if (before and before != PENDING_VOICE and before in ids
                and cnt.get(before, 0) == 1):
            continue
        r = assign_voice(c["id"])
        assigned.append({"id": c["id"], "name": c.get("name"),
                         "voice_id": (r.get("voice") or {}).get("voice_id"),
                         "speaker_id": r.get("speaker_id")})
    return assigned


def reset_voices():
    """把全部角色音色重置为待绑定（跨集重绑前用），并清除音色库。返回重置个数。"""
    chars = load_characters()
    for c in chars:
        c.setdefault("voice", {})
        c["voice"]["voice_id"] = PENDING_VOICE
    save_characters(chars)
    return len(chars)


# =====================================================================
# 图片提示词（grid-prompt-generator 的 backend）
# =====================================================================
def has_fusion_style(img):
    return FUSION_STYLE_MARK in (img or "")


def build_image_prompt(char):
    """按 grid 规范给角色生成 image_prompt：统一风格前置 + 颜值 + 主体 + 收尾。

    幂等：
      - 已内置风格段 -> 原样返回；
      - 已有主体但缺风格段 -> 补风格前置 + 颜值；
      - 完全没有 image_prompt 且无 appearance（如旁白）-> 返回 ''（无实体形象，不造图）。
    """
    img = char.get("image_prompt") or ""
    beauty = ATTRACTIVE_MALE if char.get("gender") == "男" else ATTRACTIVE_FEMALE
    if img and has_fusion_style(img):
        return img
    if img:
        # 已有主体，仅补风格前置与颜值词
        if beauty and beauty.lower() not in img.lower():
            img = img.rstrip().rstrip(",") + ", " + beauty
        return STYLE_FUSION + ", " + img
    app = (char.get("appearance") or "").strip()
    if not app:
        return ""  # 无实体形象角色（旁白），不生成图像提示词
    props = char.get("随身道具") or char.get("props") or []
    prop_en = ", ".join(_PROP_ZH2EN.get(p, p) for p in props) if props else ""
    tail = "cinematic portrait, high quality, consistent art style, no text, no watermark"
    body = app + (f", {beauty}" if beauty else "")
    if prop_en:
        body += f", {prop_en}"
    return f"{STYLE_FUSION}, {body}, {tail}"


_PROP_ZH2EN = {
    "竹钓竿": "a bamboo fishing rod",
    "草帽": "a conical straw hat",
    "铁皮灯笼": "an iron gang lantern painted with a blood-red Chinese character",
    "短刀": "a short knife",
    "棍棒": "a thick wooden club",
    "粗木棍": "a thick wooden club",
    "粗绳": "a coil of thick rope",
}


def ensure_image_prompt(char_id=None):
    """grid 环节：把缺风格段的角色 image_prompt 补齐并落盘。返回处理个数。"""
    chars = load_characters()
    n = 0
    for c in chars:
        if char_id and c.get("id") != char_id:
            continue
        if not (c.get("image_prompt") or "").strip():
            continue  # 无实体形象角色（旁白），跳过，不造提示词
        if not has_fusion_style(c.get("image_prompt")):
            c["image_prompt"] = build_image_prompt(c)
            n += 1
    save_characters(chars)
    return n


def validate_characters():
    """体检：每个角色是否缺 image_prompt / 风格段 / 音色 / speaker_id。返回问题列表。"""
    issues = []
    for c in get_characters():
        flags = []
        if not (c.get("image_prompt") or "").strip():
            continue  # 无实体形象（旁白），不参与图像校验
        if not has_fusion_style(c["image_prompt"]):
            flags.append("缺统一风格前置段")
        if c.get("current_voice") in (None, "", PENDING_VOICE):
            flags.append("音色未绑定")
        if not c.get("speaker_id"):
            flags.append("缺 speaker_id")
        if flags:
            issues.append({"id": c.get("id"), "name": c.get("name"),
                           "voice_id": c.get("current_voice"),
                           "speaker_id": c.get("speaker_id"), "problems": flags})
    return issues


# =====================================================================
# 自检
# =====================================================================
def selftest():
    print("== 数据工具库自检 ==")
    print("角色库:", os.path.basename(CHAR_DB), "->", len(load_characters()), "个角色")
    print("场景库:", os.path.basename(SCENE_DB), "->", len(load_scenes()), "个场景")
    print("道具库:", os.path.basename(PROP_DB), "->", len(load_props()), "个道具")
    print("分镜库:", os.path.basename(_board_path("第1集")), "->", len(load_storyboards("第1集")), "个镜头")
    print("剧本文件:", os.path.basename(script_path("第1集")), "->", len(read_formatted_script("第1集")), "字符")

    voices = init_voice_library()
    print("音色库:", os.path.basename(VOICE_DB), "->", len(voices), "条")
    for v in voices:
        print("   -", v["voice_id"], v.get("role_tags"), v.get("gender"))

    print("\n角色体检:")
    issues = validate_characters()
    if not issues:
        print("   全部通过")
    for it in issues:
        print("   [%s]%s speaker=%s voice=%s 问题=%s"
              % (it["id"], it["name"], it["speaker_id"], it["voice_id"], ",".join(it["problems"])))


if __name__ == "__main__":
    import sys
    if "--reset-voice" in sys.argv:
        n = reset_voices()
        if os.path.exists(VOICE_DB):
            os.remove(VOICE_DB)
        init_voice_library()
        res = auto_assign_voices()
        print(f"已重置 {n} 个角色音色 -> 重新分配:")
        print(json.dumps(res, ensure_ascii=False, indent=2) if res else "(无待绑定)")
        print("剩余问题:", json.dumps(validate_characters(), ensure_ascii=False, indent=2))
    elif "--voice" in sys.argv:
        res = auto_assign_voices()
        print("已绑定音色:", json.dumps(res, ensure_ascii=False, indent=2) if res else "无待绑定")
        print("剩余问题:", json.dumps(validate_characters(), ensure_ascii=False, indent=2))
    else:
        selftest()
