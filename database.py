# database.py
# সহজ JSON ফাইল ভিত্তিক ডেটাবেস (এডমিন সেটিংস + ইউজার তথ্য সেভ রাখার জন্য)

import json
import os
import threading

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.json")
_lock = threading.RLock()

DEFAULT_DB = {
    "users": {},  # "user_id": {"requests_today", "last_date", "banned", "bonus_limit", "referred_by", "referrals_count"}
    "config": {
        # একাধিক API রাখা যায়, এডমিন প্যানেল থেকে যেকোনো একটাকে "active" (চালু) করা যায়
        "apis": [
            {
                "name": "Deep AI",
                "url": "https://r-bots-free-apis.co08.art/api/v1/api/deep-ai",
                "key": "https://r-bots-free-apis.co08.art/api/v1/api/deep-ai",
                "query_param": "query",
                "apikey_param": "apikey",
            }
        ],
        "active_api_index": 0,
        # ছবি/ইমেজ জেনারেশনের জন্য আলাদা API লিস্ট (টেক্সট API থেকে সম্পূর্ণ আলাদা)
        "image_apis": [],
        "active_image_api_index": 0,
        # ইউজারের পাঠানো ছবি অ্যানালাইসিসের জন্য আলাদা API লিস্ট
        "vision_apis": [],
        "active_vision_api_index": 0,
        "daily_limit": 10,
        "referral_bonus": 3,           # প্রতি সফল রেফারে যত এক্সট্রা লিমিট পাবে
        "force_channels": [],           # [{"username": "@channel", "name": "চ্যানেলের নাম"}]
        "buttons": [],                   # [{"text": "🎬 মুভি সার্চ"}]
        "premium_emoji_id": "",
        "premium_emoji_char": "✨",
    },
}


def _migrate(data):
    """পুরনো (single-API) কনফিগ থাকলে নতুন multi-API ফরম্যাটে কনভার্ট করা হচ্ছে।"""
    changed = False
    config = data.setdefault("config", {})

    if "apis" not in config:
        old_url = config.pop("api_url", None)
        old_key = config.pop("api_key", None)
        old_qp = config.pop("query_param", "query")
        old_ap = config.pop("apikey_param", "apikey")
        config.pop("response_keys", None)
        config["apis"] = [{
            "name": "Deep AI",
            "url": old_url or DEFAULT_DB["config"]["apis"][0]["url"],
            "key": old_key or "",
            "query_param": old_qp,
            "apikey_param": old_ap,
        }]
        config["active_api_index"] = 0
        changed = True

    for k, v in DEFAULT_DB["config"].items():
        if k not in config:
            config[k] = v
            changed = True

    for uid, user in data.get("users", {}).items():
        for k, v in {"bonus_limit": 0, "referred_by": None, "referrals_count": 0, "banned": False, "chat_history": []}.items():
            if k not in user:
                user[k] = v
                changed = True

    return changed


def load_db():
    with _lock:
        if not os.path.exists(DB_FILE):
            data = json.loads(json.dumps(DEFAULT_DB))
            _write(data)
            return data
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if _migrate(data):
            _write(data)
        return data


def save_db(data):
    with _lock:
        _write(data)


def _write(data):
    tmp_file = DB_FILE + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, DB_FILE)
