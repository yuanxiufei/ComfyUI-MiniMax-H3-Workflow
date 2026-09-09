# -*- coding: utf-8 -*-
"""一次性提取《剑噬天下》每一回角色对应的年龄（确定性，不调 LLM）。

切回 + 角色名匹配 + 年龄词抽取 + 就近归属，输出：
  剧本/03_角色场景/全书角色年龄谱.json / .md
说明:
  - 年龄词主要围绕主角凌云(含现世身份林城)的修为进境出现；
    source=explicit 就近有角色名 / infer 该回有主角但未点名 / unknown 无归属。
  - 已过滤"长命百岁/万岁/千岁/千秋"等敬语；"十五、六岁/十八九岁"按首段取实龄。
  - 原文按多卷、每卷从"第001回"重编号，故用全书全局序号 seq 作回号(1..N)。
  - 名单=内置种子 + --names；通用称呼(长老/师尊/中将等)不作人名角色。
用法: python scripts/extract_character_ages.py [--names a,b] [--out 目录]
"""
import argparse, json, os, re, sys
from collections import Counter, OrderedDict
import drama_tools as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_OUT_DIR = os.path.join(ROOT, "剧本", "03_角色场景")

ROLE_SEED = OrderedDict([
    ("凌云", []), ("林城", []), ("小雪", []), ("云姐", []), ("陈姨", []),
    ("保镖", []), ("东离", []), ("江流", []), ("江雪", []), ("徐部长", []),
    ("中将", []), ("林雪", []), ("从夜", []), ("妙音", []), ("阿九", []),
    ("寂流光", []), ("碧儿", []), ("玄隐", []), ("雪夏", []),
])

_CN = r"[\d零一二三四五六七八九十百千]{1,4}"
AGE_RE = re.compile(r"(?P<num>%s(?:[、,，~/至到]?%s)?)\s*岁" % (_CN, _CN))
_BLESS_RE = re.compile(r"长命百岁|寿比南山|万岁|千岁|千秋|万年|寿元|天年")
_DIG = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


def _cn_age(cn):
    if re.match(r'^[零一二三四五六七八九两]?十[零一二三四五六七八九]?', cn):
        a, b = cn.split('十', 1)
        return (_DIG.get(a[-1], 1) if a else 1) * 10 + (_DIG.get(b[0], 0) if b else 0)
    if '百' in cn:
        h = re.match(r'^([零一二三四五六七八九两])?', cn)
        return (_DIG.get(h.group(1), 1) if h.group(1) else 1) * 100
    if '千' in cn:
        h = re.match(r'^([零一二三四五六七八九两])?', cn)
        return (_DIG.get(h.group(1), 1) if h.group(1) else 1) * 1000
    if '万' in cn:
        h = re.match(r'^([零一二三四五六七八九两])?', cn)
        return (_DIG.get(h.group(1), 1) if h.group(1) else 1) * 10000
    return _DIG.get(cn[0], 0)


def _age_to_int(num):
    """年龄词数值 -> 实龄。范围(五、六十 / 十八九 / 十五、六)取最大一档。"""
    cands = []
    for seg in re.split(r'[、,，~/至到 ]', str(num)):
        seg = seg.strip()
        if not seg:
            continue
        if seg.isdigit():
            cands.append(int(seg))
        else:
            m = re.match(r'([零一二三四五六七八九十百千万两]+)', seg)
            if m:
                cands.append(_cn_age(m.group(1)))
    cands = [c for c in cands if 0 < c <= 200]
    return max(cands) if cands else 0


def _iter_age(text):
    for m in AGE_RE.finditer(text):
        age = _age_to_int(m.group("num"))
        if age <= 0 or age > 200:
            continue
        s, e = m.start(), m.end()
        ctx = text[max(0, s - 22):e + 22]
        if re.search(_BLESS_RE, ctx):
            continue
        yield age, m.group(0), ctx


# 年龄词紧跟"下/以下/以上"多为名单/门槛规则，不作人物年龄
_THRESHOLD_RE = re.compile(r"岁以下|岁以上|以下|之上|之下")
# 单数人物称谓，用于"试探归属"（仅在该回唯一角色时启用）
_SINGLE_RE = re.compile(r"他|她|少年|少女|老者|老人|男子|女子|青年|汉子|剑修|剑士|剑师")


def _find_named(ctx, names, maxd=14):
    """仅在年龄词附近(maxd字)且距离最近的角色名，才视为显式归属。"""
    best, bd = None, None
    for n in names:
        for m in re.finditer(re.escape(n), ctx):
            d = abs(m.start() - 22)
            if d <= maxd and (bd is None or d < bd):
                bd, best = d, n
    return best


def _scan(extra_names):
    names = list(ROLE_SEED.keys())
    if extra_names:
        names += [x.strip() for x in extra_names.split(",") if x.strip()]
    seen, nd = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            nd.append(n)
    names = nd

    files = dt.list_novel_files() or []
    raw = "".join(dt._read_text(os.path.join(dt.NOVEL_RAW, f)) for f in files)
    chapters = dt._split_chapters(raw)

    role_agg = OrderedDict((n, {"name": n, "appear": [], "ages": []}) for n in names)
    per_chapter = []
    for seq, ch in enumerate(chapters, 1):
        body = raw[ch["start"]:ch["end"]]
        present = OrderedDict((n, body.count(n)) for n in names if body.count(n))
        am = []
        for age, word, ctx in _iter_age(body):
            named = _find_named(ctx, names)
            if named and not _THRESHOLD_RE.search(ctx):
                who, src = named, "explicit"
            elif len(present) == 1 and _SINGLE_RE.search(ctx):
                who, src = next(iter(present)), "infer"
            else:
                who, src = None, "unknown"
            am.append({"age": age, "word": word, "context": ctx.strip(), "who": who, "source": src})
            if who:
                role_agg[who]["ages"].append((age, seq, src, word))
        for n, _ in present.items():
            role_agg[n]["appear"].append(seq)
        per_chapter.append({"seq": seq, "raw_num": ch["num"], "title": ch["title"],
                            "characters": [{"name": n, "count": c} for n, c in present.items()],
                            "age_mentions": am})
    return names, per_chapter, role_agg


def _summary(agg):
    ages = agg["ages"]
    if not ages:
        return None
    cnt = Counter(a[0] for a in ages)
    most = cnt.most_common()
    notes = []
    if any(a[2] == "explicit" for a in ages):
        notes.append("有显式年龄(靠近角色名)")
    if any(a[2] == "infer" for a in ages):
        notes.append("有试探年龄(该回有主角未点名)")
    if len(most) > 1:
        notes.append("全书呈进境变化: " + ", ".join("%d×%d" % (a, c) for a, c in most))
    return {"rep": most[0][0], "span": [a[0] for a in most], "notes": "; ".join(notes)}


def _dump_json(per_chapter, role_agg, out):
    def roles():
        for n, a in role_agg.items():
            s = _summary(a)
            yield {"name": n, "chapter_count": len(a["appear"]), "appear_chapters": a["appear"],
                   "ages": [{"age": x[0], "seq": x[1], "source": x[2], "word": x[3]} for x in a["ages"]],
                   **({"rep_age": s["rep"], "age_span": s["span"], "notes": s["notes"]} if s else {})}
    data = {"project": "剑噬天下", "generated_by": "extract_character_ages",
            "total_chapters": len(per_chapter),
            "note": "seq=全书全局回号(1..N); raw_num=卷内章号(多卷重复); source: explicit/infer/unknown",
            "characters": list(roles()),
            "chapters": per_chapter}
    p = os.path.join(out, "全书角色年龄谱.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("[extract_character_ages] 写 JSON:", p)


def _dump_md(per_chapter, role_agg, out):
    L = ["# 《剑噬天下》全书角色年龄谱（扫描全本%d回）" % len(per_chapter), "",
         "> 由 `scripts/extract_character_ages.py` 确定性扫描，**原始证据需人工/AI复核**。",
         "> 年龄词去向：`显式`(附近有角色名) / `试探`(该回有主角未点名) / `未知`(无归属)。",
         "> 已过滤“长命百岁/万岁/千岁/千秋”；年龄主要围绕主角凌云(含现世林城)修为进境出现。", "",
         "---", "", "## 一、角色年龄汇总", "",
         "| 角色 | 代表年龄(岁) | 年龄区间 | 出场回数 | 出场章节(seq) | 年龄证据 |",
         "|---|---|---|---|---|---|"]
    for n, a in role_agg.items():
        if not a["appear"]:
            continue
        s = _summary(a)
        span = "/".join(str(x) for x in s["span"]) if s else "—"
        rep = str(s["rep"]) if s and s["rep"] else "—"
        chs = ", ".join(str(x) for x in a["appear"][:14]) + ("…" if len(a["appear"]) > 14 else "")
        notes = s["notes"] if s else "未提取到年龄词"
        L.append("| **%s** | %s | %s | %d | %s | %s |" % (n, rep, span, len(a["appear"]), chs, notes))
    L += ["", "---", "", "## 二、按回查：每一回出场角色与年龄线索", "", "%d 回，逐回列「出场角色 + 年龄词」。" % len(per_chapter), ""]
    for c in per_chapter:
        ch = ", ".join(x["name"] for x in c["characters"]) or "（无已收录角色）"
        L += ["### 第%d回　%s" % (c["seq"], c["title"]), "", "**出场角色**：" + ch, ""]
        if c["age_mentions"]:
            for m in c["age_mentions"]:
                tag = {"explicit": "显式", "infer": "试探", "unknown": "未知"}[m["source"]]
                L.append("- 「%s」(%d岁)[%s→%s] ~ %s" % (m["word"], m["age"], tag, m["who"] or "—", m["context"]))
        else:
            L.append("- 本回未提取到年龄词")
        L.append("")
    p = os.path.join(out, "全书角色年龄谱.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print("[extract_character_ages] 写 MD:", p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default=None)
    ap.add_argument("--out", default=DEFAULT_OUT_DIR)
    args = ap.parse_args()
    names, per_chapter, role_agg = _scan(args.names)
    os.makedirs(args.out, exist_ok=True)
    _dump_json(per_chapter, role_agg, args.out)
    _dump_md(per_chapter, role_agg, args.out)
    hits = sum(len(c["characters"]) for c in per_chapter)
    print("[extract_character_ages] 完成：%d 回，角色命中 %d 次，年龄词 %d 处"
          % (len(per_chapter), hits, sum(len(c["age_mentions"]) for c in per_chapter)))


if __name__ == "__main__":
    main()

