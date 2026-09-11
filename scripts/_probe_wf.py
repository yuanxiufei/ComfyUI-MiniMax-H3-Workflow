# -*- coding: utf-8 -*-
"""临时探针：对比单镜首帧工作流的完整拓扑（节点类型 + 连线 + widget 值）。用完即删。"""
import json
import os

SIDS = ["01", "02", "03", "04"]
DIR = "workflows/singles"


def load(sid):
    p = os.path.join(DIR, "05_shotfirst_1216x832_Qwen2512_Fusion_%s.json" % sid)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def fingerprint(d):
    nodes = {n["id"]: n for n in d["nodes"]}
    # 连线
    links = {}
    for l in d.get("links", []) or []:
        if isinstance(l, list) and len(l) >= 5:
            links[l[0]] = (l[1], l[2], l[3], l[4])
    out = {}
    for nid, n in nodes.items():
        wires = []
        for port in n.get("inputs", []) or []:
            lid = port.get("link")
            if lid is None or lid not in links:
                continue
            sn, ss, dn, ds = links[lid]
            st = nodes.get(sn, {}).get("type", "?")
            out_name = ""
            so = nodes.get(sn, {}).get("outputs", []) or []
            if ss < len(so):
                out_name = so[ss].get("name", "")
            wires.append("%s<-%s#%s(%s.%s)" % (port.get("name"), sn, st, out_name, ss))
        out[nid] = (n["type"], n.get("widgets_values"), sorted(wires))
    return nodes, out


data = {}
for sid in SIDS:
    nodes, fp = fingerprint(load(sid))
    data[sid] = fp
    print("=" * 70)
    print("##### 镜%s  (%d 节点)" % (sid, len(fp)))
    for nid in sorted(fp, key=int):
        ct, wv, wires = fp[nid]
        if isinstance(wv, list) and wv and isinstance(wv[0], str) and len(wv[0]) > 120:
            wv = ["<TEXT len=%d>" % len(wv[0])] + list(wv[1:])
        print("  #%s %s" % (nid, ct))
        print("      widget: %s" % (wv,))
        for w in wires:
            print("      in    : %s" % w)

print("\n" + "=" * 70)
print("##### 结构差异：镜02 vs 镜03")
a, b = data["02"], data["03"]
for nid in sorted(set(a) | set(b), key=int):
    ta = a.get(nid, ("(缺失)", None, []))
    tb = b.get(nid, ("(缺失)", None, []))
    if ta[0] != tb[0]:
        print("  #%s 类型不同: %s vs %s" % (nid, ta[0], tb[0]))
        continue
    if ta[2] != tb[2]:
        print("  #%s %s 连线不同:" % (nid, ta[0]))
        print("       02: %s" % ta[2])
        print("       03: %s" % tb[2])

print("\n##### 结构差异：镜01 vs 镜03")
a, b = data["01"], data["03"]
for nid in sorted(set(a) | set(b), key=int):
    ta = a.get(nid, ("(缺失)", None, []))
    tb = b.get(nid, ("(缺失)", None, []))
    if ta[0] != tb[0]:
        print("  #%s 类型不同: %s vs %s" % (nid, ta[0], tb[0]))
        continue
    if ta[2] != tb[2]:
        print("  #%s %s 连线不同:" % (nid, ta[0]))
        print("       01: %s" % ta[2])
        print("       03: %s" % tb[2])
