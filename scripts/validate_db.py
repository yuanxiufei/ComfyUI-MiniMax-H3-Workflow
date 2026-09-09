# -*- coding: utf-8 -*-
"""数据契约校验器 —— 在「生成」前先给 剧本/ 数据层做离线体检（零算力、零模型）。

目的：视频生成链已相当自动化，但 角色/场景/分镜 JSON 若结构不对、类型错、
引用断裂（character_ids 指向不存在的角色）、时长非法、枚举非法，
往往拖到「生成 / build / submit」阶段才报错，白白烧算力还难定位。

本脚本在数据进 build / submit / 视频链之前，先做一次确定性契约校验，
把「必填字段 / 类型 / 枚举 / id 唯一 / 引用完整 / 台词-说话人」这类问题提前暴露，
配合 pipeline 的预检步骤或 CI，做到 *能在烧 GPU 前停下来的问题绝不晚烧*。

判定分级（与 qc_storyboard 一致口径）:
  P0 致命（会炸生成/引用缺失）: JSON 损坏 / 列表错型 / id 重复 / duration 非法 / 引用不存在
  P1 结构缺陷（必填缺失）    : 分镜缺 image_prompt / 有台词无 speaker_id 等
  P2 建议（不阻断）          : scene_type 非法枚举、角色缺统一风格段等

用法:
  python scripts/validate_db.py                          # 校验全部库 + 第1集分镜
  python scripts/validate_db.py --db characters           # 只校验角色库
  python scripts/validate_db.py --db scene --db props     # 场景 + 道具
  python scripts/validate_db.py --db storyboard --episode 第1集
  python scripts/validate_db.py --strict                  # P1 也导致退出码 1（供严门禁/CI）
  python scripts/validate_db.py --out output/validate.md  # 报告写盘
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

# scene_type 合法枚举（与 qc_storyboard / build 实际一致；其余枚举值一律算 P2 建议，
# 因为参考方法论里有 dialogue_2p/meeting 等更细枚举，但当前管道只认前四类，多余给建议）
SCENE_TYPE_OK = {"", "silent", "single", "action"}
GENDER_OK = {"男", "女"}
# 角色必填字段（旁白无实体形象，豁免 image/容貌 相关）
CHAR_REQUIRED = ["id", "name"]
SCENE_REQUIRED = ["id", "name"]
PROP_REQUIRED = ["id", "name"]
SHOT_REQUIRED = ["shot_id", "scene_id", "character_ids", "scene_type",
                 "image_prompt", "video_prompt", "duration"]


def _load_raw(path):
    """读原始 JSON，返回 (ok, data, err)。顶层结构 = dict 且含必需 key 才算 ok。"""
    if not os.path.exists(path):
        return False, None, f"文件不存在: {path}"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, None, f"JSON 解析失败: {e}"
    return True, data, None


def _items(data, key):
    """从顶层 dict 里取列表；不是列表则返回 None 并给出类型线索。"""
    if data is None:
        return None
    v = data.get(key)
    if isinstance(v, list):
        return v
    if v is None:
        return []
    return v  # 非 list（dict/str），由调用方判型


def _check_list_type(name, data, key) -> list[dict]:
    """校验顶层 <key> 是否为 list。返回 findings。"""
    if data is None:
        return []
    v = data.get(key)
    if v is not None and not isinstance(v, list):
        return [{"level": "P0", "code": f"P0-{key.upper()}-TYPE", "item": "-",
                 "message": f"{key} 应为数组(Array)，实为 {type(v).__name__}，下游遍历会炸"}]
    return []


def _check_unique(items, key, label, lv="P0") -> list[dict]:
    seen, out = {}, []
    for it in items:
        v = (it or {}).get(key)
        if v is None:
            continue
        if v in seen:
            out.append({"level": lv, "code": f"P0-{key.upper()}-DUP", "item": str(v),
                        "message": f"{label} {key}={v} 重复（与 {seen[v]}），跨集/下游按 id 定位会错乱"})
        else:
            seen[v] = it.get("id") or it.get("name") or str(v)
    return out


def _check_characters() -> list[dict]:
    path = dt.CHAR_DB
    ok, data, err = _load_raw(path)
    findings = []
    if not ok:
        findings.append({"level": "P0", "code": "P0-JSON", "item": "-", "message": err})
        return findings
    findings += _check_list_type("角色", data, "characters")
    chars = data.get("characters") if isinstance(data.get("characters"), list) else []
    findings += _check_unique(chars, "id", "角色")
    findings += _check_unique(chars, "speaker_id", "角色", lv="P2")
    for c in chars:
        label = c.get("name") or c.get("id") or "?"
        for f in CHAR_REQUIRED:
            if f not in c or c[f] in (None, ""):
                findings.append({"level": "P1", "code": "P1-CHAR-MISS", "item": label,
                                 "message": f"角色 {label} 缺必填字段 {f}"})
        g = c.get("gender")
        if g and g not in GENDER_OK:
            findings.append({"level": "P2", "code": "P2-CHAR-GENDER", "item": label,
                             "message": f"角色 {label} gender={g} 非枚举({'/'.join(sorted(GENDER_OK))})"})
        # 有实体的角色必须能出图
        if c.get("role_type") != "旁白" and not (c.get("image_prompt") or "").strip():
            findings.append({"level": "P1", "code": "P1-CHAR-NO-IMG", "item": label,
                             "message": f"角色 {label} 缺 image_prompt（三视图/全景出不了图）"})
        if (c.get("image_prompt") or "").strip() and not dt.has_fusion_style(c["image_prompt"]):
            findings.append({"level": "P2", "code": "P2-CHAR-NO-STYLE", "item": label,
                             "message": f"角色 {label} 缺统一风格前置段（build 会兜底 STYLE_FUSION，但建议补齐）"})
        v = c.get("voice") or {}
        if v.get("voice_id") in (None, "", dt.PENDING_VOICE) and c.get("role_type") != "旁白":
            findings.append({"level": "P2", "code": "P2-CHAR-NO-VOICE", "item": label,
                             "message": f"角色 {label} 音色未绑定（先跑 voice_assigner，否则对白一致性无保障）"})
    return findings


def _check_scenes() -> list[dict]:
    path = dt.SCENE_DB
    ok, data, err = _load_raw(path)
    findings = []
    if not ok:
        findings.append({"level": "P0", "code": "P0-JSON", "item": "-", "message": err})
        return findings
    findings += _check_list_type("场景", data, "scenes")
    scenes = data.get("scenes") if isinstance(data.get("scenes"), list) else []
    findings += _check_unique(scenes, "id", "场景")
    for s in scenes:
        label = s.get("name") or s.get("id") or "?"
        for f in SCENE_REQUIRED:
            if f not in s or s[f] in (None, ""):
                findings.append({"level": "P1", "code": "P1-SCENE-MISS", "item": label,
                                 "message": f"场景 {label} 缺必填字段 {f}"})
    return findings


def _check_props() -> list[dict]:
    path = dt.PROP_DB
    ok, data, err = _load_raw(path)
    findings = []
    if not ok:
        findings.append({"level": "P0", "code": "P0-JSON", "item": "-", "message": err})
        return findings
    findings += _check_list_type("道具", data, "props")
    props = data.get("props") if isinstance(data.get("props"), list) else []
    findings += _check_unique(props, "id", "道具")
    for p in props:
        label = p.get("name") or p.get("id") or "?"
        for f in PROP_REQUIRED:
            if f not in p or p[f] in (None, ""):
                findings.append({"level": "P1", "code": "P1-PROP-MISS", "item": label,
                                 "message": f"道具 {label} 缺必填字段 {f}"})
    return findings


def _check_storyboard(episode: str) -> list[dict]:
    path = dt._board_path(episode)
    ok, data, err = _load_raw(path)
    findings = []
    if not ok:
        findings.append({"level": "P0", "code": "P0-JSON", "item": "-",
                         "message": f"{episode} 分镜: {err}"})
        return findings
    findings += _check_list_type("分镜", data, "storyboards")
    boards = data.get("storyboards") if isinstance(data.get("storyboards"), list) else []
    char_map = {c.get("id"): c for c in dt.load_characters() if c.get("id")}
    scene_map = {s.get("id"): s for s in dt.load_scenes() if s.get("id")}
    spk_map = {c.get("speaker_id"): c for c in dt.load_characters() if c.get("speaker_id")}
    findings += _check_unique(boards, "shot_id", "分镜")
    for b in boards:
        label = f"镜{b.get('shot_id')}" if b.get("shot_id") is not None else "镜?"
        for f in ("scene_id", "scene_type", "image_prompt", "video_prompt"):
            if f not in b or b[f] in (None, ""):
                findings.append({"level": "P1", "code": "P1-SHOT-MISS", "item": label,
                                 "message": f"{label} 缺必填分镜字段 {f}"})
        # duration 必须为数字 > 0
        d = b.get("duration")
        ok_d = isinstance(d, (int, float)) and not isinstance(d, bool) and d > 0
        if not ok_d:
            findings.append({"level": "P0", "code": "P0-DUR-TYPE", "item": label,
                             "message": f"{label} duration={d!r}({type(d).__name__}) 非正数，"
                                        "下游按秒累加/判断会错乱"})
        # character_ids 必须为 list，且引用存在（r2v 缺参考图）
        cids = b.get("character_ids")
        if not isinstance(cids, list):
            findings.append({"level": "P0", "code": "P0-CHARIDS-TYPE", "item": label,
                             "message": f"{label} character_ids 应为数组(Array)，实为 {type(cids).__name__}"})
        else:
            for cid in cids:
                if cid not in char_map:
                    findings.append({"level": "P0", "code": "P0-CHAR-UNKNOWN", "item": label,
                                     "message": f"{label} character_id={cid} 不在角色库，r2v 会缺参考图"})
        # scene_id 引用存在
        sc = b.get("scene_id") or ""
        if sc and sc not in scene_map:
            findings.append({"level": "P0", "code": "P0-SCENE-UNKNOWN", "item": label,
                             "message": f"{label} scene_id={sc} 不在场景库，r2v 会缺九宫格"})
        # scene_type 枚举
        st = b.get("scene_type") or ""
        if st not in SCENE_TYPE_OK:
            findings.append({"level": "P2", "code": "P2-SCENE-TYPE", "item": label,
                             "message": f"{label} scene_type={st} 非当前管道枚举"
                                        f"({'/'.join(sorted(SCENE_TYPE_OK))})，qc 会误判"})
        # 台词-说话人：有台词必须有 speaker_id
        spoken = (b.get("dialogue") or "").strip()
        if spoken and not b.get("speaker_id"):
            findings.append({"level": "P1", "code": "P1-SPK-MISS", "item": label,
                             "message": f"{label} 有台词但缺 speaker_id，音色绑定会落空"})
        sid = b.get("speaker_id") or ""
        if sid and sid not in spk_map:
            findings.append({"level": "P1", "code": "P1-SPK-UNKNOWN", "item": label,
                             "message": f"{label} speaker_id={sid} 不在角色库，音色无法绑定"})
    return findings


# =====================================================================
# 汇总
# =====================================================================
def build_summary(bucket: list[dict], mode: str, strict: bool) -> dict:
    counts = {"P0": 0, "P1": 0, "P2": 0}
    for f in bucket:
        counts[f["level"]] = counts.get(f["level"], 0) + 1
    p0, p1 = counts["P0"], counts["P1"]
    blocked = p0 > 0 or (strict and p1 > 0)
    return {
        "mode": mode,
        "counts": counts,
        "valid": p0 == 0 and not (strict and p1 > 0),
        "blocked": blocked,
        "summary": (f"契约校验: {'[PASS] 通过' if not (p0 or (strict and p1)) else '[FAIL] 存在问题'} | "
                    f"P0 {p0} | P1 {p1} | P2 {counts['P2']}")
    }


def run_validate(episode: str = "第1集", dbs: list[str] | None = None,
                 strict: bool = False) -> dict:
    wanted = set(dbs or ["characters", "scene", "props", "storyboard"])
    findings = []
    if "characters" in wanted:
        findings += _check_characters()
    if "scene" in wanted:
        findings += _check_scenes()
    if "props" in wanted:
        findings += _check_props()
    if "storyboard" in wanted:
        findings += _check_storyboard(episode)
    report = build_summary(findings, ",".join(sorted(wanted)), strict)
    report["findings"] = findings
    return report


def format_report(report: dict) -> str:
    lines = ["# 数据契约校验报告", "", f"- {report['summary']}", ""]
    for lv, title in (("P0", "P0 致命（会炸生成/引用缺失）"),
                       ("P1", "P1 结构缺陷（必填缺失，建议修）"),
                       ("P2", "P2 建议（不阻断）")):
        items = [f for f in report["findings"] if f.get("level") == lv]
        lines.append(f"## {title}（{len(items)}）")
        if not items:
            lines.append("- 无")
        else:
            for f in items:
                lines.append(f"- `{f['code']}` {f['item']}: {f['message']}")
        lines.append("")
    return "\n".join(lines)


def print_compact(report: dict):
    c = report["counts"]
    print(f"  契约校验: P0={c['P0']} P1={c['P1']} P2={c['P2']} | 模式 {report['mode']}")
    for f in report["findings"]:
        if f["level"] == "P0":
            print(f"    [P0] {f['code']} {f['item']}: {f['message']}")


def main(argv=None):
    p = argparse.ArgumentParser(description="剧本数据契约校验（离线，零算力）")
    p.add_argument("--episode", default="第1集", help="集号（默认 第1集）")
    p.add_argument("--db", action="append", dest="dbs",
                   choices=["characters", "scene", "props", "storyboard"],
                   help="只校验指定库，可多传（默认全部）")
    p.add_argument("--strict", action="store_true", help="P1 也导致退出码 1（严门禁/CI）")
    p.add_argument("--compact", action="store_true", help="只打紧凑摘要")
    p.add_argument("--out", default=None, help="报告写盘（Markdown 路径）")
    args = p.parse_args(argv)

    report = run_validate(args.episode, dbs=args.dbs, strict=args.strict)
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
