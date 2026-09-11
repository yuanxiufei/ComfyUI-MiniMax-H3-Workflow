# -*- coding: utf-8 -*-
"""把场景九宫格（3x3 机位拼图）裁切成 9 张单机位参考图。

九宫格每格代表该场景的一个机位（见 build_new_workflows.SCENE_GRID_PANELS）：
  panel1 大远景定场 / 2 远景全景 / 3 广角地面 / 4 前景边缘中景 / 5 平视中景 /
  6 仰视 / 7 俯视鸟瞰 / 8 关键道具特写 / 9 暮色变体。

r2v 生视频时，参考图只应提供「锁定环境主体 / 单一机位构图」，
因此按镜头机位选用对应单格，而非把整张拼图喂给 H3。

每格按内缩比例（PANEL_INSET_RATIO）向内收缩后裁切，去掉九宫格细网格线，
避免低清单格（约 405x277）边缘蹭线污染视频参考图。

产物命名（与 build_r2v_refs.scene_ref_file 对齐，取 _00001_ 首张）：
  output/01_场景素材/{场景名}/{场景名}_panel{1-9}_00001_.png
同时复制到 input 供 LoadImage 读取。

用法:
  python scripts/crop_scene_panels.py
"""
import os
import shutil
import sys
from PIL import Image

import comfy_config  # noqa: F401  —— import 即把 stdout/stderr 统一为 UTF-8

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SB_DB = os.path.join(ROOT, "剧本", "02_分镜", "第1集_分镜.json")
SCENE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "场景.json")
# 默认 ComfyUI 根目录（output 与 input 均为其子目录）
COMFY = r"D:\Comfy-Desktop\ComfyUI-Shared"
SCENE_PREFIX = "01_场景素材"

# 九宫格用细网格线分隔九格；直接按 1/3 裁会把网格线蹭进单格边缘（低清单格约 405x277，
# 线更显眼），污染视频参考图。规划裁剪时每格向内收缩，把分隔线裁掉、保留格子主体构图。
PANEL_INSET_RATIO = 0.02   # 向内收缩比例（相对格子短边）
PANEL_INSET_MIN = 5        # 最小收缩像素
SINGLE_SUFFIX = "单场景"  # 「一张图一个场景」素材后缀



def load_json(path, key, default=None):
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key, default) if isinstance(data, dict) else data


def _col_diffs(im):
    g = im.convert("L").resize((181, 97))
    px = g.load()
    out = []
    for x in range(1, 180):
        s = 0
        for y in range(97):
            s += abs(px[x + 1, y] - px[x - 1, y])
        out.append(s / 97.0)
    return out


def has_center_split(im):
    """格内中缝自检（左右双拼的格子不可用）。"""
    d = _col_diffs(im)
    run = best = 0
    for v in d[78:102]:
        run = run + 1 if v > 25.0 else 0
        best = max(best, run)
    return best >= 3


def single_rel(name):
    return "%s/%s/%s_%s_00001_.png" % (SCENE_PREFIX, name, name, SINGLE_SUFFIX)


def _use_single(rel, name):
    src = os.path.join(COMFY, "output", rel)
    if not os.path.isfile(src):
        print("  [!] 无九宫格也无单场景图：%s" % name)
        return
    dst = os.path.join(COMFY, "input", rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print("场景 %s：使用单场景图" % name)


def main():
    scenes = load_json(SCENE_DB, "scenes", []) or []
    sid2name = {s.get("id"): s.get("name") for s in scenes if s.get("name")}
    modes = {s.get("id"): (s.get("ref_mode") or "") for s in scenes}
    # 收集分镜中实际用到的场景
    storyboards = load_json(SB_DB, "storyboards", []) or []
    used = {}
    for sb in storyboards:
        sid = sb.get("scene_id", "")
        name = sid2name.get(sid)
        if name:
            used.setdefault(sid, name)

    if not used:
        print("分镜中没有可用的场景引用")
        return

    for sid, name in used.items():
        if modes.get(sid) == "single":
            _use_single(single_rel(name), name)
            continue
        src_grid = os.path.join(COMFY, "output", SCENE_PREFIX, name,
                                "%s_九宫格_00001_.png" % name)
        if not os.path.isfile(src_grid):
            _use_single(single_rel(name), name)
            continue
        im = Image.open(src_grid)
        w, h = im.size
        cw, ch = w / 3.0, h / 3.0
        inset = max(PANEL_INSET_MIN, int(round(min(cw, ch) * PANEL_INSET_RATIO)))
        made, bad = [], []
        for idx in range(9):
            row, col = divmod(idx, 3)
            x0 = int(col * cw)
            y0 = int(row * ch)
            box = (x0 + inset, y0 + inset,
                   int((col + 1) * cw) - inset, int((row + 1) * ch) - inset)
            crop = im.crop(box)
            if has_center_split(crop):
                bad.append("panel%d" % (idx + 1))
            rel = os.path.join(SCENE_PREFIX, name, "%s_panel%d_00001_.png" % (name, idx + 1))
            src = os.path.join(COMFY, "output", rel)
            crop.save(src)
            made.append("panel%d" % (idx + 1))
            # 复制到 input（LoadImage 读 input）
            dst = os.path.join(COMFY, "input", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        print("场景 %s：已裁切 %s" % (name, ", ".join(made)))
        if bad:
            print("  [!] %s 疑似双拼格：%s（建议改用单场景图）" % (name, ", ".join(bad)))


if __name__ == "__main__":
    main()
