# -*- coding: utf-8 -*-
"""4x-UltraSharp 视频超分：把低清单镜 mp4 超分到 1080P 出片链路。

原理：ComfyUI 端用 4x-UltraSharp(UpscaleModelLoader+ImageUpscaleWithModel)逐帧超分，
再 ImageScale 缩放到目标分辨率(默认 1920x1080)，SaveImage 输出；脚本按帧号收集，
最后 ffmpeg 按序合成 mp4。逐帧提交，规避 DatasetLoad 的路径限制/乱序/OOM。

用法：
    python scripts/upscale_video.py --input <in.mp4> --out <out.mp4> [--fps 30] [--frames N]
    python scripts/upscale_video.py --image <one.png>                  # 单图超分测试
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

# 超分进度带中文：编码统一交给 import 时的 comfy_config.setup_stdio()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comfy_config as cc  # noqa: E402   # 唯一配置源：host / 共享池根

HOST = cc.HOST          # --host 仍可覆盖
# ComfyUI 可见的 input/output 根目录（共享目录），用于放待超分帧 / 读结果。
# 可用 --input-root --output-root 覆盖。
DEFAULT_INPUT_ROOT = cc.INPUT_DIR
DEFAULT_OUTPUT_ROOT = cc.OUTPUT_DIR
MODEL_NAME = "4x-UltraSharp.pth"

TIMEOUT = 30


def _post(path, data):
    req = urllib.request.Request(HOST + path, data=json.dumps(data).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _get(path):
    with urllib.request.urlopen(HOST + path, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def probe_fps(inp):
    """用 ffmpeg -i 解析帧率(近似)。返回 float 或 None。"""
    ff = ffmpeg_exe()
    p = subprocess.run([ff, "-hide_banner", "-i", inp], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    txt = (p.stderr or "") + (p.stdout or "")
    import re
    hits = re.findall(r"([\d.]+)\s*fps", txt)
    if hits:
        return float(hits[-1])
    return None


def probe_dims(inp):
    """解析分辨率 (w,h)。"""
    ff = ffmpeg_exe()
    p = subprocess.run([ff, "-hide_banner", "-i", inp], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    txt = (p.stderr or "") + (p.stdout or "")
    import re
    m = re.search(r"(\d{2,5})x(\d{2,5})", txt)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def extract_frames(inp, outdir, fps, frames=None):
    """用固定 fps 抽帧到 outdir/f%05d.png。frames: 可选，只抽前 N 帧(str 传给 ffmpeg)。
    返回抽到帧文件名列表(排序)。"""
    os.makedirs(outdir, exist_ok=True)
    vf = "fps=%s" % fps
    cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-i", inp, "-vf", vf,
           "-start_number", "1", os.path.join(outdir, "f%05d.png")]
    if frames:
        cmd = [ffmpeg_exe(), "-hide_banner", "-y", "-i", inp, "-vf", vf,
               "-frames:v", str(frames), "-start_number", "1",
               os.path.join(outdir, "f%05d.png")]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("抽帧失败: %s" % (p.stderr or p.stdout))
    return sorted(glob.glob(os.path.join(outdir, "f*.png")))


def parse_size(text, default=(1920, 1080)):
    """'WxH' → (W, H)；非法/为空返回 default。"""
    import re
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\s*$", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else default


def make_prompt(rel_img, prefix, size=(1920, 1080)):
    """构造单帧超分 API prompt。rel_img: 相对 ComfyUI input 的路径。

    size：4x 超分后的目标分辨率（ImageScale 用 lanczos 缩放），默认 1080P。
    """
    w, h = size
    return {
        "1": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": MODEL_NAME}},
        "2": {"class_type": "LoadImage", "inputs": {"image": rel_img}},
        "3": {"class_type": "ImageUpscaleWithModel",
              "inputs": {"upscale_model": ["1", 0], "image": ["2", 0]}},
        "4": {"class_type": "ImageScale",
              "inputs": {"image": ["3", 0], "upscale_method": "lanczos",
                         "width": w, "height": h, "crop": "center"}},
        "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0], "filename_prefix": prefix}},
    }


def submit(api):
    resp = _post("/api/prompt", {"prompt": api, "client_id": "codebuddy"})
    if resp.get("error"):
        raise RuntimeError("提交失败: %s" % json.dumps(resp, ensure_ascii=False))
    return resp["prompt_id"]


def poll_batch(pids, poll=3, timeout=900):
    """轮询一批 pid，直到全部 success；返回 {pid: history_item}。失败抛异常。"""
    pending = set(pids)
    done = {}
    start = time.time()
    while pending and (time.time() - start) < timeout:
        time.sleep(poll)
        for pid in list(pending):
            try:
                hist = _get("/history/%s" % pid)
            except Exception:
                continue
            if pid in hist:
                st = hist[pid].get("status", {})
                sts = st.get("status_str")
                if sts == "success":
                    done[pid] = hist[pid]
                    pending.discard(pid)
                elif sts == "error":
                    raise RuntimeError("帧任务失败 pid=%s: %s" % (pid, json.dumps(st, ensure_ascii=False)))
    if pending:
        raise RuntimeError("超时仍有 %d 帧未完成" % len(pending))
    return done


def _collect_image(item, node_id=5):
    """从 history 条目取 SaveImage 输出文件信息。"""
    outs = item.get("outputs", {}).get(str(node_id), {})
    for key, lst in outs.items():
        if isinstance(lst, list):
            for it in lst:
                if isinstance(it, dict) and it.get("filename"):
                    return it
    return None


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "codebuddy"})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())


def view_url(info):
    return ("%s/view?filename=%s&subfolder=%s&type=%s"
            % (HOST, urllib.parse.quote(info["filename"]),
               urllib.parse.quote(info.get("subfolder", "")), info.get("type", "output")))


def upscale_image(inp_png, out_png, input_root, prefix, size=(1920, 1080)):
    """单图超分并保存，返回耗时秒。inp_png 会被复制到 input_root/<prefix>/<name>。"""
    rel_dir = prefix
    os.makedirs(os.path.join(input_root, rel_dir), exist_ok=True)
    src_name = os.path.basename(inp_png)
    rel_img = "%s/%s" % (rel_dir, src_name)
    shutil.copy2(inp_png, os.path.join(input_root, rel_dir, src_name))
    api = make_prompt(rel_img, prefix, size)
    pid = submit(api)
    t0 = time.time()
    done = poll_batch([pid], timeout=600)
    info = _collect_image(done[pid])
    if not info:
        raise RuntimeError("超分无输出图片")
    _download(view_url(info), out_png)
    return time.time() - t0


def upscale_video(inp, out, fps_override, frames, input_root, batch, prefix, keep,
                  size=(1920, 1080)):
    ff = ffmpeg_exe()
    if fps_override:
        fps = fps_override
    else:
        fps = probe_fps(inp)
        if not fps:
            fps = 30.0
    w, h = probe_dims(inp)
    print("输入: %s  fps=%.2f  分辨率=%sx%s  目标=%dx%d"
          % (inp, fps, w, h, size[0], size[1]))

    tmp = tempfile.mkdtemp(prefix="upscale_")
    frames_dir = os.path.join(tmp, "frames")
    frame_files = extract_frames(inp, frames_dir, fps, frames)
    n = len(frame_files)
    print("已抽帧 %d 张 -> %s" % (n, frames_dir))
    if n == 0:
        raise RuntimeError("无帧")

    up_dir = os.path.join(tmp, "up")
    os.makedirs(up_dir, exist_ok=True)

    # 提前把帧放到 ComfyUI input，LoadImage 一次一张(避免数据集节点限制)。
    # 此处用绝对路径复制到 input_root/<prefix>/；LoadImage 相对 input 路径引用。
    rel_img_list = []
    for i, fp in enumerate(frame_files, 1):
        rel = "%s/f%05d.png" % (prefix, i)
        os.makedirs(os.path.join(input_root, prefix), exist_ok=True)
        shutil.copy2(fp, os.path.join(input_root, prefix, os.path.basename(rel)))
        rel_img_list.append(rel)

    print("批量超分中（每批 %d 帧）..." % batch)
    t0 = time.time()
    per_batch = []
    for s in range(0, n, batch):
        chunk = rel_img_list[s:s + batch]
        ids = {}
        for rel in chunk:
            api = make_prompt(rel, prefix, size)
            pid = submit(api)
            ids[pid] = rel
        done = poll_batch(list(ids.keys()))
        for pid, item in done.items():
            info = _collect_image(item)
            if not info:
                raise RuntimeError("帧 %s 无输出" % ids[pid])
            # 按 inp 相对 input 顺序映射到帧序号
            rel = ids[pid]
            i = rel_img_list.index(rel) + 1
            _download(view_url(info), os.path.join(up_dir, "f%05d.png" % i))
        print("  批次 %d-%d/%d 完成（累计 %ss）" % (s + 1, min(s + batch, n), n, int(time.time() - t0)))

    print("超分完成（共用 %.1fs），合成 %s ..." % (time.time() - t0, out))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # 音轨原样透传（H3 会生成对白/音效，重编码视频时不能把声音丢掉）
    p = subprocess.run(
        [ff, "-hide_banner", "-y", "-framerate", "%.4f" % fps,
         "-i", os.path.join(up_dir, "f%05d.png"),
         "-i", inp, "-map", "0:v:0", "-map", "1:a?",
         "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-shortest", out],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError("合成失败: %s" % (p.stderr or p.stdout))
    print("已输出: %s" % out)

    if not keep:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    global HOST
    ap = argparse.ArgumentParser(description="4x-UltraSharp 视频/图片超分到 1080P")
    ap.add_argument("--input", help="低清单镜 mp4")
    ap.add_argument("--image", help="单图超分测试")
    ap.add_argument("--out", help="输出 mp4")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--frames", type=int, default=None, help="只处理前 N 帧(测试)")
    ap.add_argument("--batch", type=int, default=24)
    ap.add_argument("--size", default="1920x1080",
                    help="超分目标分辨率 WxH（默认 1920x1080，即 4x 后再 lanczos 缩到 1080P）")
    ap.add_argument("--input-root", default=DEFAULT_INPUT_ROOT)
    ap.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    ap.add_argument("--prefix", default="upscale_tmp")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--host", default=HOST)
    a = ap.parse_args()
    if a.host:
        HOST = a.host.rstrip("/")

    for d in (a.input_root,):
        if not os.path.isdir(d):
            print("警告: input 根不存在: %s" % d)

    if a.image:
        out = a.out or os.path.splitext(a.image)[0] + "_1080p.png"
        dt = upscale_image(a.image, out, a.input_root, a.prefix, parse_size(a.size))
        print("单图超分完成，耗时 %.2fs -> %s" % (dt, out))
        return 0

    if not a.input:
        ap.print_help()
        return 1
    out = a.out or (os.path.splitext(a.input)[0] + "_1080p.mp4")
    upscale_video(a.input, out, a.fps, a.frames, a.input_root, a.batch, a.prefix, a.keep,
                  parse_size(a.size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
