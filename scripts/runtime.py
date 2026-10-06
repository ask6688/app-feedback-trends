"""Local job paths and profile; no other repository dependency."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from trendlib.profiles import load_profile

PROFILE = load_profile(os.environ["TREND_PROFILE"])
TOPICS = PROFILE.names
PROFILE_META = PROFILE.metadata
SOURCES = ["IOS", "VIVO", "OPPO", "华为", "小米", "魅族"]
records = json.loads((Path(os.environ["TREND_DATA_DIR"]) / "classification.json").read_text(encoding="utf-8"))
SOURCES += sorted({r["and_channel"] for r in records if r["platform"] == "AND"} - set(SOURCES))
