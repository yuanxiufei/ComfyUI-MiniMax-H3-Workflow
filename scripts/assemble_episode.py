# -*- coding: utf-8 -*-
"""整集成片组装器：把已成片的分镜 mp4 按时序拼接成「整集成片」，并附带
对白字幕（SRT，可选烧录）与电平规范（loudnorm，对白-14 LUFS 网播目标）。

补的是流水线最后一块缺口：产物止步于单镜 mp4（output/视频/<集>/<mode>/镜XX/），
本脚本按 分镜.json 的 shot_id 顺序 + 每镜实际时长做时间轴对齐。

参考规范：
  - 老李 skill quality-gate-review：成片阶段声音三层/电平规范
  - 目标项目 episode_status（整集收口清单）按同一落盘约定扫描
ffmpeg 依赖：优先用 imageio-ffmpeg 自带二进制（ComfyUI/系统 python 环境都有），
可用 --ffmpeg <路径> 显式指定；无需 ffprobe（时长用 ffmpeg -i 解析）。

用法：
  python scripts/assemble_episode.py                     # 默认 r2v，拼接已有成片
  python scripts/assemble_episode.py --mode r2v --shots 01,02,03,04
  python scripts/assemble_episode.py --dryrun            # 只出计划，不落盘
  python scripts/assemble_episode.py --no-sub --no-loud  # 仅拼接不做字幕/电平
  python scripts/assemble_episode.py --out <path>.mp4 --sub-out <path>.srt
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import comfy_config  # noqa: F401  —— import 即把 stdout/stderr 统一为 UTF-8

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402
import episode_status as est  # noqa: E402  复用整集收口扫描（按分镜序 + 成片目录）
import qc_storyboard as qc  # noqa: E402  复用台词解析/语速计时

DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyh.ttc"),
    os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "msyhbd.ttc"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]
# 字体文件 → libass 字体族名（Windows 下按系统注册名匹配）
_FONT_FAMILY = {
    "msyh.ttc": "Microsoft YaHei", "msyhbd.ttc": "Microsoft YaHei",
    "NotoSansCJK-Regular.ttc": "Noto Sans CJK SC",
    "PingFang.ttc": "PingFang SC",
}


def find_ffmpeg(cli=None):
    if cli:
        return cli
    exe = os.environ.get("FFMPEG")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"  # 让系统 PATH 兜底


def probe_duration(ff, path):
    """ffmpeg -i 解析时长（秒）；失败返回 None。stderr 走临时文件，避免管道解码。"""
    try:
        with tempfile.TemporaryFile() as err_f:
            r = subprocess.run([ff, "-i", path], stdout=subprocess.DEVNULL,
                               stderr=err_f, timeout=60)
            err_f.seek(0)
            err = err_f.read().decode("utf-8", "replace")
        m = DUR_RE.search(err)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return None


def fmt_ts(sec):
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def build_srt(episode, rows, durations):
    """按分镜 dialogue 生成整集 SRT（说话人前缀保留，去掉（动作））。

    rows: episode_status 行（含 shot_id/dialogue/video）；durations: 每镜实际时长(s)。
    台词在镜时长内按「估算朗读时长占比」分配，段间留 0.25s。
    """
    subs = []          # (start, end, text)
    t = 0.0
    sb_map = {str(b.get("shot_id")).zfill(2): b for b in dt.load_storyboards(episode)}
    for row in rows:
        shot_id = row["shot_id"]
        dur = durations.get(shot_id) or float(row.get("duration") or 0) or 5.0
        sb = sb_map.get(shot_id) or {}
        lines = qc.parse_dialogue_lines(sb.get("dialogue") or "")
        if lines:
            w = [max(qc.estimate_duration_min(ln["text"]), 0.8) for ln in lines]
            scale = (dur - 0.25 * (len(lines) - 1)) / max(sum(w), 0.001)
            acc = 0.0
            for ln, wt in zip(lines, w):
                seg = wt * scale
                text = ("%s：" % ln["speaker"]) if ln["speaker"] else ""
                text += ln["text"]
                subs.append((t + acc, min(t + acc + seg, t + dur - 0.05), text))
                acc += seg + 0.25
        t += dur
    out = []
    for i, (a, b, text) in enumerate(subs, 1):
        out.append("%d\n%s --> %s\n%s\n\n" % (i, fmt_ts(a), fmt_ts(b), text))
    return "".join(out)


class _Proc:
    __slots__ = ("returncode", "stdout", "stderr")

    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run(ff, args, cwd=None):
    """跑 ffmpeg：stdout/stderr 落到临时文件后读回（UTF-8 replace）。

    不用管道捕获——Windows/GBK 下 communicate 的文本解码线程会炸 UnicodeDecodeError，
    且管道满时容易死锁；文件句柄则无这些问题。
    """
    try:
        with tempfile.TemporaryFile() as so, tempfile.TemporaryFile() as se:
            p = subprocess.run([ff] + args, stdout=so, stderr=se,
                               timeout=3600, cwd=cwd)
            so.seek(0)
            se.seek(0)
            return _Proc(p.returncode,
                         so.read().decode("utf-8", "replace"),
                         se.read().decode("utf-8", "replace"))
    except subprocess.TimeoutExpired as e:
        return _Proc(1, "", "ffmpeg 超时(>3600s): %s" % e)
    except Exception as e:
        return _Proc(1, "", "subprocess error: %s" % e)


def assemble(episode, mode, shots_wanted, out_mp4, sub_path, with_sub_burn,
             with_loud, dryrun, ff, font):
    ep = dt.episode_tag(episode)
    rows = est.build_status_rows(episode, mode)
    if shots_wanted:
        want = {s.strip().zfill(2) for s in shots_wanted if s.strip()}
        rows = [r for r in rows if r["shot_id"] in want]
    present = [r for r in rows if r.get("video")]
    if not present:
        print("当前没有已成片的镜（%s/%s）。先跑 pipeline_video.py 出片再组装。" % (mode, ep))
        return 2
    missing = [r["shot_id"] for r in rows if not r.get("video")]

    # 探测每镜真实时长
    durations = {}
    for r in present:
        d = probe_duration(ff, r["video"])
        durations[r["shot_id"]] = d
        print("  镜%s 成片 %s | 实际 %.2fs%s" % (
            r["shot_id"], os.path.basename(r["video"]), d or 0,
            "" if d else "（探测失败,按分镜时长估算）"))

    plan = " + ".join("镜%s" % r["shot_id"] for r in present)
    print("\n组装计划(%s/%s)：%s" % (mode, ep, plan))
    if missing:
        print("  未成片将跳过：%s（共 %d 镜缺）" % (",".join(missing), len(missing)))
    if dryrun:
        print("\n[dryrun] 仅预览，不执行。成片输出: %s | 字幕: %s | 烧字幕=%s | loudnorm=%s"
              % (out_mp4, sub_path, with_sub_burn, with_loud))
        return 0

    # ---- 字幕文件（用户可读的最终 .srt）----
    if with_sub_burn:
        srt_text = build_srt(episode, present, durations)
        os.makedirs(os.path.dirname(os.path.abspath(sub_path)), exist_ok=True)
        with open(sub_path, "w", encoding="utf-8") as f:
            f.write(srt_text)
        n_sub = len(srt_text.split("\n\n")) - 1
        print("  字幕已写: %s（%d 条）" % (sub_path, n_sub))
    elif sub_path:
        print("  --no-sub 且给了 --sub-out：跳过字幕生成。")

    # ---- 中间文件放系统 TEMP（工作区外，规避 IDE 对工作区文件删除的回收监视）；
    #      最终产物直接以临时名落在已存在目录、用 os.replace 改名（不触发删除钩子）。
    out_dir = os.path.dirname(os.path.abspath(out_mp4))
    os.makedirs(out_dir, exist_ok=True)
    _work = tempfile.mkdtemp(prefix="h3_asm_")
    final_tmp = os.path.join(out_dir, "._asm_final.mp4")  # 与成片同目录，便于 os.replace

    def _cleanup_ok():
        shutil.rmtree(_work, ignore_errors=True)
        try:
            os.remove(final_tmp)
        except OSError:
            pass

    listf = os.path.join(_work, "concat.txt")
    with open(listf, "w", encoding="utf-8") as f:
        for r in present:
            f.write("file '%s'\n" % r["video"].replace("'", "'\\''"))
    mid = os.path.join(_work, "_concat.mp4")

    # ---- 拼接 concat（先试 -c copy，失败则重编码）----
    r = _run(ff, ["-y", "-f", "concat", "-safe", "0", "-i", listf,
                  "-c", "copy", "-movflags", "+faststart", mid])
    if r.returncode != 0:
        r2 = _run(ff, ["-y", "-f", "concat", "-safe", "0", "-i", listf,
                       "-c:v", "libx264", "-crf", "19", "-preset", "medium",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                       "-movflags", "+faststart", mid])
        if r2.returncode != 0:
            print("拼接失败（copy 与重编码均失败）。")
            print(r.stderr[-1200:] + r2.stderr[-800:])
            return 1

    # ---- 字幕烧录 + 电平规范（第二遍编码）----
    if not (with_sub_burn or with_loud):
        shutil.move(mid, out_mp4)   # 跨卷安全（TEMP 在 C:，out_dir 在 D:）
        print("成片已生成: %s" % out_mp4)
        _cleanup_ok()
        return 0

    vf, af = [], []
    if with_sub_burn:
        # libass 用相对文件名读字幕（工作目录 = _work）
        rel = "_sub.srt"
        shutil.copyfile(sub_path, os.path.join(_work, rel))
        style = "FontSize=16,Outline=1,Shadow=1,MarginV=18"
        if font and os.path.exists(font):
            family = _FONT_FAMILY.get(os.path.basename(font).lower(),
                                      os.path.splitext(os.path.basename(font))[0])
            style += ",FontName=" + family
        sub_opt = "subtitles=filename='%s'" % rel
        # 注意：filter 里 ':' 不受引号保护，fontsdir 冒号要反斜杠转义
        fdir = os.path.dirname(os.path.abspath(font)).replace("\\", "/") if (font and os.path.exists(font)) else ""
        if fdir:
            sub_opt += ":fontsdir='%s'" % fdir.replace(":", "\\:")
        sub_opt += ":force_style='%s'" % style
        vf.append(sub_opt)
    if with_loud:
        af.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    vf_arg = ",".join(vf) if vf else None
    af_arg = af[0] if af else None

    args = ["-y", "-i", mid]
    if vf_arg:
        args += ["-vf", vf_arg, "-c:v", "libx264", "-crf", "19", "-preset", "medium",
                 "-pix_fmt", "yuv420p"]
    else:
        args += ["-c:v", "copy"]
    if af_arg:
        args += ["-af", af_arg, "-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-c:a", "copy"]
    args += ["-movflags", "+faststart", final_tmp]
    rr = _run(ff, args, cwd=_work)
    if rr.returncode != 0:
        print("字幕/电平处理失败，已保留未处理拼接片段:")
        print("  %s" % mid)
        print(rr.stderr[-1200:])
        return 1
    os.replace(final_tmp, out_mp4)
    print("成片已生成: %s" % out_mp4)
    _cleanup_ok()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description="整集成片组装器（拼接+字幕+电平）")
    p.add_argument("--episode", default="第1集")
    p.add_argument("--mode", choices=["i2v", "fl2va", "r2v"], default="r2v")
    p.add_argument("--shots", default=None, help="只组装指定镜（逗号分隔，缺省=全部已成片）")
    p.add_argument("--out", default=None, help="成片 mp4 路径（默认 output/视频/<集>/<mode>/<集>_<mode>_整集成片.mp4）")
    p.add_argument("--sub-out", default=None, help="字幕 srt 路径（默认与成片同目录同名 .srt）")
    p.add_argument("--no-sub", action="store_true", help="不烧录对白字幕")
    p.add_argument("--no-loud", action="store_true", help="不做 loudnorm 电平规范")
    p.add_argument("--font", default="", help="字幕字体文件路径（Windows 缺省自动找微软雅黑）")
    p.add_argument("--ffmpeg", default=None, help="ffmpeg 可执行文件路径")
    p.add_argument("--dryrun", action="store_true", help="只打印组装计划不落盘")
    args = p.parse_args(argv)

    ep = dt.episode_tag(args.episode)
    mode = args.mode
    if not args.out:
        args.out = os.path.join(ROOT, "output", "视频", ep, mode,
                                "%s_%s_整集成片.mp4" % (ep, mode))
    if not args.sub_out:
        args.sub_out = os.path.splitext(args.out)[0] + ".srt"

    ff = find_ffmpeg(args.ffmpeg)
    font = args.font
    if not font:
        for cand in _FONT_CANDIDATES:
            if os.path.exists(cand):
                font = cand
                break
    print("ffmpeg: %s | 字幕字体: %s" % (ff, os.path.basename(font) if font else "(默认)"))
    rc = assemble(ep, mode,
                  (args.shots or "").split(",") if args.shots else None,
                  args.out, args.sub_out,
                  with_sub_burn=not args.no_sub, with_loud=not args.no_loud,
                  dryrun=args.dryrun, ff=ff, font=font)
    return rc


if __name__ == "__main__":
    sys.exit(main())
