
"""Preserved legacy behavior."""

import io, json, os, csv, datetime as dt
from collections import defaultdict, Counter

OUT = os.environ["TREND_DATA_DIR"]
SCRATCH = os.path.join(OUT, "scripts")
from runtime import TOPICS, SOURCES
SCOPES = ["IOS", "AND", "双端汇总"]

C = json.load(io.open(os.path.join(OUT, "classification.json"), encoding="utf-8"))
for r in C:
    r["_d"] = dt.date.fromisoformat(r["comment_date"])
    r["_topics"] = set(r["final_topics"])

MAX_DATE = max(r["_d"] for r in C)
MIN_DATE = min(r["_d"] for r in C)
print("数据范围:", MIN_DATE, "→", MAX_DATE, "| 记录数:", len(C))

def month_key(d):
    return "%04d-%02d" % (d.year, d.month)

def month_bounds(key):
    y, m = int(key[:4]), int(key[5:7])
    start = dt.date(y, m, 1)
    end = dt.date(y + (m // 12), (m % 12) + 1, 1) - dt.timedelta(days=1)
    return start, end

def month_add(key, n):
    y, m = int(key[:4]), int(key[5:7])
    t = (y * 12 + (m - 1)) + n
    return "%04d-%02d" % (t // 12, t % 12 + 1)

ALL_MONTHS = []
k = month_key(MIN_DATE)
while k <= month_key(MAX_DATE):
    ALL_MONTHS.append(k)
    k = month_add(k, 1)

def is_complete_month(key):
    s, e = month_bounds(key)

    return s >= MIN_DATE and e <= MAX_DATE

def monday_of(d):
    return d - dt.timedelta(days=d.weekday())

def month_minus(d, n):
    y, m = d.year, d.month - n
    while m <= 0:
        m += 12
        y -= 1
    day = min(d.day, [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return dt.date(y, m, day)

WINDOW_START = month_minus(MAX_DATE, 3)
FIRST_MONDAY = monday_of(WINDOW_START)

WEEKS = []
w = FIRST_MONDAY
while w <= MAX_DATE:
    WEEKS.append(w)
    w += dt.timedelta(days=7)

def week_label(w):
    return "%s ~ %s" % (w.isoformat(), (w + dt.timedelta(days=6)).isoformat())

def is_complete_week(w):
    return (w + dt.timedelta(days=6)) <= MAX_DATE

print("最近三个月窗口起点:", WINDOW_START, "| 首个自然周:", FIRST_MONDAY,
      "| 周数:", len(WEEKS), "| 最后一周完整:", is_complete_week(WEEKS[-1]))

def blank():
    return {"total": 0, "topic": {t: 0 for t in TOPICS}, "neg": {t: 0 for t in TOPICS}}

def add(acc, r):
    acc["total"] += 1
    for t in r["_topics"]:
        acc["topic"][t] += 1
        if r["is_negative"]:
            acc["neg"][t] += 1

def combine(a, b):
    """双端汇总：分子分母各自相加"""
    o = {"total": a["total"] + b["total"],
         "topic": {t: a["topic"][t] + b["topic"][t] for t in TOPICS},
         "neg": {t: a["neg"][t] + b["neg"][t] for t in TOPICS}}
    return o

def rows_from(acc, period, scope, complete):
    out = []
    for t in TOPICS:
        tot = acc["total"]
        tc = acc["topic"][t]
        nc = acc["neg"][t]
        out.append({
            "period": period,
            "platform_scope": scope,
            "topic": t,
            "total_comments": tot,
            "topic_comments": tc,
            "topic_negative_comments": nc,
            "feedback_rate": (tc / tot) if tot else 0.0,
            "negative_feedback_rate": (nc / tot) if tot else 0.0,
            "is_complete_period": complete,
        })
    return out

monthly_rows = []
monthly_index = {}
for key in ALL_MONTHS:
    s, e = month_bounds(key)
    accs = {sc: blank() for sc in ["IOS", "AND"]}
    for r in C:
        if s <= r["_d"] <= e:
            add(accs[r["platform"]], r)
    accs["双端汇总"] = combine(accs["IOS"], accs["AND"])
    comp = is_complete_month(key)
    for sc in SCOPES:
        rs = rows_from(accs[sc], key, sc, comp)
        monthly_rows.extend(rs)
        for row in rs:
            monthly_index[(key, sc, row["topic"])] = row

weekly_rows = []
weekly_index = {}
for w0 in WEEKS:
    s, e = w0, w0 + dt.timedelta(days=6)
    accs = {sc: blank() for sc in ["IOS", "AND"]}
    for r in C:
        if s <= r["_d"] <= e:
            add(accs[r["platform"]], r)
    accs["双端汇总"] = combine(accs["IOS"], accs["AND"])
    comp = is_complete_week(w0)
    for sc in SCOPES:
        rs = rows_from(accs[sc], week_label(w0), sc, comp)
        rs_ = rs
        weekly_rows.extend(rs_)
        for row in rs_:
            weekly_index[(week_label(w0), sc, row["topic"])] = row

overall_acc = {sc: blank() for sc in ["IOS", "AND"]}
for r in C:
    add(overall_acc[r["platform"]], r)
overall_acc["双端汇总"] = combine(overall_acc["IOS"], overall_acc["AND"])

overview = {sc: {} for sc in SCOPES}
for sc in SCOPES:
    a = overall_acc[sc]
    for t in TOPICS:
        overview[sc][t] = {
            "total_comments": a["total"],
            "topic_comments": a["topic"][t],
            "topic_negative_comments": a["neg"][t],
            "feedback_rate": a["topic"][t] / a["total"] if a["total"] else 0.0,
            "negative_feedback_rate": a["neg"][t] / a["total"] if a["total"] else 0.0,
        }

checks = {"monthly": {"passed": 0, "failed": []}, "weekly": {"passed": 0, "failed": []},
          "combined": {"passed": 0, "failed": []}}
EPS = 1e-9

def check_rows(rows, bucket, complete_flag_key="is_complete_period"):
    idx = {(r["period"], r["platform_scope"], r["topic"]): r for r in rows}
    for r in rows:
        p, sc, t = r["period"], r["platform_scope"], r["topic"]
        tot, tc, nc = r["total_comments"], r["topic_comments"], r["topic_negative_comments"]
        errs = []
        if tc > tot:
            errs.append("topic_comments>total_comments")
        if nc > tc:
            errs.append("topic_negative_comments>topic_comments")
        if abs(r["feedback_rate"] - (tc / tot if tot else 0)) > EPS:
            errs.append("feedback_rate 不等于 topic/total")
        if abs(r["negative_feedback_rate"] - (nc / tot if tot else 0)) > EPS:
            errs.append("negative_feedback_rate 不等于 neg/total")
        if errs:
            checks[bucket]["failed"].append({"key": [p, sc, t], "errors": errs})
        else:
            checks[bucket]["passed"] += 1

check_rows(monthly_rows, "monthly")
check_rows(weekly_rows, "weekly")

for rows, bucket in [(monthly_rows, "monthly"), (weekly_rows, "weekly")]:
    idx = {(r["period"], r["platform_scope"], r["topic"]): r for r in rows}
    periods = sorted(set(r["period"] for r in rows))
    for p in periods:
        for t in TOPICS:
            i = idx[(p, "IOS", t)]
            a = idx[(p, "AND", t)]
            c = idx[(p, "双端汇总", t)]
            errs = []
            if c["topic_comments"] != i["topic_comments"] + a["topic_comments"]:
                errs.append("双端 topic_comments != IOS+AND")
            if c["total_comments"] != i["total_comments"] + a["total_comments"]:
                errs.append("双端 total_comments != IOS+AND")
            if c["topic_negative_comments"] != i["topic_negative_comments"] + a["topic_negative_comments"]:
                errs.append("双端 topic_negative_comments != IOS+AND")
            if abs(c["feedback_rate"] - (c["topic_comments"] / c["total_comments"] if c["total_comments"] else 0)) > EPS:
                errs.append("双端 feedback_rate 未按合并后分子分母重算")
            avg = (i["feedback_rate"] + a["feedback_rate"]) / 2
            if abs(c["feedback_rate"] - avg) < EPS and abs(i["feedback_rate"] - a["feedback_rate"]) > 1e-6:
                errs.append("疑似使用了比例平均")
            if errs:
                checks["combined"]["failed"].append({"key": [p, t], "errors": errs})
            else:
                checks["combined"]["passed"] += 1

with io.open(os.path.join(OUT, "monthly_metrics.json"), "w", encoding="utf-8") as f:
    json.dump(monthly_rows, f, ensure_ascii=False)
with io.open(os.path.join(OUT, "weekly_metrics.json"), "w", encoding="utf-8") as f:
    json.dump(weekly_rows, f, ensure_ascii=False)
for name, rows in (("monthly_metrics", monthly_rows), ("weekly_metrics", weekly_rows)):
    with open(os.path.join(OUT, name + ".csv"), "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
assert not any(block["failed"] for block in checks.values()), "Metric consistency checks failed"

meta = {
    "min_date": MIN_DATE.isoformat(),
    "max_date": MAX_DATE.isoformat(),
    "months": ALL_MONTHS,
    "monthly_complete": {m: is_complete_month(m) for m in ALL_MONTHS},
    "window_start": WINDOW_START.isoformat(),
    "first_week_monday": FIRST_MONDAY.isoformat(),
    "weeks": [{"label": week_label(w), "start": w.isoformat(),
               "end": (w + dt.timedelta(days=6)).isoformat(),
               "is_complete": is_complete_week(w)} for w in WEEKS],
    "overview": overview,
    "checks": checks,
    "precision": "rates stored as full float (double precision), formatted to % only in HTML",
}
with io.open(os.path.join(SCRATCH, "metrics_meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("\n=== 校验结果 ===")
for b in ["monthly", "weekly", "combined"]:
    print("%-9s passed=%d failed=%d" % (b, checks[b]["passed"], len(checks[b]["failed"])))
    for x in checks[b]["failed"][:5]:
        print("   ✗", x)

print("\n=== 全周期概览（双端汇总）===")
for t in TOPICS:
    o = overview["双端汇总"][t]
    print("  %s: 相关 %d / 全量 %d = %.4f%%  | 差评 %d → %.4f%%" % (
        t, o["topic_comments"], o["total_comments"],
        o["feedback_rate"] * 100, o["topic_negative_comments"],
        o["negative_feedback_rate"] * 100))
print("\n最新完整月:", next(iter(reversed([m for m in ALL_MONTHS if is_complete_month(m)])), None))
print("最新月(未完整):", ALL_MONTHS[-1], "| 最新周完整:", is_complete_week(WEEKS[-1]))
