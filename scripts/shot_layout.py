# -*- coding: utf-8 -*-
"""整集产物「按镜归位」：把平铺的批量成片整理成 镜NN/ 子目录约定。

为什么需要：
  r2v 整集工作流（Director 批量生成）一次提交产出 N 段视频，submit_workflow.py
  --collect-dir 会把产物平铺到 output/视频/<集>/<mode>/ 下 + 一份 collect_manifest.json；
  而 episode_status.py（收口清单）、assemble_episode.py（整集拼接/字幕/电平）、
  pipeline_video.py --chain（断点续跑找上一镜尾帧）都按 `镜NN/` 子目录约定找成片，
  平铺产物会被整体判成「缺镜」，整集拼接直接空跑。

归位规则（唯一事实来源）：
  - 段序 = collect_manifest.json 中 kind=='video' 条目的出现顺序
    = Director 批量节点保存顺序 = build 时镜号升序。
    注意不能拿文件名里的 _000NN_ 当镜号：那是 ComfyUI 全局计数器，跨多次提交连续递增
    （单镜跑过 00001-00014 后，整集 12 段会从 00015 起），与镜号无关。
  - 每镜目录 `镜NN/` 内保留原文件名（便于溯源），并写一份该镜的 collect_manifest.json，
    内容为该段条目 + shot_id/segment_index，供下游按同一约定读取。
  - 段数与镜数不一致时不做任何移动并报错：宁可人工确认，也不要错位拼接。

用法：
  python scripts/shot_layout.py --episode 第1集 --mode r2v --dryrun   # 只看归位计划
  python scripts/shot_layout.py --episode 第1集 --mode r2v            # 执行归位（移动）
  python scripts/shot_layout.py --episode 第1集 --mode r2v --copy     # 保留平铺副本
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402

MANIFEST = "collect_manifest.json"
_SHOT_RE = re.compile(r"^镜\d{1,2}$")


def shot_dir_name(sid):
    return "镜%s" % str(sid).zfill(2)


def shot_ids(storyboards):
    """分镜列表 → 归一化镜号序列（段序即此顺序）。"""
    out = []
    for sb in storyboards or []:
        sid = sb.get("shot_id")
        if sid not in (None, ""):
            out.append(str(sid).zfill(2))
    return out


def episode_shot_ids(episode):
    return shot_ids(dt.load_storyboards(episode))


def read_manifest(dirpath):
    """读目录下 collect_manifest.json；不存在/损坏返回 None。"""
    p = os.path.join(dirpath, MANIFEST)
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else None
    except Exception:  # noqa: BLE001
        return None


def write_manifest(dirpath, items):
    os.makedirs(dirpath, exist_ok=True)
    with open(os.path.join(dirpath, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _in_shot_dir(base, path):
    """path 是否已位于 base 下的 镜NN/ 子目录里（= 已归位）。"""
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except Exception:  # noqa: BLE001
        return False
    parts = rel.split(os.sep)
    return len(parts) >= 2 and _SHOT_RE.match(parts[0]) is not None


def video_entries(manifest, base=None, flat_only=False):
    """按出现顺序取 kind=='video' 且文件仍在的条目（即平铺段序）。

    flat_only=True 时排除已归位到 镜NN/ 的条目——归位后顶层清单仍会记录新路径，
    不过滤的话二次调用会把「已归位」当成「平铺产物」重新分配。
    """
    out = []
    for it in manifest or []:
        if not isinstance(it, dict) or it.get("kind") != "video":
            continue
        saved = it.get("saved")
        if not saved or not os.path.isfile(saved):
            continue
        if flat_only and base and _in_shot_dir(base, saved):
            continue
        out.append(it)
    return out


def plan(base, sids):
    """归位计划：返回 (assign, reason)。

    assign: [(sid, entry, dest_path)]，段序 zip 镜号序；
    reason: 不可归位的原因（assign 为空时给出，便于调用方原样提示）。
    """
    if not os.path.isdir(base):
        return [], "目录不存在：%s" % base
    vids = video_entries(read_manifest(base), base=base, flat_only=True)
    if not vids:
        return [], "平铺产物清单为空（%s/%s）" % (base, MANIFEST)
    if not sids:
        return [], "分镜为空"
    if len(vids) != len(sids):
        return [], ("段数与镜数不一致：产物 %d 段 vs 分镜 %d 镜，跳过归位以免错位"
                    % (len(vids), len(sids)))
    assign = []
    for i, (sid, e) in enumerate(zip(sids, vids)):
        dest = os.path.join(base, shot_dir_name(sid), os.path.basename(e["saved"]))
        assign.append((sid, e, dest, i))
    return assign, ""


def distribute(base, sids, dryrun=False, copy=False, quiet=False):
    """执行归位：平铺 mp4 → base/镜NN/，并改写镜内 + 顶层清单。返回归位镜数。"""
    assign, reason = plan(base, sids)
    if not assign:
        if not quiet:
            print("  [归位] 跳过：%s" % reason)
        return 0
    moved = {}
    n = 0
    for sid, e, dest, seg in assign:
        d = os.path.dirname(dest)
        if os.path.isfile(dest):
            moved[os.path.abspath(e["saved"])] = dest
            n += 1
            continue
        if dryrun:
            print("  [归位][dryrun] 镜%s ← %s" % (sid, os.path.basename(e["saved"])))
            n += 1
            continue
        os.makedirs(d, exist_ok=True)
        if copy:
            shutil.copy2(e["saved"], dest)
        else:
            shutil.move(e["saved"], dest)
            moved[os.path.abspath(e["saved"])] = dest
        entry = dict(e)
        entry["saved"] = dest
        entry["shot_id"] = sid
        entry["segment_index"] = seg
        write_manifest(d, [entry])
        n += 1
        print("  [归位] 镜%s ← %s" % (sid, os.path.basename(dest)))
    if moved and not copy and not dryrun:
        _rewrite_top_manifest(base, moved)
    return n


def _rewrite_top_manifest(base, moved):
    """把顶层清单里被移动的产物路径改写为新位置（保持清单与现实一致）。"""
    items = read_manifest(base)
    if items is None:
        return
    for it in items:
        if isinstance(it, dict) and it.get("saved"):
            new = moved.get(os.path.abspath(it["saved"]))
            if new:
                it["saved"] = new
                it["subfolder"] = os.path.relpath(os.path.dirname(new), base)
    write_manifest(base, items)


def mark_upscaled(src, out):
    """把超分产物登记为所在目录清单里的首选 video 条目。

    下游（episode_status / assemble_episode）取清单里第一条 kind=='video' 的现存文件，
    故这里把 1080P 产物插到最前、原片降级为 video_src，整集拼接就会用超分后的成片。
    """
    d = os.path.dirname(os.path.abspath(src))
    items = read_manifest(d)
    if items is None:
        items = [{"filename": os.path.basename(src), "kind": "video", "saved": src}]
    keep = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if os.path.abspath(it.get("saved") or "") == os.path.abspath(out):
            continue
        if os.path.abspath(it.get("saved") or "") == os.path.abspath(src) and it.get("kind") == "video":
            it["kind"] = "video_src"
        keep.append(it)
    keep.insert(0, {"filename": os.path.basename(out), "kind": "video",
                    "saved": out, "upscaled": True, "source": src})
    write_manifest(d, keep)


def main(argv=None):
    p = argparse.ArgumentParser(description="整集平铺产物按镜归位到 镜NN/ 子目录")
    p.add_argument("--episode", default="第1集")
    p.add_argument("--mode", choices=["i2v", "fl2va", "r2v"], default="r2v")
    p.add_argument("--collect-dir", default=None, help="产物目录（默认 output/视频/<集>/<mode>）")
    p.add_argument("--dryrun", action="store_true", help="只打印归位计划，不动文件")
    p.add_argument("--copy", action="store_true", help="复制而非移动（保留平铺副本）")
    a = p.parse_args(argv)

    ep = dt.episode_tag(a.episode)
    base = a.collect_dir or os.path.join(ROOT, "output", "视频", ep, a.mode)
    sids = episode_shot_ids(a.episode)
    print("归位目标：%s（%d 镜）" % (base, len(sids)))
    n = distribute(base, sids, dryrun=a.dryrun, copy=a.copy)
    print("归位完成：%d 镜%s" % (n, "（dryrun）" if a.dryrun else ""))
    return 0 if n else 2


if __name__ == "__main__":
    sys.exit(main())
