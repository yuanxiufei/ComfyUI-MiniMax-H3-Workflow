#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""角色渐进多次审核（QC）引擎 —— 确定性门禁（零模型 / 零算力）。

定位：在「角色提取(extractor) 之后」「角色三视图(build_new_workflows) 生成之后」运行，
按轮次渐进审核，防止：
  1) 三视图没有正常生成（漏生成 / 布局错 / 表情板缺格 / 下装缺失露腿 / 道具板带人手持）；
  2) 角色形象不符时代 / 剧本 / 小说（era 写错、古代画成现代装，或反过来）。

轮次（渐进 gating，逐轮递进，全部通过才放行）：
  R1 基础契约      -> id/name/gender/role_type/age 必填 + speaker_id/ 卡通 id 唯一
  R2 时代合规      -> era ∈ {ancient,modern}，且 image_prompt 着装词与时代一致（防"不符时代"）
  R3 剧本/小说一致 -> 分镜引用的角色都已提取、实体角色能出图、无手持道具穿帮、无泛模板
  R4 三视图硬约束  -> 每个实体角色都有三视图工作流；工作流正向提示词含全部硬约束段
                      （布局/表情板8格/无墙线/同脸/身形一致/下装/道具板仅道具）
  R5 资产分级      -> asset_level ∈ {A,B,C}

严重级别：
  P0 致命（缺硬约束段 / 漏生成 / era 非法 / 无下装）→ 会直接导致三视图异常或穿帮，必须修复；
  P1 缺陷（措辞/一致性/时代冲突）→ 需人工复核，默认提示（--strict 才阻断）；
  P2 建议（分级不规范 / 亲缘未标注等）。

用法：
  python scripts/qc_characters.py                       # 跑全轮次，P0 阻断（退出码 1）
  python scripts/qc_characters.py --strict              # P1 也阻断
  python scripts/qc_characters.py --warn                # P0/P1 仅打印，不置非零退出码
  python scripts/qc_characters.py --storyboard <path>   # 指定分镜路径（默认自动定位第1集）
  python scripts/qc_characters.py --skip-3view          # 提取后角色卡审核：跳过三视图 R4（此时尚未生成，避免误报）
"""

import argparse
import glob
import json
import os
import re
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

ROLE_JSON = os.path.join(ROOT, "剧本", "03_角色场景", "角色.json")
STATB_DIR = os.path.join(ROOT, "剧本", "02_分镜")
CHAR_WS_DIR = os.path.join(ROOT, "workflows")
IMAGE_W, IMAGE_H, SFX = "1216", "832", "Fusion"

# ---------------------------------------------------------------- 硬约束标记
# 与 build_new_workflows.char_3view_fusion / grid_prompt_generator:character-prompt.md 对齐
MARK_LAYOUT = ("character concept sheet", "turnaround reference sheet")
MARK_EMOTION = ("panel 8", "all eight faces", "eight close-up face-only portraits")
MARK_EMOTION_STYLE = ("unified 3D animated film style in every expression panel",)
MARK_GRIDLINE = ("no dividing lines", "no grid lines", "no borders", "no panel outlines")
MARK_CONSISTENCY = ("same face, same costume, same character", "same hairstyle", "identical features")
MARK_BUILD = ("same height and build in all three views", "realistic head-to-body ratio")
MARK_BOTTOM = ("full-length trousers", "no bare legs", "no bare feet", "wearing shoes",
               "wearing boots", "footwear", "trousers",
               "长裤", "裤装", "裤子", "锦靴", "皮鞋", "布靴", "靴子", "靴", "鞋",
               "足踏", "脚踩")
MARK_PROP_BOARD = ("prop-only showcase", "no person holding", "no character, no arm",
                   "detached from", "not held by")
MARK_EMOTION_FULL = ("two columns of four", "occupy all")

# 时代强词（服装 / 造型）。用于"不符时代"检测：命中对立的强词即冲突。
ANCIENT_STRONG = (
    "广袖", "长袍", "长衫", "汉服", "衣袂", "云纹锦靴", "银冠", "青玉簪", "交领",
    "仙侠", "古装", "ancient costume", "traditional ancient", "xianxia",
)
MODERN_STRONG = (
    "现代", "西装", "职业套裙", "职业装", "衬衫", "小皮靴", "司机制服", "耳麦",
    "现代长裤", "modern suit", "modern outfit", "contemporary", "现代职业装",
)

# 道具应入道具板，角色卡（image_prompt / appearance）不应出现"人物手持道具"。
HANDHELD_WORDS = (
    "手持", "提着", "握着", "拎着", "端着", "拿着", "手拿", "扛着",
    "wielding", "gripping", "holding a", "holding the",
)
# 泛指模板（防跨角色套用）。
GENERIC_WORDS = (
    "high school student", "generic", "placeholder", "passerby",
    "standard anime character template", "default character",
)

VALID_GENDER = ("男", "女")
VALID_ROLE_TYPE = ("主角", "配角", "龙套", "旁白")
VALID_ERA = ("ancient", "modern")
VALID_LEVEL = ("A", "B", "C")


# ---------------------------------------------------------------- 基础工具
def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _radix_minus(cid):
    """按 build 命名规则得到该角色三视图工作流文件名（c01 用默认名，无 _c01 后缀）。"""
    rid = "" if cid == "c01" else f"_{cid}"
    return f"01_char3view_{IMAGE_W}x{IMAGE_H}_Qwen2512{rid}_{SFX}.json"


def _collect_char_ids(obj, acc):
    """递归收集对象里所有 character_id 字符串值。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("character_id", "ch_id", "role_id") and isinstance(v, str):
                acc.add(v)
            else:
                _collect_char_ids(v, acc)
    elif isinstance(obj, list):
        for item in obj:
            _collect_char_ids(item, acc)


def _existing_3view_map():
    """glob 所有 01_char3view_*.json → {角色id: 文件路径}。c01 用默认名。"""
    m = {}
    for path in glob.glob(os.path.join(CHAR_WS_DIR, "01_char3view_*.json")):
        base = os.path.basename(path)
        m2 = re.search(r"_c(\d{2})_", base)
        cid = f"c{m2.group(1)}" if m2 else "c01"
        m[cid] = path
    return m


def _3view_positive_prompt(path):
    """从工作流 JSON 里取「正向提示词」CLIPTextEncode 节点的文本。"""
    try:
        wf = _load_json(path)
    except Exception:
        return None
    for n in wf.get("nodes", []):
        if n.get("type") == "CLIPTextEncode":
            title = n.get("title") or ""
            if "正向" in title:
                vals = n.get("widgets_values") or []
                if vals and isinstance(vals[0], str):
                    return vals[0]
    return None


def _any_in(mark_list, text_lower):
    return any(m.lower() in text_lower for m in mark_list)


# ---------------------------------------------------------------- R1 基础契约
def validate_contract(role, findings):
    cid = role.get("id") or "?"
    for key in ("name", "gender", "role_type", "age"):
        if not role.get(key):
            findings.append(dict(level="P1", code="CONTRACT-MISS", item=cid,
                                 msg=f"基础字段 {key!r} 缺失"))
    gender = role.get("gender")
    if gender and gender not in VALID_GENDER:
        findings.append(dict(level="P1", code="CONTRACT-GENDER", item=cid,
                             msg=f"gender={gender!r} 非法，应为 {VALID_GENDER}"))
    rtype = role.get("role_type")
    if rtype and rtype not in VALID_ROLE_TYPE:
        findings.append(dict(level="P1", code="CONTRACT-ROLE-TYPE", item=cid,
                             msg=f"role_type={rtype!r} 非法，应为 {VALID_ROLE_TYPE}"))
    if not role.get("image_prompt"):
        findings.append(dict(level="P0", code="CONTRACT-IMAGE-PROMPT", item=cid,
                             msg="缺 image_prompt，无法出三视图/分镜首帧"))


# ---------------------------------------------------------------- R2 时代合规
def validate_era(role, findings):
    cid = role.get("id") or "?"
    era = (role.get("era") or "").strip()
    if era not in VALID_ERA:
        findings.append(dict(level="P0", code="ERA-UNKNOWN", item=cid,
                             msg=f"era={era!r} 非法，应为 ancient/modern（缺失将默认古代），显式写明避免画错时代"))
        return
    text = ("%s %s" % (role.get("image_prompt") or "", role.get("appearance") or "")).lower()
    if era == "ancient":
        if not _any_in(ANCIENT_STRONG, text):
            findings.append(dict(level="P1", code="ERA-ANCIENT-MARK", item=cid,
                                 msg="古代角色缺朝代着装强词（广袖长袍/长衫/汉服/交领等），可能画成现代装"))
        contra = [w for w in MODERN_STRONG if w.lower() in text]
        if contra:
            findings.append(dict(level="P1", code="ERA-CONTRADICT-ANCIENT", item=cid,
                                 msg=f"古代角色混入现代着装/造型强词 {contra}，可能不符时代"))
    else:  # modern
        if not _any_in(MODERN_STRONG, text):
            findings.append(dict(level="P1", code="ERA-MODERN-MARK", item=cid,
                                 msg="现代角色缺现代着装强词（现代/西装/职业装等），可能画成古装"))
        contra = [w for w in ANCIENT_STRONG if w.lower() in text]
        if contra:
            findings.append(dict(level="P1", code="ERA-CONTRADICT-MODERN", item=cid,
                                 msg=f"现代角色混入古装/朝代服装强词 {contra}，可能不符时代"))


# ---------------------------------------------------------------- R3 剧本/小说一致
def validate_look(role, findings):
    """角色卡 image_prompt 层面的下装 / 手持 / 约束段检查（防三视图露腿、道具穿帮、跨角色套用）。"""
    cid = role.get("id") or "?"
    text = role.get("image_prompt") or ""
    tl = text.lower()
    if text and not text.startswith("stylized 3D Chinese anime character"):
        findings.append(dict(level="P1", code="LOOK-CONSTRAINT", item=cid,
                             msg="image_prompt 未前置统一约束段（stylized 3D Chinese anime character …），三视图/首帧风格可能不一致"))
    # 旁白不出图；空 image_prompt 不下装/道具卡检查
    if role.get("role_type") == "旁白" or not text:
        return
    # 下装必写（下装/鞋 缺一不可，否则三视图易露腿缺裤）
    if text and not _any_in(MARK_BOTTOM, tl):
        findings.append(dict(level="P0", code="LOOK-BOTTOM", item=cid,
                             msg="image_prompt 缺下装/鞋段（长裤/裤/靴/鞋/boots），三视图极易露腿、缺裤"))
    handheld = [w for w in HANDHELD_WORDS if w.lower() in tl]
    if handheld:
        findings.append(dict(level="P1", code="LOOK-HANDHELD", item=cid,
                             msg=f"角色卡出现手持道具词 {handheld}，道具应入道具板且禁止人物手持"))
    gen = [w for w in GENERIC_WORDS if w.lower() in tl]
    if gen:
        findings.append(dict(level="P1", code="LOOK-GENERIC", item=cid,
                             msg=f"疑似套用泛指模板 {gen}，需按剧本设定重写"))


def validate_storyboard_consistency(roles, storyboard_path, findings):
    """分镜引用的角色都应已提取，且旁白之外的实体角色能出图。"""
    if not storyboard_path or not os.path.exists(storyboard_path):
        return
    role_by_id = {r.get("id"): r for r in roles}
    try:
        sb = _load_json(storyboard_path)
    except Exception:
        return
    used = set()
    _collect_char_ids(sb, used)
    for cid in sorted(used):
        role = role_by_id.get(cid)
        if role is None:
            findings.append(dict(level="P0", code="SB-CHAR-UNEXTRACTED", item=cid,
                                 msg=f"分镜引用了角色 {cid}，但角色库未提取到"))
            continue
        if not role.get("image_prompt") and role.get("role_type") != "旁白":
            findings.append(dict(level="P1", code="SB-CHAR-NO-IMAGE", item=cid,
                                 msg="分镜引用但在角色库缺 image_prompt，无法出图"))


# ---------------------------------------------------------------- R4 三视图硬约束
def validate_3view_prompt(prompt, role, findings):
    """单个角色的三视图正向提示词硬约束自检（可被 build_new_workflows 复用）。"""
    cid = role.get("id") or "?"
    if not prompt or not isinstance(prompt, str):
        findings.append(dict(level="P0", code="3VIEW-PROMPT-EMPTY", item=cid,
                             msg="三视图工作流找不到正向提示词"))
        return findings
    s = prompt.lower()
    if not _any_in(MARK_LAYOUT, s):
        findings.append(dict(level="P0", code="3VIEW-LAYOUT", item=cid,
                             msg="缺三视图宫格布局标记（character concept sheet / turnaround reference sheet）"))
    if not _any_in(MARK_EMOTION, s):
        findings.append(dict(level="P0", code="3VIEW-EMOTION", item=cid,
                             msg="缺表情板 8 格标记（panel 8 / all eight faces）"))
    if not _any_in(MARK_EMOTION_STYLE, s):
        findings.append(dict(level="P1", code="3VIEW-EMOTION-STYLE", item=cid,
                             msg="缺表情板风格统一标记（unified 3D animated film style in every expression panel）"))
    if not _any_in(MARK_GRIDLINE, s):
        findings.append(dict(level="P0", code="3VIEW-GRIDLINE", item=cid,
                             msg="缺无分割线/网格线/边框标记（no dividing lines / no grid lines）"))
    if not _any_in(MARK_CONSISTENCY, s):
        findings.append(dict(level="P0", code="3VIEW-CONSISTENCY", item=cid,
                             msg="缺同一张脸/同一服装一致标记（same face, same costume, same character）"))
    if not _any_in(MARK_BUILD, s):
        findings.append(dict(level="P1", code="3VIEW-BUILD", item=cid,
                             msg="缺三视图身形一致标记（same height and build in all three views）"))
    if not _any_in(MARK_BOTTOM, s):
        findings.append(dict(level="P0", code="3VIEW-BOTTOM", item=cid,
                             msg="缺下装/鞋段（full-length trousers / no bare legs / shoes），三视图易露腿缺裤"))
    props = role.get("随身道具") or role.get("props") or []
    if props:
        if not _any_in(MARK_PROP_BOARD, s):
            findings.append(dict(level="P0", code="3VIEW-PROP-BOARD", item=cid,
                                 msg=f"有随身道具 {props}，但三视图缺'道具只展示、无人物手持'标记（prop-only / no person holding）"))
    else:
        if _any_in(MARK_PROP_BOARD, s):
            findings.append(dict(level="P1", code="3VIEW-PROP-MISMATCH", item=cid,
                                 msg="角色无随身道具，但三视图仍带道具板标记，应只靠表情占满右列"))
        if not _any_in(MARK_EMOTION_FULL, s):
            findings.append(dict(level="P1", code="3VIEW-EMOTION-FULL", item=cid,
                                 msg="无道具角色，表情板应'两列四格占满右列'，缺该标记"))
    return findings


def validate_3view_coverage_and_prompts(roles, findings):
    """R4 汇总：每个实体角色都有三视图工作流 + 逐个工作流做硬约束自检。"""
    existing = _existing_3view_map()
    role_by_id = {r.get("id"): r for r in roles}
    for role in roles:
        cid = role.get("id")
        if role.get("role_type") == "旁白":
            continue
        if not role.get("image_prompt"):
            continue
        if cid not in existing:
            findings.append(dict(level="P0", code="3VIEW-MISSING", item=cid,
                                 msg=f"角色无对应三视图工作流 {_radix_minus(cid)}（未正常生成），应先跑 build_new_workflows"))
            continue
        prompt = _3view_positive_prompt(existing[cid])
        validate_3view_prompt(prompt, role, findings)


# ---------------------------------------------------------------- R5 资产分级
def validate_asset_level(role, findings):
    cid = role.get("id") or "?"
    level = role.get("asset_level")
    if level and level not in VALID_LEVEL:
        findings.append(dict(level="P2", code="LEVEL-INVALID", item=cid,
                             msg=f"asset_level={level!r} 非法，应为 {VALID_LEVEL}"))
    if not level:
        findings.append(dict(level="P2", code="LEVEL-MISSING", item=cid,
                             msg="未标注 asset_level（A/B/C），建议标注以确定复用优先级"))


# ---------------------------------------------------------------- 统一入口
def find_storyboard(episode=None):
    if not os.path.isdir(STATB_DIR):
        return None
    files = sorted(glob.glob(os.path.join(STATB_DIR, "*分镜.json")))
    if not files:
        return None
    if episode is None:
        return files[0]
    for f in files:
        if episode in os.path.basename(f):
            return f
    return files[0]


def check_characters(episode=None, storyboard=None, skip_3view=False):
    roles = (_load_json(ROLE_JSON) or {}).get("characters", [])
    findings = []

    # 唯一性
    ids = [r.get("id") for r in roles]
    seen = {}
    for cid in ids:
        seen[cid] = seen.get(cid, 0) + 1
    for cid, cnt in seen.items():
        if cnt > 1:
            findings.append(dict(level="P0", code="DUP-ID", item=cid, msg=f"角色 id 重复 {cnt} 次"))

    for role in roles:
        validate_contract(role, findings)
        validate_era(role, findings)
        validate_look(role, findings)
        validate_asset_level(role, findings)

    # 剧本/小说一致性（分镜引用）
    sb_path = storyboard or find_storyboard(episode)
    validate_storyboard_consistency(roles, sb_path, findings)

    # 三视图硬约束（覆盖 + 提示词自检）。提取后尚未生成三视图时用 --skip-3view 跳过
    if not skip_3view:
        validate_3view_coverage_and_prompts(roles, findings)
    return roles, findings


def _print_report(roles, findings):
    print("=" * 78)
    print("角色渐进多次审核  QC")
    print("角色库: %s" % ROLE_JSON)
    print("实体角色数: %d    发现: P0=%d  P1=%d  P2=%d"
          % (len(roles),
             sum(1 for f in findings if f["level"] == "P0"),
             sum(1 for f in findings if f["level"] == "P1"),
             sum(1 for f in findings if f["level"] == "P2")))
    print("=" * 78)
    if not findings:
        print("√ 全部通过")
        return 0
    order = {"P0": 0, "P1": 1, "P2": 2}
    findings_sorted = sorted(findings, key=lambda f: (order[f["level"]], f["item"]))
    for f in findings_sorted:
        print("[%s] %-24s %s" % (f["level"], f["item"], f["code"]))
        print("       %s" % f["msg"])
    n_p0 = sum(1 for f in findings if f["level"] == "P0")
    n_p1 = sum(1 for f in findings if f["level"] == "P1")
    return (n_p0 > 0 or n_p1 > 0)


def main():
    ap = argparse.ArgumentParser(description="角色渐进多次审核（三视图硬约束 + 时代/剧本一致性）")
    ap.add_argument("--episode", default=None, help="分镜集数编号（默认自动取第1集分镜）")
    ap.add_argument("--storyboard", default=None, help="指定分镜 JSON 路径")
    ap.add_argument("--strict", action="store_true", help="P1 也视为失败（阻断）")
    ap.add_argument("--warn", action="store_true", help="只打印，不置非零退出码")
    ap.add_argument("--skip-3view", action="store_true", help="跳过三视图硬约束检查(R4)——角色提取后尚未生成三视图时用")
    args = ap.parse_args()

    roles, findings = check_characters(episode=args.episode, storyboard=args.storyboard, skip_3view=args.skip_3view)
    has_fail = _print_report(roles, findings)

    n_p0 = sum(1 for f in findings if f["level"] == "P0")
    n_p1 = sum(1 for f in findings if f["level"] == "P1")
    if args.warn:
        return 0
    # 默认：P0 阻断；--strict 时 P1 也阻断
    block = n_p0 > 0 or (args.strict and n_p1 > 0)
    return 1 if block else 0


if __name__ == "__main__":
    sys.exit(main())
