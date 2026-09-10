# -*- coding: utf-8 -*-
"""评估每个场景该用「九宫格单机位」还是「单张场景图」，并把结论写回场景.json。

判据（自上而下，命中任一即建议 single）：
  1. 本场景镜头【实际需要的机位格】中存在不可用格（左右双拼，或该格缺失）→ 该镜无格可用；
  2. 不可用格（坏格 + 缺格）>= 3/9 → 九宫格整体质量不稳，改单张；
  3. 需要的不同机位格 <= 2 且镜头数 >= 3 → 机位高度重复，九宫格用不满，收益低于风险；
  4. 其余情况保留九宫格（不同镜头能取到不同机位参考）。

格质量直接检测 output 下已裁好的 {场景名}_panel{1-9}_00001_.png（即 LoadImage 实际读取的文件），
比重新裁九宫格更准；某格缺失但九宫格源图还在时，就地在内存里裁一格检测。
坏格判定沿用 crop_scene_panels.has_center_split（启发式），命中会打印具体格号供人工复核。

用法:
  python scripts/suggest_scene_ref_mode.py                    # 只评估、打印建议
  python scripts/suggest_scene_ref_mode.py --apply            # 写回 剧本/03_角色场景/场景.json
  python scripts/suggest_scene_ref_mode.py --comfy-input D:\\Comfy-Desktop\\ComfyUI-Shared
"""
import argparse
import json
import os
import sys

from PIL import Image

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import build_r2v_refs as BR          # panel_for_shot（景别/角度/运镜 → 机位格）
import crop_scene_panels as CP       # PANEL_INSET_*、has_center_split（中缝自检）

SB_DB = os.path.join(ROOT, "剧本", "02_分镜", "第1集_分镜.json")
SCENE_DB = os.path.join(ROOT, "剧本", "03_角色场景", "场景.json")
COMFY = r"D:\Comfy-Desktop\ComfyUI-Shared"

GRID_SUFFIX = "九宫格"
BAD_LIMIT = 3              # 坏格数达到该值即放弃九宫格
PANEL_KEEP_MIN = 3         # 需要的不同机位格少于此值且镜头够多 → 改单张
SHOT_KEEP_MIN = 3


def load_json(path, key, default=None):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key, default) if isinstance(data, dict) else data


def asset_dir(name):
    return os.path.join(COMFY, "output", CP.SCENE_PREFIX, name)


def grid_file(name):
    return os.path.join(asset_dir(name), "%s_%s_00001_.png" % (name, GRID_SUFFIX))


def panel_file(name, idx):
    return os.path.join(asset_dir(name), "%s_panel%d_00001_.png" % (name, idx))


def single_file(name):
    return os.path.join(COMFY, "output", *CP.single_rel(name).split("/"))


def panel_status(name):
    """返回 (坏格集合, 缺格集合)。坏格=格内左右双拼；缺格=单格与九宫格源图都没有。"""
    bad, missing = set(), set()
    grid = grid_file(name)
    im = None
    for idx in range(1, 10):
        path = panel_file(name, idx)
        if os.path.isfile(path):
            crop = Image.open(path)
        elif os.path.isfile(grid):
            if im is None:
                im = Image.open(grid)
                w, h = im.size
                cw, ch = w / 3.0, h / 3.0
                inset = max(CP.PANEL_INSET_MIN,
                            int(round(min(cw, ch) * CP.PANEL_INSET_RATIO)))
            row, col = divmod(idx - 1, 3)
            crop = im.crop((int(col * cw) + inset, int(row * ch) + inset,
                            int((col + 1) * cw) - inset, int((row + 1) * ch) - inset))
        else:
            missing.add(idx)
            continue
        if CP.has_center_split(crop):
            bad.add(idx)
    return bad, missing


def evaluate(name, shots):
    panels = [BR.panel_for_shot(sb) for sb in shots]
    need = sorted(set(panels))
    bad, missing = panel_status(name)
    unusable = bad | missing

    reasons = []
    hit = [p for p in need if p in unusable]
    if hit:
        reasons.append("所需机位不可用：%s" % "、".join("panel%d" % p for p in hit))
    if len(unusable) >= BAD_LIMIT:
        reasons.append("不可用格 %d/9 偏多" % len(unusable))
    if len(need) < PANEL_KEEP_MIN and len(shots) >= SHOT_KEEP_MIN:
        reasons.append("机位高度重复（%d 种 / %d 镜）" % (len(need), len(shots)))
    if reasons:
        return {"mode": "single", "need": need, "bad": bad, "missing": missing,
                "reasons": reasons}
    return {"mode": "grid", "need": need, "bad": bad, "missing": missing,
            "reasons": ["可覆盖 %d 种机位" % len(need)]}


def main():
    global COMFY

    ap = argparse.ArgumentParser()
    ap.add_argument("--comfy-input", default=COMFY, help="ComfyUI 根目录（output/input 的父目录）")
    ap.add_argument("--apply", action="store_true", help="把建议写入 场景.json")
    args = ap.parse_args()
    COMFY = args.comfy_input

    with open(SCENE_DB, encoding="utf-8") as f:
        db = json.load(f)
    scenes = db.get("scenes", []) or []
    sid2scene = {s.get("id", ""): s for s in scenes}

    storyboards = load_json(SB_DB, "storyboards", []) or []
    by_scene = {}
    unknown = set()
    for sb in storyboards:
        sid = sb.get("scene_id", "")
        if not sid:
            continue
        if sid not in sid2scene:
            unknown.add(sid)
            continue
        by_scene.setdefault(sid, []).append(sb)

    if unknown:
        print("[!] 分镜引用了场景库中不存在的场景 id：%s" % "、".join(sorted(unknown)))
    if not by_scene:
        print("分镜中没有可评估的场景")
        return

    print("%-7s %-16s %4s %-14s %-12s %-12s %-6s %-6s %s" %
          ("场景", "名称", "镜数", "需要机位", "坏格", "缺格", "现状", "建议", "理由"))
    changes = []
    for sid in sorted(by_scene):
        scene = sid2scene[sid]
        name = scene.get("name", sid)
        shots = by_scene[sid]
        cur = scene.get("ref_mode") or ""
        res = evaluate(name, shots)
        advice = res["mode"]
        print("%-7s %-16s %4d %-14s %-12s %-12s %-6s %s%-6s %s" % (
            sid, name, len(shots),
            ",".join(str(p) for p in res["need"]) or "-",
            ",".join(str(p) for p in sorted(res["bad"])) or "-",
            ",".join(str(p) for p in sorted(res["missing"])) or "-",
            cur or "(默认格)", "⚠" if cur != advice else " ",
            advice, "；".join(res["reasons"])))
        if advice == "single" and not os.path.isfile(single_file(name)):
            print("        [!] 缺单场景图：需先跑 workflows/03b_scenefull_*.json 生成 "
                  "%s_单场景_00001_.png" % name)
        if res["missing"] and os.path.isfile(grid_file(name)):
            print("        [!] 有单格缺失但九宫格源图还在，可重跑 scripts/crop_scene_panels.py 补齐")
        if cur != advice:
            changes.append((sid, name, cur, advice))

    print()
    if not changes:
        print("全部场景的 ref_mode 与建议一致，无需改动。")
        return
    print("待写入 %d 个场景：" % len(changes))
    for sid, name, cur, advice in changes:
        print("  %s %s：%s → %s" % (sid, name, cur or "(默认格)", advice))
    if not args.apply:
        print("（仅预览，加 --apply 才会写回 %s）" % os.path.relpath(SCENE_DB, ROOT))
        return

    for sid, _, _, advice in changes:
        if advice == "single":
            sid2scene[sid]["ref_mode"] = "single"
        else:
            sid2scene[sid].pop("ref_mode", None)
    with open(SCENE_DB, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("已写回 %s" % os.path.relpath(SCENE_DB, ROOT))


if __name__ == "__main__":
    main()
