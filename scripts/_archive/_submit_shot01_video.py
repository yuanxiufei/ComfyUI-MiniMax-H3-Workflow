# -*- coding: utf-8 -*-
"""临时脚本：提交第一镜 I2V 视频工作流（避免命令行中文乱码）。"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw

WF = os.path.abspath(os.path.join(HERE, "..", "workflows", "08_video_I2V_镜01_1280x736.json"))


def main():
    sw.do_submit(WF)


if __name__ == "__main__":
    main()
