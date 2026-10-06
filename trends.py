#!/usr/bin/env python3
"""Preview incremental feedback, commit history, and build a local trend dashboard."""
import argparse
import contextlib
import functools
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

from trendlib import importer
from trendlib.classifier import classify_market, classify_cs
from trendlib.profiles import DEFAULT_PROFILE, load_profile

ROOT = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def lock(directory):
    # ponytail: one lock per dataset; use a database if concurrent writers become necessary.
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError("Dataset is locked; if a previous process crashed, remove its .lock after verifying it stopped")
    try:
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def token(directory):
    path = directory / "history.json"
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "empty"


def validate_records(market, cs, profile):
    if not isinstance(market, list) or not isinstance(cs, list):
        raise ValueError("History files must contain JSON arrays")
    ids = set()
    for records, prefix in ((market, "R"), (cs, "CS")):
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("History records must be objects")
            rid = record.get("record_id")
            if not isinstance(rid, str) or not re.fullmatch(prefix + r"\d+", rid) or rid in ids:
                raise ValueError("Invalid or duplicate history record_id")
            ids.add(rid)
            topics = record.get("final_topics")
            if not isinstance(topics, list) or any(t not in profile.names for t in topics):
                raise ValueError("History contains labels outside the selected profile")
            if prefix == "R":
                if record.get("platform") not in ("IOS", "AND") or not record.get("comment_date"):
                    raise ValueError("Market records need IOS/AND and an ISO date")
                importer.dt.date.fromisoformat(record["comment_date"])
                star = record.get("star")
                if star is not None and (type(star) is not int or star not in range(1, 6)):
                    raise ValueError("Rating must be empty or an integer 1–5")
                if record.get("is_negative") != (star is not None and star <= 3):
                    raise ValueError("History is_negative disagrees with star <= 3")
                if not isinstance(record.get("comment_text"), str) or not isinstance(record.get("and_channel"), str):
                    raise ValueError("Market text and channel must be strings")
            else:
                start = importer.dt.date.fromisoformat(record["period_start"])
                end = importer.dt.date.fromisoformat(record["period_end"])
                if start > end or not isinstance(record.get("cs_text_clean"), str):
                    raise ValueError("Customer-service history needs ordered dates and text")


def history(directory, profile):
    path = directory / "history.json"
    if not path.exists():
        return {"revision": 0, "market": [], "cs": [], "dataset_id": str(uuid.uuid4()),
                "profile": profile.data, "profile_sha256": profile.signature}
    data = read_json(path)
    if data.get("profile_sha256") != profile.signature:
        raise ValueError("Profile changed. Use a new data directory; existing history is never silently reclassified")
    validate_records(data["market"], data["cs"], profile)
    return data


def preview(directory, profile, ios, android, cs, time_mode="auto"):
    with lock(directory):
        data = history(directory, profile)
        market_index = importer.MarketIndex("multiset")
        for record in data["market"]:
            market_index.add(*importer.market_keys(record), record)
        market_index.records = data["market"]
        cs_index = importer.CsIndex("multiset", "overlap")
        for record in data["cs"]:
            cs_index.add(record)
        plan = {"base_token": token(directory), "dataset_id": data["dataset_id"],
                "profile_sha256": profile.signature, "new_market": [], "new_cs": [], "sources": {}}
        for kind, paths, index, domain, prefix in (
            ("ios", ios, market_index, "market", "IOS"),
            ("and", android, market_index, "market", "AND"),
            ("cs", cs, cs_index, "cs", "CS"),
        ):
            if not paths:
                continue
            paths = [str(Path(p).resolve()) for p in paths]
            bucket, stats, collisions, sheets, anomalies = importer.process(
                kind, paths, index, domain, prefix, importer.now_str(), time_mode)
            for record in bucket["new"]:
                if domain == "market":
                    if not record.get("comment_date") or record.get("platform") not in ("IOS", "AND"):
                        raise ValueError("Invalid market date/platform; fix the source before applying")
                    if record.get("star") is not None and record["star"] not in range(1, 6):
                        raise ValueError("Invalid rating")
                    raw_rating = next((v for k, v in record.get("raw", {}).items()
                                       if importer._norm_header(k) in {importer._norm_header(a) for a in importer.ALIAS_STAR}), "")
                    if raw_rating.strip() and record.get("star") is None:
                        raise ValueError("Unrecognized rating; use 1–5 or an empty cell")
                    plan["new_market"].append(record)
                else:
                    if not record.get("period_start") or not record.get("period_end"):
                        raise ValueError("Customer-service records need a valid batch period")
                    if record["period_start"] > record["period_end"]:
                        raise ValueError("Customer-service period start is after its end")
                    plan["new_cs"].append(record)
            plan["sources"][kind] = {"stats": stats, "updated": bucket["updated"],
                                     "ambiguous_lossy": bucket["ambiguous_lossy"],
                                     "existing_lossy": bucket["existing_lossy"],
                                     "collisions": collisions, "sheets": sheets, "anomalies": anomalies}
            if not sheets:
                raise ValueError("No recognizable input table; check the headers")
        plan["duplicates"] = importer.scan_platform_duplicates(data["market"] + plan["new_market"])
        atomic_json(directory / "preview.json", plan)
        print(json.dumps({"preview": str(directory / "preview.json"),
                          "new_market": len(plan["new_market"]), "new_cs": len(plan["new_cs"]),
                          "sources": {k: v["stats"] for k, v in plan["sources"].items()}}, ensure_ascii=False, indent=2))


def build(directory, data, profile):
    if not data["market"]:
        raise ValueError("Dashboard requires at least one dated market record; customer service is optional")
    reports = directory / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    destination = reports / ("%06d-" % data["revision"] + uuid.uuid4().hex[:8])
    with tempfile.TemporaryDirectory(prefix=".building-", dir=reports) as temporary:
        stage = Path(temporary)
        (stage / "scripts").mkdir()
        (stage / "assets").mkdir()
        atomic_json(stage / "classification.json", data["market"])
        atomic_json(stage / "classification_cs.json", data["cs"])
        atomic_json(stage / "scripts/raw_records.json", data["market"])
        atomic_json(stage / "profile.json", profile.data)
        env = {**os.environ, "TREND_DATA_DIR": str(stage), "TREND_PROFILE": str(stage / "profile.json"),
               "TREND_DATASET_ID": data["dataset_id"]}
        for script in ("audit.py", "metrics.py", "metrics_extra.py", "build_report.py"):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / script)],
                                    env=env, capture_output=True, text=True)
            if result.returncode:
                raise ValueError(script + " failed:\n" + result.stdout + result.stderr)
        # The generated dashboard includes original feedback. All runtime files stay local.
        stage.rename(destination)
    return str(destination.relative_to(directory))


def apply(directory, profile):
    with lock(directory):
        data = history(directory, profile)
        plan = read_json(directory / "preview.json")
        if plan["base_token"] != token(directory) or plan["profile_sha256"] != profile.signature:
            raise ValueError("Preview is stale; run preview again")
        if plan["duplicates"]["counts"]["true_dup_groups"]:
            raise ValueError("Confirmed platform duplicates require review before applying")
        if not plan["new_market"] and not plan["new_cs"]:
            print("No new records; history unchanged")
            return
        for kind, function, prefix, new in (("market", classify_market, "R", plan["new_market"]),
                                             ("cs", classify_cs, "CS", plan["new_cs"])):
            number = max((int(r["record_id"][len(prefix):]) for r in data[kind]), default=0)
            for offset, record in enumerate(new, 1):
                record["_proposed_record_id"] = prefix + "%06d" % (number + offset)
                classified = function(record, profile)
                classified.pop("_incremental", None)
                data[kind].append(classified)
        data["revision"] += 1
        data["dataset_id"] = plan["dataset_id"]
        validate_records(data["market"], data["cs"], profile)
        data["report"] = build(directory, data, profile)
        # One atomic history file commits both domains only after the report succeeds.
        atomic_json(directory / "history.json", data)
        print("Dashboard:", directory / data["report"] / "report.html")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "apply", "report", "demo", "serve", "adopt-history"):
        ap = sub.add_parser(command)
        ap.add_argument("--data-dir", type=Path, default=Path("outputs/demo"))
        ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
        if command == "preview":
            ap.add_argument("--ios", nargs="+", default=[])
            ap.add_argument("--android", nargs="+", default=[])
            ap.add_argument("--cs", nargs="+", default=[])
            ap.add_argument("--cs-time-mode", choices=("auto", "overlap", "ignore"), default="auto")
        if command == "serve":
            ap.add_argument("--port", type=int, default=8000)
        if command == "adopt-history":
            ap.add_argument("--market", type=Path, required=True)
            ap.add_argument("--cs", type=Path)
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    try:
        profile = load_profile(args.profile)
        if args.command == "preview":
            if not (args.ios or args.android or args.cs):
                raise ValueError("Provide --ios, --android or --cs")
            preview(directory, profile, args.ios, args.android, args.cs, args.cs_time_mode)
        elif args.command == "demo":
            preview(directory, profile, [ROOT / "examples/media-ios.csv"],
                    [ROOT / "examples/media-OPPO.csv"], [ROOT / "examples/support.csv"])
            apply(directory, profile)
        elif args.command == "apply":
            apply(directory, profile)
        elif args.command in ("report", "adopt-history"):
            with lock(directory):
                if args.command == "adopt-history" and (directory / "history.json").exists():
                    raise ValueError("Adopt history only into a new data directory")
                data = history(directory, profile)
                if args.command == "adopt-history":
                    data["market"] = read_json(args.market)
                    data["cs"] = read_json(args.cs) if args.cs else []
                    data["revision"] = 1
                    validate_records(data["market"], data["cs"], profile)
                data["report"] = build(directory, data, profile)
                atomic_json(directory / "history.json", data)
                print("Dashboard:", directory / data["report"] / "report.html")
        elif args.command == "serve":
            data = history(directory, profile)
            target = (directory / data["report"]).resolve()
            if not target.is_relative_to(directory / "reports"):
                raise ValueError("Invalid report path")
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(target))
            print("Dashboard: http://127.0.0.1:%d/report.html" % args.port, flush=True)
            with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
                server.serve_forever()
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, "error: " + str(error) + "\n")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
