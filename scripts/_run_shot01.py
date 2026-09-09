# -*- coding: utf-8 -*-
"""一键生成第一镜（镜01）：等首帧→复制→出尾帧→复制→出视频成片。跑完即得。"""
import os, sys, time, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import submit_workflow as SW

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY_OUT = r"D:\Comfy-Desktop\ComfyUI-Shared\output\02_分镜\第1集"
COMFY_IN = r"D:\Comfy-Desktop\ComfyUI-Shared\input\02_分镜\第1集"
WF = os.path.join(ROOT, "workflows")
COL = os.path.join(ROOT, "output")

FIRST = "第1集_镜1_首帧_写实CG融合_00001_.png"
LAST = "第1集_镜1_尾帧_写实CG融合_00001_.png"


def wait_file(name, timeout=1800):
    t0 = time.time()
    p = os.path.join(COMFY_OUT, name)
    while time.time() - t0 < timeout:
        if os.path.exists(p):
            return p
        time.sleep(10)
    raise SystemExit("[超时] 未产出 %s" % name)


def copy2input(name):
    os.makedirs(COMFY_IN, exist_ok=True)
    src = os.path.join(COMFY_OUT, name)
    dst = os.path.join(COMFY_IN, name)
    if os.path.exists(src) and not os.path.exists(dst):
        shutil.copy2(src, dst)
        print("[复制] -> input:", dst)


def submit_watch(wf, timeout, tag):
    pid = SW.do_submit(wf)
    print("[%s] prompt_id=%s" % (tag, pid))
    return SW.do_watch(pid, poll=12, timeout=timeout, collect_dir=COL)


def main():
    print("[1/4] 等待首帧生成...")
    fp = wait_file(FIRST)
    print("      首帧:", fp)
    copy2input(FIRST)

    print("[2/4] 生成尾帧...")
    r = submit_watch(os.path.join(WF, "06_shotlast_1216x832_Qwen2512_Fusion_01.json"), 1800, "尾帧")
    if r != 0:
        sys.exit("尾帧失败 rc=%s" % r)
    wait_file(LAST)
    copy2input(LAST)

    print("[3/4] 生成第一镜视频...")
    r = submit_watch(os.path.join(WF, "09_video_FL2VA_镜01_1280x736.json"), 3600, "视频")
    if r != 0:
        sys.exit("视频失败 rc=%s" % r)

    print("[4/4] 第一镜（镜01）已完成，成片已落盘至 %s（含 collect_manifest.json）" % COL)


if __name__ == "__main__":
    main()
