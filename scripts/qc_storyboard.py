# -*- coding: utf-8 -*-
"""分镜 P0/P1/P2 质量门禁（QC 引擎 · 适配本项目分镜 schema）。

口径来源:
  - 老李skill short-drama-director/references/dialogue-speed-check.md / quality-gate-review.md
  - voide-skill-master/engines/{dialogue_speed,combat_tier,quality_gates}.py
    （上一阶段建立的通用引擎；本模块把相同判定口径适配到 剧本/02_分镜/<集>_分镜.json
    的字段：storyboards[] / duration / dialogue(「说话人：（动作）台词」串) /
    shot_type(中文) / movement / scene_type / character_ids / speaker_id）

判定分级（与通用引擎一致）:
  P0 致命（阻断 GPU）：单镜时长突破上限 / 台词极速也塞不进镜预算
  P1 结构缺陷：单句超长、整篇节奏雷同、数据引用缺失、分镜字段缺漏
  P2 审美建议：运镜单一、空镜无任务、多说话人未拆镜等

确定性、零模型、零算力：直接读 剧本/ 数据层输出报告，供出片前把关。
用法:
  python scripts/qc_storyboard.py --episode 第1集             # 打印报告（P0 不阻断，退出码 0）
  python scripts/qc_storyboard.py --episode 第1集 --block     # 存在 P0 时退出码 1（供门禁）
  python scripts/qc_storyboard.py --episode 第1集 --out 剧本/02_分镜/第1集_质检.md
"""
from __future__ import annotations

import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import drama_tools as dt  # noqa: E402

# ── 判定阈值 ──
MAX_SHOT_SEC = 15.0          # P0-DUR15：单镜时长上限
STD_MAX_RATE = 5.0           # 极速 字/秒（P0 超时判定用最快有效口播）
STD_MIN_RATE = 3.5           # 慢速档 字/秒
LONG_SENTENCE_CHARS = 24     # P1-LONGSENT：单句 > 24 字
PER_SHOT_TARGET_CHARS = 18   # 拆镜后每镜建议 <= 18 字
CAMERA_REUSE_LIMIT = 6       # P2/P1：同一运镜连续镜数
MIN_TEMPO_LEVELS = 3         # 节奏档位下限
MIN_SHOTS_FOR_TEMPO = 12     # 少于 12 镜不做节奏判定
OVERRUN_SLACK = 0.2          # P0 超时容忍秒

# 停顿预算（与通用 dialogue_speed 一致）
LIGHT_PAUSE_SEC = (0.1, 0.3)   # 顿号/逗号
HEAVY_PAUSE_SEC = (0.3, 0.6)   # 句末
LIGHT_PAUSE = re.compile(r"[，、,;；]")
HEAVY_PAUSE = re.compile(r"[。！？!?…\.]+")
SENTENCE_END = re.compile(r"[。！？!?…]+")
_PUNCT = set("，。！？；：、（）()《》〈〉「」『』【】“”‘’\"'…—–·,.;:!?~`%&*@#$^|\\/<>[]{}＿_")


# ================================================================
# 台词解析：把「说话人：（动作）台词」串拆成可读句
# ================================================================
def _is_speech_char(ch: str) -> bool:
    if ch in _PUNCT or ch.isspace():
        return False
    import unicodedata
    cat = unicodedata.category(ch)
    return cat.startswith(("L", "N")) or cat in ("Mc", "Me") or cat not in (
        "Po", "Ps", "Pe", "Pi", "Pf", "Pd", "Pc", "Cf", "Co", "Cs",
        "Sk", "So", "Zs", "Zl", "Zp")


def count_speech_chars(text: str) -> int:
    """只数可发音字符（汉字/数字/字母），标点空白不计。"""
    return sum(1 for ch in text if _is_speech_char(ch))


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_END.split(text) if p and p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def parse_dialogue_lines(dialogue: str) -> list[dict]:
    """分镜 dialogue → [{speaker, action, text}]。

    兼容格式：`说话人：（动作）台词`；`旁白：xxx`；以及无前缀的纯台词行。
    JSON 里可能把换行写成字面 `\\n`，先归一化成真换行再逐行拆。
    """
    if not dialogue:
        return []
    text = dialogue.replace("\\n", "\n")
    lines = [ln.strip() for ln in re.split(r"\n+", text) if ln and ln.strip()]
    out = []
    # 说话人前缀：姓名 + 中文/英文冒号，随后是可选（动作提示）再是台词
    pat = re.compile(r"^(?P<name>[^：:]{1,12}?)[：:]\s*(?:（(?P<act>[^）]*)）|\((?P<act2>[^)]*)\))?\s*(?P<txt>.*)$")
    for ln in lines:
        m = pat.match(ln)
        if m and (m.group("txt") or "").strip():
            out.append({
                "speaker": m.group("name").strip(),
                "action": (m.group("act") or m.group("act2") or "").strip(),
                "text": m.group("txt").strip(),
            })
        else:
            # 没有「姓名：」前缀：整行当纯台词（可能是旁白/空镜描述残留）
            out.append({"speaker": "", "action": "", "text": ln})
    return out


def estimate_pause_range(text: str) -> tuple[float, float]:
    light_n = len(LIGHT_PAUSE.findall(text))
    heavy_n = len(HEAVY_PAUSE.findall(text))
    return (
        light_n * LIGHT_PAUSE_SEC[0] + heavy_n * HEAVY_PAUSE_SEC[0],
        light_n * LIGHT_PAUSE_SEC[1] + heavy_n * HEAVY_PAUSE_SEC[1],
    )


def estimate_duration_min(text: str) -> float:
    """该台词最短所需秒数：极速 5字/s + 最小停顿。"""
    chars = count_speech_chars(text)
    if chars == 0:
        return 0.0
    p_min, _ = estimate_pause_range(text)
    return round(chars / STD_MAX_RATE + p_min, 1)


# ================================================================
# 逐镜门禁
# ================================================================
def check_shot(shot: dict, idx: int, char_map: dict, scene_map: dict,
               speech_map: dict, prev_fixed: dict) -> list[dict]:
    """对单个分镜跑可计算门禁，返回 findings 列表。"""
    sid = str(shot.get("shot_id") or (idx + 1))
    findings: list[dict] = []
    label = f"镜{sid}"
    dur = None
    try:
        dur = float(shot.get("duration") or 0)
    except (TypeError, ValueError):
        dur = None

    # ---- P0-DUR15 ----
    if dur is not None and dur > MAX_SHOT_SEC:
        findings.append({"level": "P0", "code": "P0-DUR15", "shot": label,
                         "message": f"单镜时长 {dur}s > {MAX_SHOT_SEC}s（单组上限），阻断交付"})

    dialogue = shot.get("dialogue") or ""
    lines = parse_dialogue_lines(dialogue)
    spoken = " ".join(ln["text"] for ln in lines)
    scene_type = shot.get("scene_type", "")

    # ---- 台词：超长句 / 超时（只对真的有台词的镜判定）----
    if spoken:
        max_sent = max((count_speech_chars(s) for s in split_sentences(spoken)), default=0)
        if max_sent > LONG_SENTENCE_CHARS:
            findings.append({"level": "P1", "code": "P1-LONGSENT", "shot": label,
                             "message": f"单句 {max_sent} 字 > {LONG_SENTENCE_CHARS} 字超长句，"
                                        f"建议拆 2~3 镜，每镜台词 ≤ {PER_SHOT_TARGET_CHARS} 字"})
        if dur is not None:
            need_min = estimate_duration_min(spoken)
            if need_min > dur + OVERRUN_SLACK:
                findings.append({"level": "P0", "code": "P0-DIALOG-OVERRUN", "shot": label,
                                 "message": f"台词最短所需 {need_min}s（5字/s 极速+最小停顿）"
                                            f"超出镜预算 {dur}s，台词会念不完/被压缩 → 重构或改镜次"})

    # ---- 多说话人：同镜多说话但非 action 且 >2 人 → 建议拆镜 ----
    speakers = sorted({ln["speaker"] for ln in lines if ln["speaker"]})
    if len(speakers) > 2 and scene_type != "action":
        findings.append({"level": "P2", "code": "P2-MULTI-SPK", "shot": label,
                         "message": f"同镜 {len(speakers)} 个说话人({'、'.join(speakers)})，"
                                    "建议拆镜或明确主次（除 action 外一镜一句更稳）"})

    # ---- 说话人引用完整性 ----
    spk_id = shot.get("speaker_id") or ""
    if spoken and not spk_id and not speakers:
        findings.append({"level": "P1", "code": "P1-SPK-MISS", "shot": label,
                         "message": "有台词但缺 speaker_id，音色绑定会落空"})
    if spk_id and spk_id not in speech_map:
        findings.append({"level": "P1", "code": "P1-SPK-UNKNOWN", "shot": label,
                         "message": f"speaker_id={spk_id} 不在角色库，音色无法绑定"})
    elif spk_id:
        c = speech_map[spk_id]
        v = c.get("voice") or {}
        if not v.get("voice_id") or v.get("voice_id") == dt.PENDING_VOICE:
            findings.append({"level": "P1", "code": "P1-VOICE-PENDING", "shot": label,
                             "message": f"说话人 {c.get('name')}({spk_id}) 音色未绑定，"
                                        "语音一致性无保障（先跑 voice_assigner）"})

    # ---- 角色/场景引用完整性 ----
    for cid in shot.get("character_ids", []) or []:
        c = char_map.get(cid)
        if c is None:
            findings.append({"level": "P1", "code": "P1-CHAR-UNKNOWN", "shot": label,
                             "message": f"character_id={cid} 不在角色库，r2v 会缺参考图"})
        elif c.get("role_type") != "旁白" and not (c.get("image_prompt") or "").strip():
            findings.append({"level": "P1", "code": "P1-CHAR-NO-IMG", "shot": label,
                             "message": f"角色 {c.get('name')}({cid}) 缺 image_prompt，无法出三视图"})
    sc = shot.get("scene_id") or ""
    if sc and sc not in scene_map:
        findings.append({"level": "P1", "code": "P1-SCENE-UNKNOWN", "shot": label,
                         "message": f"scene_id={sc} 不在场景库，r2v 会缺九宫格"})

    # ---- 字段缺漏 ----
    if not (shot.get("image_prompt") or "").strip():
        findings.append({"level": "P1", "code": "P1-NO-IMG-PROMPT", "shot": label,
                         "message": "缺 image_prompt（首帧/参考图会没内容）"})
    if not (shot.get("video_prompt") or "").strip():
        findings.append({"level": "P1", "code": "P1-NO-VID-PROMPT", "shot": label,
                         "message": "缺 video_prompt（视频动作无从生成）"})
    if scene_type not in ("", "silent", "single", "action"):
        findings.append({"level": "P2", "code": "P2-SCENE-TYPE", "shot": label,
                         "message": f"scene_type={scene_type} 非枚举值(silent/single/action)"})
    if scene_type == "silent" and spoken:
        findings.append({"level": "P2", "code": "P2-SILENT-SPK", "shot": label,
                         "message": "scene_type=silent 却带台词，语义冲突"})

    # ---- 运动一致性：同一非静态运镜连用 >=6 镜（固定机位属对白常态，不判）----
    move = shot.get("movement") or ""
    is_static = move in ("", "固定")
    if prev_fixed["move"] == move and not is_static:
        prev_fixed["run"] += 1
    else:
        prev_fixed["move"], prev_fixed["run"] = move, 1
    if not is_static and prev_fixed["run"] >= CAMERA_REUSE_LIMIT:
        findings.append({"level": "P2", "code": "P2-CAMERA-REUSE", "shot": label,
                         "message": f"连续 {prev_fixed['run']} 镜同一运镜「{move}」，"
                                    "镜头语言单一，建议插反打/反应镜"})
        prev_fixed["run"] = 0   # 只报一次

    # ---- 空镜无任务 ----
    if scene_type == "silent" and not spoken and not (shot.get("description") or "").strip() \
            and not (shot.get("action") or "").strip():
        findings.append({"level": "P2", "code": "P2-BLANK-SHOT", "shot": label,
                         "message": "空镜且无戏剧任务（description/action 全空）"})
    return findings


# ================================================================
# 整篇门禁（节奏）
# ================================================================
def _check_tempo(shots: list[dict]) -> list[dict]:
    if len(shots) < MIN_SHOTS_FOR_TEMPO:
        return []
    durs = []
    for s in shots:
        try:
            d = float(s.get("duration") or 0)
            if d > 0:
                durs.append(d)
        except (TypeError, ValueError):
            pass
    if len(durs) < MIN_SHOTS_FOR_TEMPO:
        return []
    levels = sorted({round(d) for d in durs})
    if len(levels) < MIN_TEMPO_LEVELS:
        return [{"level": "P1", "code": "P1-TEMPO-FLAT", "shot": "-",
                 "message": f"全篇 {len(shots)} 镜时长仅 {len(levels)} 种档位({levels})，"
                            "无快慢节奏，建议文戏留白/武戏切短制造节奏差"}]
    return []


# ================================================================
# 汇总报告
# ================================================================
def run_qc(episode: str = "第1集", block_on_p0: bool = False) -> dict:
    """对一集分镜跑质量门禁。block_on_p0 仅影响调用方退出码，不影响报告本身。"""
    boards = dt.load_storyboards(episode)
    char_map = {c.get("id"): c for c in dt.load_characters()}
    scene_map = {s.get("id"): s for s in dt.load_scenes()}
    speech_map = {c.get("speaker_id"): c for c in dt.load_characters()
                  if c.get("speaker_id")}
    prev_fixed = {"move": "", "run": 0}

    findings: list[dict] = []
    for i, sb in enumerate(boards):
        if isinstance(sb, dict):
            findings.extend(check_shot(sb, i, char_map, scene_map, speech_map, prev_fixed))
    findings.extend(_check_tempo(boards))

    counts = {"P0": 0, "P1": 0, "P2": 0}
    for f in findings:
        counts[f["level"]] = counts.get(f["level"], 0) + 1
    p0 = counts["P0"]
    report = {
        "episode": dt.episode_tag(episode),
        "total_shots": len(boards),
        "counts": counts,
        "findings": findings,
        "valid": p0 == 0,
        "blocked": bool(block_on_p0 and p0 > 0),
    }
    report["summary"] = (
        f"门禁结论: {'[PASS] 通过' if report['valid'] else '[FAIL] 存在 P0 致命项'} | "
        f"P0 {p0} | P1 {counts['P1']} | P2 {counts['P2']} | 共 {len(boards)} 镜"
    )
    return report


def format_report(report: dict) -> str:
    lines = [
        "# 分镜 P0/P1/P2 质检报告",
        "",
        f"- {report['summary']}",
        "",
    ]
    for lv, title in (("P0", "P0 致命（阻断 GPU）"),
                      ("P1", "P1 结构缺陷（建议修复）"),
                      ("P2", "P2 审美建议")):
        items = [f for f in report["findings"] if f.get("level") == lv]
        lines.append(f"## {title}（{len(items)}）")
        if not items:
            lines.append("- 无")
        else:
            for f in items:
                lines.append(f"- `{f['code']}` {f['shot']}: {f['message']}")
        lines.append("")
    return "\n".join(lines)


def print_compact(report: dict):
    """pipeline 用的紧凑摘要（一行/级别 + 前几个 P0）。"""
    c = report["counts"]
    print(f"  门禁: P0={c['P0']} P1={c['P1']} P2={c['P2']} | 共 {report['total_shots']} 镜")
    p0s = [f for f in report["findings"] if f["level"] == "P0"]
    for f in p0s[:8]:
        print(f"    [P0] {f['code']} {f['shot']}: {f['message']}")


def main(argv=None):
    p = argparse.ArgumentParser(description="分镜 P0/P1/P2 质量门禁")
    p.add_argument("--episode", default="第1集", help="集号（默认 第1集）")
    p.add_argument("--block", action="store_true", help="存在 P0 时退出码 1（供门禁/CI）")
    p.add_argument("--out", default=None, help="把报告写盘（Markdown 路径）")
    p.add_argument("--compact", action="store_true", help="只打紧凑摘要")
    args = p.parse_args(argv)

    report = run_qc(args.episode, block_on_p0=args.block)
    if args.compact:
        print_compact(report)
    else:
        print(format_report(report))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(format_report(report))
        print(f"[ok] 报告已写: {args.out}")
    print(report["summary"])
    return 1 if report["blocked"] else 0


if __name__ == "__main__":
    sys.exit(main())
