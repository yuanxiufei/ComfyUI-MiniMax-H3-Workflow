# -*- coding: utf-8 -*-
"""逐镜生图编排：提交 05 首帧 -> 盯守 -> 复制到 ComfyUI input -> 提交 06 尾帧 -> 盯守 -> 复制。

复用 submit_workflow 的 do_submit / do_watch（均返回可判定成功的 returncode）。
产物落盘到 collect_dir，再按 manifest 定位复制到 ComfyUI input/02_分镜/第1集/。

用法:
    python scripts/gen_shots_images.py 01                      # 只做镜01的首尾帧
    python scripts/gen_shots_images.py 01 --then-video --submit-real
                                                               # 首尾帧就绪后直接续跑视频成片（fl2va）
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402
import comfy_config as cc  # noqa: E402

# 常量（与 build_new_workflows / pipeline_video 保持一致）
COMFY_ROOT = cc.SHARED_ROOT              # 唯一配置源（scripts/comfy_config.py）
IMG_SUBDIR = "02_分镜"
EPISODE = "第1集"
WF_DIR = os.path.join(ROOT, "workflows")
SINGLES_DIR = os.path.join(WF_DIR, "singles")  # consolidate_workflows 归并后单镜工作流所在目录
ARTIFACTS = os.path.join(ROOT, "artifacts")
SHOTS = [str(i).zfill(2) for i in range(1, 13)]

SNAME = "写实CG融合"      # 与 build_new_workflows 保存前缀一致

# 坏图判据：Qwen 单镜工作流偶发输出纯黑帧（~7-13KB 且灰度均值 0；正常分镜图 ~1.2MB/均值 120+）。
# 「文件存在」≠「可用」——黑帧喂进 fl2va 会让成片首尾黑屏（镜01 成片开头/结尾就是这样来的），
# 所以生成后必须按体积 + 亮度再验一次，不达标就换 seed 重来。
MIN_GOOD_BYTES = 60 * 1024
MIN_MEAN = 6.0
FRAME_TRIES = 4           # 坏图最多重试次数（第 2 次起换 seed）
_FORCE = {"value": False}  # --force：无视已有素材强制重生成（首/尾帧需成对一致时用）

try:
    from PIL import Image as _PILImage
except Exception:  # noqa: BLE001  仅用于坏图判定，缺失时退化为体积判定
    _PILImage = None

POLL = 10
TIMEOUT = 1800  # 单张图 30 步 Qwen-2512，通常 40-120s，给 30 分钟宽裕


def first_save_dir():
    """ComfyUI input 中的首/尾帧子目录。"""
    return os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE)


def shot_wf(kind, sid):
    tag = "Fusion"
    fname = f"{kind}_1216x832_Qwen2512_{tag}_{sid}.json"
    p = os.path.join(SINGLES_DIR, fname)
    if os.path.isfile(p):
        return p
    return os.path.join(WF_DIR, fname)


def _out_dir():
    """ComfyUI output 中本次首/尾帧的子目录。"""
    return os.path.join(COMFY_ROOT, "output", IMG_SUBDIR, EPISODE)


def frame_prefix(kind, sid):
    """首/尾帧文件名前缀（kind: first/last）。"""
    return f"{EPISODE}_镜{sid}_{'首帧' if kind == 'first' else '尾帧'}_{SNAME}"


def canonical_name(kind, sid):
    """下游消费的固定素材名。

    build_fl2va_refs 与分镜 json 都按 `..._首帧_写实CG融合_00001_.png` 这种固定名引用，
    所以 input 里最终必须落到 _00001_ 上，不能是重生成后的 _00002_。
    """
    return frame_prefix(kind, sid) + "_00001_.png"


def _newest_png(d, kind, sid):
    """目录内该帧最新的一张 PNG。

    重生成时 ComfyUI 会递增序号（_00002_/_00003_），只挑 _00001_ 会拿到旧的坏图，
    所以一律按 mtime 取最新。
    """
    if not os.path.isdir(d):
        return None
    prefix = frame_prefix(kind, sid)
    hits = [f for f in os.listdir(d) if f.startswith(prefix) and f.endswith(".png")]
    return max(hits, key=lambda f: os.path.getmtime(os.path.join(d, f))) if hits else None


def find_shot_frame(kind, sid, tries=6, wait=5):
    """在 ComfyUI output/02_分镜/第1集/ 下找该帧最新产物，返回文件名，找不到返回 None。"""
    d = _out_dir()
    for _ in range(tries):
        fn = _newest_png(d, kind, sid)
        if fn:
            return fn
        time.sleep(wait)
    return None


def frame_png(kind, sid):
    """定位该帧文件：优先 output（本次新产物），回退 input（已有素材）。返回 (文件名, 绝对路径)。"""
    fn = find_shot_frame(kind, sid, tries=1, wait=0)
    if fn:
        return fn, os.path.join(_out_dir(), fn)
    in_d = os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE)
    fn = _newest_png(in_d, kind, sid)
    return (fn, os.path.join(in_d, fn)) if fn else (None, None)


def copy_to_input(kind, sid, filename):
    """把产物落到 ComfyUI input 的【规范名】上，并清掉同帧的旧序号副本。"""
    src = os.path.join(_out_dir(), filename)
    if not os.path.isfile(src):
        print(f"    [!!] 输出不存在: {src}")
        return False
    dst_dir = os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, canonical_name(kind, sid))
    prefix = frame_prefix(kind, sid)
    for f in os.listdir(dst_dir):
        if f.startswith(prefix) and f.endswith(".png") and f != os.path.basename(dst):
            os.remove(os.path.join(dst_dir, f))
    shutil.copy2(src, dst)
    print(f"    [copy] {filename} -> {dst}")
    return True


def frame_ok(path):
    """首/尾帧是否为「真画面」：体积达标 + 灰度均值不为 0（排除纯黑坏图）。"""
    if not os.path.isfile(path) or os.path.getsize(path) < MIN_GOOD_BYTES:
        return False
    if _PILImage is None:
        return True
    try:
        px = list(_PILImage.open(path).convert("L").resize((64, 64)).getdata())
    except Exception:  # noqa: BLE001
        return False
    return sum(px) / len(px) >= MIN_MEAN


def gen_frame(kind, sid, tries=FRAME_TRIES):
    """生成并校验一帧（首/尾），出现纯黑坏图自动换 seed 重试。

    返回 ComfyUI output 下可用的文件名（含 _00001_.png），连续失败返回 None。
    """
    wf = shot_wf("05_shotfirst" if kind == "first" else "06_shotlast", sid)
    label = "首帧" if kind == "first" else "尾帧"
    for i in range(max(1, tries)):
        seed = None if i == 0 else 1000 + i * 137   # 先按工作流自带 seed，其后换 seed 绕开坏样本
        pid = sw.do_submit(wf, seed=seed)
        rc = sw.do_watch(pid, poll=POLL, timeout=TIMEOUT)
        if rc != 0:
            print(f"  [{label}] 第{i + 1}次提交失败 rc={rc}（seed={seed or '默认'}）")
            continue
        fn = find_shot_frame(kind, sid, tries=3, wait=3)
        if not fn:
            print(f"  [{label}] 第{i + 1}次未在 output 定位到产物")
            continue
        p = os.path.join(_out_dir(), fn)
        if frame_ok(p):
            print(f"  [{label}] 校验通过：{fn}（{os.path.getsize(p) / 1024:.0f} KB，seed={seed or '默认'}）")
            return fn
        print(f"  [{label}] 第{i + 1}次产物疑似黑图（{os.path.getsize(p) / 1024:.0f} KB），换 seed 重试")
    print(f"  [{label}] 镜 {sid} 连续 {tries} 次未产出可用画面")
    return None


def _already(kind, sid):
    """首/尾帧是否已就绪【且可用】。

    fl2va 只吃 ComfyUI input 的素材，所以判据是「input 有一张非黑图」：output 被清理过
    而 input 还在时不必重跑（镜02 尾帧即此情况）。纯黑坏图一律视为未就绪。
    """
    if _FORCE["value"]:
        return False
    fn, p = frame_png(kind, sid)
    if not fn:
        return False
    if not frame_ok(p):
        print(f"    [检查] {fn} 体积/亮度异常（疑似黑图），将重新生成")
        return False
    return os.path.isfile(os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE, fn))


def run_one(sid):
    print(f"\n===== 镜 {sid} =====")
    # 0) 跳过已就绪且可用的镜（避免重复提交浪费算力）
    if _already("first", sid) and _already("last", sid):
        print("  [跳过] 首/尾帧均已就绪")
        return True

    # 1) 首帧：提交 -> 盯守 -> 黑图校验 -> 复制到 input
    if _already("first", sid):
        print("  [首帧] 已就绪，跳过生成")
    else:
        fn1 = gen_frame("first", sid)
        if not fn1 or not copy_to_input("first", sid, fn1):
            return False

    # 2) 尾帧（img2img 读取首帧，须与新首帧成对）
    if _already("last", sid):
        print("  [尾帧] 已就绪，跳过生成")
    else:
        fn2 = gen_frame("last", sid)
        if not fn2 or not copy_to_input("last", sid, fn2):
            return False
    print(f"  [完成] 镜 {sid}")
    return True


def run_video(args, shots):
    """首尾帧就绪后按流程续跑视频链（build -> 校验 -> 提交 -> 盯守 -> 归集）。

    等价于手动执行 pipeline_video.py --mode fl2va --shots ...，把「图 → 视频」两段
    收成一个入口，省掉中间那次临时接续脚本。
    """
    cmd = [sys.executable, os.path.join(HERE, "pipeline_video.py"),
           "--mode", args.video_mode, "--shots", ",".join(shots),
           "--poll", str(POLL), "--timeout", str(args.video_timeout)]
    if args.submit_real:
        cmd.append("--submit-real")
    if args.no_turbo:
        cmd.append("--no-turbo")
    if args.fast:
        cmd.append("--fast")                     # 加速档：低分出片 + 出片后本地超分
    if args.res:
        cmd += ["--res", args.res]
    print("\n== 续跑视频链 ==\n  $ " + " ".join(cmd))
    return cc.run(cmd, cwd=ROOT, echo=False)


def main():
    p = argparse.ArgumentParser(description="逐镜生图：05 首帧 -> 06 尾帧（可续跑视频成片）")
    p.add_argument("shots", nargs="*", help="镜号，如 01 02；缺省为全部（%s）" % " ".join(SHOTS))
    p.add_argument("--force", action="store_true",
                   help="无视已有素材强制重生成首/尾帧（首帧重做后尾帧需跟着重做才连贯）")
    p.add_argument("--then-video", action="store_true",
                   help="首尾帧全部就绪后直接续跑视频链（默认 fl2va；需 --submit-real 才真提交）")
    p.add_argument("--video-mode", choices=["i2v", "fl2va", "r2v"], default="fl2va",
                   help="视频模式（默认 fl2va 首尾帧）")
    p.add_argument("--submit-real", action="store_true", help="视频环节真正提交到 ComfyUI（消耗算力）")
    p.add_argument("--no-turbo", action="store_true", help="视频不插 turbo LoRA、保持 25 步")
    p.add_argument("--fast", action="store_true",
                   help="视频链加速档：低分辨率出片 + 出片后自动超分（透传 pipeline_video --fast）")
    p.add_argument("--res", default=None, help="视频链出片分辨率 WxH（透传 pipeline_video，如 864x480）")
    p.add_argument("--video-timeout", type=int, default=7200, help="视频盯守超时秒（默认 2h）")
    args = p.parse_args()

    # 生成任务都在本地 ComfyUI 上跑：先确保桌面端实例在线（离线则自动拉起）
    cc.require_service(auto_start=True)
    _FORCE["value"] = args.force

    shots = args.shots or SHOTS
    ok = 0
    for sid in shots:
        try:
            if run_one(sid):
                ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  [出错] 镜 {sid}: {e}")
    print(f"\n全部处理完成：成功 {ok}/{len(shots)}")
    if ok != len(shots):
        return 1
    if args.then_video:
        return run_video(args, shots)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
