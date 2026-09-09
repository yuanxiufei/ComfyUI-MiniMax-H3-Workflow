# -*- coding: utf-8 -*-
"""把 build_new_workflows 生成的【逐镜首/尾帧 json】合并成"每集每类型一个 json"。

背景：main() 逐镜 write 出 05_shotfirst_*_01~28.json + 06_shotlast_*_01~28.json，
一个镜头一个文件，workflows/ 根目录堆几十个结构重复的 json，极难管理。

本脚本把同分辨率/同引擎/同风格后缀的一组单镜 json 归并成 1 个整集 json：
  - 共享一份 UNETLoader / CLIPLoader / VAELoader（模型只加载一次）；
  - 每个镜头是独立采样分支（各自 CLIPTextEncode(正/负) + (可选 LoRA) +
    KSampler + VAEDecode + SaveImage），输出文件名仍保留原"镜N_首帧_xxx"前缀，
    因此视频层 build_video_refs.py 的引用不受影响。

输出规则：
  05_shotfirst_1216x832_Qwen2512_Fusion_01~28.json  -> 05_shotfirst_1216x832_Qwen2512_Fusion.json
  06_shotlast_1216x832_Qwen2512_Fusion_01~28.json   -> 06_shotlast_1216x832_Qwen2512_Fusion.json

用法：
  python scripts/consolidate_workflows.py                # 扫描并合并，原单镜 json 移入 workflows/singles/
  python scripts/consolidate_workflows.py --keep-singles # 合并后保留原单镜 json 不动
  python scripts/consolidate_workflows.py --delete        # 合并后直接删除原单镜 json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
WF = os.path.join(ROOT, "workflows")

# 节点输入类型（决定 KSampler 各输入槽类型，用于 link[5]）
MODEL = "MODEL"
CLIP = "CLIP"
VAE = "VAE"
COND = "CONDITIONING"
LATENT = "LATENT"
IMAGE = "IMAGE"


# ---------------------------------------------------------------- 提取单镜数据
def _input(node, name):
    for i in node.get("inputs", []):
        if i.get("name") == name:
            return i
    return None


def extract_shot(doc):
    """从单个首帧/尾帧 json 解析出重建所需的关键字段。"""
    nodes = {n["id"]: n for n in doc["nodes"]}
    node5 = nodes.get(5)  # CLIPTextEncode 正向
    node6 = nodes.get(6)  # CLIPTextEncode 负向
    node7 = nodes.get(7)  # EmptySD3LatentImage / LoadImage
    node8 = nodes.get(8)  # KSampler
    node10 = nodes.get(10)  # SaveImage
    is_last = any(n["type"] == "LoadImage" for n in doc["nodes"])
    wv8 = node8.get("widgets_values", [])
    # wv8 = [seed, fixed, steps, cfg, sampler, scheduler, denoise]
    return {
        "is_last": is_last,
        "pos": node5["widgets_values"][0],
        "neg": node6["widgets_values"][0],
        "seed": wv8[0],
        "steps": wv8[2],
        "cfg": wv8[3],
        "sampler": wv8[4],
        "scheduler": wv8[5],
        "denoise": wv8[6],
        "width": node7["widgets_values"][0] if not is_last else None,
        "height": node7["widgets_values"][1] if not is_last else None,
        "init_image": node7["widgets_values"][0] if is_last else None,
        "prefix": node10["widgets_values"][0],
    }


def _loader_widget(doc, ntype):
    """取某个 loader 节点（UNETLoader/CLIPLoader/VAELoader）的 widgets_values。"""
    for n in doc["nodes"]:
        if n["type"] == ntype:
            return n["widgets_values"]
    return None


# ---------------------------------------------------------------- 合并构建
def _mk_node(nid, ntype, title, inputs, outputs, widgets=None, pos=(0, 0), size=(420, 120)):
    """构造一个标准 ComfyUI 前端节点。"""
    return {
        "id": nid, "type": ntype, "pos": [pos[0], pos[1]], "size": [size[0], size[1]],
        "flags": {}, "order": 0, "mode": 0, "inputs": inputs, "outputs": outputs,
        "properties": {"Node name for S&R": ntype},
        "widgets_values": widgets if widgets is not None else [], "title": title,
    }


def _io(name, type_, link=None):
    return {"name": name, "type": type_} if link is None else {"name": name, "type": type_, "link": link}


def _out(name, type_, links=None):
    return {"name": name, "type": type_, "links": links if links is not None else []}


def _spos(x, y):
    return (x, y)


def merge_shot_group(shot_docs, is_last, w, h, out_path):
    """把同一类型（首帧/尾帧）的 n 个单镜 json 合并成一个整集 json。

    共享 UNET(1)/CLIP(2)/VAE(3)；每镜独立分支。is_last 决定 latent 来源
    （首帧 EmptySD3LatentImage，尾帧 LoadImage+VAEEncode）。
    """
    shared_kind = "img2img" if is_last else "text2img"
    nodes, links = [], []
    nid = 1
    lid = 1

    def alloc():
        nonlocal nid
        cur = nid
        nid += 1
        return cur

    def add_link(a_node, a_out, b_node, b_in_idx, type_):
        nonlocal lid
        links.append([lid, a_node, a_out, b_node, b_in_idx, type_])
        lid += 1
        return lid - 1

    # ---- 共享模型加载节点 ----
    unet = _mk_node(alloc(), "UNETLoader", "Qwen-2512 DiT",
                    [_io("unet_name", "COMBO"), _io("weight_dtype", "COMBO")],
                    [_out("MODEL", MODEL)],
                    widgets=shot_docs[0]["unet"], pos=(0, 0), size=(360, 82))
    clip = _mk_node(alloc(), "CLIPLoader", "CLIP",
                    [_io("clip_name", "COMBO"), _io("type", "COMBO"), _io("device", "COMBO")],
                    [_out("CLIP", CLIP)],
                    widgets=shot_docs[0]["clip"], pos=(420, 0), size=(360, 106))
    vae = _mk_node(alloc(), "VAELoader", "VAE",
                   [_io("vae_name", "COMBO")],
                   [_out("VAE", VAE)],
                   widgets=shot_docs[0]["vae"], pos=(840, 0), size=(360, 58))
    nodes.extend([unet, clip, vae])

    # ---- 每个镜头一个分支 ----
    for m, s in enumerate(shot_docs):
        col = 1280 + (m % 3) * 0  # 让分支错落，避免重叠
        # 正向/负向编码（共享 CLIP）
        pos_id = alloc()
        posn = _mk_node(pos_id, "CLIPTextEncode", "正向提示词",
                        [_io("clip", CLIP, None), _io("text", "STRING")],
                        [_out("CONDITIONING", COND)],
                        widgets=[s["pos"]], pos=(420, 180 + m * 60), size=(420, 180))
        pos_link = add_link(clip["id"], 0, posn["id"], 0, CLIP)
        posn["inputs"][0]["link"] = pos_link
        neg_id = alloc()
        negn = _mk_node(neg_id, "CLIPTextEncode", "负面提示词",
                        [_io("clip", CLIP, None), _io("text", "STRING")],
                        [_out("CONDITIONING", COND)],
                        widgets=[s["neg"]], pos=(420, 480 + m * 60), size=(420, 160))
        # CLIPLoader 只有第 0 个输出，正/负向都连它（一个输出可接多输入）
        neg_link = add_link(clip["id"], 0, negn["id"], 0, CLIP)
        negn["inputs"][0]["link"] = neg_link

        # LoRA（仅当该镜用 lora）
        model_in = unet
        if s.get("use_lora"):
            lora_id = alloc()
            loran = _mk_node(lora_id, "LoraLoaderModelOnly", "角色 LoRA",
                             [_io("model", MODEL, None), _io("lora_name", "COMBO"),
                              _io("strength_model", "FLOAT")],
                             [_out("MODEL", MODEL)],
                             widgets=s["lora"], pos=(0, 160 + m * 60), size=(360, 82))
            lo_link = add_link(unet["id"], 0, loran["id"], 0, MODEL)
            loran["inputs"][0]["link"] = lo_link
            model_in = loran
            nodes.append(loran)

        # latent 生成
        if not is_last:
            lat_id = alloc()
            latn = _mk_node(lat_id, "EmptySD3LatentImage", "空潜空间 16:9",
                            [_io("width", "INT"), _io("height", "INT"), _io("batch_size", "INT")],
                            [_out("LATENT", LATENT)],
                            widgets=[s["width"], s["height"], 1],
                            pos=(840, 160 + m * 60), size=(280, 106))
            lat_link = None
            nodes.append(latn)
        else:
            load_id = alloc()
            loadn = _mk_node(load_id, "LoadImage", "首帧底图",
                             [{"localized_name": "图像", "name": "image", "type": "COMBO",
                               "widget": {"name": "image"}, "link": None},
                              {"localized_name": "选择文件上传", "name": "upload", "type": "IMAGEUPLOAD",
                               "widget": {"name": "upload"}, "link": None}],
                             [{"localized_name": "图像", "name": "IMAGE", "type": IMAGE, "links": []},
                              {"localized_name": "遮罩", "name": "MASK", "type": "MASK", "links": None}],
                             widgets=[s["init_image"], "image"], pos=(840, 160 + m * 60), size=(280, 314))
            ve_id = alloc()
            ven = _mk_node(ve_id, "VAEEncode", "VAE Encode", [],
                           [_out("LATENT", LATENT)],
                           widgets=[], pos=(1160, 160 + m * 60), size=(210, 46))
            ve_img_link = add_link(loadn["id"], 0, ven["id"], 0, IMAGE)
            ve_vae_link = add_link(vae["id"], 0, ven["id"], 1, VAE)
            ven["inputs"] = [_io("pixels", IMAGE, ve_img_link), _io("vae", VAE, ve_vae_link)]
            nodes.extend([loadn, ven])
            latn = ven

        # KSampler（model 源 + 正负 + latent）
        sam_id = alloc()
        samn = _mk_node(sam_id, "KSampler", "KSampler",
                        [_io("model", MODEL, None), _io("positive", COND, None),
                         _io("negative", COND, None), _io("latent_image", LATENT, None),
                         _io("seed", "INT"), _io("steps", "INT"), _io("cfg", "FLOAT"),
                         _io("sampler_name", "COMBO"), _io("scheduler", "COMBO"),
                         _io("denoise", "FLOAT")],
                        [_out("LATENT", LATENT)],
                        widgets=[s["seed"], "fixed", s["steps"], s["cfg"],
                                 s["sampler"], s["scheduler"], s["denoise"]],
                        pos=(1160, 240 + m * 60), size=(380, 262))
        m_link = add_link(model_in["id"], 0, samn["id"], 0, MODEL)
        p_link = add_link(posn["id"], 0, samn["id"], 1, COND)
        n_link = add_link(negn["id"], 0, samn["id"], 2, COND)
        lat_link = add_link(latn["id"], 0, samn["id"], 3, LATENT)
        samn["inputs"][0]["link"] = m_link
        samn["inputs"][1]["link"] = p_link
        samn["inputs"][2]["link"] = n_link
        samn["inputs"][3]["link"] = lat_link

        # VAEDecode
        dec_id = alloc()
        decn = _mk_node(dec_id, "VAEDecode", "VAE Decode", [],
                        [_out("IMAGE", IMAGE)],
                        widgets=[], pos=(1500, 240 + m * 60), size=(210, 46))
        dec_s_link = add_link(samn["id"], 0, decn["id"], 0, LATENT)
        dec_v_link = add_link(vae["id"], 0, decn["id"], 1, VAE)
        decn["inputs"] = [_io("samples", LATENT, dec_s_link), _io("vae", VAE, dec_v_link)]

        # SaveImage
        sav_id = alloc()
        savn = _mk_node(sav_id, "SaveImage", "保存图片",
                        [_io("images", IMAGE, None), _io("filename_prefix", "STRING")],
                        [],
                        widgets=[s["prefix"]], pos=(1500, 340 + m * 60), size=(380, 120))
        sav_link = add_link(decn["id"], 0, savn["id"], 0, IMAGE)
        savn["inputs"][0]["link"] = sav_link

        # 修正正/负向节点输出 links（它们没有真正的下游占位，直接指向 KSampler）
        posn["outputs"][0]["links"] = [p_link]
        negn["outputs"][0]["links"] = [n_link]

        nodes.extend([posn, negn])
        if s.get("use_lora"):
            pass  # loran 已在上文 append
        nodes.append(samn)
        nodes.append(decn)
        nodes.append(savn)

    # ---- 归一化：让每个节点 outputs[].links 与全局 links 数组一致 ----
    # ComfyUI 前端依赖 outputs[].links 来显示连线；submit 转换也据此解析。
    by_id = {n["id"]: n for n in nodes}
    for n in nodes:
        for o in n.get("outputs", []):
            o["links"] = []
    for lk in links:
        na = by_id.get(lk[1])
        if na and lk[2] < len(na.get("outputs", [])):
            na["outputs"][lk[2]]["links"].append(lk[0])

    return {
        "last_node_id": nid - 1,
        "last_link_id": lid - 1,
        "nodes": nodes,
        "links": links,
        "groups": [], "config": {}, "extra": {}, "version": 0.4,
    }


def build_index(shot_docs):
    """给每个单镜 doc 附加统一的 loader widgets 与 use_lora 信息。"""
    base = shot_docs[0]["_doc"]
    unet = _loader_widget(base, "UNETLoader")
    clip = _loader_widget(base, "CLIPLoader")
    vae = _loader_widget(base, "VAELoader")
    for s in shot_docs:
        s["unet"] = unet
        s["clip"] = clip
        s["vae"] = vae
        lora_nodes = [n for n in s["_doc"]["nodes"] if n["type"] == "LoraLoaderModelOnly"]
        if lora_nodes:
            s["use_lora"] = True
            s["lora"] = lora_nodes[0]["widgets_values"]
        else:
            s["use_lora"] = False
            s["lora"] = []
    return shot_docs


def scan_and_merge(target=None, keep_singles=False, delete_singles=False):
    """扫描 workflows/ 下 05_shotfirst_*.json 与 06_shotlast_*.json，按组归并。"""
    files = sorted(glob.glob(os.path.join(WF, "05_shotfirst_*.json")))
    files += sorted(glob.glob(os.path.join(WF, "06_shotlast_*.json")))
    if target:
        files = [f for f in files if target in os.path.basename(f)]
    # 分组键：去掉尾部镜号(_NN) 得到类型+规格键
    groups = {}
    for f in files:
        b = os.path.basename(f)
        m = re.match(r"^(.*?)_(\d{2})\.json$", b)
        if not m:
            continue
        key = m.group(1)
        groups.setdefault(key, []).append(f)
    if not groups:
        print("[consolidate] 无待合并的单镜 json")
        return
    for key, gs in sorted(groups.items()):
        gs_sorted = sorted(gs)
        docs = []
        for p in gs_sorted:
            with open(p, encoding="utf-8") as fh:
                doc = json.load(fh)
            s = extract_shot(doc)
            s["_doc"] = doc
            docs.append(s)
        docs = build_index(docs)
        is_last = docs[0]["is_last"]
        out = os.path.join(WF, key + ".json")
        merged = merge_shot_group(docs, is_last, 1216, 832, out)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(merged, fh, ensure_ascii=False, indent=2)
        n = len(docs)
        print(f"[consolidate] {os.path.basename(out)} <- {n} 个单镜 -> 整集 json")
        # 处理原单镜
        if delete_singles:
            for p in gs_sorted:
                os.remove(p)
        elif not keep_singles:
            singles_dir = os.path.join(WF, "singles")
            os.makedirs(singles_dir, exist_ok=True)
            for p in gs_sorted:
                shutil.move(p, os.path.join(singles_dir, os.path.basename(p)))
            print(f"          原单镜已移至 workflows/singles/（--keep-singles 可保留原位，--delete 删除）")


def main():
    ap = argparse.ArgumentParser(description="合并逐镜首/尾帧工作流为整集 json")
    ap.add_argument("--target", help="只处理文件名含 target 的组（如 1216x832）")
    ap.add_argument("--keep-singles", action="store_true", help="合并后保留原单镜 json")
    ap.add_argument("--delete", action="store_true", help="合并后删除原单镜 json")
    args = ap.parse_args()
    scan_and_merge(args.target, keep_singles=args.keep_singles, delete_singles=args.delete)


if __name__ == "__main__":
    main()
