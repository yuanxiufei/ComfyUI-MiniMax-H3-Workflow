# -*- coding: utf-8 -*-
"""临时：提取《剑噬天下》主线开篇（剑之文明~气运）正文，作为编剧底本。用完即删。"""
import io

p = r"d:/code/voide/ComfyUI-MiniMax-H3-Workflow/剧本/00_小说原文/《剑噬天下》（精校全本）.txt"
with io.open(p, encoding="gbk", errors="ignore") as f:
    txt = f.read()

i = txt.find("第001回 剑之文明")
print("idx:", i)
# 打印剑之文明起 5000 字，覆盖 001~003 回
print(txt[i:i + 5000])
