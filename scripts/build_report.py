
"""Preserved legacy behavior."""

import io, json, os, shutil, datetime as dt
from collections import Counter, defaultdict

OUT = os.environ["TREND_DATA_DIR"]
SCRATCH = os.path.join(OUT, "scripts")
from runtime import TOPICS, PROFILE_META, SOURCES
SCOPES = ["双端汇总", "IOS", "AND"]

C = json.load(io.open(os.path.join(OUT, "classification.json"), encoding="utf-8"))
M = json.load(io.open(os.path.join(OUT, "monthly_metrics.json"), encoding="utf-8"))
W = json.load(io.open(os.path.join(OUT, "weekly_metrics.json"), encoding="utf-8"))
META = json.load(io.open(os.path.join(SCRATCH, "metrics_meta.json"), encoding="utf-8"))
RAW_AUDIT = json.load(io.open(os.path.join(SCRATCH, "audit_raw.json"), encoding="utf-8"))

STAR = json.load(io.open(os.path.join(SCRATCH, "star_metrics.json"), encoding="utf-8"))
CSM = json.load(io.open(os.path.join(SCRATCH, "cs_metrics.json"), encoding="utf-8"))
CSC = json.load(io.open(os.path.join(OUT, "classification_cs.json"), encoding="utf-8"))

num = lambda n: ("{:,}".format(n))
pct2 = lambda x: "%.2f%%" % (x * 100)
pct1 = lambda x: "%.1f%%" % (x * 100)

W7_END = META["max_date"]
W7_START = (dt.date.fromisoformat(W7_END) - dt.timedelta(days=6)).isoformat()
W7_RANGE = "%s ～ %s" % (W7_START, W7_END)
assert (dt.date.fromisoformat(W7_END) - dt.date.fromisoformat(W7_START)).days == 6, "近一周口径不是 7 天"

assert STAR["week7"]["range"] == W7_RANGE, "近一周窗口与 star_metrics 不一致：%s vs %s" % (W7_RANGE, STAR["week7"]["range"])

def month_bounds(key):
    y, m = int(key[:4]), int(key[5:7])
    s = dt.date(y, m, 1)
    e = dt.date(y + (m // 12), (m % 12) + 1, 1) - dt.timedelta(days=1)
    return s, e

def pack(rows, kind):
    """rows → {scope: {topic: [ {period, axis, start, end, complete, total, rel, neg, rate, negRate} ]}}"""
    out = {sc: {t: [] for t in TOPICS} for sc in SCOPES}
    for r in rows:
        p = r["period"]
        if kind == "monthly":
            s, e = month_bounds(p)
            axis = p[2:]
            label = p
        else:
            s = dt.date.fromisoformat(p.split(" ~ ")[0])
            e = dt.date.fromisoformat(p.split(" ~ ")[1])
            axis = s.strftime("%m-%d")
            label = p
        out[r["platform_scope"]][r["topic"]].append({
            "period": label,
            "axis": axis,
            "start": s.isoformat(),
            "end": e.isoformat(),
            "complete": bool(r["is_complete_period"]),
            "total": r["total_comments"],
            "rel": r["topic_comments"],
            "neg": r["topic_negative_comments"],
            "rate": r["feedback_rate"],
            "negRate": r["negative_feedback_rate"],
        })
    return out

MONTHLY = pack(M, "monthly")
WEEKLY = pack(W, "weekly")

def pack_daily(start, end):
    days = []
    d = dt.date.fromisoformat(start)
    d_end = dt.date.fromisoformat(end)
    while d <= d_end:
        days.append(d.isoformat())
        d += dt.timedelta(days=1)
    out = {sc: {t: [] for t in TOPICS} for sc in SCOPES}
    for day in days:
        sub = [r for r in C if r["comment_date"] == day]
        for sc in SCOPES:
            rs = sub if sc == "双端汇总" else [r for r in sub if r["platform"] == sc]
            total = len(rs)
            for t in TOPICS:
                rel = sum(1 for r in rs if t in r["final_topics"])
                neg = sum(1 for r in rs if t in r["final_topics"] and r["is_negative"])
                out[sc][t].append({
                    "period": day,
                    "axis": day[5:],
                    "start": day,
                    "end": day,
                    "complete": day != end,
                    "total": total,
                    "rel": rel,
                    "neg": neg,
                    "rate": (rel / total) if total else 0.0,
                    "negRate": (neg / total) if total else 0.0,
                })
    return out

def overview_for(start, end, scope):
    sub = [r for r in C if start <= r["comment_date"] <= end
           and (scope == "双端汇总" or r["platform"] == scope)]
    total = len(sub)
    out = {}
    for t in TOPICS:
        rel = sum(1 for r in sub if t in r["final_topics"])
        neg = sum(1 for r in sub if t in r["final_topics"] and r["is_negative"])
        out[t] = {
            "total": total, "rel": rel, "neg": neg,
            "rate": (rel / total) if total else 0.0,
            "negRate": (neg / total) if total else 0.0,
        }
    return out

OVERVIEW = {
    "monthly": {sc: overview_for(META["min_date"], META["max_date"], sc) for sc in SCOPES},
    "weekly":  {sc: overview_for(META["window_start"], META["max_date"], sc) for sc in SCOPES},
    "week7":   {sc: overview_for(W7_START, W7_END, sc) for sc in SCOPES},
}

overview = OVERVIEW["monthly"]
ov_check = []
for sc in SCOPES:
    for t in TOPICS:
        o = META["overview"][sc][t]
        mine = overview[sc][t]
        for k, ref in (("total", o["total_comments"]), ("rel", o["topic_comments"]),
                       ("neg", o["topic_negative_comments"])):
            if mine[k] != ref:
                ov_check.append("%s/%s/%s: %s != %s" % (sc, t, k, mine[k], ref))
        if abs(mine["rate"] - o["feedback_rate"]) > 1e-12:
            ov_check.append("%s/%s/rate 不一致" % (sc, t))
        if abs(mine["negRate"] - o["negative_feedback_rate"]) > 1e-12:
            ov_check.append("%s/%s/negRate 不一致" % (sc, t))
assert not ov_check, "概览与独立指标不一致：%s" % ov_check[:6]

for md in ("monthly", "weekly", "week7"):
    for t in TOPICS:
        a, b, c = OVERVIEW[md]["IOS"][t], OVERVIEW[md]["AND"][t], OVERVIEW[md]["双端汇总"][t]
        assert c["total"] == a["total"] + b["total"], (md, t, "total")
        assert c["rel"] == a["rel"] + b["rel"], (md, t, "rel")
        assert c["neg"] == a["neg"] + b["neg"], (md, t, "neg")
        assert abs(c["rate"] - (c["rel"] / c["total"] if c["total"] else 0)) < 1e-12
        assert abs(c["negRate"] - (c["neg"] / c["total"] if c["total"] else 0)) < 1e-12

assert OVERVIEW["week7"]["双端汇总"][TOPICS[0]]["total"] == \
    len([r for r in C if W7_START <= r["comment_date"] <= W7_END]), "近一周概览分母 != 基线样本量"

DAILY7 = pack_daily(W7_START, W7_END)
assert all(len(DAILY7[sc][t]) == 7 for sc in SCOPES for t in TOPICS), "近一周日粒度序列不是 7 个点"

for sc in SCOPES:
    for t in TOPICS:
        rows = DAILY7[sc][t]
        o = OVERVIEW["week7"][sc][t]
        assert sum(r["rel"] for r in rows) == o["rel"], ("近一周日序列 rel 之和", sc, t)
        assert sum(r["neg"] for r in rows) == o["neg"], ("近一周日序列 neg 之和", sc, t)
        assert rows[-1]["total"] == len([r for r in C if r["comment_date"] == W7_END
                                         and (sc == "双端汇总" or r["platform"] == sc)]), ("末日全量", sc)

STAR_PAYLOAD = {
    md: {
        "range": STAR[md]["range"],
        "scopes": {
            sc: {
                "total": STAR[md]["scopes"][sc]["total"],
                "neg": STAR[md]["scopes"][sc]["neg"],
                "rate": STAR[md]["scopes"][sc]["rate"],
                "stars": STAR[md]["scopes"][sc]["stars"],
                "bySource": STAR[md]["scopes"][sc]["by_source"],
            } for sc in SCOPES
        },
    } for md in ("monthly", "weekly", "week7")
}

for md in ("monthly", "weekly", "week7"):
    for sc in SCOPES:
        blk = STAR_PAYLOAD[md]["scopes"][sc]
        assert abs(blk["rate"] - ((blk["neg"] / blk["total"] if blk["total"] else 0))) < 1e-12, (md, sc, "rate")
        assert sum(blk["stars"].values()) == blk["total"], (md, sc, "stars")
    a = STAR_PAYLOAD[md]["scopes"]["IOS"]
    b = STAR_PAYLOAD[md]["scopes"]["AND"]
    c = STAR_PAYLOAD[md]["scopes"]["双端汇总"]
    assert c["total"] == a["total"] + b["total"], (md, "total")
    assert c["neg"] == a["neg"] + b["neg"], (md, "neg")
    assert sum(c["bySource"][s]["total"] for s in SOURCES) == c["total"], (md, "src total")
    assert sum(c["bySource"][s]["neg"] for s in SOURCES) == c["neg"], (md, "src neg")

import datetime as _dt

_cs_p = CSM["periods"]

def _cs_days(p):
    try:
        return (
            _dt.date.fromisoformat(p["end"])
            - _dt.date.fromisoformat(p["start"])
        ).days + 1
    except Exception:
        return 0

CS_PAYLOAD = {
    "range": "%s ～ %s" % ((_cs_p[0]["start"] if _cs_p else META["min_date"]), (_cs_p[-1]["end"] if _cs_p else META["max_date"])),
    "min": (_cs_p[0]["start"] if _cs_p else META["min_date"]),
    "max": (_cs_p[-1]["end"] if _cs_p else META["max_date"]),
    "latest": (_cs_p[-1]["end"] if _cs_p else META["max_date"]),
    "batches": len(_cs_p),
    "total": CSM["overview_total"],
    "hitTotal": CSM["overview_total"] - CSM["no_topic_records"],
    "multi": CSM["multi_label_records"],
    "none": CSM["no_topic_records"],
    "periods": [{
        "label": p["label"],
        "start": p["start"],
        "end": p["end"],
        "axis": p.get("axis") or p["start"][5:],
        "days": _cs_days(p),
        "total": p["total"],
        "short": _cs_days(p) < 5,
    } for p in _cs_p],
    "overview": {t: CSM["overview"][t] for t in TOPICS},
    "byModule": {
        t: [
            dict(r, short=_cs_days(_cs_p[i]) < 5)
            for i, r in enumerate(CSM["by_module"][t])
        ]
        for t in TOPICS
    },
}

assert sum(p["total"] for p in CS_PAYLOAD["periods"]) == CS_PAYLOAD["total"], "客服批次合计"
assert len(CS_PAYLOAD["periods"]) == CS_PAYLOAD["batches"], "客服批次数量"
for t in TOPICS:
    o = CS_PAYLOAD["overview"][t]
    assert abs(o["rate"] - ((o["rel"] / o["total"] if o["total"] else 0))) < 1e-12, ("客服占比", t)
    assert o["total"] == CS_PAYLOAD["total"], ("客服分母", t)
    ser = CS_PAYLOAD["byModule"][t]
    assert sum(r["rel"] for r in ser) == o["rel"], ("客服批次 rel 之和", t)
    for r in ser:
        assert abs(r["rate"] - ((r["rel"] / r["total"] if r["total"] else 0))) < 1e-12, ("客服批次占比", t, r["label"])
assert CS_PAYLOAD["hitTotal"] == CS_PAYLOAD["total"] - CS_PAYLOAD["none"], "客服命中会话"

def baseline_for(start, end):
    sub = [r for r in C if start <= r["comment_date"] <= end]
    ios = sum(1 for r in sub if r["platform"] == "IOS")
    and_ = sum(1 for r in sub if r["platform"] == "AND")
    latest = max((r["comment_date"] for r in sub), default=META["max_date"])
    return {"range": "%s ～ %s" % (start, end), "ios": ios, "and": and_, "latest": latest}

BASELINE = {
    "monthly": baseline_for(META["min_date"], META["max_date"]),
    "weekly": baseline_for(META["window_start"], META["max_date"]),
    "week7": baseline_for(W7_START, W7_END),
}

assert BASELINE["week7"]["ios"] + BASELINE["week7"]["and"] == \
    OVERVIEW["week7"]["双端汇总"][TOPICS[0]]["total"], "近一周基线样本量 != 概览分母"

weeks_all = META["weeks"]
full_months = [m for m in META["months"] if META["monthly_complete"][m]]
s = {
    "minDate": META["min_date"],
    "maxDate": META["max_date"],
    "dataPeriod": "%s ～ %s" % (META["min_date"], META["max_date"]),
    "iosCount": RAW_AUDIT["IOS"]["count"],
    "andCount": RAW_AUDIT["AND"]["count"],
    "totalCount": RAW_AUDIT["total_records"],
    "channels": RAW_AUDIT["AND_channels"],
    "negativeDef": "1～3 星为差评",
    "latestMonth": META["months"][-1],
    "latestMonthComplete": META["monthly_complete"][META["months"][-1]],
    "latestWeek": weeks_all[-1]["label"],
    "latestWeekComplete": weeks_all[-1]["is_complete"],
    "lastCompleteMonth": (full_months[-1] if full_months else None),
    "windowStart": META["window_start"],
    "week7Start": W7_START,
    "week7Range": W7_RANGE,
    "monthRange": "%s ～ %s" % (META["months"][0], META["months"][-1]),
    "weekRange": "%s ～ %s" % (weeks_all[0]["start"], weeks_all[-1]["end"]),
    "negativeTotal": sum(1 for r in C if r["is_negative"]),
}

payload = {
    "topics": TOPICS,
    "profile": PROFILE_META,
    "sources": SOURCES,
    "datasetId": os.environ.get("TREND_DATASET_ID", "local"),
    "summary": s,
    "baseline": BASELINE,
    "overview": OVERVIEW,
    "monthly": MONTHLY,
    "weekly": WEEKLY,
    "daily7": DAILY7,
    "star": STAR_PAYLOAD,
    "cs": CS_PAYLOAD,
}

tpl = io.open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "dashboard.html"), encoding="utf-8").read()
html = tpl.replace("__DATA_JSON__", json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c"))
with io.open(os.path.join(OUT, "report.html"), "w", encoding="utf-8") as f:
    f.write(html)

details = [[r["record_id"], r["comment_date"], r["platform"], r["and_channel"],
            r["star"], r["final_topics"], r["comment_text"]] for r in C]
js = "window.__DETAILS__=" + json.dumps(details, ensure_ascii=False, separators=(",", ":")) + ";"
with io.open(os.path.join(OUT, "assets", "details.js"), "w", encoding="utf-8") as f:
    f.write(js)

CS_TEXT_CAP = 600
_pidx = {
    (p["file"], p["start"], p["end"]): i
    for i, p in enumerate(_cs_p)
}
cs_details = []
for r in CSC:
    txt = r["cs_text_clean"]
    if len(txt) > CS_TEXT_CAP:
        txt = txt[:CS_TEXT_CAP] + "…"
    cs_details.append([
        int(r["record_id"][2:]),
        _pidx[(
            r.get("source_file", ""),
            r.get("period_start", ""),
            r.get("period_end", ""),
        )],
        [TOPICS.index(t) for t in TOPICS if t in r["final_topics"]],
        txt,
    ])
assert len(cs_details) == len(CSC) == CS_PAYLOAD["total"], "客服明细条数不一致"
assert max((x[1] for x in cs_details), default=-1) < CS_PAYLOAD["batches"], "客服批次下标越界"
cs_js = "window.__DETAILS_CS__=" + json.dumps(cs_details, ensure_ascii=False, separators=(",", ":")) + ";"
with io.open(os.path.join(OUT, "assets", "details_cs.js"), "w", encoding="utf-8") as f:
    f.write(cs_js)

audit = {"generated_at": dt.datetime.now().isoformat(), "profile": PROFILE_META,
         "totals": s, "checks": META["checks"], "data_acquisition": "Local files only"}
with io.open(os.path.join(OUT, "audit.json"), "w", encoding="utf-8") as f:
    json.dump(audit, f, ensure_ascii=False, indent=2)
print("Dashboard:", os.path.join(OUT, "report.html"))
