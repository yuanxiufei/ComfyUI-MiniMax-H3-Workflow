# -*- coding: utf-8 -*-
"""临时诊断：汇总分镜图的「内嵌工作流参数 + 实际亮度」，定位黑图（用完即删）。

用法：
  python scripts/_diag_black.py <目录或png...> [--full]
"""
import glob
import json
import os
import sys

import comfy_config  # noqa: F401
from PIL import Image


def mean_of(path):
    im = Image.open(path).convert("L")
    px = im.resize((64, 64)).getdata()
    return sum(px) / len(px)


def probe(path):
    im = Image.open(path)
    nodes = json.loads(im.info.get("prompt") or "{}")
    def find(t):
        return next((n for n in nodes.values() if n.get("class_type") == t), None)

    lora = find("LoraLoaderModelOnly") or {"inputs": {}}
    ks = find("KSampler") or {"inputs": {}}
    sv = find("SaveImage") or {"inputs": {}}
    pos = find("CLIPTextEncode") or {"inputs": {}}
    return {
        "file": os.path.basename(path),
        "mean": mean_of(path),
        "strength": lora["inputs"].get("strength_model"),
        "lora": (lora["inputs"].get("lora_name") or "")[:34],
        "seed": ks["inputs"].get("seed"),
        "steps": ks["inputs"].get("steps"),
        "cfg": ks["inputs"].get("cfg"),
        "prefix": sv["inputs"].get("filename_prefix"),
        "text": (pos["inputs"].get("text") or ""),
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    full = "--full" in sys.argv
    paths = []
    for a in args:
        paths.extend(sorted(glob.glob(os.path.join(a, "*.png"))) if os.path.isdir(a) else [a])
    rows = [probe(p) for p in paths]
    for r in rows:
        print("%-42s mean=%6.1f strength=%-4s steps=%-3s cfg=%-4s seed=%s" % (
            r["file"], r["mean"], r["strength"], r["steps"], r["cfg"], r["seed"]))
        print("      lora=%s" % r["lora"])
        print("      prefix=%s" % r["prefix"])
        print("      text=%s" % (r["text"] if full else r["text"][:150].replace("\n", "\\n")))
        if full:
            print("      textlen=%d md5=%s" % (len(r["text"]), __import__("hashlib").md5(r["text"].encode()).hexdigest()[:12]))


if __name__ == "__main__":
    main()
