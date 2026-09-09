# -*- coding: utf-8 -*-
"""清理 workflows/ 中重复的中文命名旧版 JSON，保留英文命名新版（build 脚本产物）。

规则：删除文件名含「横屏」的中文命名文件（01-10 号段的旧版），
保留：英文命名（01_char3view_* 等）与 11/12 Multishot（仅中文命名，需保留）。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "workflows"))

keep_prefixes = ("11_", "12_")
delete, keep = [], []
for name in sorted(os.listdir(OUT)):
    if not name.endswith(".json"):
        continue
    if "横屏" in name and not name.startswith(keep_prefixes):
        delete.append(name)
    else:
        keep.append(name)

print("=== 待删除（中文命名旧版）===")
for n in delete:
    print("  del", n)
print("=== 保留 ===")
for n in keep:
    print("  keep", n)

if "--yes" not in sys.argv:
    print("\n预览模式：加 --yes 参数实际删除")
else:
    for n in delete:
        os.remove(os.path.join(OUT, n))
    print("\n已删除 %d 个文件，剩余 %d 个。" % (len(delete), len(keep)))
