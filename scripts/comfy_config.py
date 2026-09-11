# -*- coding: utf-8 -*-
"""ComfyUI 连接与路径的**唯一配置源**（对应当前在用的「桌面端那份安装」）。

约定：本项目所有需要算力的任务（角色三视图 / 场景 / 首尾帧 / 视频 / 超分）一律
提交到本地 ComfyUI 执行；脚本只做「拼工作流 → 提交 → 盯守 → 归集」。
既然算力都在 ComfyUI，host 与 input/output 目录就只能有一处定义——本文件。
各脚本从这里 import，不要再各写一份，否则会出现「校验用的根」与「build 模板
用的根」不一致（曾出现过：build_multishot_workflows 指向另一套安装目录）。

配置优先级：环境变量 > 本文件默认值

    COMFY_HOST            服务地址      默认 http://127.0.0.1:8188
    COMFY_ROOT            共享池根      默认 D:\\Comfy-Desktop\\ComfyUI-Shared
    COMFY_INSTANCE_ROOT   桌面端安装根  默认 ...\\ComfyUI-Installs\\ComfyUI-MiniMax-H3-Workflow\\ComfyUI
    COMFY_MODEL_PATHS_YAML 模型路径 yaml（仅启动脚本用）

共享池（COMFY_ROOT）下同时放着实例的 input/ output/ custom_nodes/，
_start_comfyui.ps1 以 --input-directory / --output-directory 把它们指给实例。

命令行自检：
    python scripts/comfy_config.py            # 打印解析结果 + 服务状态
    python scripts/comfy_config.py --ensure   # 服务离线则拉起实例（带 SageAttention）并等就绪
    python scripts/comfy_config.py --start    # 强制重启实例

编码约定（全项目统一在这里实现，别处不要重复）：
    setup_stdio()   本进程 stdout/stderr 统一 UTF-8（import 本模块即自动调用）
    child_env()     子进程环境：PYTHONUTF8=1 / PYTHONIOENCODING=utf-8
    run()           子进程统一执行入口：UTF-8 环境 + 失败重试
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

def setup_stdio(errors="replace"):
    """把本进程 stdout/stderr 统一为 UTF-8（唯一的编码策略入口）。

    Windows 下 Python 默认按系统区域编码（cp936）写 stdio：脚本被 `> log.txt`
    或启动脚本重定向到文件时，中文就变成乱码，而读日志的工具按 UTF-8 解析。
    各脚本只要 `import comfy_config` 即自动生效——不要再在各自文件里各写一份
    reconfigure（曾因此让同一份日志里 GBK/UTF-8 混杂）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors=errors)
        except Exception:  # noqa: BLE001
            pass


setup_stdio()

DEFAULT_HOST = "http://127.0.0.1:8188"
DEFAULT_SHARED_ROOT = r"D:\Comfy-Desktop\ComfyUI-Shared"
DEFAULT_INSTANCE_ROOT = r"D:\Comfy-Desktop\ComfyUI-Installs\ComfyUI-MiniMax-H3-Workflow\ComfyUI"

HOST = os.environ.get("COMFY_HOST", DEFAULT_HOST).rstrip("/")
SHARED_ROOT = os.environ.get("COMFY_ROOT", DEFAULT_SHARED_ROOT).rstrip("\\/")
INSTANCE_ROOT = os.environ.get("COMFY_INSTANCE_ROOT", DEFAULT_INSTANCE_ROOT).rstrip("\\/")

INPUT_DIR = os.path.join(SHARED_ROOT, "input")
OUTPUT_DIR = os.path.join(SHARED_ROOT, "output")
CUSTOM_NODES_DIR = os.path.join(SHARED_ROOT, "custom_nodes")
EXAMPLES_DIR = os.path.join(CUSTOM_NODES_DIR, "ComfyUI_MiniMaxH3_Director", "example_workflows")
MAIN_PY = os.path.join(INSTANCE_ROOT, "main.py")

START_PS1 = os.path.join(HERE, "_start_comfyui.ps1")
START_BAT = os.path.join(HERE, "_start_comfyui.bat")
ERR_LOG = os.path.join(HERE, "_comfyui.err.log")

HTTP_TIMEOUT = 5
WAIT_TIMEOUT = 240   # 拉起到就绪的宽裕上限（冷启动加载模型较慢）


def child_env():
    """子进程环境：强制子 Python 的 stdio 走 UTF-8。

    父进程已统一 UTF-8 输出；若子进程仍按 cp936 写，同一份日志里就会两种编码
    混杂（父按 UTF-8 读会把子进程中文显示成乱码）。所有子进程都从本函数取 env。
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"          # Python UTF-8 模式：stdio 直接 UTF-8
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run(cmd, cwd=None, retry=1, task="", echo=True, env=None, **kwargs):
    """统一的子进程执行入口：UTF-8 环境 + 失败重试，返回 returncode。

    retry 是「允许执行的总次数」(>=1)。子进程输出直接继承本进程 stdio 透传，
    所以这里不做捕获/解码，也就不会出现「父按 UTF-8 解 GBK」的乱码或解码异常。
    """
    if echo:
        print("  $", " ".join(str(c) for c in cmd))
    env = env or child_env()
    last = 1
    for i in range(max(1, retry)):
        try:
            r = subprocess.run(cmd, cwd=cwd, env=env, **kwargs)
        except OSError as e:
            print("  [!] %s 无法启动：%s" % (task or "子进程", e))
            return 1
        if r.returncode == 0:
            return 0
        last = r.returncode
        if i < retry - 1:
            print("  [!] %s 失败(rc=%d)，第 %d/%d 次重试..."
                  % (task or "步骤", r.returncode, i + 2, retry))
    return last


def is_up(timeout=HTTP_TIMEOUT):
    """服务是否可连（GET /system_stats）。"""
    try:
        with urllib.request.urlopen(HOST + "/system_stats", timeout=timeout) as r:
            json.loads(r.read().decode("utf-8"))
        return True
    except Exception:  # noqa: BLE001
        return False


def describe():
    """打印当前生效的实例信息与连通状态（排查「连错实例 / 找错目录」用）。"""
    print("[comfy] host        = %s" % HOST)
    print("[comfy] 共享池根     = %s" % SHARED_ROOT)
    print("[comfy] input       = %s" % INPUT_DIR)
    print("[comfy] output      = %s" % OUTPUT_DIR)
    print("[comfy] 实例安装根   = %s" % INSTANCE_ROOT)
    print("[comfy] 实例 main.py = %s" % ("存在" if os.path.exists(MAIN_PY) else "缺失！"))
    print("[comfy] 服务状态     = %s" % ("在线" if is_up() else "离线"))


def wait_up(timeout=WAIT_TIMEOUT, interval=3, verbose=True):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if is_up():
            if verbose:
                print("[comfy] 服务已就绪（%s，耗时 %.0fs）" % (HOST, time.time() - t0))
            return True
        if verbose:
            print("  ... 等待服务就绪 %ds" % int(time.time() - t0))
        time.sleep(interval)
    return False


def start_service(verbose=True):
    """调 _start_comfyui.ps1 重启桌面端实例（带 SageAttention），幂等。"""
    if not os.path.exists(START_PS1):
        raise FileNotFoundError("找不到启动脚本：%s" % START_PS1)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", START_PS1]
    if verbose:
        print("[comfy] $ %s" % " ".join(cmd))
    # 带上 UTF-8 环境：实例继承后日志也按 UTF-8 写（ps1 里亦有同样设置，双保险）
    return subprocess.run(cmd, cwd=PROJECT_ROOT, env=child_env()).returncode


def ensure_service(auto_start=True, timeout=WAIT_TIMEOUT, verbose=True):
    """在线直接 True；离线且允许则拉起实例并等就绪，返回最终是否在线。"""
    if is_up():
        if verbose:
            print("[comfy] 服务在线：%s" % HOST)
        return True
    if not auto_start:
        if verbose:
            print("[comfy] 服务离线，且未允许自动拉起：%s" % HOST)
        return False
    if verbose:
        print("[comfy] 服务离线，正在拉起桌面端实例（带 SageAttention）...")
    rc = start_service(verbose=verbose)
    ok = wait_up(timeout=timeout, verbose=verbose)
    if not ok and verbose:
        print("[comfy] 拉起失败（启动脚本返回码=%s），看错误日志尾部：%s" % (rc, ERR_LOG))
    return ok


def require_service(auto_start=True, timeout=WAIT_TIMEOUT, verbose=True):
    """确保服务在线，否则给出可照做的修复指引后退出。

    放在「真正提交」之前调用，避免跑到半途才发现连不上、白等一轮队列。
    """
    if ensure_service(auto_start=auto_start, timeout=timeout, verbose=verbose):
        return True
    print("\n[comfy] 无法连接 ComfyUI（%s）。任选一种方式：")
    print("  1) 自动拉起（带 SageAttention）：python scripts/comfy_config.py --ensure")
    print("  2) 一键启动脚本：scripts\\_start_comfyui.bat")
    print("  3) 若桌面端已启动：确认端口是 8188、未被别的进程占用")
    print("  错误日志：%s" % ERR_LOG)
    raise SystemExit(1)


def main():
    p = argparse.ArgumentParser(description="ComfyUI 配置自检 / 桌面端实例拉起")
    p.add_argument("--ensure", action="store_true", help="服务离线则自动拉起并等就绪")
    p.add_argument("--start", action="store_true", help="强制重启实例（带 SageAttention）")
    p.add_argument("--timeout", type=int, default=WAIT_TIMEOUT, help="等待就绪超时秒（默认 %d）" % WAIT_TIMEOUT)
    args = p.parse_args()

    describe()
    if args.start:
        start_service()
        return 0 if wait_up(timeout=args.timeout) else 1
    if args.ensure:
        return 0 if ensure_service(auto_start=True, timeout=args.timeout) else 1
    return 0 if is_up() else 1


if __name__ == "__main__":
    raise SystemExit(main())
