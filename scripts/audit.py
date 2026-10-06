
"""02_audit_raw.py — 原始数据质量体检（不做任何删除）"""
import io, json, os
from collections import Counter, defaultdict

OUT = os.environ["TREND_DATA_DIR"]
SCRATCH = os.path.join(OUT, "scripts")

R = json.load(io.open(os.path.join(SCRATCH, "raw_records.json"), encoding="utf-8"))

rep = {}
rep["total_records"] = len(R)

ios = [r for r in R if r["platform"] == "IOS"]
and_ = [r for r in R if r["platform"] == "AND"]

def span(rs):
    ds = sorted(r["comment_date"] for r in rs if r["comment_date"])
    return (ds[0], ds[-1]) if ds else (None, None)

rep["IOS"] = {"count": len(ios), "min_date": span(ios)[0], "max_date": span(ios)[1]}
rep["AND"] = {"count": len(and_), "min_date": span(and_)[0], "max_date": span(and_)[1]}
rep["overall_max_date"] = span(R)[1]
rep["overall_min_date"] = span(R)[0]

ch = Counter(r["and_channel"] for r in and_)
rep["AND_channels"] = dict(ch)

rep["star_distribution"] = {
    "IOS": dict(sorted(Counter(r["star"] for r in ios).items(), key=lambda x: (x[0] is None, x[0]))),
    "AND": dict(sorted(Counter(r["star"] for r in and_).items(), key=lambda x: (x[0] is None, x[0]))),
}
rep["negative_definition"] = "star <= 3"

def empties(rs):
    return {
        "empty_text": sum(1 for r in rs if not r["comment_text"]),
        "null_date": sum(1 for r in rs if not r["comment_date"]),
        "null_star": sum(1 for r in rs if r["star"] is None),
        "text_len_lt_2": sum(1 for r in rs if len(r["comment_text"]) < 2),
    }
rep["empties"] = {"IOS": empties(ios), "AND": empties(and_)}

def dup(rs, label):
    seen = defaultdict(list)
    for r in rs:
        k = (r["platform"], r["and_channel"], r["comment_date"], r["star"], r["comment_text"])
        seen[k].append(r["record_id"])
    groups = {k: v for k, v in seen.items() if len(v) > 1}
    extra = sum(len(v) - 1 for v in groups.values())

    seen2 = defaultdict(list)
    for r in rs:
        seen2[r["comment_text"]].append(r["record_id"])
    g2 = {k: v for k, v in seen2.items() if len(v) > 1 and k}
    extra2 = sum(len(v) - 1 for v in g2.values())
    return {
        "exact_duplicate_groups": len(groups),
        "exact_duplicate_extra_rows": extra,
        "same_text_groups": len(g2),
        "same_text_extra_rows": extra2,
        "sample_exact_dup_ids": [v for v in list(groups.values())[:5]],
    }

rep["duplicates"] = {"IOS": dup(ios, "IOS"), "AND": dup(and_, "AND")}

text_channels = defaultdict(set)
for r in and_:
    if r["comment_text"]:
        text_channels[r["comment_text"]].add(r["and_channel"])
cross = {t: sorted(cs) for t, cs in text_channels.items() if len(cs) > 1}
rep["cross_channel_same_text_groups"] = len(cross)
rep["cross_channel_same_text_samples"] = [
    {"text": t[:60], "channels": cs} for t, cs in list(cross.items())[:5]
]

tc2 = defaultdict(set)
for r in R:
    if r["comment_text"]:
        tc2[r["comment_text"]].add(r["platform"])
cross2 = {t: sorted(cs) for t, cs in tc2.items() if len(cs) > 1}
rep["cross_platform_same_text_groups"] = len(cross2)

bym = Counter((r["platform"], r["comment_date"][:7]) for r in R if r["comment_date"])
months = sorted(set(m for _, m in bym))
rep["month_list"] = months
rep["records_per_month"] = {
    m: {"IOS": bym.get(("IOS", m), 0), "AND": bym.get(("AND", m), 0)} for m in months
}

rep["dedup_decision"] = {
    "has_stable_unique_id": False,
    "policy": "保留原始全部记录，不做任何删除",
    "rationale": "两份导出均无评论唯一 ID；同一商店同一用户在不同日期可发表相同短评（如『垃圾』），"
                 "仅凭正文相同删除会造成误删，故最终统计采用原始记录。"
                 "完全相同的五元组重复已单独记录数量供复核。",
    "counting_basis": "raw (原始记录)",
}

with io.open(os.path.join(SCRATCH, "audit_raw.json"), "w", encoding="utf-8") as f:
    json.dump(rep, f, ensure_ascii=False, indent=2)

print(json.dumps({k: rep[k] for k in
                  ["total_records", "IOS", "AND", "AND_channels", "overall_min_date",
                   "overall_max_date", "empties", "duplicates",
                   "cross_channel_same_text_groups", "cross_platform_same_text_groups"]},
                 ensure_ascii=False, indent=2))
print("\n星级分布:", json.dumps(rep["star_distribution"], ensure_ascii=False))
print("\n月份:", rep["month_list"][0], "→", rep["month_list"][-1], "共", len(rep["month_list"]), "个月")
