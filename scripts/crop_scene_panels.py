# -*- coding: utf-8 -*-
"""把场景九宫格（3x3 机位拼图）裁切成 9 张单机位参考图。

九宫格每格代表该场景的一个机位（见 build_new_workflows.SCENE_GRID_PANELS）：
  panel1 大远景定场 / 2 远景全景 / 3 广角地面 / 4 前景边缘中景 / 5 平视中景 /
  6 仰视 / 7 俯视鸟瞰 / 8 关键道具特写 / 9 暮色变体。

r2v 生视频时，参考图只应提供「锁定环境主体 / 单一机位构图」，
因此按镜头机位选用对应单格，而非把整张拼图喂给 H3。

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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
SB_DB = os.path.join(ROOT, "剧本", "02_分镜", "第1集_分镜.json")
SCENE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "场景.json")
# 默认 ComfyUI 根目录（output 与 input 均为其子目录）
COMFY = r"D:\Comfy-Desktop\ComfyUI-Shared"
SCENE_PREFIX = "01_场景素材"


def load_json(path, key, default=None):
    import json
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key, default) if isinstance(data, dict) else data


def main():
    scenes = load_json(SCENE_DB, "scenes", []) or []
    sid2name = {s.get("id"): s.get("name") for s in scenes if s.get("name")}
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
        src_grid = os.path.join(COMFY, "output", SCENE_PREFIX, name,
                                "%s_九宫格_00001_.png" % name)
        if not os.path.isfile(src_grid):
            print("  [!] 缺少九宫格：%s" % src_grid)
            continue
        im = Image.open(src_grid)
        w, h = im.size
        cw, ch = w / 3.0, h / 3.0
        made = []
        for idx in range(9):
            row, col = divmod(idx, 3)
            box = (int(col * cw), int(row * ch), int((col + 1) * cw), int((row + 1) * ch))
            crop = im.crop(box)
            rel = os.path.join(SCENE_PREFIX, name, "%s_panel%d_00001_.png" % (name, idx + 1))
            src = os.path.join(COMFY, "output", rel)
            crop.save(src)
            made.append("panel%d" % (idx + 1))
            # 复制到 input（LoadImage 读 input）
            dst = os.path.join(COMFY, "input", rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        print("场景 %s：已裁切 %s" % (name, ", ".join(made)))


if __name__ == "__main__":
    main()
