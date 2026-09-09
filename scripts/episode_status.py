# -*- coding: utf-8 -*-
"""整集产物收口清单：分镜 vs 成片落盘对比 + 续跑命令建议。

用途：
  - 一键看出「第N集 / 某模式（r2v/fl2va/i2v）」哪些镜已成片、哪些缺失；
  - 给缺失镜生成可直接执行的续跑命令（对接 pipeline_video.py 的断点续跑能力）；
  - 输出 Markdown 收口清单 / JSON 供脚本消费。

落盘约定（与 pipeline_video.py 一致）:
  output/视频/<集>/<mode>/
      镜01/collect_manifest.json + 成片.mp4
      镜02/...
  空镜/missing = 该镜目录缺失或目录内无 manifest/mp4。

用法:
  python scripts/episode_status.py --episode 第1集 --mode r2v
  python scripts/episode_status.py --episode 第1集 --mode r2v --out 剧本/02_分镜/第1集_成片清单.md
  python scripts/episode_status.py --episode 第1集 --mode r2v --json 剧本/02_分镜/第1集_成片清单.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402

SHOT_PAT = re.compile(r"^(?:镜)?(\d{1,2})$")


def scan_episode_collects(episode: str, mode: str) -> dict:
    """扫描 output/视频/<集>/<mode>/ 下已成片子目录。

    返回 {shot_id: {"video": 绝对路径|None, "manifest": bool, "shots_dir": dir}}
    """
    ep = dt.episode_tag(episode)
    base = os.path.join(ROOT, "output", "视频", ep, mode)
    if not os.path.isdir(base):
        return {}
    out = {}
    for d in sorted(os.listdir(base)):
        m = SHOT_PAT.match(d)
        if not m:
            continue
        shot_dir = os.path.join(base, d)
        if not os.path.isdir(shot_dir):
            continue
        sid = m.group(1)
        manifest_ok = os.path.isfile(os.path.join(shot_dir, "collect_manifest.json"))
        videos = glob.glob(os.path.join(shot_dir, "*.mp4")) or glob.glob(os.path.join(shot_dir, "*.gif"))
        primary = None
        # 优先取 manifest 里 kind=='video' 的记录；否则取最新 mp4
        if manifest_ok:
            try:
                with open(os.path.join(shot_dir, "collect_manifest.json"), encoding="utf-8") as f:
                    items = json.load(f)
                for it in items:
                    if it.get("kind") == "video" and it.get("saved") and os.path.isfile(it["saved"]):
                        primary = it["saved"]
                        break
            except Exception:
                pass
        if not primary and videos:
            primary = max(videos, key=os.path.getmtime)
        out[sid] = {"video": primary, "manifest": manifest_ok, "videos": sorted(videos),
                    "shots_dir": shot_dir}
    return out


def build_status_rows(episode: str, mode: str) -> list[dict]:
    boards = dt.load_storyboards(episode)
    collects = scan_episode_collects(episode, mode)
    rows = []
    for i, sb in enumerate(boards):
        sid = str(sb.get("shot_id") or (i + 1)).zfill(2)
        dur = sb.get("duration")
        c = collects.get(sid)
        done = bool(c and c.get("video"))
        rows.append({
            "idx": i + 1,
            "shot_id": sid,
            "title": (sb.get("title") or sb.get("description") or "")[:24],
            "scene_type": sb.get("scene_type", ""),
            "duration": dur,
            "dialogue_chars": _count_chars(sb.get("dialogue") or ""),
            "done": done,
            "video": (c or {}).get("video"),
            "shots_dir": (c or {}).get("shots_dir"),
            "videos": (c or {}).get("videos", []),
            "manifest": bool(c and c.get("manifest")),
        })
    return rows


def _count_chars(dialogue: str) -> int:
    """去掉「说话人：（动作）」前缀后的台词字数（用于状态概览，仅近似）。"""
    text = dialogue.replace("\\n", "\n")
    # 去掉 （...） 括注
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    # 去掉「姓名：」前缀
    text = re.sub(r"^[^：:]{1,12}[：:]\s*", "", text, flags=re.M)
    return sum(1 for ch in text if not ch.isspace() and ch not in set("，。！？；：、“”‘’《》…—~ ")) 


def make_markdown(rows, episode, mode, resume_hint="") -> str:
    done = [r for r in rows if r["done"]]
    missing = [r for r in rows if not r["done"]]
    done_sec = sum(float(r["duration"] or 0) for r in done)
    all_sec = sum(float(r["duration"] or 0) for r in rows)
    lines = [
        "# %s 成片收口清单（%s）" % (dt.episode_tag(episode), mode),
        "",
        "- 状态：**%d/%d 镜已成片**（%s）" % (len(done), len(rows),
                                               "已完成 ✅" if not missing else "缺 %d 镜 ❌" % len(missing)),
        "- 成片秒数：%s / %s" % (_fmt(done_sec), _fmt(all_sec)),
        "",
        "| # | 镜 | 时长 | 状态 | 成片 |",
        "|---:|---|---:|:--:|---|",
    ]
    for r in rows:
        mark = "✅" if r["done"] else "❌"
        vid = os.path.basename(r["video"]) if r.get("video") else ("(manifest有)" if r["manifest"] else "-")
        lines.append("| %d | %s | %ss | %s | %s |" % (r["idx"], r["shot_id"],
                                                      r["duration"], mark, vid))
    lines.append("")
    if missing:
        ids = ",".join(r["shot_id"] for r in missing)
        lines.extend([
            "## 缺失镜（%d）" % len(missing),
            "",
            "缺失镜号：`%s`" % ids,
            "",
            "### 续跑命令",
            "",
            "```bash",
            resume_hint or ("python scripts/pipeline_video.py --mode %s --shots %s --submit-real"
                            % (mode, ids)),
            "```",
            "",
            "> 说明：r2v 想整集链式衔接请用 `--chain`（无 --shots 走整集自动续跑，已有成片会自动跳过）。",
            "",
        ])
    else:
        lines.append("整集已成片，可进入拼接/字幕/质检阶段。")
        lines.append("")
    return "\n".join(lines)


def _fmt(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return "%d分%02d秒" % (m, s) if m else "%d秒" % s


def main(argv=None):
    p = argparse.ArgumentParser(description="整集产物收口清单 + 续跑建议")
    p.add_argument("--episode", default="第1集")
    p.add_argument("--mode", choices=["i2v", "fl2va", "r2v"], default="r2v",
                   help="视频模式（默认 r2v；当前实际有产物的是 r2v）")
    p.add_argument("--out", default=None, help="写 Markdown 清单到指定路径")
    p.add_argument("--json", dest="json_out", default=None, help="写 JSON 到指定路径")
    p.add_argument("--shots", default=None, help="只看这些镜（逗号分隔）")
    args = p.parse_args(argv)

    rows = build_status_rows(args.episode, args.mode)
    if args.shots:
        want = {s.strip().zfill(2) for s in args.shots.split(",") if s.strip()}
        rows = [r for r in rows if r["shot_id"] in want]
    if not rows:
        print("没有可用分镜（%s）或没有匹配镜。" % dt.episode_tag(args.episode))
        return 3

    done = sum(1 for r in rows if r["done"])
    missing = [r for r in rows if not r["done"]]
    ids = ",".join(r["shot_id"] for r in missing)
    resume = ("python scripts/pipeline_video.py --mode %s --shots %s --submit-real"
              % (args.mode, ids)) if missing else ""

    md = make_markdown(rows, args.episode, args.mode, resume)
    print("\n".join(md.splitlines()[:12]))
    print("  … %s" % ("（另有缺失清单/续跑命令，见下方或 --out 文件）" if missing else "（整集完成）"))
    if missing:
        print("\n缺失镜号：%s" % ids)
        print("续跑命令：%s" % resume)
        print("  （r2v 整集链式衔接可用：python scripts/pipeline_video.py --mode %s --chain --submit-real）" % args.mode)

    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
        print("清单已写: %s" % args.out)
    if args.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump({"episode": dt.episode_tag(args.episode), "mode": args.mode,
                       "rows": rows, "missing": [r["shot_id"] for r in missing],
                       "resume_command": resume}, f, ensure_ascii=False, indent=2)
        print("JSON 已写: %s" % args.json_out)
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
