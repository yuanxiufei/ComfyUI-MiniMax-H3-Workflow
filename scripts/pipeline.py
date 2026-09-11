# -*- coding: utf-8 -*-
"""小说→短剧 一键流水线：把 5 个 Skill 的产物串起来，收口到 build + submit。

链条（对应方案文档「环节全覆盖」）:
    script_rewriter → extractor → storyboard_breaker → voice_assigner
    → grid_prompt_generator → qc_storyboard（质量门禁，--qc-block 硬阻断）
    → build_new_workflows.py → submit_workflow.py → ComfyUI
    → pipeline_video.py（I2V/FL2VA/R2V 成片）→ 盯守落盘

「内容生成」环节（小说→剧本→分镜）本质是 LLM 语义任务，本脚本默认做**确定性数据驱动**：
从现有 剧本/ 数据推进 + 规范化 + 校验 + 落盘，并在缺内容时提示需要 LLM/手工。
`--llm` 预留接口（未配置 LLM 时跳过生成、只走数据层）。

自动化与稳健性增强（本次）:
  - `--validate`：在 extract / storyboard 后自动做数据契约预检（validate_db），
    把"结构/引用/枚举"问题提前到烧 GPU 前暴露；`--validate-block` 遇 P0 硬阻断。
  - `--retry N`：build / submit / video 每步失败自动重试 N 次（抗显存/网络瞬态失败）。
  - `--log <file>`：当前这次 pipeline 的输出同时写入日志文件，便于回溯。

用法:
    python scripts/pipeline.py --dryrun --all                 # 全链，结尾只离线转换（安全）
    python scripts/pipeline.py --step voice --dryrun          # 只跑音色绑定
    python scripts/pipeline.py --all --submit-real            # 真正提交到 ComfyUI（会自动确保桌面端实例在跑）
    python scripts/pipeline.py --all --validate --retry 2 --log output/pipeline.log
    python scripts/comfy_config.py --ensure                   # 只确认/拉起桌面端实例（幂等，可单独用）
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402
import comfy_config as cc  # noqa: E402   # 唯一配置源：host / 共享池根 / 实例根

WORKFLOWS = os.path.join(ROOT, "workflows")
BUILD = os.path.join(HERE, "build_new_workflows.py")
SUBMIT = os.path.join(HERE, "submit_workflow.py")
VIDEO = os.path.join(HERE, "pipeline_video.py")
CONSOLIDATE = os.path.join(HERE, "consolidate_workflows.py")

EPISODE = "第1集"


def _run(cmd, retry=1, task=""):
    """在项目根执行命令，失败可自动重试，返回 returncode。

    统一走 comfy_config.run：子进程注入 UTF-8 环境（PYTHONUTF8），日志不会再
    出现「父按 UTF-8 读、子按 GBK 写」的混杂乱码。retry 是允许执行的总次数。
    """
    return cc.run(cmd, cwd=ROOT, retry=retry, task=task or "步骤")


class _Tee:
    """把 print 同时写控制台和日志文件（仅当 --log 启用）。"""
    def __init__(self, f):
        self.f = f
    def write(self, s):
        sys.__stdout__.write(s)
        self.f.write(s)
    def flush(self):
        sys.__stdout__.flush()
        self.f.flush()


# ---------------------------------------------------------------
# 各步骤
# ---------------------------------------------------------------
def step_script_rewriter(args):
    """0/1 小说 → 格式化剧本。剧本已存在则跳过（--llm 强制重写）。"""
    print("\n== [step] script_rewriter 小说→剧本 ==")
    title, body = dt.read_episode_script(EPISODE)
    print(f"  原著: {title} ({len(body)} 字)")
    existing = dt.read_formatted_script(EPISODE)
    if existing.strip():
        print(f"  剧本已存在: {os.path.basename(dt.script_path(EPISODE))} ({len(existing)} 字) -> 跳过生成")
    else:
        print("  剧本缺失 -> 需用 LLM 生成。请运行 --llm 或手工写 01_剧本/第1集_剧本.md")


def step_extract(args):
    """2 角色/场景/道具 提取与规范化（确定性）。"""
    print("\n== [step] extractor 角色/场景/道具 ==")
    chars = dt.load_characters()
    scenes = dt.load_scenes()
    props = dt.load_props()
    if not (chars or scenes):
        print("  角色/场景库为空 -> 需先由 LLM 按 extractor 规范生成。")
        return
    # 规范化：补齐 voice 结构 / speaker_id / 随身道具数组化
    fixed = 0
    for c in chars:
        changed = False
        if "voice" not in c:
            c["voice"] = {"voice_id": dt.PENDING_VOICE, "voice_desc": "", "role_tag": ""}
            changed = True
        if not c.get("speaker_id"):
            used = {x.get("speaker_id", "") for x in chars}
            n = 1
            while f"S{n}" in used:
                n += 1
            c["speaker_id"] = f"S{n}"
            changed = True
        if "随身道具" in c and not isinstance(c["随身道具"], list):
            c["随身道具"] = []
            changed = True
        fixed += 1 if changed else 0
    if fixed:
        dt.save_characters(chars)
    print(f"  角色 {len(chars)}、场景 {len(scenes)}、道具 {len(props)}；规范化修复 {fixed} 处")


def step_storyboard(args):
    """3 分镜拆解与校验（确定性）。"""
    print("\n== [step] storyboard_breaker 分镜 ==")
    boards = dt.load_storyboards(EPISODE)
    if not boards:
        print("  分镜库为空 -> 需由 LLM 按 storyboard_breaker 规范生成。")
        return
    # 补默认字段
    fixed = 0
    for b in boards:
        for k, v in (("character_ids", []), ("speaker_id", ""),
                     ("scene_type", "single"), ("duration", 8)):
            if k not in b:
                b[k] = v
                fixed += 1
    dt.save_storyboards(EPISODE, boards)
    total = sum(b.get("duration", 0) for b in boards)
    print(f"  镜头 {len(boards)} 个，合计约 {total}s；补默认字段 {fixed} 处")


def step_voice(args):
    """4 voice_assigner 音色绑定（确定性：一角色一音色 + speaker_id 跨集锁定）。"""
    print("\n== [step] voice_assigner 音色绑定 ==")
    voices = dt.init_voice_library()
    print(f"  音色库 {len(voices)} 条: {[v['voice_id'] for v in voices]}")
    assigned = dt.auto_assign_voices()
    if assigned:
        for a in assigned:
            print(f"  [已绑定] {a['name']} ({a['id']}) voice={a['voice_id']} speaker={a['speaker_id']}")
    else:
        print("  (所有角色音色已锁定，无需再绑定)")
    issues = dt.validate_characters()
    pending = [it for it in issues if "音色未绑定" in it["problems"] or "缺 speaker_id" in it["problems"]]
    print(f"  音色/编号待处理: {len(pending)} 个角色")


def step_grid(args):
    """5 grid_prompt_generator 图片提示词（补齐统一风格前置段，幂等）。"""
    print("\n== [step] grid_prompt_generator 图片提示词 ==")
    n = dt.ensure_image_prompt()
    print(f"  补齐/重建 image_prompt: {n} 个角色")
    issues = dt.validate_characters()
    no_style = [it["name"] for it in issues if "缺统一风格前置段" in it["problems"]]
    print(f"  仍缺风格段的角色: {no_style if no_style else '无'}")


def step_qc(args):
    """5.5 分镜 P0/P1/P2 质量门禁（确定性）。

    默认只打印报告并落盘 output/<集>_分镜质检.md，不阻断；
    传 --qc-block 时若存在 P0（致命项）则返回 1，让全链在烧 GPU 前停下。
    """
    print("\n== [step] qc_storyboard 分镜质量门禁 ==")
    boards = dt.load_storyboards(EPISODE)
    if not boards:
        print("  分镜库为空 -> 跳过门禁（先跑 storyboard_breaker）")
        return None
    sys.path.insert(0, HERE)
    import qc_storyboard as qc  # noqa: E402

    report = qc.run_qc(EPISODE)
    qc.print_compact(report)
    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    out_md = args.qc_report or os.path.join(ROOT, "output", f"{EPISODE}_分镜质检.md")
    try:
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(qc.format_report(report))
        print(f"  质检报告已写: {out_md}")
    except OSError as e:
        print(f"  [!] 写质检报告失败: {e}")
    if report["counts"]["P0"] and getattr(args, "qc_block", False):
        print("\n[门禁阻断] 存在 P0 致命项（台词塞不下/单镜超长），建议先修分镜再出片。")
        print("  不放行则去掉 --qc-block 重跑（默认只报告不阻断）。")
        return 1
    return None


def step_validate(args, what=None):
    """5.6 数据契约预检（validate_db，零算力）：进 build/submit 前校验结构/枚举/引用。

    what: 'asset'（角色/场景/道具）或 'storyboard'（本集分镜）；None 校验全部。
    遇 P0 且 --validate-block 时返回 1 让全链停下。
    """
    print("\n== [step] validate_db 数据契约预检 ==")
    import validate_db as vdb  # noqa: E402
    dbs = None
    if what == "asset":
        dbs = ["characters", "scene", "props"]
    elif what == "storyboard":
        dbs = ["storyboard"]
    report = vdb.run_validate(EPISODE, dbs=dbs)
    vdb.print_compact(report)
    os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
    out_md = getattr(args, "validate_report", None) or os.path.join(
        ROOT, "output", f"{EPISODE}_数据契约校验.md")
    try:
        with open(out_md, "w", encoding="utf-8") as f:
            f.write(vdb.format_report(report))
        print(f"  契约校验报告已写: {out_md}")
    except OSError as e:
        print(f"  [!] 写契约校验报告失败: {e}")
    if report["counts"]["P0"] and getattr(args, "validate_block", False):
        print("\n[契约阻断] 存在 P0（结构/类型/引用/枚举致命项），建议先修数据再出片。")
        print("  若确认可忽略，去掉 --validate-block 或先跑 extract/storyboard 补齐。")
        return 1
    return None


def step_build(args):
    """6 构建全部工作流（调 build_new_workflows.py）+ 自动把单镜首/尾帧合并成整集 json。

    合并把 28×2=56 个重复结构的单镜 json 归并成"每集每类型一个 json"，
    避免 workflows/ 根目录堆积，且一次提交即可产出整集首帧/尾帧。
    """
    print("\n== [step] build_new_workflows.py ==")
    r = _run([sys.executable, BUILD], retry=args.retry, task="build")
    if r != 0:
        return r
    print("\n== [step] consolidate_workflows.py（合并单镜 -> 整集 json）==")
    return _run([sys.executable, CONSOLIDATE], retry=1, task="consolidate")


def step_submit(args):
    """7 提交/离线转换 生成的工作流到本地 ComfyUI。任一失败会累计并让全链停止。"""
    mode = "--submit" if args.submit_real else "--dryrun"
    print(f"\n== [step] submit_workflow.py ({mode}) ==")
    files = sorted(glob.glob(os.path.join(WORKFLOWS, "*.json")))
    if not files:
        print(f"  {WORKFLOWS} 下没有待提交的工作流 -> 先跑 build")
        return None
    print(f"  发现 {len(files)} 个工作流")
    failed = []
    for f in files:
        rc = _run([sys.executable, SUBMIT, mode, f], retry=args.retry, task="submit")
        if rc != 0:
            failed.append(os.path.basename(f))
    if failed:
        print(f"  [失败] {len(failed)} 个提交/转换失败: {', '.join(failed)}")
        return 1
    print("  全部提交/转换成功")
    return 0


def step_video(args):
    """8 视频成片：调 pipeline_video.py（build→校验→提交→盯守→落盘）。"""
    print(f"\n== [step] pipeline_video 视频成片 ({args.video_mode}) ==")
    cmd = [sys.executable, VIDEO, "--mode", args.video_mode]
    if args.video_shots:
        cmd += ["--shots", args.video_shots]
    if args.submit_real:
        cmd += ["--submit-real"]
    if args.no_watch:
        cmd += ["--no-watch"]
    if args.no_turbo:
        cmd += ["--no-turbo"]
    cmd += ["--poll", str(args.poll), "--timeout", str(args.timeout)]
    return _run(cmd, retry=args.retry, task="video")


STEPS = {
    "script_rewriter": step_script_rewriter,
    "extractor": step_extract,
    "storyboard_breaker": step_storyboard,
    "voice_assigner": step_voice,
    "grid_prompt_generator": step_grid,
    "qc": step_qc,
    "validate": step_validate,
    "build": step_build,
    "submit": step_submit,
    "video": step_video,
}

ORDER = ["script_rewriter", "extractor", "storyboard_breaker",
         "voice_assigner", "grid_prompt_generator", "qc", "build", "submit", "video"]


def _normalize_step(name):
    """环节短名 -> 标准名（也接受标准名原样）。"""
    alias = {"script": "script_rewriter", "extract": "extractor",
             "storyboard": "storyboard_breaker", "voice": "voice_assigner",
             "grid": "grid_prompt_generator", "qc": "qc", "video": "video",
             "validate": "validate"}
    v = alias.get(name, name)
    if v not in STEPS:
        raise argparse.ArgumentTypeError(f"未知环节: {name}")
    return v


def main():
    p = argparse.ArgumentParser(description="小说→短剧 流水线编排")
    p.add_argument("--step", type=_normalize_step,
                   help="只跑单个环节（支持别名 script/extract/storyboard/voice/grid/qc/validate）")
    p.add_argument("--all", action="store_true", help="按序跑完 9 步（含分镜质检与视频成片）")
    p.add_argument("--qc-block", action="store_true",
                   help="qc 步骤遇 P0 致命项即硬阻断整链（默认只报告不阻断）")
    p.add_argument("--qc-report", default=None, help="质检报告写盘路径（默认 output/第1集_分镜质检.md）")
    p.add_argument("--validate", action="store_true",
                   help="extract / storyboard 之后自动做数据契约预检（validate_db，零算力）")
    p.add_argument("--validate-block", action="store_true",
                   help="契约预检遇 P0 即硬阻断（默认仅报告）")
    p.add_argument("--validate-report", default=None, help="契约校验报告写盘路径")
    p.add_argument("--retry", type=int, default=1,
                   help="build/submit/video 每步失败重试次数（默认 1，抗显存/网络瞬态失败）")
    p.add_argument("--log", default=None,
                   help="把本次 pipeline 的 stdout 同时写入指定日志文件")
    p.add_argument("--llm", action="store_true", help="（预留）内容生成环节调用 LLM")
    p.add_argument("--submit-real", action="store_true",
                   help="submit 环节真正提交到 ComfyUI（默认仅 dryrun 离线转换）")
    p.add_argument("--dryrun", action="store_true", help="等价于不传 --submit-real（默认安全）")
    p.add_argument("--ensure-service", action="store_true",
                   help="先确认桌面端 ComfyUI 实例在跑，离线则自动拉起并等就绪"
                        "（--submit-real 时默认开启）")
    # video 阶段透传项
    p.add_argument("--video-mode", choices=["i2v", "fl2va", "r2v"], default="fl2va",
                   help="视频模式（默认 fl2va 首尾帧）")
    p.add_argument("--video-shots", default=None, help="逗号分隔镜号（默认全部）")
    p.add_argument("--no-watch", action="store_true", help="video 提交后不自动盯守")
    p.add_argument("--no-turbo", action="store_true",
                   help="video 不插 turbo LoRA、保持 25 步（i2v/fl2va）")
    p.add_argument("--poll", type=int, default=10, help="video 盯守轮询间隔秒")
    p.add_argument("--timeout", type=int, default=3600, help="video 盯守超时秒")
    args = p.parse_args()

    # --log：把 stdout 同时写入日志文件（回溯用）
    if args.log:
        os.makedirs(os.path.join(ROOT, "output"), exist_ok=True)
        logf = open(args.log, "a", encoding="utf-8")
        sys.stdout = _Tee(logf)
        print(f"\n[log] 本次 pipeline 输出写入 {args.log}")

    # 生成任务都跑在本地 ComfyUI 上：真实提交前先确认实例在跑，
    # 免得跑到 submit 环节才发现连不上、白等一轮长队列。
    if args.ensure_service or args.submit_real:
        print("\n== 检查 ComfyUI 桌面端实例 ==")
        cc.describe()
        cc.require_service(auto_start=True)

    try:
        if args.step:
            rc = STEPS[args.step](args)
            if rc:
                print(f"\n停止：步骤 {args.step} 失败 (rc={rc})")
                return rc
            return 0
        if args.all or not args.step:
            # 默认 --all（安全：submit 用 dryrun）
            total = len(ORDER)
            for i, name in enumerate(ORDER, 1):
                # 契约预检：内容生成环节落地后、进 build 前先校验数据层
                if args.validate:
                    pre = ("asset" if name == "extractor"
                           else ("storyboard" if name == "storyboard_breaker" else None))
                    if pre:
                        rc = step_validate(args, pre)
                        if rc is not None and rc != 0:
                            print(f"\n停止：契约预检（{name} 后）失败 (rc={rc})")
                            return rc
                rc = STEPS[name](args)
                if rc is not None and rc != 0:
                    print(f"\n停止：步骤 {name}（第 {i}/{total} 步）失败 (rc={rc})")
                    print("  后续步骤未运行。常见原因：素材缺失 / 模板损坏 / 显存不足；")
                    print("  可用 --no-turbo 降规格，或先补齐首尾帧/参考图再重跑。")
                    return rc
            print("\n流水线完成。")
            return 0
    finally:
        if args.log:
            try:
                logf.close()
            finally:
                sys.stdout = sys.__stdout__


if __name__ == "__main__":
    sys.exit(main())
