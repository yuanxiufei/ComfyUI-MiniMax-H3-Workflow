# -*- coding: utf-8 -*-
"""Build 竖屏短剧(9:16, 736x1280) workflows for the novel -> short-drama pipeline.

遵循《小说转短剧视频生产方案(H3固定方案)》：
  - 竖屏 9:16，H3 生成 736x1280，剪映导出 1080x1920
  - 素材目录规范：output/00_角色素材、01_场景素材、02_分镜
  - 演进路线：T2V -> I2V -> FL2VA -> Ref2VA -> Multishot -> Turbo
  - 视频模板默认只产出最终主力 09_video_FL2VA（I2V/FL2VA）；
    探路 T2V(07) 需加 --with-t2v、暂缓 Ref2VA(10) 需加 --with-ref2va，才一并生成。
生图模型与 D:\\AIGC中国风3D漫剧 实际主力一致（Qwen-2512；ZImage 仅早期试做已弃用，不再生成）。
只向本工作区 workflows/ 写新 JSON，不修改 D:\\AIGC中国风3D漫剧\\workflows 下原有工作流。
"""

import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "workflows"))
EXAMPLES = r"D:\Comfy-Desktop\ComfyUI-Shared\custom_nodes\ComfyUI_MiniMaxH3_Director\example_workflows"
ROLE_DB = os.path.abspath(os.path.join(HERE, "..", "剧本", "03_角色场景", "角色.json"))
SCENE_DB = os.path.abspath(os.path.join(HERE, "..", "剧本", "03_角色场景", "场景.json"))
STORYBOARD_DB = os.path.abspath(os.path.join(HERE, "..", "剧本", "02_分镜", "第1集_分镜.json"))

# --- 生图模型（与 D:\AIGC中国风3D漫剧 一致） ---
Q = ("qwen_image_2512_bf16.safetensors",
     "qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen_image",
     "qwen_image_vae.safetensors",
     "Qwen-国漫短剧3D CG质感角色V1_Qwen-国漫短剧3D CG质感角色V1.safetensors")

NEG_CHAR = ("人物分身，复制人，多余人物，角色增殖，多人重叠，嘴型错乱，串台词，人物五官变动，服饰跳变，"
            "手部畸形，肢体扭曲，画面抖动，闪烁，模糊，低清晰度，水印，英文文字，"
            "丑陋，畸形五官，歪斜五官，不对称脸，歪嘴，暴牙，龅牙，皱纹过多，未老先衰")
NEG_SCENE = ("人物，角色，分身，复制人，嘴型错乱，串台词，手部畸形，肢体扭曲，画面抖动，闪烁，模糊，"
             "低清晰度，水印，英文文字")
# 宫格图负面词：同一角色多格属于正常布局，必须去掉"人物分身/角色增殖/多人重叠"，避免抑制网格生成
NEG_GRID = ("嘴型错乱，串台词，人物五官变动，服饰跳变，手部畸形，肢体扭曲，"
            "格子重叠，格子合并，格子缺失，人物溢出格子，"
            "画面抖动，闪烁，模糊，低清晰度，水印，英文文字，"
            "丑陋，畸形五官，歪斜五官，不对称脸，歪嘴，暴牙，龅牙，皱纹过多，未老先衰")

# 场景素材专属风格：纯环境，不含任何人物皮肤/面部词，避免模型把场景画成"人物三视图"。
STYLE_SCENE = ("K-GM, 3D次时代CG风格渲染, PBR材质渲染, 高精度3D模型, 戏剧性体积光, "
               "浅景深, 电影感氛围, 现代都市场景环境, 4K高清纹理, 电影级布光, 体积雾, 大气透视, "
               "Octane渲染器质感, Unreal Engine 5, "
               "Chinese Guoman 3D style, Chinese digital environment concept art, cinematic matte painting")
# 场景九宫格负面词：与角色宫格不同，场景必须强排人物（人脸/人影/身体/五官），
# 并控制格子布局不重叠/不缺失/不溢出。
NEG_SCENE_GRID = ("人物，人脸，人像，人影，全身人，半身人，背影，身体，手臂，手指，手掌，"
                  "皮肤，五官，嘴，眼睛，头发，"
                  "格子重叠，格子合并，格子缺失，格子溢出，画面破碎，构图混乱，"
                  "嘴型错乱，串台词，肢体扭曲，画面抖动，闪烁，模糊，低清晰度，"
                  "水印，英文文字，文字，签名")

# ---- 统一风格：写实与CG融合的完美动漫人物（3D国漫动画电影质感） ----
# 角色是"动漫人物造型"（动漫脸/发/设计），渲染走"写实质感"（真实皮肤纹理优先：细毛孔、自然皮纹、
# 皮肤细节高分辨率、非塑料材质、柔和自然高光），避免两个极端：真人照片式写实、塑料卡通式CG。
# 皮肤关键词强调"真实皮肤纹理"而非"3D渲染着色"，否则会出塑料娃娃脸。
STYLE_FUSION = ("stylized 3D Chinese anime character, perfect fusion of realistic rendering "
                "and CG animation, premium 3D animated film quality, "
                "3D次时代CG风格渲染, high-precision sculpted model, dramatic volumetric lighting, "
                "soft-focus shallow depth of field, atmospheric smoke and mist simulation, "
                "China-style aesthetic background, Octane renderer look, Unreal Engine 5, "
                "very realistic textured human skin, fine visible skin pores, natural skin grain "
                "and subtle realistic skin details, natural skin tones, "
                "realistic non-plastic non-waxy skin material with soft natural highlights, "
                "subsurface scattering, "
                "expressive detailed anime eyes with realistic iris depth, "
                "subtle natural facial micro-expressions, "
                "电影感氛围, 电影级布光, 浅景深, 4K高清纹理, 高精度3D模型, PBR材质, "
                "Chinese Guoman 3D style, East Asian anime face")

# 布料防塑料段：角色服装统一走"真实哑光布料"，抑制 3D CG 渲染最常见的"光滑塑料衣服"。
# 角色库 image_prompt 只写服装款式与颜色（青布衫/粗麻短褐…），材质共性与织纹在此统一注入，
# 挂在三视图/全景图服装描述之前，让布纹/褶皱/旧化压过 CG 默认的高光平滑着色。
FABRIC_MATTE = ("realistic matte period fabric clothing, coarse natural cloth with visible "
                "woven thread grain and fine fabric texture, dull non-reflective cloth surface, "
                "natural cloth wrinkles, soft folds and fabric drape, "
                "faded washed slightly worn aged texture, authentic handwoven hemp and cotton feel, "
                "no shiny smooth plastic-like garments, no glossy lacquered cloth")

# 角色下装硬约束：所有角色必须穿裤子/完整下装，双腿被衣裤完整遮盖，绝不裸露双腿。
# 模型常把角色下半身画成"光腿/没裤子/缩成短装/裙下露腿"，故在此统一钉死；
# 只要是 16:9 全景/三视图角色，都强制 lower body 完整穿着长裤，裙/衫内也须有内衬裤装。
LOWER_BODY_PANTS = ("wearing proper full-length trousers and complete lower-body clothing, "
                    "lower body fully covered, legs completely wrapped in cloth, "
                    "modest full-length pants beneath any dress robe or skirt, "
                    "no bare legs, no exposed thighs or knees, no bare skin on the legs, "
                    "no missing lower-body garment, no overly short or revealing bottoms, "
                    "no bikini-like or underwear-only lower body, "
                    "legs visible only inside full-length clothing, "
                    "the character fully clothed and modestly covered from neck to ankles, "
                    "crotch and whole legs entirely hidden under fabric, no exposed crotch, "
                    "wearing shoes, decently and completely dressed from head to toe")

# 角色"耐看"修饰词：除非小说明确写丑，默认所有角色都要五官端正耐看，避免模型生成歪瓜裂枣脸。
# 词条为年龄中性（不含 youth/young），对少年、中年角色都适用，年龄感由角色库 image_prompt 自带。
ATTRACTIVE_MALE = "handsome and clean-cut facial features, a well-proportioned attractive face, "
ATTRACTIVE_FEMALE = "pretty and lovely facial features, a well-proportioned attractive face, "

# 融合风格负面词：双向抑制三个极端——塑料CG（防塑料）、纯2D动漫（防扁平卡通）、真人实拍（防照片脸）。
# 注意：只防"真人实拍/写实照片"整体风格，不抑制"真实皮肤纹理/毛孔"——两者不同，
# 若把"真人皮肤特写/毛孔"当负面会得到光滑无纹的塑料娃娃脸（用户反馈的核心问题）。
NEG_CHAR_FUSION = NEG_CHAR + ("，塑料感，橡胶皮肤，蜡像质感，雕塑质感，玩具感，光洁塑料，"
                              "陶瓷娃娃皮肤，光滑无毛孔，磨皮过度，滤镜磨皮，无皮肤纹理，"
                              "纯2D动漫，扁平卡通，二次元平面，日系动漫，厚涂，赛璐璐，漫画线稿，漫画脸，"
                              "真人实拍，真实人物照片，电影剧照，写实照片，"
                              "面瘫表情，面无表情，表情呆滞，眼神空洞，"
                              "人物手持道具，手拿道具，手持物品，道具被手持，拿着道具，人拿道具，"
                              "塑料衣服，塑料质感衣物，光滑塑料布面，无布料织纹，反光布面，"
                              "油亮衣物，蜡质衣物，皮革质感衣服，缎面强反光，水光绸缎，"
                              "没穿裤子，未穿长裤，裸露男性下体，裸露生殖器，性器官暴露，裸体，全裸，半裸，"
                              "下身裸露，裸露大腿，裸露小腿，光腿，露腿，短裙，超短下摆，"
                              "裆部裸露，下体外露，赤脚，光脚，未穿鞋")
NEG_GRID_FUSION = NEG_GRID + ("，塑料感，橡胶皮肤，蜡像质感，雕塑质感，玩具感，光洁塑料，"
                              "陶瓷娃娃皮肤，光滑无毛孔，磨皮过度，滤镜磨皮，无皮肤纹理，"
                              "纯2D动漫，扁平卡通，二次元平面，日系动漫，厚涂，赛璐璐，漫画线稿，漫画脸，"
                              "真人实拍，真实人物照片，电影剧照，写实照片，"
                              "面瘫表情，面无表情，表情呆滞，眼神空洞，"
                              "人物手持道具，手拿道具，手持物品，道具被手持，拿着道具，人拿道具，"
                              "塑料衣服，塑料质感衣物，光滑塑料布面，无布料织纹，反光布面，"
                              "油亮衣物，蜡质衣物，皮革质感衣服，缎面强反光，水光绸缎，"
                              "没穿裤子，未穿长裤，裸露男性下体，裸露生殖器，性器官暴露，裸体，全裸，半裸，"
                              "下身裸露，裸露大腿，裸露小腿，光腿，露腿，短裙，超短下摆，"
                              "裆部裸露，下体外露，赤脚，光脚，未穿鞋")

# 统一风格已前置内嵌进角色库每个角色的 image_prompt（写实CG融合 + 真实皮肤纹理 + 耐看颜值）；
# 这里仅在角色库未内置时兜底拼接，避免重复堆叠两遍风格词。
# 检测标记与角色库内置约束段的开头一致（见 剧本/03_角色场景/角色.json）。
FUSION_STYLE_MARK = "stylized 3D Chinese anime character"
FUSION_BEAUTY_MARKS = ("handsome and clean-cut facial features", "pretty and lovely facial features")


def _fusion_base(look):
    return "" if FUSION_STYLE_MARK in look else STYLE_FUSION + ", "


# 角色随身道具：中文名 → 三视图道具板英文描述（与 剧本/03_角色场景/角色.json「随身道具」字段对齐）。
# 仅收录当前《剑噬天下》角色库实际出现的道具，避免旧剧道具残留进角色素材。
PROP_ZH2EN = {
    "佩剑": "an academy standard sword with dark blue wrapped hilt",
    "寒冰长剑": "a long icy sword glowing with pale blue light",
}


def _props_en(props):
    """角色随身道具（中文名列表）→ 道具板英文描述；列表为空返回 None。"""
    if not props:
        return None
    names = [PROP_ZH2EN.get(p, p) for p in props]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


# ---- 角色年龄 → 三视图/全景图的体型与面容成熟度段 ----
# 角色库 age 字段为中文年龄（"15岁"、"40岁"、"中年"…）。三视图模板原来的身体段
# "well-proportioned natural human body, realistic head-to-body ratio" 是统一成人比例，
# 不分年龄，导致少年画成成年人、中年画成小年轻。这里把 age 解析成年龄段，
# 按年龄段注入由年龄决定的共性命中词（身高体态/发育程度/头身比/面部成熟度），
# 具体的高矮胖瘦仍由角色库 image_prompt 自带，避免与各角色专属体型冲突。
# 头身比/体型约束：从"定性描绘"改成"具体头身比 + 腿长/肩宽"，让模型有明确数字可依。
# 原先 "adult head-to-body ratio" 这类模糊说法被模型理解成"正常成人"，出图头偏大、腿偏短；
# 现在按年龄段给出 6.5（少年）/7（少女·青年女性·中年女性）/7.5~8（成年男性）头身，
# 并正面强调"长腿、正确的头身平衡"，比负面式 "no oversized head"（模板里保留）更能锁比例。
AGE_PHYSIQUE = {
    "teen_m": ("a correct slim teenage boy's body proportions, roughly a 6.5-head-tall "
               "natural human figure, long slim legs, narrow youthful shoulders, "
               "balanced correct head-to-body ratio, noticeably shorter than a fully grown adult, "
               "youthful but composed early-maturing features, quiet and aloof, "
               "not a cute childish chibi cartoon face, not a baby face"),
    "teen_f": ("a correct slim teenage girl's body proportions, roughly a 6.5-head-tall "
               "natural human figure, long slim legs, narrow youthful shoulders, "
               "balanced correct head-to-body ratio, noticeably shorter than a fully grown adult, "
               "youthful pretty features with a lively spirited charm, "
               "not a cute childish chibi cartoon face, not a baby face"),
    "young_m": ("a correct tall young adult man's body proportions, roughly a 7.5 to 8-head-tall "
                "natural human figure, long slender legs, broad athletic shoulders, "
                "balanced correct head-to-body ratio, mature youthful man's face"),
    "young_f": ("a correct tall young adult woman's body proportions, roughly a 7-head-tall "
                "natural human figure, long slender legs, narrow elegant shoulders, "
                "balanced correct head-to-body ratio, mature youthful woman's face"),
    "middle_m": ("a correct solid middle-aged man's body proportions, roughly a 7.5-head-tall "
                 "natural human figure, long legs, broad solid shoulders, "
                 "balanced correct head-to-body ratio, mature adult face with subtle age lines"),
    "middle_f": ("a correct middle-aged woman's body proportions, roughly a 7-head-tall "
                 "natural human figure, long legs, balanced correct head-to-body ratio, "
                 "mature adult face with subtle age lines"),
    "elderly_m": ("a thin stooped elderly man's body proportions, long lean limbs, "
                  "correct age-appropriate head-to-body ratio, deeply wrinkled aged face"),
    "elderly_f": ("a thin stooped elderly woman's body proportions, long lean limbs, "
                  "correct age-appropriate head-to-body ratio, deeply wrinkled aged face"),
}


def _age_bucket(age, gender="男"):
    """角色库 age（"15岁"、"40岁"、"中年"…）→ AGE_PHYSIQUE 键；无法识别返回 None。

    分档：未成年(<18)少年少女 / 青年(18~35) / 中年(36~55) / 老年(>55)。
    兼容纯中文档位词（中年/青年/老年/少年），数字优先。
    """
    if not age:
        return None
    m = re.search(r"\d+", age)
    if m:
        n = int(m.group())
    elif "老年" in age or "老汉" in age or "老妇" in age:
        n = 70
    elif "中年" in age:
        n = 45
    elif "青年" in age or "成年" in age:
        n = 28
    elif "少年" in age or "少女" in age or "孩" in age or "童" in age:
        n = 13
    else:
        return None
    g = "f" if gender == "女" else "m"
    if n < 18:
        return "teen_" + g
    if n <= 35:
        return "young_" + g
    if n <= 55:
        return "middle_" + g
    return "elderly_" + g


# 道具板固定模板（用户验收硬要求）：右下角道具板【只展示道具、绝不出现人物】。
# 道具板是一块"纯道具陈列区"，道具作为孤立物品特写、与角色完全分离；
# 严禁任何"人物拿着/手持道具/人拿道具/人体/手/手指"——这段是硬约束，禁止改动削弱。
# 之前 "product display of the character's handheld props only" 被模型理解成"展示角色手持道具"，
# 常画成人拿着道具（人物伸手提灯笼/握刀/端筐）。这里固定为"道具单独陈列 + 无人物 + 无手持/抓握 + 无人影"。
PROP_BOARD_ONLY = ("this panel is a pure prop-only showcase zone, limited to the props by themselves, "
                   "the props shown alone as isolated standalone objects, "
                   "a pure product-photography display of the props by themselves, "
                   "laid or standing on a plain neutral background, "
                   "completely detached from and not held by any character, "
                   "no character, no arm, no hand, no fingers, no wrist, no foot, no limb, "
                   "no person holding, grabbing, wielding, carrying or touching the props, "
                   "no person, no face, no head, no body, no human figure anywhere in the prop board")


# 角色三视图 = 标准设定图布局：左侧大版面为全身三视图（正/侧/背），
# 右侧为表情板（各种表情特写），有随身道具的角色右下另设道具板（仅该角色自己的道具、无人物），
# 无随身道具的角色不设道具板（表情板占满右列），避免模型凭空给角色画道具。
# 右下角道具板是固定模板：永远【只展示道具、绝不出现人物】——见 PROP_BOARD_ONLY 硬约束，不可改动削弱。
# 三块区域自然拼接成一张完整插画，不画分割线/网格线/边框。
# 每个角色传入各自的外貌描述 look + 随身道具 props，保证"每角色对得上剧本设定"；
# physique 为按角色年龄分档注入的身形/头身比/面容成熟度段（见 AGE_PHYSIQUE），
# 缺省退回统一成人比例，避免破坏旧用法。
def char_3view_fusion(look, props=None, physique=None):
    en = _props_en(props or [])
    # 表情板开头：有道具板 → 右上横排一格一面；无道具板 → 右列两列占满
    expr_head = ("right top area: facial expression board, "
                 "eight close-up face-only portraits in a row, one face per panel, "
                 if en else
                 "right side area: facial expression board, "
                 "eight close-up face-only portraits arranged in two columns of four, one face per panel, ")
    panels = ("panel 1: calm and composed with steady determined eyes, "
              "panel 2: gentle warm smile, "
              "panel 3: joyful laugh with open mouth, "
              "panel 4: surprised with raised eyebrows, "
              "panel 5: angry with furrowed brows, "
              "panel 6: sad with drooping mouth, "
              "panel 7: focused and serious, "
              "panel 8: worried and uneasy, "
              "each portrait shows only the face with a distinct clear emotion, "
              "all eight emotions clearly visible and exaggerated, "
              "all eight faces are the same person with the exact same face, "
              "identical features, same hairstyle and same realistic textured skin, "
              "unified 3D animated film style in every expression panel, ")
    prop_board = (("right bottom area: a fixed stand-alone prop-only showcase panel, "
                   "the props only, no people at all, " + en + PROP_BOARD_ONLY + ", ")
                  if en else "")
    body = physique or "well-proportioned natural human body, realistic head-to-body ratio"
    return (_fusion_base(look) + "character concept sheet, standard turnaround reference sheet, "
            "seamless single illustration, "
            "left side large area: three full-body views of the character, "
            "front view standing / side view standing straight / back view, "
            "full body head to toe, feet fully visible, no cut off, "
            + body + ", "
            "same height and build in all three views, "
            "limbs in correct proportion, no oversized head, no distorted torso, "
            + expr_head + panels + prop_board +
            "natural seamless layout, no dividing lines, no grid lines, no borders, no panel outlines, no frames, "
            "elements must not overlap, no elements bleeding into adjacent areas, "
            + FABRIC_MATTE + ", " + LOWER_BODY_PANTS + ", " + look + ", same face, same costume, same character in all areas, "
            "16:9 landscape, clean light background, no text, no watermark")


def char_full_fusion(look, props=None, physique=None):
    en = _props_en(props or [])
    # 有随身道具的角色：右/下侧补一块纯道具产品板（无人物），保证全景图道具也对得上剧本；
    # 无道具的角色不设道具板，避免模型凭空画道具。
    prop_board = ((", prop board, " + en + PROP_BOARD_ONLY + ", ")
                   if en else "")
    return (_fusion_base(look) + "full body standing portrait of one character, front view, "
            "16:9 landscape, " + FABRIC_MATTE + ", " + LOWER_BODY_PANTS + ", " + look + (", " + physique if physique else "") +
            prop_board +
            ", full body from head to toe, "
            "feet fully visible, no cut off, clean light background, "
            "calm resolute natural expression, no text, no watermark")

# —— 时代锚点：剧本《剑噬天下》是「现代都市 + 古武世界」（都市修仙/都市古武题材）——
# 背景是现代都市（摩天大楼、都市夜景、城堡豪宅、豪车、司机、保镖），环境/空镜必须描现代；
# 但这个世界藏着隐世的古武/剑修传承（剑之文明、qi、飞剑、剑灵）。
# 角色（如凌云）的古装长衫保留在角色库 image_prompt 里，不通过环境锚点注入古装，避免全剧古装化。
ERA = (
    "modern urban setting, a contemporary metropolitan world, "
    "a hidden ancient martial and sword-cultivation undercurrent thriving within a modern city, "
    "modern city skyscrapers, luxury mansions and villas, modern vehicles and luxury cars, "
    "modern city streets, architecture and skylines, "
    "ancient xianxia sword forces concealed and coexisting in the modern world, "
    "grand classical aristocratic manor estates of hidden xianxia clans integrated within the modern city, "
    "not a fully ancient world, not a purely feudal old town, not a medieval fantasy village, "
    "not an ancient rural village, not a classical-fantasy sect campus in the countryside"
)

# 场景时代锚点：本剧是「现代都市 + 隐世古武」都市古武世界观。场景素材据此补全世界观定位，
# 将场景框定为现代都市中隐世古武世家（如东家）的居所地，使"古典奢华庄园/城堡/庭院"与现代
# 都市融合，而不落入纯古装/纯古代场景。
SCENE_ERA_ANCHOR = ("a grand luxuriant classical aristocratic estate of a hidden xianxia "
                    "sword-cultivation clan, opulent timeless old-world splendor harmoniously "
                    "integrated within and framed by a contemporary modern metropolis, "
                    "rare fusion of ancient clan grandeur and modern urban elegance")

# —— 剑之文明（都市古武）明亮清透基调（校色核心）：干净通透、清透明亮、温润大气 ——
GLOOMY_TONE = (
    "clean bright cinematic color palette, crisp natural vibrant tones, "
    "warm polished ambient light, translucent airy clarity, "
    "明亮清爽，通透大气，莹润质感"
)

# 按场景库 time 字段推断灯光基调（统一为现代都市基调，弱化"明亮唯美落日"）
TIME_LIGHT = {
    "黄昏": ("golden dusk light, warm amber sunset glow across the modern cityscape, soft long "
             "shadows, calm serene twilight"),
    "傍晚": ("warm amber evening light, golden hour glow, soft long shadows, "
             "pleasant serene sunset warmth"),
    "夜晚": ("moonlit night, soft cool moonlight blended with warm lamp glow, "
             "balanced cinematic low-key light"),
    "清晨": ("soft bright morning light, gentle warm sunlight through windows, clean airy "
             "clarity, fresh dawn glow"),
}


def _time_light(t):
    t = t or ""
    base = TIME_LIGHT["黄昏"]
    if t.startswith("黄昏") or "夕照" in t or "暮" in t:
        base = TIME_LIGHT["黄昏"] + ", twilight fading light"
    elif t.startswith("傍晚") or t.startswith("夜幕"):
        base = TIME_LIGHT["傍晚"]
    elif "夜" in t:
        base = TIME_LIGHT["夜晚"]
    else:
        base = TIME_LIGHT["清晨"]
    return base + ", " + GLOOMY_TONE


# 场景九宫格：3x3 九格，每格是同一场景、不同机位/构图（大远景/全景/广角/中景/平视/仰视/俯视/局部特写/暮色变体），
# 纯环境、无人物；用细网格线分隔九格，保证九格清晰、彼此不重叠、内容不溢出。
SCENE_GRID_PANELS = (
    "a 3x3 nine-panel grid, nine distinct panels of the exact same empty scene, "
    "panel 1: extreme wide establishing shot of the whole landscape, "
    "panel 2: wide shot framing the entire environment, "
    "panel 3: wide-angle ground-level shot from inside the scene, "
    "panel 4: medium shot from the near edge of the foreground, "
    "panel 5: eye-level medium shot centered on the main area of the scene, "
    "panel 6: dramatic low angle up-shot of the tall elements, "
    "panel 7: high-angle aerial top-down layout view of the whole area, "
    "panel 8: close-up detail of the key environmental props, "
    "panel 9: a moodier contrasting time-of-day take on the same environment, "
    "each panel shows the identical scene with the same props, same layout and same lighting, "
    "each panel differs only in camera angle, vantage point and composition, "
)


def _scene_props_en(scene):
    """把场景库该场景的专属道具清单 → 英文视觉定妆段。

    同一场景九宫格的 9 个格子必须出现同一批道具、同一视觉定妆；
    不同场景的道具互不借用。道具库同一道具在不同场景按剧本要求呈现不同状态。
    无 props 字段时返回空串，顺滑兼容旧场景库。
    """
    props = scene.get("props") or []
    descs = [p.get("image_prompt", "").strip() for p in props if p.get("image_prompt", "").strip()]
    if not descs:
        return ""
    return ("Key props, a fixed set consistent across ALL nine panels: " + " ; ".join(descs) +
            "; every panel shows the exact same props, identical silhouette, shape, material, color, "
            "scale and placement, nothing differs from panel to panel; "
            "only this scene's own props, no props borrowed from any other scene")


def scene_concept(scene, kind, iw=1216, ih=832):
    """把场景库一条场景 → 场景素材正向提示词（替代原占位符模板）。

    kind: '3view'（九宫格环境参考图，3x3 九格同一场景不同机位，无人物）/
          'full'（wide 全景大远景）。
    纯场景、完全无人；风格用 STYLE_SCENE（去掉皮肤/面部/五官词），负面用 NEG_SCENE_GRID，
    避免模型把场景画成"人物三视图"或混入人影。场景专属道具清单（props）以固定定妆
    注入，九格共用同一批道具、道具形象跨格一致；不同场景道具互不相同。
    """
    is_3v = kind == "3view"
    props_seg = _scene_props_en(scene)
    head = SCENE_GRID_PANELS if is_3v else (
        "wide environment concept sheet, wide establishing shot, cinematic single expansive vista, ")
    camera = ("front / side / back consistent vantage points, eye-level, "
              "identical layout and props across all views" if is_3v else
              "wide establishing shot, elevated eye-level vantage")
    return (STYLE_SCENE + ", " + ERA + ", " + head + "16:9 landscape, %dx%d, " % (iw, ih) +
            scene.get("name", "") + ", " +
            "Subject & Environment: " + scene.get("prompt", "") +
            (", " + props_seg if props_seg else "") + ", " +
            SCENE_ERA_ANCHOR + ", " +
            "Composition & Space: clear spatial depth, layered foreground-midground-background, " +
            "natural framing, open negative space, " +
            "Lighting & Color: " + _time_light(scene.get("time", "")) + ", " +
            "Cinematography & Imaging: wide-angle perspective, deep scenic focus, " +
            "volumetric light, PBR materials, atmospheric haze, " +
            "Camera: " + camera + ", " +
            "no character, absolutely no people, empty environment, no human figure, " +
            "no face, no body, no silhouette of any person anywhere, " +
            "same layout, same props, same lighting, " +
            "clean thin grid lines separating the nine panels, " +
            "Chinese Guoman 3D style, China-style illustration background, " +
            "no text, no watermark")


# 分镜 result（中文收尾）→ 尾帧英文收尾定格段（兜底回退到首帧 image_prompt 主体）
RESULT_EN = {
    "s01": "the camera gently settles on the grand sword monument amid soft morning mist",
    "s02": "the faint qi above the young man's palm stills as he holds his focus",
    "s03": "the cheerful young man grins, waiting for his roommate's reply",
    "s04": "he keeps teasing, the mood light and playful",
    "s05": "the dark-haired young man stays calm, unmoved by the words",
    "s06": "a quiet resolve settles in his eyes as he speaks",
    "s07": "the young man leans in, eyes wide with surprise and hope",
    "s08": "he laughs, brimming with pride for their dorm",
    "s09": "the slight frown fades as he closes his eyes again",
    "s10": "the young man backs off with a cheerful wave of the hand",
    "s11": "the young man sinks deeper into meditation, energy slowly circling",
    "s12": "the camera drifts quietly along the sunlit tree-lined path",
    "s13": "the stocky friend grumbles, half-teasing",
    "s14": "he puffs out his chest, boastful and pleased",
    "s15": "their laughter rings out as the distant icy glint catches a cold gleam",
    "s16": "the young man finishes bandaging his finger, gaze fixed on the horizon",
    "s17": "the determined silhouette stands tall against the blazing dusk sky",
}


def _attach_props(subject, sb, props_by_id=None):
    """把该镜在场角色的随身道具并进去重，转英文追加到主语描述尾部。

    分镜库 image_prompt 只写了人物动作与场景，角色库「随身道具」（佩剑/寒冰长剑）没进分镜链路，
    导致关键道具在首尾帧丢失。此处在主语后补一句道具清单，
    让凌云的佩剑、雪韵的寒冰长剑与《剑噬天下》剧本对上。
    无在场角色或无道具时原样返回，避免出现空段/悬空逗号。
    """
    if not props_by_id:
        return subject
    zh = []
    for cid in (sb.get("character_ids") or []):
        for p in (props_by_id.get(cid) or []):
            if p not in zh:
                zh.append(p)
    en = _props_en(zh) if zh else None
    if not en:
        return subject
    return subject.rstrip(", ") + ", key handheld props present: " + en


def shot_negative(sb, is_empty):
    """按分镜数据精准组装反向提示词（替代"空镜/非空"一刀切）。

    空镜：强排人（复用 NEG_SCENE_GRID，与场景素材一致）。
    单角：防加成"第二人 / 换脸 / 多余角色"。
    多角：防"角色重叠 / 串角色 / 超人数"，并按该镜实际人数锁定上限。
    统一底座 NEG_CHAR_FUSION：防塑料CG / 纯2D动漫 / 真人实拍 + 手持道具 + 下装穿帮。
    """
    if is_empty:
        return NEG_SCENE_GRID
    neg = NEG_CHAR_FUSION
    n = len(sb.get("character_ids") or [])
    if n <= 1:
        return neg + ("，多余的第二个入镜人物，额外人物，多余角色，群演，路人，"
                      "同一角色变出两个，主角人脸被替换，角色面容中途改变，换脸，"
                      "画面出现未设定的人")
    return neg + ("，角色相互重叠融合，角色身份互换，甲乙串角色，多人脸混叠，"
                  "人数超过 %d 个，多余的路人甲乙丙" % n)


def frame_shot(sb, kind, props_by_id=None, iw=1216, ih=832):
    """把分镜一条 storyboard → 首帧/尾帧正向提示词（替代原占位符模板）。

    首帧：主体直接用分镜 image_prompt（storyboard-breaker 已产出的镜头英文描述）。
    尾帧：另写，主体复用 image_prompt 并以分镜 result 映射的"收尾定格段"收束。
    镜头/光影/机位细分由分镜 angle/shot_type/movement/atmosphere/time 推断填充；
    props_by_id（角色 id → 随身道具列表）把在场角色道具注入主语，保证道具对得上剧本。
    """
    ip = sb.get("image_prompt", "")
    if kind == "first":
        subject = ip
        end_seg = ""
    else:
        # 尾帧：Subject 与首帧【完全一致】，绝不往 Subject 里塞首帧没有的新物体，
        # 只把"收尾定格"作为镜头语言追加到 Composition 尾部，保证同一场景/道具不变两版。
        subject = ip
        end = RESULT_EN.get(sb.get("shot_id", ""))
        end_seg = ("final end-of-shot framed composition, " +
                   (end if end else "the moment resolves as the shot ends"))
    subject = _attach_props(subject, sb, props_by_id)
    angle = sb.get("angle", "平视")
    shot_type = sb.get("shot_type", "近景")
    movement = sb.get("movement", "固定")
    time = sb.get("time", "")
    atmo = sb.get("atmosphere", "")
    # 空镜（无在场角色）：切换为纯场景风格、显式排除任何人物/人脸，
    # 避免角色 LoRA / 人脸风格词把空镜画成"场景里冒人头"。
    char_ids = sb.get("character_ids") or []
    has_char = bool(char_ids)
    if has_char:
        style_head = STYLE_FUSION + ", " + ERA + ", "
        empty_seg = ""
        n = len(char_ids)
        # 精准锁定本镜在场角色数：防模型自由加多/加成群演/漏人。
        # "exactly N people / only these specific characters" 是 H3 首尾帧防加错人的关键。
        people_seg = (", strictly exactly %d person%s in this shot, scene shows only these specific " %
                      (n, "" if n == 1 else "s") +
                      "character%s, no additional people, no extra crowd, no passing strangers" %
                      ("" if n == 1 else "s"))
    else:
        style_head = STYLE_SCENE + ", " + ERA + ", "
        empty_seg = (", absolutely no people, empty environment, no human figure, "
                     "no face, no body, no silhouette of any person anywhere")
        people_seg = ""
    return (style_head + "16:9 landscape, %dx%d, cinematic single shot, " % (iw, ih) +
            "Subject & Environment: " + subject + empty_seg + people_seg + ", "
            "Composition & Space: camera angle " + angle + ", " + shot_type +
            ", " + movement + " camera movement, layered spatial depth, natural framing"
            + (", " + end_seg if end_seg else "") + ", "
            "Lighting & Color: " + _time_light(time) + ", " + atmo + ", cinematic color grading, "
            "Cinematography & Imaging: realistic rendering, volumetric light, "
            "shallow depth of field, 4K detail, PBR materials, "
            "Camera: " + angle + " " + shot_type + ", " + movement +
            ", no text, no watermark")


def _node(nid, ntype, title, widgets, inputs, outputs, pos, size=(360, 82), order=0):
    return {"id": nid, "type": ntype, "pos": pos, "size": size, "flags": {},
            "order": order, "mode": 0, "inputs": inputs, "outputs": outputs,
            "properties": {"Node name for S&R": ntype}, "widgets_values": widgets,
            "title": title}


def _io(name, typ, link=None):
    d = {"name": name, "type": typ}
    if link is not None:
        d["link"] = link
    return d


def make_img(unet, clip, ctype, vae, lora, strength, pos, neg, w, h,
             steps, cfg, seed, prefix, utitle, ltitle):
    n = []
    n = []
    n.append(_node(1, "UNETLoader", utitle, [unet, "default"],
                   [_io("unet_name", "COMBO"), _io("weight_dtype", "COMBO")],
                   [{"name": "MODEL", "type": "MODEL", "links": []}], [0, 0]))
    n.append(_node(2, "CLIPLoader", "CLIP", [clip, ctype, "default"],
                   [_io("clip_name", "COMBO"), _io("type", "COMBO"), _io("device", "COMBO")],
                   [{"name": "CLIP", "type": "CLIP", "links": [2, 3]}], [420, 0], size=(360, 106)))
    n.append(_node(3, "VAELoader", "VAE", [vae],
                   [_io("vae_name", "COMBO")],
                   [{"name": "VAE", "type": "VAE", "links": [4]}], [840, 0], size=(360, 58)))
    # 可选 LoRA 注入：传 lora 则插 LoraLoaderModelOnly；lora=None 时 UNET 直接连 KSampler（场景图不用角色 LoRA）。
    if lora:
        n.append(_node(4, "LoraLoaderModelOnly", ltitle, [lora, strength],
                       [_io("model", "MODEL", 1), _io("lora_name", "COMBO"), _io("strength_model", "FLOAT")],
                       [{"name": "MODEL", "type": "MODEL", "links": [5]}], [0, 160]))
        model_src = (4, 0, 5)
        n[0]["outputs"][0]["links"].append(1)
    else:
        model_src = (1, 0, 5)
        n[0]["outputs"][0]["links"].append(5)
    n.append(_node(5, "CLIPTextEncode", "正向提示词", [pos],
                   [_io("clip", "CLIP", 2), _io("text", "STRING")],
                   [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [6]}], [420, 200], size=(420, 260)))
    n.append(_node(6, "CLIPTextEncode", "负面提示词", [neg],
                   [_io("clip", "CLIP", 3), _io("text", "STRING")],
                   [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [7]}], [420, 500], size=(420, 160)))
    n.append(_node(7, "EmptySD3LatentImage", "空潜空间 16:9", [w, h, 1],
                   [_io("width", "INT"), _io("height", "INT"), _io("batch_size", "INT")],
                   [{"name": "LATENT", "type": "LATENT", "links": [8]}], [840, 160], size=(280, 106)))
    # 注：KSampler 的 seed 字段声明了 control_after_generate，前端保存时会在 widgets_values
    # 的 seed 后紧跟一个控制占位值（如 "fixed"）。这里必须写入占位，保证与标准/ComfyUI 序列一致，
    # 否则 submit_workflow.ui_to_api 顺序解析会把后续 steps/cfg/sampler/scheduler 全部错位。
    n.append(_node(8, "KSampler", "KSampler", [seed, "fixed", steps, cfg, "euler", "normal", 1.0],
                   [_io("model", "MODEL", model_src[2]), _io("positive", "CONDITIONING", 6),
                    _io("negative", "CONDITIONING", 7), _io("latent_image", "LATENT", 8),
                    _io("seed", "INT"), _io("steps", "INT"), _io("cfg", "FLOAT"),
                    _io("sampler_name", "COMBO"), _io("scheduler", "COMBO"), _io("denoise", "FLOAT")],
                   [{"name": "LATENT", "type": "LATENT", "links": [9]}], [840, 340], size=(380, 262)))
    n.append(_node(9, "VAEDecode", "VAE Decode", [],
                   [_io("samples", "LATENT", 9), _io("vae", "VAE", 4)],
                   [{"name": "IMAGE", "type": "IMAGE", "links": [10]}], [1260, 340], size=(210, 46)))
    n.append(_node(10, "SaveImage", "保存图片", [prefix],
                   [_io("images", "IMAGE", 10), _io("filename_prefix", "STRING")],
                   [], [1260, 440], size=(380, 120)))
    links = []
    if lora:
        links.append([1, 1, 0, 4, 0, "MODEL"])
    links += [
        [2, 2, 0, 5, 0, "CLIP"],
        [3, 2, 0, 6, 0, "CLIP"],
        [4, 3, 0, 9, 1, "VAE"],
        [5, model_src[0], 0, 8, 0, "MODEL"],
        [6, 5, 0, 8, 1, "CONDITIONING"],
        [7, 6, 0, 8, 2, "CONDITIONING"],
        [8, 7, 0, 8, 3, "LATENT"],
        [9, 8, 0, 9, 0, "LATENT"],
        [10, 9, 0, 10, 0, "IMAGE"],
    ]
    return {"last_node_id": 10, "last_link_id": 10, "nodes": n, "links": links,
            "groups": [], "config": {}, "extra": {}, "version": 0.4}


def make_img2img(unet, clip, ctype, vae, lora, strength, pos, neg,
                 init_image, denoise, steps, cfg, seed, prefix, utitle, ltitle):
    """img2img 版生图工作流：以一张已有图(init_image)为底图，denoise<1 做"收尾定格"重绘。

    专门用于【尾帧】，底图=该镜首帧图(LoadImage 读 ComfyUI input 目录)。这样尾帧会
    继承首帧的场景/方向/人物位置，只在 denoise 范围内微调构图收束，从根本上保证
    首尾帧同一场景、同一道具、同一人物"不变两版"——此前尾帧是独立 text2img，
    且提示词里多了首帧没有的额外物体会导致尾帧场景被重新生成而"变了两版"。
    init_image 为相对 ComfyUI input 目录的路径(如 02_分镜/第1集/第1集_镜s01_首帧_*.png)。

    其余节点(id 1..6 模型/CLIP/VAE/LoRA/正负提示词、8..10 采样/解码/保存)与 make_img 一致，
    只把 latent 来源从 EmptySD3LatentImage 换成 LoadImage(7)+VAEEncode(11)。
    """
    n = []
    n.append(_node(1, "UNETLoader", utitle, [unet, "default"],
                   [_io("unet_name", "COMBO"), _io("weight_dtype", "COMBO")],
                   [{"name": "MODEL", "type": "MODEL", "links": []}], [0, 0]))
    n.append(_node(2, "CLIPLoader", "CLIP", [clip, ctype, "default"],
                   [_io("clip_name", "COMBO"), _io("type", "COMBO"), _io("device", "COMBO")],
                   [{"name": "CLIP", "type": "CLIP", "links": [2, 3]}], [420, 0], size=(360, 106)))
    n.append(_node(3, "VAELoader", "VAE", [vae],
                   [_io("vae_name", "COMBO")],
                   [{"name": "VAE", "type": "VAE", "links": [4]}], [840, 0], size=(360, 58)))
    if lora:
        n.append(_node(4, "LoraLoaderModelOnly", ltitle, [lora, strength],
                       [_io("model", "MODEL", 1), _io("lora_name", "COMBO"), _io("strength_model", "FLOAT")],
                       [{"name": "MODEL", "type": "MODEL", "links": [5]}], [0, 160]))
        model_src = (4, 0, 5)
        n[0]["outputs"][0]["links"].append(1)
    else:
        model_src = (1, 0, 5)
        n[0]["outputs"][0]["links"].append(5)
    n.append(_node(5, "CLIPTextEncode", "正向提示词", [pos],
                   [_io("clip", "CLIP", 2), _io("text", "STRING")],
                   [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [6]}], [420, 200], size=(420, 260)))
    n.append(_node(6, "CLIPTextEncode", "负面提示词", [neg],
                   [_io("clip", "CLIP", 3), _io("text", "STRING")],
                   [{"name": "CONDITIONING", "type": "CONDITIONING", "links": [7]}], [420, 500], size=(420, 160)))
    # img2img：读首帧底图 → VAE 编码成潜空间 → 作为 KSampler 的 latent_image(denoise<1)
    # LoadImage 的 inputs 采用 build_fl2va_refs 已验证的结构(localized_name/widget)，确保 submit 转换正确。
    n.append(_node(7, "LoadImage", "首帧底图", [init_image, "image"],
                   [{"localized_name": "图像", "name": "image", "type": "COMBO",
                     "widget": {"name": "image"}, "link": None},
                    {"localized_name": "选择文件上传", "name": "upload", "type": "IMAGEUPLOAD",
                     "widget": {"name": "upload"}, "link": None}],
                   [{"localized_name": "图像", "name": "IMAGE", "type": "IMAGE", "links": [12]},
                    {"localized_name": "遮罩", "name": "MASK", "type": "MASK", "links": None}],
                   [840, 160], size=(280, 314)))
    n.append(_node(11, "VAEEncode", "VAE Encode", [],
                   [_io("pixels", "IMAGE", 12), _io("vae", "VAE", 11)],
                   [{"name": "LATENT", "type": "LATENT", "links": [8]}], [1160, 160], size=(210, 46)))
    # 注：seed 后紧跟 "fixed" 控制占位，保证 widgets_values 与标准序列一致(见 make_img 注释)。
    n.append(_node(8, "KSampler", "KSampler", [seed, "fixed", steps, cfg, "euler", "normal", denoise],
                   [_io("model", "MODEL", model_src[2]), _io("positive", "CONDITIONING", 6),
                    _io("negative", "CONDITIONING", 7), _io("latent_image", "LATENT", 8),
                    _io("seed", "INT"), _io("steps", "INT"), _io("cfg", "FLOAT"),
                    _io("sampler_name", "COMBO"), _io("scheduler", "COMBO"), _io("denoise", "FLOAT")],
                   [{"name": "LATENT", "type": "LATENT", "links": [9]}], [1160, 340], size=(380, 262)))
    n.append(_node(9, "VAEDecode", "VAE Decode", [],
                   [_io("samples", "LATENT", 9), _io("vae", "VAE", 4)],
                   [{"name": "IMAGE", "type": "IMAGE", "links": [10]}], [1560, 340], size=(210, 46)))
    n.append(_node(10, "SaveImage", "保存图片", [prefix],
                   [_io("images", "IMAGE", 10), _io("filename_prefix", "STRING")],
                   [], [1560, 440], size=(380, 120)))
    links = []
    if lora:
        links.append([1, 1, 0, 4, 0, "MODEL"])
    links += [
        [2, 2, 0, 5, 0, "CLIP"],
        [3, 2, 0, 6, 0, "CLIP"],
        [4, 3, 0, 9, 1, "VAE"],
        [5, model_src[0], 0, 8, 0, "MODEL"],
        [6, 5, 0, 8, 1, "CONDITIONING"],
        [7, 6, 0, 8, 2, "CONDITIONING"],
        [8, 11, 0, 8, 3, "LATENT"],
        [9, 8, 0, 9, 0, "LATENT"],
        [10, 9, 0, 10, 0, "IMAGE"],
        [11, 3, 0, 11, 1, "VAE"],
        [12, 7, 0, 11, 0, "IMAGE"],
    ]
    return {"last_node_id": 11, "last_link_id": 12, "nodes": n, "links": links,
            "groups": [], "config": {}, "extra": {}, "version": 0.4}


def load_example(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
        return json.load(f)


def _set_timeline_size(wv, width, height):
    wv[7] = width
    wv[8] = height
    wv[9] = max(width, height)
    tl = json.loads(wv[11])
    tl["width"] = width
    tl["height"] = height
    tl["refMaxSize"] = max(width, height)
    if isinstance(tl.get("output"), dict):
        tl["output"]["width"] = width
        tl["output"]["height"] = height
        tl["output"]["longEdge"] = max(width, height)
    wv[11] = json.dumps(tl, ensure_ascii=False)


def insert_lora(wf, lora_name, strength=1.0, lora_title="H3 Turbo LoRA (8-step)"):
    nodes = wf["nodes"]
    links = wf["links"]
    unet = next(n for n in nodes if n["type"] == "UNETLoader")
    director = next(n for n in nodes if n["type"] == "MiniMaxH3Director")
    new_id = max(n["id"] for n in nodes) + 1
    lora_node = {
        "id": new_id, "type": "LoraLoaderModelOnly", "pos": [0, 160],
        "size": [360, 82], "flags": {}, "order": max(n["order"] for n in nodes) + 1,
        "mode": 0,
        "inputs": [_io("model", "MODEL", None), _io("lora_name", "COMBO"),
                   _io("strength_model", "FLOAT")],
        "outputs": [{"name": "MODEL", "type": "MODEL", "links": []}],
        "properties": {"Node name for S&R": "LoraLoaderModelOnly"},
        "widgets_values": [lora_name, strength], "title": lora_title,
    }
    nodes.append(lora_node)
    old_link = next(l for l in links if l[1] == unet["id"] and l[3] == director["id"] and l[5] == "MODEL")
    old_link_id = old_link[0]
    old_link[3] = new_id
    old_link[4] = 0
    lora_node["inputs"][0]["link"] = old_link_id
    new_link_id = max(l[0] for l in links) + 1
    links.append([new_link_id, new_id, 0, director["id"], 0, "MODEL"])
    lora_node["outputs"][0]["links"].append(new_link_id)
    model_input = next(i for i in director["inputs"] if i["name"] == "model")
    model_input["link"] = new_link_id
    wf["last_node_id"] = max(wf.get("last_node_id", new_id), new_id)
    wf["last_link_id"] = max(wf.get("last_link_id", new_link_id), new_link_id)
    return wf


def modify_director(wf, steps, width, height, save_prefix):
    director = next(n for n in wf["nodes"] if n["type"] == "MiniMaxH3Director")
    wv = director["widgets_values"]
    wv[13] = steps
    _set_timeline_size(wv, width, height)
    save = next(n for n in wf["nodes"] if n["type"] == "SaveVideo")
    save["widgets_values"][0] = save_prefix
    return wf


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_scenes():
    """从场景库读取全部场景（sc001/sc002…）。库缺失/损坏返回空，不裸抛炸链。"""
    if not os.path.exists(SCENE_DB):
        print("[build] 提示: 场景库缺失 -> %s" % SCENE_DB)
        return []
    try:
        with open(SCENE_DB, encoding="utf-8") as f:
            return json.load(f).get("scenes", [])
    except (OSError, json.JSONDecodeError) as e:
        print("[build] 警告: 场景库读取失败 %s -> %s，按空返回" % (os.path.basename(SCENE_DB), e))
        return []


def load_storyboards():
    """从分镜库读取全部分镜（每镜一条 storyboard）。库缺失/损坏返回空，不裸抛炸链。"""
    if not os.path.exists(STORYBOARD_DB):
        print("[build] 提示: 分镜库缺失 -> %s" % STORYBOARD_DB)
        return []
    try:
        with open(STORYBOARD_DB, encoding="utf-8") as f:
            return json.load(f).get("storyboards", [])
    except (OSError, json.JSONDecodeError) as e:
        print("[build] 警告: 分镜库读取失败 %s -> %s，按空返回" % (os.path.basename(STORYBOARD_DB), e))
        return []


def load_roles():
    """从角色库读取全部角色（含 image_prompt 的实体角色，排除旁白）。"""
    _default_c01 = {"id": "c01", "name": "凌云", "gender": "男", "age": "18岁",
                    "image_prompt": "A lean dark-haired 18-year-old young man, short neat black hair, "
                                    "sharp calm determined eyes, strong will in his gaze, slender but "
                                    "athletic build, dark blue academy uniform with gold trim and white collar"}
    if not os.path.exists(ROLE_DB):
        print("[build] 提示: 角色库缺失 -> %s，使用默认角色 c01 凌云" % ROLE_DB)
        return [_default_c01]
    try:
        with open(ROLE_DB, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print("[build] 警告: 角色库读取失败 %s -> %s，使用默认角色 c01" % (os.path.basename(ROLE_DB), e))
        return [_default_c01]
    roles = []
    for c in data.get("characters", []):
        if c.get("role_type") == "旁白":
            continue  # 跳过旁白（无实体形象）
        if c.get("image_prompt", "N/A") in ("N/A", ""):
            continue  # 跳过无实体形象角色
        roles.append({"id": c["id"], "name": c["name"], "gender": c.get("gender", "男"),
                      "age": c.get("age", ""),
                      "image_prompt": c["image_prompt"],
                      "props": c.get("随身道具", [])})
    return roles


def build_char_assets(IMG_W, IMG_H, SNAME, SFX, STRENGTH):
    """重建全部角色的三视图工作流（01_char3view_*）。

    人物只需三视图（含表情板/道具板），不做人物全景图——全景/写实大图由
    场景三视图工作流（03_scene3view_*）承担。
    每个角色按角色库 age 分档注入身形段（AGE_PHYSIQUE），保证三视图
    画出来的身高体态、头身比、面部成熟度符合该角色年龄；age 缺失时退回统一成人比例。
    """
    roles = load_roles()
    for role in roles:
        physique = AGE_PHYSIQUE.get(_age_bucket(role.get("age"), role.get("gender", "男")))
        look = role_look(role)
        pfx = f"00_角色素材/{role['name']}/{role['id']}_"
        rid = "" if role["id"] == "c01" else f"_{role['id']}"
        unet, clip, ctype, vae, lora = Q
        write(os.path.join(OUT, f"01_char3view_{IMG_W}x{IMG_H}_Qwen2512{rid}_{SFX}.json"),
              make_img(unet, clip, ctype, vae, lora, STRENGTH,
                       char_3view_fusion(look, role.get("props", []), physique),
                       NEG_GRID_FUSION, IMG_W, IMG_H, 30, 4.0, 42, pfx + "三视图_" + SNAME,
                       "Qwen-2512 DiT", f"角色 LoRA ({STRENGTH})"))
        if physique:
            print(f"  [{role['id']}]{role['name']} age={role.get('age')} -> "
                  f"({_age_bucket(role.get('age'), role.get('gender', '男'))}) 注入年龄身形段")
        else:
            print(f"  [{role['id']}]{role['name']} age={role.get('age')} -> 未识别，保持统一成人比例")


def build_scene_assets(IMG_W, IMG_H):
    """重建全部场景的九宫格工作流（03_scene3view_*）。

    场景图=3x3 九宫格纯环境参考图（同一场景九个机位，无人物，不再单独出全景图 04_scenefull_*）。
    纯环境不用角色 LoRA（lora=None），风格用 STYLE_SCENE、负面用 NEG_SCENE_GRID，
    避免模型把场景画成"人物三视图"或混入人影/人脸。
    """
    unet, clip, ctype, vae, _ = Q
    for sc in load_scenes():
        sid = sc.get("id", "sc")
        sname = sc.get("name", sid)
        psc = f"01_场景素材/{sname}/{sname}_"
        write(os.path.join(OUT, f"03_scene3view_{IMG_W}x{IMG_H}_Qwen2512_{sid}.json"),
              make_img(unet, clip, ctype, vae, None, 0.0, scene_concept(sc, "3view"), NEG_SCENE_GRID,
                       IMG_W, IMG_H, 30, 4.0, 42, psc + "九宫格", "Qwen-2512 DiT", "背景 LoRA"))
        print(f"  [场景 {sid}]{sname} -> 九宫格(无人物)")


# 剧本**明确写丑**（丑/畸形/毁容/脸部疤痕/黄牙/龅牙/烂牙/麻子）才豁免颜值修饰；
# 仅"凶悍/阴鸷/狰狞表情"等气质描写不算丑，依然加耐看词——凶可以，但脸不能歪。
# 中年/沧桑/憔悴/普通也不算丑，默认同样保证五官端正。
UGLY_MARKERS = ("ugly", "ugliness", "hideous", "deformed", "disfigured", "scarred",
                "scar on face", "scar on cheek", "scar across", "yellow teeth", "yellowed teeth",
                "rotten teeth", "missing teeth", "snaggletooth", "gapped teeth", "mole-covered",
                "warty", "pockmarked", "harelip")


# 时代背景锚点：本剧《剑噬天下》为「现代都市 + 隐世古武」的都市古武/都市修仙世界。
# 角色提取（三视图 look）据此补全世界观定位，让角色形象对得上时代而不过度古装化。
# 该段只补"世界观定位 + 从头到脚完整穿着"，不硬塞都市服装，保留角色库 image_prompt 的角色自身设定。
ROLE_ERA_ANCHOR = ("a character of a hidden ancient sword-cultivation legacy tucked within a "
                   "modern metropolis, timeless xianxia aesthetics blending with a contemporary "
                   "urban presence, a fully dressed and well-groomed character from head to toe, "
                   "complete and proper clothing with footwear, lower body decently clad")


def role_look(role):
    """把角色库 image_prompt 转成三视图可用的外貌描述段：
    去掉姿势/环境/画质尾巴，仅保留人物外貌 + 颜值修饰词 + 时代背景锚点。
    image_prompt 已内置统一风格/皮肤/颜值约束（角色库前置），这里做幂等兜底：
    已含颜值词不重复追加；旧角色库未前置约束时仍按性别补颜值词（丑豁免）。
    三视图统一站姿/无手持，因此把 image_prompt 里的坐姿/手持/携带词一并裁掉（道具由道具板单独陈列）。"""
    img = role["image_prompt"]
    # 逐段裁掉姿势/手持/环境/画质尾巴，只留纯人物造型（发型/脸/服装/气质）
    for cut in ("cinematic portrait", "cinematic close-up", "cinematic portrait,",
                ", standing", ", sitting", ", walking", ", kneeling", ", crouching",
                ", holding", ", carrying", ", wielding", ", gripping",
                ", resting at his side", ", resting at her side", ", resting at"):
        idx = img.find(cut)
        if idx > 0:
            img = img[:idx]
    img = img.strip().rstrip(",")
    # 下装兜底（"下装必写"的脚本层保证）：若外貌只写了盖腿长袍/长衫/裙（robe/gown/dress/衫/袍/裙）
    # 而未明示下装（trousers/pants/裤），统一注入"内着长裤、全身从头到脚完整着装、含鞋"，
    # 防止模型画出"袍下光腿 / 没裤子 / 缩成短装 / 裙下露腿"。剧本多为长衫/裙装角色，此兜底必开启。
    low = img.lower()
    _ROBE_LIKE = ("robe", "gown", "dress", "tunic", "long coat", "长衫", "长袍", "衫", "袍", "裙")
    _BOTTOM_OK = ("trousers", "pants", "裤", "breeches", "leggings", "slacks", "bottoms")
    if any(w in low for w in _ROBE_LIKE) and not any(w in low for w in _BOTTOM_OK):
        img = (img.rstrip().rstrip(",") +
               ", proper full-length trousers and complete full lower-body clothing beneath "
               "the robe or dress, fully and modestly dressed from head to toe, footwear included")
        low = img.lower()
    # 默认颜值：除非小说明确写丑，否则统一加耐看修饰；若角色库已前置颜值词则跳过
    if any(m in low for m in FUSION_BEAUTY_MARKS):
        return img + ", " + ROLE_ERA_ANCHOR
    if not any(m in low for m in UGLY_MARKERS):
        img += (", " + ATTRACTIVE_MALE if role["gender"] == "男" else ", " + ATTRACTIVE_FEMALE)
    return img + ", " + ROLE_ERA_ANCHOR


def main():
    # 可选：只重建指定镜头（--shot=01），用于单独重生成某个镜的首尾帧
    shot_filter = None
    for a in sys.argv:
        if a.startswith("--shot="):
            shot_filter = a.split("=", 1)[1]
    IMG_W, IMG_H = 1216, 832  # 生图横屏（Qwen 常用横屏尺寸）
    VID_W, VID_H = 1280, 736  # 视频横屏（H3 官方横屏推荐值，可导出 1920x1080）
    TAIL_DENOISE = 0.55       # 尾帧 img2img 重绘强度：中等，保留首帧场景/方向/人物，仅重绘收尾构图
    # 视频成品前缀（示例，跑通即可改）
    PFX_VIDEO = "02_分镜/第1集/第1集_镜s01_成片"

    # 统一风格：写实CG融合的完美动漫人物（3D国漫动画电影质感）
    # 角色LoRA"国漫短剧3D CG质感角色"正是"动漫造型+CG渲染"，强度 0.8 保持风格
    # 文件名用 ASCII 后缀（Fusion），避免命令行/API 传中文路径的编码问题
    SNAME = "写实CG融合"
    SFX = "Fusion"
    STRENGTH = 0.8

    # 仅加了 --shot=N（单独重出某镜首尾帧）时，不重建角色/场景素材与视频模板，
    # 避免把已调好的素材工作流覆盖；只有全量重建(不带 --shot)才走全部。
    if not shot_filter:
        # ---- 角色素材（Qwen-2512 单模型，横屏 1216x832）----
        # 与外部项目 D:\AIGC中国风3D漫剧 实际主力一致：分镜只用 Qwen，ZImage 仅早期试做已弃用
        # 每个角色用自己的 image_prompt → 各自的三视图工作流，保证"每角色对得上剧本设定"；
        # c01 凌云保留默认文件名（兼容方案文档一键 SOP 命令），其余角色文件名带角色 id；
        # 按角色库 age 分档注入身形段（少年/青年/中年/老年），见 build_char_assets()
        build_char_assets(IMG_W, IMG_H, SNAME, SFX, STRENGTH)

        # ---- 场景素材（Qwen-2512 单模型，消费 场景.json 逐场景生成三视图）----
        # 场景三视图已覆盖场景全景（wide 大远景），不再单独出全景图（04_scenefull_*）
        build_scene_assets(IMG_W, IMG_H)

    # ---- 分镜首帧 / 尾帧（Qwen，横屏 1216x832，融合风格，消费 分镜库 逐镜生成）----
    # 把在场角色的随身道具（角色.json「随身道具」）注入首尾帧主语，保证道具对得上剧本
    unet, clip, ctype, vae, lora = Q
    props_map = {r["id"]: r.get("props", []) for r in load_roles()}
    for sb in load_storyboards():
        sid = sb.get("shot_id")
        # 兼容整数 shot_id(1) 与补零字符串("01")：统一用 zfill(2) 比较
        if shot_filter and str(sid).zfill(2) != shot_filter:
            continue
        # 空镜（character_ids 为空）：不用角色 LoRA、负面切换为场景排人词 NEG_SCENE_GRID，
        # 与场景素材一致，避免空镜被角色 LoRA 强塞人物/人脸。
        is_empty = not sb.get("character_ids")
        shot_lora = None if is_empty else lora
        shot_strength = 0.0 if is_empty else STRENGTH
        shot_neg = shot_negative(sb, is_empty)
        shot_title = "背景(无人物)" if is_empty else f"角色 LoRA ({STRENGTH})"
        # 保存到固定子目录（不再用「!」前缀：当前 ComfyUI 不识别该跳过序号语法，
        # 会把 ! 当作目录名并仍追加 _00001 序号）。首帧固定名带 _00001 序号，
        # 供视频工作流按镜头动态引入（build_video_refs.py 引用同一带序号固定名）。
        pfr = f"02_分镜/第1集/第1集_镜{sid}_"
        write(os.path.join(OUT, f"05_shotfirst_{IMG_W}x{IMG_H}_Qwen2512_{SFX}_{str(sid).zfill(2)}.json"),
              make_img(unet, clip, ctype, vae, shot_lora, shot_strength,
                       frame_shot(sb, "first", props_map), shot_neg,
                       IMG_W, IMG_H, 30, 4.0, 42, pfr + "首帧_" + SNAME,
                       "Qwen-2512 DiT", shot_title))
        # 尾帧改用 img2img：以本镜首帧图为底图(LoadImage 读 ComfyUI input 目录)，denoise<1 重绘，
        # 使尾帧继承首帧的场景/方向/人物，同一场景、同一道具、同一人物"不变两版"。
        # 生成顺序：先提交 05 首帧 → 把生成的图复制到 <ComfyUI>/input/02_分镜/第1集/ → 再提交 06 尾帧。
        init_first = "02_分镜/第1集/第1集_镜%s_首帧_%s_00001_.png" % (sid, SNAME)
        write(os.path.join(OUT, f"06_shotlast_{IMG_W}x{IMG_H}_Qwen2512_{SFX}_{str(sid).zfill(2)}.json"),
              make_img2img(unet, clip, ctype, vae, shot_lora, shot_strength,
                           frame_shot(sb, "last", props_map), shot_neg,
                           init_first, TAIL_DENOISE, 30, 4.0, 42, pfr + "尾帧_" + SNAME,
                           "Qwen-2512 DiT", shot_title))
        print(f"  [镜 {sid}]{sb.get('title', '')} -> 首帧 / 尾帧{'（空镜）' if is_empty else ''}")

    if not shot_filter:
        # ---- 视频工作流（H3 Director 模板 + 8步 turbo LoRA，横屏 1280x736）----
        # 默认只产出最终主力 09_FL2VA（同一 fl2v 模板：接首帧即 I2V，接首尾帧即 FL2VA）。
        # 探路 T2V(07) / 暂缓 Ref2VA(10) 默认不生成（避免 workflows/ 堆积探路/暂缓模板），
        # 仅在显式加 --with-t2v / --with-ref2va 时才产出，与《H3 固定方案》阶段演进一致。
        wf = load_example("minimax_h3_director_fl2v.json")
        wf = insert_lora(wf, "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", 1.0)
        wf = modify_director(wf, 8, VID_W, VID_H, PFX_VIDEO)
        write(os.path.join(OUT, f"09_video_FL2VA_{VID_W}x{VID_H}.json"), wf)
        print("  [视频模板] 09_video_FL2VA = 主力（I2V/FL2VA）")

        if "--with-t2v" in sys.argv:
            # 第一阶段 T2V 探路（默认不生成；仅探路时加 --with-t2v）
            wf = load_example("minimax_h3_director_t2v.json")
            wf = insert_lora(wf, "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors", 1.0)
            wf = modify_director(wf, 8, VID_W, VID_H, PFX_VIDEO)
            write(os.path.join(OUT, f"07_video_T2V_{VID_W}x{VID_H}.json"), wf)
            print("  [视频模板] 07_video_T2V = 探路（--with-t2v）")

        if "--with-ref2va" in sys.argv:
            # 第四阶段 Ref2VA（角色/场景参考，8 步无 4-step turbo，与外部项目 r2v 一致；默认不生成）
            wf = load_example("minimax_h3_director_r2v.json")
            wf = modify_director(wf, 8, VID_W, VID_H, PFX_VIDEO)
            write(os.path.join(OUT, f"10_video_Ref2VA_{VID_W}x{VID_H}.json"), wf)
            print("  [视频模板] 10_video_Ref2VA = 暂缓（--with-ref2va）")

    print("Wrote new landscape workflows to", OUT)


if __name__ == "__main__":
    if "--chars-only" in sys.argv:
        # 只重建角色素材（01_char3view_*），不动场景/分镜/视频模板
        # 注：人物只做三视图，不做人物全景图；全景/写实大图由场景三视图工作流承担
        build_char_assets(1216, 832, "写实CG融合", "Fusion", 0.8)
        print("Wrote character 3-view workflows to", OUT)
    elif "--scenes-only" in sys.argv:
        # 只重建场景三视图（03_scene3view_*），不动角色/分镜/视频模板
        # 注：场景三视图已覆盖场景全景，不再单独出全景图（04_scenefull_*）
        build_scene_assets(1216, 832)
        print("Wrote scene 3-view workflows to", OUT)
    else:
        main()
