# -*- coding: utf-8 -*-
"""把分镜库组装成 H3 官方六段式导演 Prompt（subject_definition /
summary / retention_analysis / detailed_description / overall_soundscape /
non_diegetic_music），对齐 MiniMax 官方 film-shot / film-reference-prompt-writer
与参考项目「AIGC中国风3D漫剧 · H3六段式Prompt」的方法论。

与既有无缝链的关系：
  - build_seamless_video.py 已产出「一镜一条英文段 + <d>[Chinese]台词</d> + S编号/音色」
    的 H3MultishotSampler script（剧本/02_分镜/第1集_无缝链剧本.txt、workflows/13_…）；
  - 本脚本把同一批段素材包装成**官方六段式导演稿**（人类审读 / 喂 H3 Director / 归档），
    确定性、零模型、零算力，只读 剧本/ 数据层。

输出：
  output/<集>_H3导演提示词_六段式.json   （结构化：全集 + 逐镜六段）
  output/<集>_H3导演提示词_六段式.md     （人读稿）

用法：
  python scripts/build_h3_prompts.py                 # 默认第1集
  python scripts/build_h3_prompts.py --episode 第1集 --out-dir output
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402
import build_seamless_video as bsv  # noqa: E402  复用 VOICE_EN/段组装/拆台词

# 六段式的官方键顺序（主题定义/摘要/留存分析/详细描述/环境声/非叙事音乐）
SECTIONS = [
    "subject_definition",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
]


def _fmt_ts(sec: float) -> str:
    """秒 → 00:00:00.000 时间轴串。"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return "%02d:%02d:%06.3f" % (h, m, s)


def build_episode_six(sbs, scene_db, role_map, segs, ep="第1集", frames_per_shot=192, fps=24):
    """把整集素材组装成官方六段式（全集级导演稿）。

    segs: bsv.build_shots() 返回的 [(seg_text, meta)]，每段时长固定 frames_per_shot/fps 秒
    """
    sec_per_seg = frames_per_shot / fps
    total_sec = len(segs) * sec_per_seg

    # ---- subject_definition：角色 + 音色 + 编号 + 场景参考图(Picture)，一镜一句锁定参考图 ----
    char_lines = []
    for sid in sorted(role_map):
        r = role_map[sid]
        is_nar = sid == "S11"
        kind = "旁白 narrator" if is_nar else "角色"
        char_lines.append(
            f"<Subject {sid}> = {kind}《{r['name']}》（编号 {sid}）：稳定音色 = "
            f"{r.get('voice_desc') or r.get('voice_en') or 'N/A'}。全片该角色的脸/声永不漂移。"
        )
    # 场景参考图登记：本集出现的每个场景都注册为 <Picture>，并声明"全片复用不漂移"，
    # 与 <Subject>（角色）两组并陈，对齐官方 film-shot 的 subject_definition 结构。
    pic_lines, seen_pic = [], set()
    for s in sbs:
        sc = scene_db.get(s.get("scene_id") or "", {})
        pid = sc.get("id")
        if pid and pid not in seen_pic:
            seen_pic.add(pid)
            pic_lines.append(
                f"<Picture {pid}> = 场景《{sc.get('name') or pid}》本集环境/机位参考图，"
                f"全片该场景逐镜复用、布局不漂移。"
            )
    subject_block = "\n".join(char_lines)
    if pic_lines:
        subject_block += "\n\n" + "\n".join(pic_lines)

    # ---- summary：首镜建立场景 + 场/角色统计（不臆造剧情）----
    opener = sbs[0]
    _act = (opener.get("action") or "").strip().rstrip("。.")
    summary = (f"本集共 {len(sbs)} 个分镜 / {len(segs)} 条连续段，每段 {sec_per_seg:.1f}s，"
               f"整集 {sec_per_seg * len(segs):.0f}s。开篇镜头[{opener.get('shot_id')}]："
               f"{opener.get('title')}，{_act}。"
               f"({opener.get('description')} / {opener.get('atmosphere')})")

    # ---- retention_analysis：节奏与入戏保持（纯数据口径）----
    dur_list = [float(s.get("duration") or 0) for s in sbs if s.get("duration")]
    max_dur = max(dur_list) if dur_list else 0
    min_dur = min(dur_list) if dur_list else 0
    spk_cnt = len({m["num"] for _, m in segs if m.get("num")})
    retention = (
        f"每段控制在 {sec_per_seg:.0f}s 内快速推进；单镜设计时长 {min_dur:.0f}~{max_dur:.0f}s，"
        f"对白紧凑不拖拍；全片 {spk_cnt} 个说话人音色绑定，情绪曲线先抑后扬；"
        f"中段设动作/冲突高潮，结尾留钩引导追更。"
    )

    # ---- detailed_description：逐段时间轴 + 台词语块 ----
    detail_lines = []
    for i, (seg, meta) in enumerate(segs):
        start = i * sec_per_seg
        end = start + sec_per_seg
        shot = meta.get("shot")
        spk = "、".join(meta.get("speakers") or ["无(对白)"]) + (
            " (" + meta["num"] + ")" if meta.get("num") else "")
        detail_lines.append(
            f"[Shot {i + 1}｜镜{shot}] At {_fmt_ts(start)} to {_fmt_ts(end)} "
            f"({sec_per_seg:.1f}s) · 说话人: {spk}\n    {seg}"
        )

    # ---- overall_soundscape：聚合全片环境音/音效 ----
    sfx = sorted({s.get("sound_effect") for s in sbs if s.get("sound_effect")})
    sfx_head = sfx[0] if sfx else ""
    soundscape = (
        f"环境底噪与动作音效全程在场、叠层不加盖：{sfx_head}"
        + (f"；另有场景间转场音 {len(sfx)} 组，逐镜在 detailed_description 的台词前触发。" if sfx else "")
        + " 对白(0dB) > SFX(-6dB) > BGM(-14~-18dB) 三层电平规范。"
    )

    # ---- non_diegetic_music：BGM 走势（取各镜 bgm_prompt 汇聚）----
    bgm_seq = [s.get("bgm_prompt") for s in sbs if s.get("bgm_prompt")]
    music = "；".join(bgm_seq[:8])
    music_meta = (
        f"按镜序推进的情绪配乐：{music}"
        + ("…（后段同型递进，见 分镜.json bgm_prompt 逐镜明细）" if len(bgm_seq) > 8 else "") +
        "。金句处留 0.3~0.8s 无对白反应镜托底。"
    )

    sections = {
        "subject_definition": subject_block,
        "summary": summary,
        "retention_analysis": retention,
        "detailed_description": "\n\n".join(detail_lines),
        "overall_soundscape": soundscape,
        "non_diegetic_music": music_meta,
    }
    return sections, {"episode": ep, "total_sec": round(total_sec, 1), "seg_count": len(segs)}


def build_shot_six(sb, scene_db, role_map, voice_en):
    """单镜级别六段（供人工审读 / 喂 Director 单镜）。subject_definition 锁定参考图语义。"""
    dlg = bsv.split_dialogue(sb.get("dialogue", ""))
    cam = bsv.camera_en(sb)
    img = bsv._clean(sb.get("image_prompt", ""))
    scene = scene_db.get(sb.get("scene_id") or "", {})
    scene_name = scene.get("name") or sb.get("scene_id") or "N/A"
    role_map_by_name = {v["name"]: v for v in role_map.values()}
    sb_speaker = sb.get("speaker_id")
    lines = []
    for spk, text in dlg:
        r = role_map_by_name.get(spk) or role_map.get(sb_speaker) or role_map.get("S11", {})
        s_num = _sid_of(role_map, r, spk)
        is_nar = s_num == "S11" or "旁白" in spk
        if is_nar:
            text = text.replace("旁白：", "").replace("旁白:", "")
        v_en = r.get("voice_en") or voice_en.get(s_num) or voice_en.get("S11", "")
        name = r.get("name", spk)
        say = (f"Narrator speaks {v_en} ({s_num}): <d>[Chinese] {text} </d>" if is_nar
               else f"{name} speaks {v_en} ({s_num}): <d>[Chinese] {text} </d>")
        lines.append(f"{img}. Camera: {cam}. {say}")

    has_people = bool(sb.get("character_ids"))
    if has_people:
        subj_def = (f"场景《{scene_name}》(<Picture {scene.get('id','')}>) 仅作环境参考；"
                    "在场角色复用全集 <Subject> 定义，不另立新脸/新声。")
    else:
        subj_def = (f"空镜：场景《{scene_name}》(<Picture {scene.get('id','')}>) 环境唯一主体，"
                    "无角色入镜。")
    return {
        "shot_id": sb.get("shot_id"),
        "subject_definition": subj_def,
        "summary": f"{sb.get('title')} | {sb.get('description') or ''}",
        "retention_analysis": f"{sb.get('action') or ''} 句内见冲突；镜长 {sb.get('duration')}s，"
                              "对白不超速，入戏不拖。",
        "detailed_description": "\n".join(lines) if lines else f"{img}. Camera: {cam}. (无对白)",
        "overall_soundscape": sb.get("sound_effect") or "",
        "non_diegetic_music": sb.get("bgm_prompt") or "",
    }


def _sid_of(role_map, role, name):
    for sid, v in role_map.items():
        if v is role or v.get("name") == name:
            return sid
    return "S11"


def build_role_map_full(episode):
    """drama_tools 角色库 → speaker_id 映射（复用无缝链同款，按真实性别校正音色）。"""
    chars = dt.load_characters()
    return {
        c.get("speaker_id"): {
            "name": c.get("name", ""),
            "gender": c.get("gender", ""),
            "voice_desc": (c.get("voice") or {}).get("voice_desc", ""),
            "voice_en": bsv.align_voice_gender(
                bsv.VOICE_EN.get(c.get("speaker_id"), bsv.VOICE_EN.get("S11", "")),
                c.get("gender", "")),
        }
        for c in chars if c.get("speaker_id")
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="H3 官方六段式导演 Prompt 生成（确定性）")
    p.add_argument("--episode", default="第1集", help="集号（默认 第1集）")
    p.add_argument("--out-dir", default=os.path.join(ROOT, "output"), help="输出目录")
    args = p.parse_args(argv)

    ep = dt.episode_tag(args.episode)
    sbs = dt.load_storyboards(ep)
    if not sbs:
        print(f"分镜库为空（{ep}），先跑 storyboard_breaker。")
        return 3
    scene_db = {s["id"]: s for s in dt.load_scenes()}
    role_map = build_role_map_full(ep)
    segs = bsv.build_shots(sbs, scene_db, role_map)

    ep_six, meta = build_episode_six(sbs, scene_db, role_map, segs, ep=ep)
    shot_six = [build_shot_six(sb, scene_db, role_map, bsv.VOICE_EN) for sb in sbs]

    payload = {
        "episode": ep,
        "meta": meta,
        "voice_map": role_map,
        "episode_six_sections": ep_six,
        "shots_six_sections": shot_six,
    }
    os.makedirs(args.out_dir, exist_ok=True)
    base = os.path.join(args.out_dir, f"{ep}_H3导演提示词_六段式")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = [_header(ep, meta), "", "## 全集版 · 六段式导演稿", ""]
    for k in SECTIONS:
        md += [f"### {k}", "", ep_six[k], ""]
    md += ["## 逐镜版 · 六段式摘要", ""]
    for sh in shot_six:
        md += [f"### 镜{sh['shot_id']} — {sh['summary']}", "",
               f"**subject_definition**  \n{sh['subject_definition']}", "",
               f"**retention_analysis**  \n{sh['retention_analysis']}", "",
               f"**detailed_description**  \n{sh['detailed_description']}", "",
               f"**overall_soundscape**  \n{sh['overall_soundscape'] or '—'}", "",
               f"**non_diegetic_music**  \n{sh['non_diegetic_music'] or '—'}", ""]
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"[ok] {ep} 六段式导演稿已生成：")
    print(f"  {base}.json")
    print(f"  {base}.md")
    print(f"  连续段 {meta['seg_count']} | 逐镜 {len(shot_six)} | 整集 {meta['total_sec']:.0f}s")
    return 0


def _header(ep, meta):
    return (f"# {ep} H3 六段式导演 Prompt（官方结构）\n\n"
            f"- 连续段 {meta['seg_count']} 段，整集约 {meta['total_sec']:.0f}s。\n"
            f"- 六段结构：subject_definition / summary / retention_analysis / "
            f"detailed_description / overall_soundscape / non_diegetic_music\n"
            f"- 台词一律 <d>[Chinese] 台词 </d> + S编号/稳定音色，逐镜复用防声音漂移。\n")


if __name__ == "__main__":
    sys.exit(main())
