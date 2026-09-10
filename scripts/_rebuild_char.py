# -*- coding: utf-8 -*-
"""临时脚本：用服装签名(OUTFIT_SIGNATURE)重建全部角色的三视图 workflow json。
只重建 01_char3view_*，不动场景/视频模板，避免覆盖无关产物。
用法: python scripts/_rebuild_char.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_new_workflows as b  # noqa: E402


def main():
    b.build_char_assets(1216, 832, "写实CG融合", "Fusion", 0.5)
    print("角色三视图 workflow 重建完成（5 个角色，已注入服装签名）", flush=True)


if __name__ == "__main__":
    main()
