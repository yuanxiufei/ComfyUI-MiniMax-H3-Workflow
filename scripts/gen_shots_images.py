# -*- coding: utf-8 -*-
"""逐镜生图编排：提交 05 首帧 -> 盯守 -> 复制到 ComfyUI input -> 提交 06 尾帧 -> 盯守 -> 复制。

复用 submit_workflow 的 do_submit / do_watch（均返回可判定成功的 returncode）。
产物落盘到 collect_dir，再按 manifest 定位复制到 ComfyUI input/02_分镜/第1集/。
"""
import os
import sys
import json
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import submit_workflow as sw  # noqa: E402

# 常量（与 build_new_workflows / pipeline_video 保持一致）
COMFY_ROOT = r"D:\Comfy-Desktop\ComfyUI-Shared"
IMG_SUBDIR = "02_分镜"
EPISODE = "第1集"
WF_DIR = os.path.join(ROOT, "workflows")
ARTIFACTS = os.path.join(ROOT, "artifacts")
SHOTS = [str(i).zfill(2) for i in range(1, 13)]

SNAME = "写实CG融合"      # 与 build_new_workflows 保存前缀一致

POLL = 10
TIMEOUT = 1800  # 单张图 30 步 Qwen-2512，通常 40-120s，给 30 分钟宽裕


def first_save_dir():
    """ComfyUI input 中的首/尾帧子目录。"""
    return os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE)


def shot_wf(kind, sid):
    tag = "Fusion"
    fname = f"{kind}_1216x832_Qwen2512_{tag}_{sid}.json"
    return os.path.join(WF_DIR, fname)


def _out_dir():
    """ComfyUI output 中本次首/尾帧的子目录。"""
    return os.path.join(COMFY_ROOT, "output", IMG_SUBDIR, EPISODE)


def find_shot_frame(kind, sid, tries=6, wait=5):
    """在 ComfyUI output/02_分镜/第1集/ 下按确定文件名模式找刚生成的首/尾帧。

    kind: "first" -> 前缀 第1集_镜{sid}_首帧_写实CG融合；"last" -> ..._尾帧_写实CG融合
    返回匹配的完整文件名（含 _00001_.png），找不到返回 None。
    """
    prefix = f"{EPISODE}_镜{sid}_{'首帧' if kind == 'first' else '尾帧'}_{SNAME}"
    d = _out_dir()
    for _ in range(tries):
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.startswith(prefix) and f.endswith(".png"):
                    return f
        time.sleep(wait)
    return None


def copy_to_input(filename):
    """把产物从 ComfyUI output/02_分镜/第1集/<filename> 复制到 input 同子目录。"""
    src = os.path.join(_out_dir(), filename)
    if not os.path.isfile(src):
        print(f"    [!!] 输出不存在: {src}")
        return False
    dst_dir = os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, filename)
    shutil.copy2(src, dst)
    print(f"    [copy] {filename} -> {dst}")
    return True


def _already(kind, sid):
    """首/尾帧是否已就绪（output 与 input 里都有对应 PNG）。已就绪则跳过生成。"""
    png = find_shot_frame(kind, sid, tries=1, wait=0)
    if not png:
        return False
    return os.path.isfile(os.path.join(COMFY_ROOT, "input", IMG_SUBDIR, EPISODE, png))


def run_one(sid):
    print(f"\n===== 镜 {sid} =====")
    # 0) 跳过已就绪的镜（避免重复提交浪费算力）
    if _already("first", sid) and _already("last", sid):
        print("  [跳过] 首/尾帧均已就绪")
        return True

    # 1) 首帧：提交 -> 盯守 -> 定位 -> 复制到 input
    if _already("first", sid):
        print("  [首帧] 已就绪，跳过生成")
    else:
        wf1 = shot_wf("05_shotfirst", sid)
        pid1 = sw.do_submit(wf1)
        rc1 = sw.do_watch(pid1, poll=POLL, timeout=TIMEOUT)
        if rc1 != 0:
            print(f"  [首帧] 镜 {sid} 失败 rc={rc1}")
            return False
        fn1 = find_shot_frame("first", sid)
        if not fn1:
            print("  [首帧] 未在 output 定位到产物")
            return False
        if not copy_to_input(fn1):
            return False

    # 2) 尾帧（img2img 读取首帧）
    if _already("last", sid):
        print("  [尾帧] 已就绪，跳过生成")
    else:
        wf2 = shot_wf("06_shotlast", sid)
        pid2 = sw.do_submit(wf2)
        rc2 = sw.do_watch(pid2, poll=POLL, timeout=TIMEOUT)
        if rc2 != 0:
            print(f"  [尾帧] 镜 {sid} 失败 rc={rc2}")
            return False
        fn2 = find_shot_frame("last", sid)
        if not fn2:
            print("  [尾帧] 未在 output 定位到产物")
            return False
        if not copy_to_input(fn2):
            return False
    print(f"  [完成] 镜 {sid}")
    return True


def main():
    shots = sys.argv[1:] or SHOTS
    ok = 0
    for sid in shots:
        try:
            if run_one(sid):
                ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"  [出题] 镜 {sid}: {e}")
    print(f"\n全部处理完成：成功 {ok}/{len(shots)}")


if __name__ == "__main__":
    main()
