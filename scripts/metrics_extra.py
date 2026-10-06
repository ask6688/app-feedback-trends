
"""
14_metrics_extra.py — 客服指标 + 应用市场差评率

产出：
  scripts/cs_metrics.json    客服：批次 × 模块 的反馈量 / 反馈占比（无差评率）
  scripts/star_metrics.json  应用市场差评率：口径 × 来源 × 周期

口径要点：
  · 客服反馈占比 = 该模块会话数 ÷ 同期全量客服会话数（与市场侧「总反馈率」同一算法）
  · 应用市场差评率 = 该口径全量评论中 1~3 星占比；分母是**全量评论**，不是专题评论
  · 双端汇总一律分子分母各自相加后重新相除，禁止比例平均
  · 客服无星级 → 不算差评率
"""
import io, json, os, datetime as dt
from collections import Counter, defaultdict

OUT = os.environ["TREND_DATA_DIR"]
SCRATCH = os.path.join(OUT, "scripts")
from runtime import TOPICS, SOURCES
SCOPES = ["双端汇总", "IOS", "AND"]

M = json.load(io.open(os.path.join(OUT, "classification.json"), encoding="utf-8"))
C = json.load(io.open(os.path.join(OUT, "classification_cs.json"), encoding="utf-8"))
META = json.load(io.open(os.path.join(SCRATCH, "metrics_meta.json"), encoding="utf-8"))

checks = []

def rate(a, b):
    return (a / b) if b else 0.0

batch_map = {}
for r in C:
    fn = r.get("source_file", "")
    ps = r.get("period_start", "")
    pe = r.get("period_end", "")
    label = r.get("period") or (
        ("%s ～ %s" % (ps, pe)) if ps and pe else (fn or "未知批次")
    )
    key = (fn, ps, pe)
    if key not in batch_map:
        batch_map[key] = label

periods = [
    (fn, ps, pe, batch_map[(fn, ps, pe)])
    for fn, ps, pe in sorted(
        batch_map,
        key=lambda x: (x[1] or "", x[2] or "", x[0] or "")
    )
]

cs = {"periods": [], "by_module": {t: [] for t in TOPICS}, "overview": {}}

for fn, s, e, label in periods:

    sub = [
        r for r in C
        if r.get("source_file", "") == fn
        and r.get("period_start", "") == s
        and r.get("period_end", "") == e
    ]

    total = len(sub)
    axis = s[5:] if isinstance(s, str) and len(s) >= 10 else label

    cs["periods"].append({
        "file": fn,
        "start": s,
        "end": e,
        "label": label,
        "axis": axis,
        "total": total
    })

    for t in TOPICS:
        rel = sum(1 for r in sub if t in r["final_topics"])
        cs["by_module"][t].append({
            "file": fn,
            "label": label,
            "start": s,
            "end": e,
            "axis": axis,
            "total": total,
            "rel": rel,
            "rate": rate(rel, total),
        })

cs_total = len(C)
for t in TOPICS:
    rel = sum(1 for r in C if t in r["final_topics"])
    cs["overview"][t] = {"total": cs_total, "rel": rel, "rate": rate(rel, cs_total)}
cs["overview_total"] = cs_total
cs["multi_label_records"] = sum(1 for r in C if len(r["final_topics"]) > 1)
cs["no_topic_records"] = sum(1 for r in C if not r["final_topics"])

for t in TOPICS:
    s_rel = sum(x["rel"] for x in cs["by_module"][t])
    s_tot = sum(x["total"] for x in cs["periods"])
    if s_rel != cs["overview"][t]["rel"]:
        checks.append("客服 %s 批次 rel 之和 %d != 全量 %d" % (t, s_rel, cs["overview"][t]["rel"]))
    if s_tot != cs_total:
        checks.append("客服批次 total 之和 %d != 全量 %d" % (s_tot, cs_total))

def month_bounds(key):
    y, m = int(key[:4]), int(key[5:7])
    a = dt.date(y, m, 1)
    b = dt.date(y + (m // 12), (m % 12) + 1, 1) - dt.timedelta(days=1)
    return a, b

def star_block(rows):
    """rows → {total, neg, rate, stars{1..5}, by_source{...}}"""
    total = len(rows)
    neg = sum(1 for r in rows if r["is_negative"])
    stars = Counter(r["star"] for r in rows)
    by_source = {}
    for src in SOURCES:
        if src == "IOS":
            sr = [r for r in rows if r["platform"] == "IOS"]
        else:
            sr = [r for r in rows if r["platform"] == "AND" and r["and_channel"] == src]
        st = len(sr)
        ng = sum(1 for r in sr if r["is_negative"])
        by_source[src] = {"total": st, "neg": ng, "rate": rate(ng, st)}
    return {
        "total": total, "neg": neg, "rate": rate(neg, total),
        "stars": {**{str(i): stars.get(i, 0) for i in range(1, 6)},
                  **({"unrated": stars[None]} if stars[None] else {})},
        "by_source": by_source,
    }

def scope_rows(rows, scope):
    if scope == "双端汇总":
        return rows
    return [r for r in rows if r["platform"] == scope]

sm = {
    "monthly": {"range": "%s ～ %s" % (META["min_date"], META["max_date"])},
    "weekly": {"range": "%s ～ %s" % (META["window_start"], META["max_date"])},
}

W7_END = META["max_date"]
W7_START = (dt.date.fromisoformat(W7_END) - dt.timedelta(days=6)).isoformat()
sm["week7"] = {"range": "%s ～ %s" % (W7_START, W7_END)}

for mode, (s, e) in (("monthly", (META["min_date"], META["max_date"])),
                     ("weekly", (META["window_start"], META["max_date"])),
                     ("week7", (W7_START, W7_END))):
    sub = [r for r in M if s <= r["comment_date"] <= e]
    sm[mode]["scopes"] = {}
    for scope in SCOPES:
        sm[mode]["scopes"][scope] = star_block(scope_rows(sub, scope))

    a, b, c = (sm[mode]["scopes"][x] for x in ("IOS", "AND", "双端汇总"))
    if c["total"] != a["total"] + b["total"] or c["neg"] != a["neg"] + b["neg"]:
        checks.append("%s 差评率 双端 != IOS+AND" % mode)
    src_tot = sum(c["by_source"][x]["total"] for x in SOURCES)
    src_neg = sum(c["by_source"][x]["neg"] for x in SOURCES)
    if src_tot != c["total"] or src_neg != c["neg"]:
        checks.append("%s 差评率 各来源之和 != 双端合计 (%d/%d vs %d/%d)"
                      % (mode, src_tot, src_neg, c["total"], c["neg"]))
    if abs(c["rate"] - rate(c["neg"], c["total"])) > 1e-12:
        checks.append("%s 差评率 rate 不等于 neg/total" % mode)
    if sum(c["stars"].values()) != c["total"]:
        checks.append("%s 星级分布之和 != 全量" % mode)

if (dt.date.fromisoformat(W7_END) - dt.date.fromisoformat(W7_START)).days != 6:
    checks.append("近一周口径不是 7 个自然日：%s ~ %s" % (W7_START, W7_END))

assert not checks, "一致性校验失败：%s" % checks

with io.open(os.path.join(SCRATCH, "cs_metrics.json"), "w", encoding="utf-8") as f:
    json.dump(cs, f, ensure_ascii=False, indent=1)
with io.open(os.path.join(SCRATCH, "star_metrics.json"), "w", encoding="utf-8") as f:
    json.dump(sm, f, ensure_ascii=False, indent=1)

print("=== 客服（%d 条会话 / %d 个批次）===" % (cs_total, len(periods)))
for t in TOPICS:
    o = cs["overview"][t]
    print("  %-4s 反馈量 %6d  反馈占比 %6.2f%%" % (t, o["rel"], o["rate"] * 100))
print("  多模块会话 %d | 未命中 %d" % (cs["multi_label_records"], cs["no_topic_records"]))
print()
print("=== 应用市场差评率 ===")
for mode in ("monthly", "weekly"):
    c = sm[mode]["scopes"]["双端汇总"]
    print("  [%s] %s  差评率 %.2f%%  (%d / %d)"
          % (mode, sm[mode]["range"], c["rate"] * 100, c["neg"], c["total"]))
    for src in SOURCES:
        b = c["by_source"][src]
        print("      %-4s %6.2f%%  (%d / %d)" % (src, b["rate"] * 100, b["neg"], b["total"]))
    print("      星级分布:", c["stars"])
