# -*- coding: utf-8 -*-
"""重跑本集的「盯守 + 自动落盘」启动器。

为什么要单独一个启动器：盯守要跑数小时，需要在后台脱离当前 shell 运行；
而产物目录含中文（output/视频/第1集/r2v），直接在命令行传中文容易被控制台
代码页破坏，故这里用 \\u 转义写成纯 ASCII 源码，默认值在脚本内拼好。

用法:
  python scripts/_watch_episode.py --pid <prompt_id> [--timeout 21000] [--collect-dir <目录>]
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_COLLECT = os.path.join(ROOT, "output", "\u89c6\u9891", "\u7b2c1\u96c6", "r2v")


def main():
    ap = argparse.ArgumentParser(description="盯守 prompt_id，完成后把产物落盘到本集成片目录")
    ap.add_argument("--pid", required=True, help="要盯守的 prompt_id")
    ap.add_argument("--poll", type=int, default=15, help="轮询间隔秒")
    ap.add_argument("--timeout", type=int, default=21000, help="盯守超时秒")
    ap.add_argument("--collect-dir", default=DEFAULT_COLLECT, help="产物落盘目录")
    a = ap.parse_args()
    cmd = [sys.executable, os.path.join(ROOT, "scripts", "submit_workflow.py"),
           "--watch", a.pid, "--poll", str(a.poll), "--timeout", str(a.timeout),
           "--collect-dir", a.collect_dir]
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
