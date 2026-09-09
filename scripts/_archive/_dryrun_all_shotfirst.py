# -*- coding: utf-8 -*-
"""临时校验脚本：遍历 05_shotfirst 全部 21 镜工作流，转 API 并检查 node_errors。
零算力。仅在数据链路正确时才会继续提交。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import submit_workflow as sw

OUT = os.path.abspath(os.path.join(HERE, "..", "workflows"))
PREFIX = "05_shotfirst_1216x832_Qwen2512_Fusion_"


def main():
    obj_info = sw.get_object_info()
    files = sorted(f for f in os.listdir(OUT) if f.startswith(PREFIX) and f.endswith(".json"))
    print("发现首帧工作流:", len(files), "个\n")
    bad = []
    for f in files:
        path = os.path.join(OUT, f)
        wf = json.load(open(path, encoding="utf-8"))
        try:
            api = sw.ui_to_api(wf, obj_info)
        except Exception as e:
            print("[转换失败]", f, "->", repr(e)[:200])
            bad.append(f)
            continue
        # 静态图校验：转换后各 connection 输入引用的目标节点必须存在。
        # 注：ui_to_api 返回的是 prompt dict，不含 node_errors 键，因此无法在此检查服务端错误。
        errs = sw.validate_references(api)
        if errs:
            print("[引用缺失]", f)
            for e in errs:
                print("   ", e)
            bad.append(f)
        else:
            print("[OK]", f)
    print("\n=== 结果: 正常 %d / 全部 %d, 异常 %d ===" % (len(files) - len(bad), len(files), len(bad)))
    if bad:
        print("异常列表:")
        for f in bad:
            print("  ", f)


if __name__ == "__main__":
    main()
