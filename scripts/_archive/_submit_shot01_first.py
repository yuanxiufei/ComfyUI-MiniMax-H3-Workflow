# -*- coding: utf-8 -*-
"""临时脚本：提交镜01 首帧重生成（1280x736），避免命令行中文乱码。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw

WF = os.path.abspath(os.path.join(HERE, "..", "workflows", "05_shotfirst_1216x832_Qwen2512_Fusion_01.json"))


def main():
    sw.do_submit(WF)


if __name__ == "__main__":
    main()
