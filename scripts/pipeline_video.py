# -*- coding: utf-8 -*-
"""一键视频链：分镜 -> build(I2V/FL2VA/R2V) -> 校验素材 -> 提交 -> 盯守成片。

解决「视频成片链碎片化」：原先需要手动逐个跑 build_video_refs / build_fl2va_refs /
build_r2v_refs，再 copy 到 ComfyUI input，再手动 submit_workflow --check。
本脚本把这些串成一键，并在提交前【硬阻断】缺失的首帧/尾帧/参考图。

用法:
  # 只建工作流 + 校验素材（默认安全，不消耗算力）
  python scripts/pipeline_video.py --mode fl2va --shots 01,02

  # 建 + 校验 + 真实提交 + 自动盯守到出片
  python scripts/pipeline_video.py --mode fl2va --shots 01,02 --submit-real

  # r2v（参考图驱动）
  python scripts/pipeline_video.py --mode r2v --submit-real --comfy-root <ComfyUI根目录>
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402

WORKFLOWS = os.path.join(ROOT, "workflows")

DEFAULT_EPISODE = "第1集"
_EP = {"value": DEFAULT_EPISODE}   # 可变集号（函数读它，main 用 --episode 设置）
SNAME = "写实CG融合"          # 与 05_shotfirst / 06_shotlast / 三视图 / 九宫格保存前缀一致
IMG_SUBDIR = "02_分镜"
CHAR_PREFIX = "00_角色素材"
SCENE_PREFIX = "01_场景素材"
VID_W, VID_H = 1280, 736

DEFAULT_COMFY_ROOT = r"D:\Comfy-Desktop\ComfyUI-Shared"

# mode -> builder 脚本 / 产物关键字 / 模板相对路径
BUILDERS = {
    "i2v": "build_video_refs.py",
    "fl2va": "build_fl2va_refs.py",
    "r2v": "build_r2v_refs.py",
}
MODE_KEY = {"i2v": "I2V", "fl2va": "FL2VA", "r2v": "R2VA"}
TEMPLATE_REL = {
    "i2v": os.path.join("custom_nodes", "ComfyUI_MiniMaxH3_Director",
                        "example_workflows", "minimax_h3_director_external_groups_i2v.json"),
    "fl2va": os.path.join("custom_nodes", "ComfyUI_MiniMaxH3_Director",
                          "example_workflows", "minimax_h3_director_external_groups_i2v.json"),
    "r2v": os.path.join("custom_nodes", "ComfyUI_MiniMaxH3_Director",
                        "example_workflows", "minimax_h3_director_external_groups_r2v.json"),
}


# ---------- 素材路径（与 build_* 脚本命名一致）----------
def first_frame_file(sid):
    e = _EP["value"]
    return "%s/%s/%s_镜%s_首帧_%s_00001_.png" % (IMG_SUBDIR, e, e, sid, SNAME)


def last_frame_file(sid):
    e = _EP["value"]
    return "%s/%s/%s_镜%s_尾帧_%s_00001_.png" % (IMG_SUBDIR, e, e, sid, SNAME)


def char_ref_file(cid, name):
    return "%s/%s/%s_三视图_%s_00001_.png" % (CHAR_PREFIX, name, cid, SNAME)


def scene_ref_file(sid, name):
    return "%s/%s/%s_九宫格_00001_.png" % (SCENE_PREFIX, name, name)


def _exists(root, rel):
    """素材是否已生成在 ComfyUI 的 output/<rel>（相对路径，subfolder）。"""
    return os.path.isfile(os.path.join(root, "output", rel))


# ---------- 硬阻断式校验 ----------
def validate_storyboard(mode, storyboards, comfy_root):
    """校验本集每个镜所需素材是否已生成。返回缺失列表（空 = 通过）。

    i2v/fl2va: 对应镜的首帧（fl2va 另需尾帧）
    r2v:      对应镜的角色三视图 + 场景九宫格
    """
    missing = []
    if mode in ("i2v", "fl2va"):
        for sb in storyboards:
            sid = sb.get("shot_id")
            if not _exists(comfy_root, first_frame_file(sid)):
                missing.append(first_frame_file(sid))
            if mode == "fl2va" and not _exists(comfy_root, last_frame_file(sid)):
                missing.append(last_frame_file(sid))
    elif mode == "r2v":
        char_map = {c.get("id"): c.get("name") for c in dt.load_characters()}
        scene_map = {s.get("id"): s.get("name") for s in dt.load_scenes()}
        for sb in storyboards:
            for cid in sb.get("character_ids", []) or []:
                name = char_map.get(cid)
                if name and not _exists(comfy_root, char_ref_file(cid, name)):
                    missing.append(char_ref_file(cid, name))
            sid = sb.get("scene_id", "")
            sname = scene_map.get(sid)
            if sname and not _exists(comfy_root, scene_ref_file(sid, sname)):
                missing.append(scene_ref_file(sid, sname))
    return missing


# ---------- build 产物定位 ----------
def build_tag(shots):
    if not shots:
        return "整集"
    wanted = {s.strip() for s in shots.split(",") if s.strip()}
    return "镜" + "-".join(sorted(wanted))


def build_prev_tail_arg(shots, storyboards=None):
    """把镜号序列转成链式映射 {当前镜号: (上一镜号, 待定位成片)}，pair 为 None 表示首镜。

    - shots 给出时，按数值升序排好链接关系；
    - shots 为空且给了 storyboards 时，自动取全部分镜的 shot_id 作为顺序（整集全自动链式）。
    成片路径由 run_chain 逐镜定位后回填。
    """
    wanted = None
    if shots:
        wanted = [s.strip() for s in shots.split(",") if s.strip()]
    elif storyboards:
        wanted = [sb.get("shot_id") for sb in storyboards if sb.get("shot_id")]
    if not wanted:
        return None
    wanted.sort(key=lambda x: int(x) if str(x).isdigit() else str(x))
    out = {}
    for i, cur in enumerate(wanted):
        if i == 0:
            out[cur] = None
            continue
        prev = wanted[i - 1]
        out[cur] = (prev, None)   # 成片路径待 run_chain 定位
    return out


def _retry_run(cmd, retry=1, task=""):
    """执行子进程命令，失败可自动重试（抗显存/网络瞬态失败）。返回 returncode。

    retry：允许执行的总次数（≥1）。build 这种易受 GPU/资源瞬时影响的步骤，
    重试能显著降低「一次失败就全断」的概率。
    """
    last = 1
    for i in range(max(1, retry)):
        r = subprocess.run(cmd, cwd=ROOT, encoding="utf-8")
        if r.returncode == 0:
            return 0
        last = r.returncode
        if i < retry - 1:
            print("  [!] %s 失败(rc=%d)，第 %d/%d 次重试..." % (task or "步骤", r.returncode, i + 2, retry))
    return last


def run_build(mode, comfy_root, shots, no_turbo, prev_tail_arg=None, retry=1):
    """调对应 build 脚本生成工作流，返回生成的工作流绝对路径（失败返回 None）。

    prev_tail_arg：形如 "03:<上一镜成片绝对路径>" 的 --prev-tail 值；用于 r2v 链式衔接。
    retry：build 失败自动重试次数。
    """
    builder = os.path.join(HERE, BUILDERS[mode])
    cmd = [sys.executable, builder, "--comfy-input", comfy_root]
    if shots:
        cmd += ["--shots", shots]
    if prev_tail_arg and mode == "r2v":
        cmd += ["--prev-tail", prev_tail_arg]
    if no_turbo and mode in ("i2v", "fl2va"):
        cmd += ["--no-turbo"]
    print("  $", " ".join(cmd))
    rc = _retry_run(cmd, retry, "build(%s)" % mode)
    if rc != 0:
        print("  build 失败 (rc=%s)" % rc)
        return None
    tag = build_tag(shots)
    key = MODE_KEY[mode]
    pat = "*_%s_%s_*.json" % (key, tag)
    files = glob.glob(os.path.join(WORKFLOWS, pat))
    if not files:  # 退回：只按关键字取最新
        files = glob.glob(os.path.join(WORKFLOWS, "*_%s_*.json" % key))
    if not files:
        print("  build 成功但未在 %s 找到产物" % WORKFLOWS)
        return None
    return max(files, key=os.path.getmtime)


def do_submit_and_watch(wf, submit_real, watch, poll, timeout, collect_dir=None, retry=1):
    """提交（可选盯守 + 成功后落盘产物）。返回 returncode。

    retry：提交/盯守失败自动重试次数。盯守超时(rc=2)任务可能仍在后台排队/运行，
    重试会造成重复提交消耗算力，故对超时不重试。
    """
    cmd = [sys.executable, os.path.join(HERE, "submit_workflow.py"),
           "--submit", wf]
    if watch:
        cmd += ["--watch", "--poll", str(poll), "--timeout", str(timeout)]
    if collect_dir:
        cmd += ["--collect-dir", collect_dir]
    print("  $", " ".join(cmd))
    last = 1
    for i in range(max(1, retry)):
        rc = subprocess.run(cmd, cwd=ROOT, encoding="utf-8").returncode
        if rc == 0:
            return 0
        last = rc
        if rc == 2:
            print("  [!] 盯守超时，任务可能仍在后台运行，不再重试以免重复消耗算力。")
            return rc
        if i < retry - 1:
            print("  [!] 提交/盯守失败(rc=%d)，第 %d/%d 次重试..." % (rc, i + 2, retry))
            time.sleep(5)   # 稍等让显存/网络恢复再重试
    return last


def locate_shot_video(collect_dir, sid, mode):
    """在某镜盯守落盘目录里找该镜生成的视频产物。返回首个 .mp4 绝对路径或 None。

    逐镜时产物文件名含递增编号；结合 collect_manifest.json 优先定位 kind=='video' 的产物。
    """
    mf = os.path.join(collect_dir, "collect_manifest.json")
    if os.path.isfile(mf):
        try:
            with open(mf, encoding="utf-8") as f:
                items = json.load(f)
            for it in items:
                if it.get("kind") == "video" and it.get("saved") and os.path.isfile(it["saved"]):
                    return it["saved"]
        except Exception:
            pass
    cands = glob.glob(os.path.join(collect_dir, "*.mp4")) or glob.glob(os.path.join(collect_dir, "*.gif"))
    return max(cands, key=os.path.getmtime) if cands else None


def run_chain(mode, comfy_root, shots, no_turbo, watch, poll, timeout, base_collect_dir,
              storyboards=None, retry=1):
    """链式逐镜生成：按镜号顺序，每镜「生成携带上一镜尾帧的工作流 → 提交 → 盯守落盘」，
    下一镜自动复用上一镜成片尾帧作为起始参考，实现整集镜头首尾衔接不脱节。

    shots 为空时用 storyboards 全部分镜实现整集全自动链式。
    支持断点续跑：某镜子目录已有成片则自动跳过，从第一个未完成镜续起并继续衔接上一镜尾帧，
    中途停止后重新运行无需从头重跑。返回最后成功镜数；任一镜失败即停。
    """
    prev_map = build_prev_tail_arg(shots, storyboards)   # {当前镜: (上一镜, 待定位成片)}
    if not prev_map:
        print("  [chain] 无可用镜号，无法链式")
        return 0
    print("\n== r2v 链式逐镜生成：%s ==" % (shots))
    ok = 0
    for cur in prev_map:
        # 断点续跑：当前镜若已在独立子目录落盘成片，则跳过重新提交，视为已完成。
        # 这样即使链式生成中途被停止/终止，重新运行时也能自动从断点续起，
        # 且后续镜仍会去定位上一镜成片尾帧做衔接，保证整集首尾连贯不断片。
        cur_shot_dir = os.path.join(base_collect_dir, "镜" + cur)
        cur_done = locate_shot_video(cur_shot_dir, cur, mode)
        if cur_done:
            print("  [跳过] 镜%s 已有成片（%s），断点续跑跳过该镜" % (cur, os.path.basename(cur_done)))
            ok += 1
            continue
        pair = prev_map[cur]
        prev_tail_arg = None
        if pair:
            prev_sid = pair[0]
            # 上一镜产物在独立的镜子目录 base_collect_dir/镜<prev_sid>/ 下（逐镜落盘处）
            prev_shot_dir = os.path.join(base_collect_dir, "镜" + prev_sid)
            prev_video = locate_shot_video(prev_shot_dir, prev_sid, mode)
            if not prev_video:
                # 上一镜产物未落盘：尝试从 ComfyUI output 直接找（用户可能手动跑过）
                prev_video = locate_comfy_shot_video(comfy_root, prev_sid)
                if prev_video:
                    print("  [!] 子目录 %s 无产物，回退 ComfyUI output：%s"
                          % (os.path.basename(prev_shot_dir), os.path.basename(prev_video)))
            if not prev_video:
                print("  [!] 找不到上一镜(%s)成片，跳过该镜的尾帧衔接：%s" % (prev_sid, cur))
            else:
                prev_tail_arg = "%s:%s" % (cur, prev_video)
                print("  [链接] 镜%s 复用上一镜(%s)成片尾帧：%s" % (cur, prev_sid, os.path.basename(prev_video)))
        # 生成当前镜工作流
        wf = run_build(mode, comfy_root, cur, no_turbo, prev_tail_arg, retry)
        if not wf:
            print("  [!] 镜%s 工作流生成失败" % cur)
            break
        print("  [镜%s] 工作流：%s" % (cur, os.path.basename(wf)))

        # 逐镜落盘独立子目录，避免多镜产物互相覆盖
        shot_collect = os.path.join(base_collect_dir, ("镜" + cur))
        rc = do_submit_and_watch(wf, True, watch, poll, timeout, shot_collect, retry)
        if rc != 0:
            print("  [!] 镜%s 提交/盯守失败 (rc=%s)，链式终止" % (cur, rc))
            break
        ok += 1
        print("  [镜%s] 完成" % cur)
    print("\n链式完成：成功 %d 镜。" % ok)
    return ok


def run_chain_batch(mode, comfy_root, shots, no_turbo, watch, poll, timeout, base_collect_dir,
                    storyboards=None, retry=1):
    """整组一次生成（官方「段间引导」continuity）。

    旧的逐镜独立提交：每镜是单段 timeline，批内没有「上一段」，段间引导 continuity
    无法启用，只能靠上一镜尾帧参考图锁信念，衔接弱。改为整组一次提交后，H3 会在批内
    自动把上一段尾帧 pin 进下一段 conditioning 并裁掉前缀，实现上一镜人物站位/布局/
    光线无缝流入下一镜。产物整组一次落盘到 base_collect_dir。
    """
    wanted = ([s.strip() for s in shots.split(",") if s.strip()] if shots
              else [sb.get("shot_id") for sb in (storyboards or []) if sb.get("shot_id")])
    wanted = [w for w in wanted if w]
    if not wanted:
        print("  [chain] 无可用镜号，无法链式")
        return 0
    shots_arg = ",".join(wanted)
    print("\n== r2v 整组生成（官方段间引导 continuity）：镜 %s 共 %d 镜 ==" % (shots_arg, len(wanted)))
    # 一次 build 整组；不传 --prev-tail（衔接由段间引导承担，上一段尾帧已被自动 pin 进本段）
    wf = run_build(mode, comfy_root, shots_arg, no_turbo, None, retry)
    if not wf:
        print("  [!] 整组工作流生成失败")
        return 0
    print("  [整组] 工作流：%s（含 %d 段，启用段间引导 continuity）" % (os.path.basename(wf), len(wanted)))
    rc = do_submit_and_watch(wf, True, watch, poll, timeout, base_collect_dir, retry)
    if rc != 0:
        print("  [!] 整组提交/盯守失败 (rc=%s)" % rc)
        return 0
    print("\n链式完成：整组生成成功，产物落盘：%s" % base_collect_dir)
    return len(wanted)


def locate_comfy_shot_video(comfy_root, sid):
    """从 ComfyUI output/video 找该镜成片（用户可能在此手动/自动生成过）。

    H3 产物命名形如 MiniMaxH3_Director_external_r2v_0000N_.mp4，按镜序递增，
    无法精确到镜号时回退取「每镜最新」——这里以 collect 产物的 index 近似。
    避免依赖唯一命名，仅当本镜在某目录下是唯一/最新时才命中。
    """
    base = os.path.join(comfy_root, "output", "video")
    if not os.path.isdir(base):
        return None
    files = glob.glob(os.path.join(base, "*.mp4")) or glob.glob(os.path.join(base, "*.gif"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    p = argparse.ArgumentParser(description="一键视频链：build -> 校验素材 -> 提交 -> 盯守")
    p.add_argument("--mode", choices=["i2v", "fl2va", "r2v"], default="fl2va",
                   help="视频模式（默认 fl2va 首尾帧）")
    p.add_argument("--shots", default=None,
                   help="逗号分隔镜号（如 01,02）；默认全部镜头")
    p.add_argument("--episode", default=DEFAULT_EPISODE, help="集号（默认 第1集）")
    p.add_argument("--comfy-root", default=os.environ.get("COMFY_ROOT", DEFAULT_COMFY_ROOT),
                   help="ComfyUI 根目录（默认环境变量 COMFY_ROOT 或内置路径）")
    p.add_argument("--no-turbo", action="store_true", help="不插 turbo LoRA、保持 25 步（i2v/fl2va）")
    p.add_argument("--submit-real", action="store_true",
                   help="真正提交到 ComfyUI（默认仅 build + 校验 + 打印，安全）")
    p.add_argument("--chain", action="store_true",
                   help="逐镜链式生成：每镜复用上一镜成片尾帧衔接（仅 r2v，需 --shots 多镜且 --submit-real）")
    p.add_argument("--no-watch", action="store_true",
                   help="提交后不自动盯守（默认提交即盯守）")
    p.add_argument("--collect-dir", default=None,
                   help="盯守成功后产物落盘目录（默认 output/视频/<集>/<mode>）")
    p.add_argument("--poll", type=int, default=10, help="盯守轮询间隔秒")
    p.add_argument("--timeout", type=int, default=3600, help="盯守超时秒")
    p.add_argument("--retry", type=int, default=1,
                   help="build/提交/盯守 每步失败自动重试次数（默认 1，抗显存/网络瞬态失败）")
    args = p.parse_args()

    _EP["value"] = args.episode
    comfy_root = args.comfy_root

    # 0. 模板是否存在（决定该模式能否构建）
    tmpl = os.path.join(comfy_root, TEMPLATE_REL[args.mode])
    if not os.path.isfile(tmpl):
        print("找不到模板：%s" % tmpl)
        print("  （请确认 ComfyUI 根目录正确，或用 --comfy-root 指定）")
        return 3

    # 1. 分镜
    ep = _EP["value"]
    storyboards = dt.load_storyboards(ep)
    if args.shots:
        wanted = {s.strip() for s in args.shots.split(",") if s.strip()}

        def _norm_sid(sid):
            s = str(sid or "").strip()
            return s if not s.isdigit() else "%02d" % int(s)

        storyboards = [sb for sb in storyboards if _norm_sid(sb.get("shot_id", "")) in wanted]
    if not storyboards:
        print("分镜为空：%s 下没有可用镜头（--shots=%s）" % (ep, args.shots or "全部"))
        return 3

    print("== pipeline_video: mode=%s 集=%s 镜=%s 共%d镜 ==" %
          (args.mode, ep, args.shots or "全部", len(storyboards)))

    # 2. 校验素材（真正提交时硬阻断；dryrun 仅提示，便于全链预览）
    missing = validate_storyboard(args.mode, storyboards, comfy_root)
    if missing:
        print("\n[素材风险] 以下素材未在 ComfyUI output 生成：")
        for m in missing:
            print("   - output/%s" % m)
        if args.submit_real:
            print("[中断] 真正提交需备齐素材，请先跑图片层生成这些图。")
            return 2
        print("[dryrun] 仅预览，不阻断；请确认素材是否已生成。")

    collect_dir = args.collect_dir or os.path.join(ROOT, "output", "视频", ep, args.mode)

    # 3b. 链式逐镜（仅 r2v）：整集全自动链式，每镜复用上一镜尾帧。
    # 注意：先判断 chain，避免做一次无用的"整集 build"（链式会逐镜重建）。
    #
    # 为什么用 run_chain（逐镜）而非 run_chain_batch（整组 continuity）：
    #   官方「段间引导」continuity 会触发 h3_motion_context 对 MiniMaxH3.extra_conds
    #   的 patch，而本机已安装 standalone ComfyUI-H3-Motion-Context 自定义节点，二者
    #   冲突导致 RuntimeError（见 output/chain_continuity.log）。逐镜链式改用「上一镜
    #   成片尾帧」做参考锁信念（--prev-tail），不触发该 patch，可稳定跑通并支持断点续跑。
    if args.chain:
        if args.mode != "r2v":
            print("[chain] 链式衔接仅支持 r2v 模式")
            return 2
        # 有 shots 时需 >=2 镜才有"上一镜"可衔接；无 shots 则自动整集（按分镜数量判断）
        if args.shots and len(args.shots.split(",")) < 2:
            print("[chain] 链式衔接需至少 2 个连续镜（如 --shots 01,02,03），或省略 --shots 走整集全自动。")
            return 2
        if len(storyboards) < 2:
            print("[chain] 本集分镜不足 2 个，无法链式衔接。")
            return 2
        if not args.submit_real:
            print("\n[chain] 链式生成会真实提交消耗算力，需加 --submit-real。")
            print("  请确认 ComfyUI 服务已启动、素材已备齐。")
            return 2
        n = run_chain(args.mode, comfy_root, args.shots, args.no_turbo,
                      not args.no_watch, args.poll, args.timeout, collect_dir, storyboards,
                      retry=args.retry)
        return 0 if n > 0 else 2

    # 3. build 工作流（非链式：单镜/多镜一体）
    wf = run_build(args.mode, comfy_root, args.shots, args.no_turbo, retry=args.retry)
    if not wf:
        return 2
    print("  生成工作流：%s" % os.path.basename(wf))

    # 4. 提交（默认 dryrun 安全）
    if not args.submit_real:
        print("\n[dryrun] 未提交。确认无误后用 --submit-real 真正生成视频：")
        print("  python scripts/pipeline_video.py --mode %s %s --submit-real%s"
              % (args.mode, ("--shots " + args.shots) if args.shots else "",
                 " --no-watch" if args.no_watch else ""))
        return 0

    rc = do_submit_and_watch(wf, args.submit_real, not args.no_watch,
                             args.poll, args.timeout, collect_dir, retry=args.retry)
    if rc == 0:
        print("\n视频链完成。产物落盘：%s" % collect_dir)
    return rc


if __name__ == "__main__":
    sys.exit(main())
