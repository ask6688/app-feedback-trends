"""Whole-record topic classification, preserving the legacy record schema."""
import re
from collections import OrderedDict

DEL_PREFIX = re.compile(r"^[（(]该条评论已经被删除[）)]\s*")

def classify_market(rec, profile):
    """把一条新增市场记录转成与 classification.json 完全同构的记录。"""
    raw_text = rec.get("comment_text") or ""
    is_del = bool(DEL_PREFIX.match(raw_text))
    text = DEL_PREFIX.sub("", raw_text).strip()

    cand, reasons = profile.recall(text)

    final, judgement = [], {}
    for t in profile.names:
        matched, reason = profile.judge(t, text)
        judgement[t] = {"matched": matched, "reason": reason}
        if matched:
            final.append(t)

    star = rec.get("star")
    return OrderedDict([
        ("record_id", rec.get("_proposed_record_id")),
        ("comment_date", rec.get("comment_date")),
        ("platform", rec.get("platform")),
        ("and_channel", rec.get("and_channel")),
        ("star", star),
        ("comment_text", raw_text),
        ("is_negative", bool(star is not None and star <= 3)),
        ("is_deleted_marker", is_del),

        ("author", rec.get("author")),
        ("recalled_topics", cand),
        ("recall_reasons", reasons),
        ("final_topics", final),
        ("semantic_judgement", judgement),
        ("semantic_reason", "；".join(
            "%s:%s" % (t, judgement[t]["reason"]) for t in profile.names if judgement[t]["matched"]
        ) or "未命中任何一级专题"),
        ("_incremental", OrderedDict([
            ("is_new", True),
            ("preview_id", rec.get("preview_id")),
            ("dedup_status", rec.get("dedup_status")),
            ("new_reason", rec.get("new_reason")),
            ("record_key", rec.get("record_key")),
            ("source_file", rec.get("source_file")),
            ("source_sheet", rec.get("source_sheet")),
            ("source_row", rec.get("source_row")),
            ("comment_time_raw", rec.get("comment_time_raw")),
            ("title", rec.get("title")),
            ("author", rec.get("author")),
            ("model", rec.get("model")),
            ("app_version", rec.get("app_version")),
            ("likes", rec.get("likes")),
            ("imported_at", rec.get("imported_at")),
        ])),
    ])

def classify_cs(rec, profile):
    """Preserved legacy behavior."""

    text = rec.get("cs_text_clean") or ""

    cand, reasons = profile.recall(text)

    final, judgement = [], {}
    for t in profile.names:
        matched, reason = profile.judge(t, text, domain="cs")
        judgement[t] = {"matched": matched, "reason": reason}
        if matched:
            final.append(t)

    return OrderedDict([
        ("record_id", rec.get("_proposed_record_id")),
        ("period", rec.get("period")),
        ("period_start", rec.get("period_start")),
        ("period_end", rec.get("period_end")),
        ("source_file", rec.get("source_file")),
        ("cs_text", rec.get("cs_text")),
        ("cs_text_clean", text),
        ("user_turns", rec.get("user_turns")),
        ("recalled_topics", cand),
        ("recall_reasons", reasons),
        ("final_topics", final),
        ("semantic_judgement", judgement),
        ("semantic_reason", "；".join(
            "%s:%s" % (t, judgement[t]["reason"]) for t in profile.names if judgement[t]["matched"]
        ) or "未命中任何一级专题"),
        ("_incremental", OrderedDict([
            ("is_new", True),
            ("preview_id", rec.get("preview_id")),
            ("dedup_status", rec.get("dedup_status")),
            ("new_reason", rec.get("new_reason")),
            ("record_key", rec.get("record_key")),
            ("source_file", rec.get("source_file")),
            ("source_sheet", rec.get("source_sheet")),
            ("source_row", rec.get("source_row")),
            ("source_path", rec.get("source_path")),
            ("source_is_lossy_export", rec.get("source_is_lossy_export")),
            ("source_lossy_reason", rec.get("source_lossy_reason")),
            ("imported_at", rec.get("imported_at")),
        ])),
    ])
