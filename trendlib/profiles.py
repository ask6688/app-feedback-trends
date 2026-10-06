"""Configurable simple topics alongside frozen Python matchers."""
import hashlib
import json
import re
from pathlib import Path

from . import legacy_rules

DEFAULT_PROFILE = Path(__file__).resolve().parents[1] / "profiles/media.json"


class Profile:
    def __init__(self, data):
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("Profile schema_version must be 1")
        if not isinstance(data.get("id"), str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", data["id"]):
            raise ValueError("Profile needs an alphanumeric id")
        if not isinstance(data.get("topics"), list) or not data["topics"]:
            raise ValueError("Profile topics must be a nonempty list")
        self.topics, keys, names = [], set(), set()
        for index, item in enumerate(data["topics"]):
            if not isinstance(item, dict):
                raise ValueError("Each topic must be an object")
            topic = dict(item)
            key, name = topic.get("key"), topic.get("name")
            if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_-]+", key) or key in keys:
                raise ValueError("Topic keys must be unique alphanumeric identifiers")
            if not isinstance(name, str) or not name.strip() or len(name) > 60 or name in names or re.search(r'[<>"\'`&\\\x00-\x1f]', name):
                raise ValueError("Topic names must be unique plain text, at most 60 characters")
            keys.add(key)
            names.add(name)
            topic.setdefault("enabled", True)
            topic.setdefault("order", index)
            topic.setdefault("matcher", "simple")
            if type(topic["enabled"]) is not bool or type(topic["order"]) is not int:
                raise ValueError("enabled must be boolean; order must be integer")
            if topic["matcher"] == "builtin":
                if topic.get("builtin") not in legacy_rules.JUDGE:
                    raise ValueError("Unknown built-in matcher")
            elif topic["matcher"] == "simple":
                for field in ("keywords", "requires", "excludes"):
                    values = topic.setdefault(field, [])
                    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                        raise ValueError(field + " must be a list of nonempty strings")
                if not topic["keywords"]:
                    raise ValueError("Simple topics need at least one keyword")
            else:
                raise ValueError("matcher must be simple or builtin")
            self.topics.append(topic)
        self.topics.sort(key=lambda t: t["order"])
        self.active = [t for t in self.topics if t["enabled"]]
        if not self.active:
            raise ValueError("At least one topic must be enabled")
        self.names = [t["name"] for t in self.active]
        self.by_name = {t["name"]: t for t in self.active}
        self.data = {"schema_version": 1, "id": data["id"], "topics": self.topics}
        self.signature = hashlib.sha256(json.dumps(self.data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        definitions = json.loads(Path(__file__).with_name("semantic_definitions.json").read_text(encoding="utf-8"))
        self.metadata = {"id": data["id"], "version": self.signature[:12],
                         "semantic_version": definitions["version"], "topics": self.active}

    def recall(self, text):
        builtins, builtin_reasons = legacy_rules.recall(text)
        candidates, reasons = [], {}
        for topic in self.active:
            name = topic["name"]
            if topic["matcher"] == "builtin":
                if topic["builtin"] in builtins:
                    candidates.append(name)
                    reasons[name] = builtin_reasons[topic["builtin"]]
            else:
                hits = [word for word in topic["keywords"] if word.casefold() in text.casefold()]
                if hits:
                    candidates.append(name)
                    reasons[name] = "命中召回词：" + "、".join(hits[:8]) + ("…" if len(hits) > 8 else "")
        return candidates, reasons

    def judge(self, name, text, domain="market"):
        topic = self.by_name[name]
        if topic["matcher"] == "builtin":
            return legacy_rules.JUDGE[topic["builtin"]](text, domain=domain)
        lowered = text.casefold()
        if any(word.casefold() in lowered for word in topic["excludes"]):
            return False, "命中排除词"
        if topic["requires"] and not any(word.casefold() in lowered for word in topic["requires"]):
            return False, "缺少必要上下文"
        hits = [word for word in topic["keywords"] if word.casefold() in lowered]
        return (True, "命中关键词：" + "、".join(hits[:8])) if hits else (False, "未命中关键词")


def load_profile(path=DEFAULT_PROFILE):
    return Profile(json.loads(Path(path).read_text(encoding="utf-8")))
