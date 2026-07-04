# database.py
# সহজ JSON ফাইল ভিত্তিক ডেটাবেস (এডমিন সেটিংস + ইউজার তথ্য সেভ রাখার জন্য)

import json
import os
import threading

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.json")
_lock = threading.RLock()

DEFAULT_DB = {
    "users": {},  # "user_id": {"requests_today": 0, "last_date": "YYYY-MM-DD", "banned": False}
    "config": {
        "api_url": "https://r-bots-free-apis.co08.art/api/v1/api/deep-ai",
        "api_key": "https://r-bots-free-apis.co08.art/api/v1/api/deep-ai",
        "query_param": "query",       # API তে প্রশ্ন পাঠানোর প্যারামিটার নাম
        "apikey_param": "apikey",     # API তে কী পাঠানোর প্যারামিটার নাম
        "response_keys": ["response", "answer", "result", "message"],  # API রেসপন্স থেকে উত্তর বের করার জন্য সম্ভাব্য key গুলো
        "daily_limit": 10,
        "force_channels": [],         # [{"username": "@channel", "name": "চ্যানেলের নাম"}]
        "buttons": [],                # [{"text": "🎬 মুভি সার্চ"}]
        "premium_emoji_id": "",       # টেলিগ্রাম প্রিমিয়াম কাস্টম ইমোজির ID
        "premium_emoji_char": "✨"     # ফলব্যাক ইমোজি (প্রিমিয়াম ইমোজি না থাকলে এটা দেখাবে)
    }
}


def load_db():
    with _lock:
        if not os.path.exists(DB_FILE):
            data = json.loads(json.dumps(DEFAULT_DB))
            _write(data)
            return data
        with open(DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # পুরনো ডেটাবেসে যদি নতুন কোনো config key যুক্ত করা হয়, সেটা যোগ করে দেওয়া হচ্ছে
        changed = False
        for k, v in DEFAULT_DB["config"].items():
            if k not in data.get("config", {}):
                data.setdefault("config", {})[k] = v
                changed = True
        if changed:
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
