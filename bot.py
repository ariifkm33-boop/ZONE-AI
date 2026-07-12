# bot.py
# ZONE AI - বাংলা টেলিগ্রাম AI বট
# ফিচার: AI চ্যাট (একাধিক কাস্টম API), ফোর্স চ্যানেল জয়েন, দৈনিক রিকোয়েস্ট লিমিট,
#         রেফার সিস্টেম (রেফার করলে লিমিট বাড়ে), এডমিন প্যানেল (একাধিক API, চ্যানেল,
#         লিমিট, বাটন, প্রিমিয়াম ইমোজি, ব্রডকাস্ট, স্ট্যাটাস)

import json
import datetime
import time
import base64
import threading
import io
import re
import random

import requests
import telebot
from telebot import types

from database import load_db, save_db

# ========================= বেসিক সেটআপ =========================
BOT_TOKEN = "8824547804:AAHIxlTU8o_E4-50p6YosWHcLm4EPeraYZ0"          # <-- @BotFather থেকে পাওয়া টোকেন এখানে দিন
ADMIN_IDS = [8210146346]                    # <-- আপনার টেলিগ্রাম নিউমেরিক ইউজার আইডি দিন (একাধিক দিতে পারবেন)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")

# admin_id -> {"step": "...", ...} : এডমিন এখন কোন ইনপুট দিচ্ছে তা ট্র্যাক করার জন্য
admin_state = {}

# বটের নিজের ইউজারনেম (রেফারেল লিংক বানানোর জন্য), স্টার্ট হওয়ার পর ফিল হবে
BOT_USERNAME = None


# ========================= হেল্পার ফাংশন =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def today_str() -> str:
    return datetime.date.today().isoformat()


def get_user(db, user_id):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "requests_today": 0,
            "last_date": today_str(),
            "banned": False,
            "bonus_limit": 0,
            "referred_by": None,
            "referrals_count": 0,
            "chat_history": [],
            "mode": "chat",  # chat | image | code | random
            "age_verified": False,
        }
    user = db["users"][uid]
    if user.get("last_date") != today_str():
        user["requests_today"] = 0
        user["last_date"] = today_str()
    # পুরনো ইউজারদের ক্ষেত্রে নতুন key গুলো না থাকলে যোগ করে দেওয়া হচ্ছে
    user.setdefault("chat_history", [])
    user.setdefault("mode", "chat")
    user.setdefault("age_verified", False)
    return user


def effective_limit(db, user) -> int:
    return db["config"]["daily_limit"] + user.get("bonus_limit", 0)


def check_joined_channels(user_id: int) -> bool:
    db = load_db()
    channels = db["config"]["force_channels"]
    if not channels:
        return True
    for ch in channels:
        try:
            member = bot.get_chat_member(ch["username"], user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception:
            return False
    return True


def join_markup(db):
    markup = types.InlineKeyboardMarkup()
    for ch in db["config"]["force_channels"]:
        uname = ch["username"].lstrip("@")
        markup.add(types.InlineKeyboardButton(f"📢 {ch['name']}", url=f"https://t.me/{uname}"))
    markup.add(types.InlineKeyboardButton("✅ জয়েন করেছি, চেক করুন", callback_data="check_join"))
    return markup


def main_menu_markup(db, user_mode=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = db["config"]["buttons"]
    row = []
    for b in buttons:
        row.append(types.KeyboardButton(b["text"]))
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)
    markup.row(types.KeyboardButton("📊 আমার তথ্য"), types.KeyboardButton("🔗 রেফার করুন"))
    if user_mode == "random":
        markup.row(types.KeyboardButton("🎲 র্যান্ডম ছবি"))
    markup.row(types.KeyboardButton("🎛 মোড পরিবর্তন"))
    markup.row(types.KeyboardButton("❓ হেল্প"))
    return markup


MODE_LABELS = {
    "chat": "💬 চ্যাট মোড",
    "image": "🎨 ইমেজ মোড",
    "code": "💻 কোড মোড",
    "random": "🎲 র্যান্ডম ছবি মোড",
}

# 'random' মোডে বয়স-নিশ্চিতকরণ পাস করলেও, কী ধরনের ছবি আসবে সেটা এই তালিকার
# মধ্যেই সীমাবদ্ধ রাখা হয়েছে — নিরাপদ, সাধারণ বিষয়। এলোমেলো/অনির্দিষ্ট কনটেন্ট
# জেনারেট করা হয় না, যাতে কেউ ভুল করে বয়স নিয়ে মিথ্যা বললেও ঝুঁকি না থাকে।
SAFE_RANDOM_SUBJECTS = [
    "beautiful nature landscape", "cute animal", "colorful flowers",
    "mountain sunset", "ocean waves", "forest scenery", "abstract art",
    "city skyline at night", "cozy coffee shop", "starry sky",
    "autumn leaves", "tropical beach", "space and galaxy art",
    "cartoon style illustration", "watercolor painting",
]


def mode_select_markup(current_mode: str):
    markup = types.InlineKeyboardMarkup()
    for mode_key, label in MODE_LABELS.items():
        mark = "✅ " if mode_key == current_mode else ""
        markup.add(types.InlineKeyboardButton(f"{mark}{label}", callback_data=f"setmode_{mode_key}"))
    return markup


def age_confirm_markup():
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ হ্যাঁ, ১৮+", callback_data="ageverify_yes"),
        types.InlineKeyboardButton("❌ না", callback_data="ageverify_no"),
    )
    return markup


def get_active_api(db):
    apis = db["config"]["apis"]
    idx = db["config"].get("active_api_index", 0)
    if not apis:
        return None
    if idx >= len(apis):
        idx = 0
    return apis[idx]


def get_active_image_api(db):
    """টেক্সট API থেকে আলাদা — শুধু ছবি/ইমেজ জেনারেশনের জন্য।"""
    apis = db["config"].get("image_apis", [])
    idx = db["config"].get("active_image_api_index", 0)
    if not apis:
        return None
    if idx >= len(apis):
        idx = 0
    return apis[idx]


# বাংলা + ইংরেজি — এই শব্দগুলোর যেকোনোটা মেসেজে থাকলে সেটাকে "ছবি চাচ্ছে" ধরে নেওয়া হবে
IMAGE_KEYWORDS = (
    "ছবি", "ইমেজ", "ফটো", "আঁকো", "আঁকা", "আর্ট", "ওয়ালপেপার", "পোস্টার",
    "picture", "photo", "image", "img", "draw", "wallpaper", "poster",
    "generate image", "make an image", "art of",
)


def is_image_request(text: str) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in IMAGE_KEYWORDS)


def extract_image_url(data):
    """
    ইমেজ API-র JSON রেসপন্স (যত nested-ই হোক) থেকে ইমেজের URL বা base64
    ডেটা খুঁজে বের করে — extract_answer() এর মতোই রিকার্সিভ লজিক।
    """
    if isinstance(data, str):
        return data.strip() or None

    if isinstance(data, dict):
        for k in ("url", "image_url", "image", "photo", "img", "link", "output", "result", "results"):
            if k in data and data[k]:
                val = data[k]
                if isinstance(val, str):
                    return val.strip()
                nested = extract_image_url(val)
                if nested:
                    return nested
        for v in data.values():
            if isinstance(v, (dict, list)):
                nested = extract_image_url(v)
                if nested:
                    return nested
        return None

    if isinstance(data, list):
        for item in data:
            nested = extract_image_url(item)
            if nested:
                return nested
        return None

    return None


def get_active_vision_api(db):
    """ব্যবহারকারীর পাঠানো ছবি অ্যানালাইসিস করার জন্য আলাদা API।"""
    apis = db["config"].get("vision_apis", [])
    idx = db["config"].get("active_vision_api_index", 0)
    if not apis:
        return None
    if idx >= len(apis):
        idx = 0
    return apis[idx]


def build_api_params(api, query_param_key, query_value):
    """
    API-র জন্য রিকোয়েস্ট প্যারামিটার বানায়। যদি API-র 'key' খালি/none হয়
    (যেমন ফ্রি API যেগুলোতে apikey লাগেই না), তাহলে apikey প্যারামিটারটা
    রিকোয়েস্টেই পাঠানো হয় না — কারণ কিছু API খালি/অপ্রত্যাশিত প্যারামিটার
    পেলে রিকোয়েস্ট রিজেক্ট করে দেয়।
    """
    params = {query_param_key: query_value}
    if api.get("key"):
        params[api["apikey_param"]] = api["key"]
    return params


def looks_like_image_bytes(data: bytes) -> bool:
    """
    অনেক ফ্রি API content-type হেডার ঠিকভাবে সেট করে না (যেমন text/plain
    দেখায় অথচ আসলে ছবির বাইট পাঠায়)। তাই হেডারের পাশাপাশি ছবির
    'ম্যাজিক বাইট' (ফাইলের শুরুর সিগনেচার) দিয়েও চেক করা হয়।
    """
    if not data or len(data) < 8:
        return False
    return (
        data.startswith(b"\xff\xd8\xff") or          # JPEG
        data.startswith(b"\x89PNG\r\n\x1a\n") or       # PNG
        data.startswith(b"GIF87a") or data.startswith(b"GIF89a") or  # GIF
        (data[:4] == b"RIFF" and data[8:12] == b"WEBP")  # WEBP
    )


def api_get_with_retry(url, params, timeout=600, retries=0):
    """
    ইউজারের চাহিদা অনুযায়ী টাইমআউট ১০ মিনিট (৬০০ সেকেন্ড) রাখা হয়েছে,
    যেহেতু কিছু ফ্রি API রেসপন্স দিতে অনেক সময় নেয়।
    """
    last_error = None
    for attempt in range(1, retries + 2):  # মোট (retries + 1) বার চেষ্টা
        try:
            return requests.get(url, params=params, timeout=timeout)
        except requests.exceptions.Timeout as e:
            last_error = e
            print(f"[DEBUG] Attempt {attempt} timed out, retrying...")
        except requests.exceptions.RequestException as e:
            last_error = e
            print(f"[DEBUG] Attempt {attempt} failed: {e}")
    raise last_error


def extract_answer(data, keys=("results", "text", "response", "answer", "result", "message", "output", "content")):
    """
    API রেসপন্স যত জটিল বা যত nested-ই হোক (যেমন {"results": {"text": "..."}}),
    এই ফাংশন রিকার্সিভভাবে ভেতরে ঢুকে আসল টেক্সট উত্তরটা খুঁজে বের করে।
    এতে ইউজারকে কখনো raw JSON দেখতে হয় না।
    """
    if isinstance(data, str):
        return data.strip() or None

    if isinstance(data, dict):
        # প্রথমে টপ-লেভেলে চেনা key গুলো খোঁজা হচ্ছে
        for k in keys:
            if k in data and data[k]:
                val = data[k]
                if isinstance(val, str):
                    return val.strip()
                nested = extract_answer(val, keys)
                if nested:
                    return nested
        # না পেলে যেকোনো nested dict/list এর ভেতরে খোঁজা হচ্ছে
        for v in data.values():
            if isinstance(v, (dict, list)):
                nested = extract_answer(v, keys)
                if nested:
                    return nested
        return None

    if isinstance(data, list):
        for item in data:
            nested = extract_answer(item, keys)
            if nested:
                return nested
        return None

    return None


# ফাইলের এক্সটেনশন বাছাইয়ের জন্য ভাষার নাম -> এক্সটেনশন ম্যাপ
LANG_EXT_MAP = {
    "python": "py", "py": "py", "javascript": "js", "js": "js",
    "typescript": "ts", "ts": "ts", "html": "html", "css": "css",
    "java": "java", "c++": "cpp", "cpp": "cpp", "c": "c",
    "bash": "sh", "sh": "sh", "shell": "sh", "json": "json",
    "sql": "sql", "php": "php", "go": "go", "rust": "rs",
    "kotlin": "kt", "swift": "swift", "xml": "xml", "yaml": "yml",
    "yml": "yml", "ruby": "rb", "dart": "dart", "r": "r",
}

# উত্তর কখন ফাইল আকারে পাঠানো হবে তার থ্রেশহোল্ড (ক্যারেক্টার সংখ্যা)
FILE_SEND_THRESHOLD = 1500


def detect_extension(text: str) -> str:
    """```python জাতীয় কোড-ফেন্স থেকে ভাষা বুঝে সঠিক এক্সটেনশন বের করে।"""
    m = re.search(r"```(\w+)", text)
    if m:
        return LANG_EXT_MAP.get(m.group(1).lower(), "txt")
    return "txt"


def strip_code_fences(text: str) -> str:
    """```lang ... ``` ব্লক থাকলে শুধু কোড অংশগুলো জোড়া দিয়ে বের করে আনে।"""
    blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if blocks:
        return "\n\n".join(blocks).strip()
    return text


def should_send_as_file(text: str) -> bool:
    """২০০০+ লাইনের কোড সহ যেকোনো বড় উত্তর/কোড ব্লক ফাইল আকারে পাঠানোর যোগ্য কিনা চেক করে।"""
    return len(text) > FILE_SEND_THRESHOLD or "```" in text


def send_long_answer(chat_id, answer: str, reply_to_message_id=None, force: bool = False):
    """
    উত্তর বড় (কয়েক হাজার লাইনও হতে পারে) বা কোড হলে সেটাকে সঠিক নামের একটা
    ফাইল বানিয়ে, ব্যবহারের নির্দেশনাসহ পাঠায়। ছোট সাধারণ উত্তর হলে সরাসরি
    চ্যাট মেসেজ হিসেবেই পাঠায় — তবে force=True হলে (যেমন 'কোড মোড' অন থাকলে)
    ছোট উত্তরও ফাইল আকারে পাঠানো হয়।
    """
    if not force and not should_send_as_file(answer):
        bot.send_message(chat_id, answer, reply_to_message_id=reply_to_message_id)
        return

    ext = detect_extension(answer)
    code_content = strip_code_fences(answer)
    filename = f"zoneai_code_{int(time.time())}.{ext}"

    caption = (
        "📁 উত্তর/কোডটা বড় হওয়ায় ফাইল আকারে পাঠানো হলো।\n"
        f"🗂 ফাইলের নাম: `{filename}`\n\n"
        "▶️ *নির্দেশনা:*\n"
        "১) ফাইলটা ডাউনলোড করুন\n"
        "২) প্রয়োজনমতো আপনার প্রজেক্ট ফোল্ডারে রাখুন\n"
        "৩) এক্সটেনশন সঠিক না হলে চাহিদামতো পরিবর্তন করে নিন"
    )

    bio = io.BytesIO(code_content.encode("utf-8"))
    bio.name = filename
    try:
        bot.send_document(chat_id, bio, caption=caption, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        print(f"[DEBUG] send_document failed, falling back to text: {e}")
        bot.send_message(chat_id, answer, reply_to_message_id=reply_to_message_id)


def build_emoji_entities(db, prefix_len):
    emoji_id = db["config"].get("premium_emoji_id")
    if not emoji_id:
        return None
    try:
        return [types.MessageEntity(
            type="custom_emoji",
            offset=0,
            length=prefix_len,
            custom_emoji_id=emoji_id
        )]
    except Exception:
        return None


def referral_link(user_id):
    uname = BOT_USERNAME or "your_bot"
    return f"https://t.me/{uname}?start=ref_{user_id}"


# ========================= ইউজার কমান্ড =========================
@bot.message_handler(commands=["start"])
def start_handler(message):
    db = load_db()
    user_id = message.from_user.id
    uid = str(user_id)
    is_new_user = uid not in db["users"]
    user = get_user(db, user_id)

    # ---- রেফারেল পেলোড চেক (/start ref_12345) ----
    parts = message.text.split(maxsplit=1)
    if is_new_user and len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1][4:])
        except ValueError:
            referrer_id = None

        if referrer_id and referrer_id != user_id:
            user["referred_by"] = str(referrer_id)
            ref_uid = str(referrer_id)
            if ref_uid in db["users"]:
                bonus = db["config"]["referral_bonus"]
                db["users"][ref_uid]["bonus_limit"] = db["users"][ref_uid].get("bonus_limit", 0) + bonus
                db["users"][ref_uid]["referrals_count"] = db["users"][ref_uid].get("referrals_count", 0) + 1
                save_db(db)
                try:
                    bot.send_message(
                        referrer_id,
                        "🎉 আপনার রেফার লিংক দিয়ে একজন নতুন ইউজার জয়েন করেছে!\n"
                        f"⚡ আপনার দৈনিক লিমিট *+{bonus}* বেড়ে গেছে। ধন্যবাদ! 🙏"
                    )
                except Exception:
                    pass

    save_db(db)

    if not check_joined_channels(user_id):
        bot.send_message(
            message.chat.id,
            "👋 *ZONE AI* বটে স্বাগতম!\n\n"
            "ব্যবহার শুরু করতে নিচের চ্যানেল(গুলো)-তে জয়েন করুন 👇",
            reply_markup=join_markup(db)
        )
        return

    bot.send_message(
        message.chat.id,
        "👋 *ZONE AI* — এখন থেকে যা মনে চায় লিখুন, আমি উত্তর দিব। 🤖",
        reply_markup=main_menu_markup(db)
    )


@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    db = load_db()
    if check_joined_channels(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ ধন্যবাদ! এখন বট ব্যবহার করতে পারবেন।")
        bot.send_message(
            call.message.chat.id,
            "🎉 এখন যা ইচ্ছা লিখে পাঠান!",
            reply_markup=main_menu_markup(db)
        )
    else:
        bot.answer_callback_query(call.id, "❌ আপনি এখনো সব চ্যানেলে জয়েন করেননি!", show_alert=True)


# ========================= এডমিন প্যানেল =========================
@bot.message_handler(commands=["admin"])
def admin_handler(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ আপনি এডমিন নন।")
        return
    send_admin_panel(message.chat.id)


def send_admin_panel(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("➕ API যুক্ত করুন", callback_data="adm_add_api"),
        types.InlineKeyboardButton("📋 API লিস্ট/সিলেক্ট", callback_data="adm_list_apis"),
        types.InlineKeyboardButton("🗑 API রিমুভ", callback_data="adm_remove_api"),
        types.InlineKeyboardButton("🖼 ইমেজ API যুক্ত করুন", callback_data="adm_add_img_api"),
        types.InlineKeyboardButton("🖼 ইমেজ API লিস্ট/সিলেক্ট", callback_data="adm_list_img_apis"),
        types.InlineKeyboardButton("🗑 ইমেজ API রিমুভ", callback_data="adm_remove_img_api"),
        types.InlineKeyboardButton("🔍 ভিশন API যুক্ত করুন", callback_data="adm_add_vision_api"),
        types.InlineKeyboardButton("🔍 ভিশন API লিস্ট/সিলেক্ট", callback_data="adm_list_vision_apis"),
        types.InlineKeyboardButton("🗑 ভিশন API রিমুভ", callback_data="adm_remove_vision_api"),
        types.InlineKeyboardButton("📢 চ্যানেল যুক্ত করুন", callback_data="adm_add_channel"),
        types.InlineKeyboardButton("🗑 চ্যানেল রিমুভ", callback_data="adm_remove_channel"),
        types.InlineKeyboardButton("🔢 লিমিট পরিবর্তন", callback_data="adm_set_limit"),
        types.InlineKeyboardButton("🎁 রেফার বোনাস সেট", callback_data="adm_set_refbonus"),
        types.InlineKeyboardButton("🔘 বাটন যুক্ত করুন", callback_data="adm_add_button"),
        types.InlineKeyboardButton("🗑 বাটন রিমুভ", callback_data="adm_remove_button"),
        types.InlineKeyboardButton("😎 প্রিমিয়াম ইমোজি সেট", callback_data="adm_set_emoji"),
        types.InlineKeyboardButton("📊 স্ট্যাটাস দেখুন", callback_data="adm_stats"),
        types.InlineKeyboardButton("📣 ব্রডকাস্ট করুন", callback_data="adm_broadcast"),
    )
    bot.send_message(
        chat_id,
        "🛠 *ZONE AI — অ্যাডমিন প্যানেল*\n\nনিচ থেকে একটি অপশন বেছে নিন 👇",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_callback(call):
    if not is_admin(call.from_user.id):
        bot.answer_callback_query(call.id, "⛔ অনুমতি নেই।", show_alert=True)
        return

    action = call.data
    admin_id = call.from_user.id
    bot.answer_callback_query(call.id)
    db = load_db()

    if action == "adm_add_api":
        admin_state[admin_id] = {"step": "api_name"}
        bot.send_message(call.message.chat.id, "🆕 নতুন API-র একটা *নাম* দিন (যেমন: `GPT`, `Deep AI`):")

    elif action == "adm_list_apis":
        apis = db["config"]["apis"]
        active_idx = db["config"].get("active_api_index", 0)
        if not apis:
            bot.send_message(call.message.chat.id, "কোনো API যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, api in enumerate(apis):
            mark = "✅ " if i == active_idx else ""
            markup.add(types.InlineKeyboardButton(f"{mark}{api['name']}", callback_data=f"setapi_{i}"))
        bot.send_message(
            call.message.chat.id,
            "📋 *API লিস্ট* — যেটা এখন *চালু* করতে চান সেটায় ট্যাপ করুন:",
            reply_markup=markup
        )

    elif action == "adm_remove_api":
        apis = db["config"]["apis"]
        if len(apis) <= 1:
            bot.send_message(call.message.chat.id, "⚠️ কমপক্ষে একটা API থাকতে হবে, এটা রিমুভ করা যাবে না।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, api in enumerate(apis):
            markup.add(types.InlineKeyboardButton(f"❌ {api['name']}", callback_data=f"delapi_{i}"))
        bot.send_message(call.message.chat.id, "রিমুভ করতে চান এমন API বেছে নিন:", reply_markup=markup)

    elif action == "adm_add_img_api":
        admin_state[admin_id] = {"step": "img_api_name"}
        bot.send_message(call.message.chat.id, "🆕 নতুন ইমেজ API-র একটা *নাম* দিন (যেমন: `Flux Image`):")

    elif action == "adm_list_img_apis":
        apis = db["config"].get("image_apis", [])
        active_idx = db["config"].get("active_image_api_index", 0)
        if not apis:
            bot.send_message(call.message.chat.id, "কোনো ইমেজ API যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, api in enumerate(apis):
            mark = "✅ " if i == active_idx else ""
            markup.add(types.InlineKeyboardButton(f"{mark}{api['name']}", callback_data=f"setimgapi_{i}"))
        bot.send_message(
            call.message.chat.id,
            "🖼 *ইমেজ API লিস্ট* — যেটা এখন *চালু* করতে চান সেটায় ট্যাপ করুন:",
            reply_markup=markup
        )

    elif action == "adm_remove_img_api":
        apis = db["config"].get("image_apis", [])
        if not apis:
            bot.send_message(call.message.chat.id, "কোনো ইমেজ API যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, api in enumerate(apis):
            markup.add(types.InlineKeyboardButton(f"❌ {api['name']}", callback_data=f"delimgapi_{i}"))
        bot.send_message(call.message.chat.id, "রিমুভ করতে চান এমন ইমেজ API বেছে নিন:", reply_markup=markup)

    elif action == "adm_add_vision_api":
        admin_state[admin_id] = {"step": "vision_api_name"}
        bot.send_message(call.message.chat.id, "🆕 নতুন ভিশন (ছবি অ্যানালাইসিস) API-র একটা *নাম* দিন:")

    elif action == "adm_list_vision_apis":
        apis = db["config"].get("vision_apis", [])
        active_idx = db["config"].get("active_vision_api_index", 0)
        if not apis:
            bot.send_message(call.message.chat.id, "কোনো ভিশন API যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, api in enumerate(apis):
            mark = "✅ " if i == active_idx else ""
            markup.add(types.InlineKeyboardButton(f"{mark}{api['name']}", callback_data=f"setvisionapi_{i}"))
        bot.send_message(
            call.message.chat.id,
            "🔍 *ভিশন API লিস্ট* — যেটা চালু করতে চান সেটায় ট্যাপ করুন:",
            reply_markup=markup
        )

    elif action == "adm_remove_vision_api":
        apis = db["config"].get("vision_apis", [])
        if not apis:
            bot.send_message(call.message.chat.id, "কোনো ভিশন API যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, api in enumerate(apis):
            markup.add(types.InlineKeyboardButton(f"❌ {api['name']}", callback_data=f"delvisionapi_{i}"))
        bot.send_message(call.message.chat.id, "রিমুভ করতে চান এমন ভিশন API বেছে নিন:", reply_markup=markup)

    elif action == "adm_add_channel":
        admin_state[admin_id] = {"step": "channel_username"}
        bot.send_message(call.message.chat.id, "📢 চ্যানেলের *ইউজারনেম* পাঠান (যেমন: `@mychannel`):")

    elif action == "adm_remove_channel":
        channels = db["config"]["force_channels"]
        if not channels:
            bot.send_message(call.message.chat.id, "কোনো চ্যানেল যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, ch in enumerate(channels):
            markup.add(types.InlineKeyboardButton(f"❌ {ch['name']}", callback_data=f"delch_{i}"))
        bot.send_message(call.message.chat.id, "রিমুভ করতে চান এমন চ্যানেল বেছে নিন:", reply_markup=markup)

    elif action == "adm_set_limit":
        admin_state[admin_id] = {"step": "limit"}
        bot.send_message(call.message.chat.id, "🔢 নতুন দৈনিক লিমিট সংখ্যা পাঠান (যেমন: `15`):")

    elif action == "adm_set_refbonus":
        admin_state[admin_id] = {"step": "refbonus"}
        bot.send_message(
            call.message.chat.id,
            "🎁 প্রতিটা সফল রেফারে ইউজার কত এক্সট্রা রিকোয়েস্ট লিমিট পাবে তা লিখুন (যেমন: `3`):"
        )

    elif action == "adm_add_button":
        admin_state[admin_id] = {"step": "button_text"}
        bot.send_message(call.message.chat.id, "🔘 নতুন বাটনের নাম পাঠান (যেমন: `🎬 মুভি সার্চ`):")

    elif action == "adm_remove_button":
        buttons = db["config"]["buttons"]
        if not buttons:
            bot.send_message(call.message.chat.id, "কোনো কাস্টম বাটন যুক্ত নেই।")
            return
        markup = types.InlineKeyboardMarkup()
        for i, b in enumerate(buttons):
            markup.add(types.InlineKeyboardButton(f"❌ {b['text']}", callback_data=f"delbtn_{i}"))
        bot.send_message(call.message.chat.id, "রিমুভ করতে চান এমন বাটন বেছে নিন:", reply_markup=markup)

    elif action == "adm_set_emoji":
        admin_state[admin_id] = {"step": "emoji_id"}
        bot.send_message(
            call.message.chat.id,
            "😎 প্রিমিয়াম ইমোজির *custom_emoji_id* পাঠান (না জানলে `skip` লিখুন):"
        )

    elif action == "adm_stats":
        total_users = len(db["users"])
        active_api = get_active_api(db)
        bot.send_message(
            call.message.chat.id,
            "📊 *বট স্ট্যাটাস*\n\n"
            f"👤 মোট ইউজার: *{total_users}*\n"
            f"🔢 দৈনিক লিমিট: *{db['config']['daily_limit']}*\n"
            f"🎁 রেফার বোনাস: *{db['config']['referral_bonus']}*\n"
            f"🔗 চালু থাকা API: *{active_api['name'] if active_api else 'নেই'}*\n"
            f"📢 ফোর্স চ্যানেল: *{len(db['config']['force_channels'])}*\n"
            f"🔘 কাস্টম বাটন: *{len(db['config']['buttons'])}*"
        )

    elif action == "adm_broadcast":
        admin_state[admin_id] = {"step": "broadcast"}
        bot.send_message(call.message.chat.id, "📣 সব ইউজারকে যে মেসেজ পাঠাতে চান তা লিখুন:")


@bot.callback_query_handler(func=lambda call: call.data.startswith("setapi_"))
def set_active_api_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    if 0 <= idx < len(db["config"]["apis"]):
        db["config"]["active_api_index"] = idx
        save_db(db)
        bot.answer_callback_query(call.id, f"✅ '{db['config']['apis'][idx]['name']}' চালু করা হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ এখন থেকে বট *{db['config']['apis'][idx]['name']}* API ব্যবহার করবে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delapi_"))
def delete_api_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    try:
        if len(db["config"]["apis"]) <= 1:
            bot.answer_callback_query(call.id, "⚠️ কমপক্ষে একটা API থাকা লাগবে।", show_alert=True)
            return
        removed = db["config"]["apis"].pop(idx)
        if db["config"]["active_api_index"] >= len(db["config"]["apis"]):
            db["config"]["active_api_index"] = 0
        save_db(db)
        bot.answer_callback_query(call.id, "✅ রিমুভ হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ API *{removed['name']}* রিমুভ করা হয়েছে।")
    except IndexError:
        bot.answer_callback_query(call.id, "❌ ভুল হয়েছে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("setmode_"))
def set_mode_callback(call):
    mode_key = call.data.split("_", 1)[1]
    if mode_key not in MODE_LABELS:
        return
    db = load_db()
    user = get_user(db, call.from_user.id)

    # 'random' মোড চালু করতে হলে আগে বয়স নিশ্চিত করতে হবে
    if mode_key == "random" and not user.get("age_verified"):
        save_db(db)
        bot.answer_callback_query(call.id)
        bot.send_message(
            call.message.chat.id,
            "🔞 *বয়স নিশ্চিতকরণ*\n\nএই মোড চালু করার আগে জানাতে হবে — আপনার বয়স কি ১৮ বছরের বেশি?",
            reply_markup=age_confirm_markup()
        )
        return

    user["mode"] = mode_key
    save_db(db)
    bot.answer_callback_query(call.id, f"✅ {MODE_LABELS[mode_key]} চালু হয়েছে।")
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id,
            reply_markup=mode_select_markup(mode_key)
        )
    except Exception:
        pass
    bot.send_message(
        call.message.chat.id, f"✅ {MODE_LABELS[mode_key]} চালু করা হয়েছে।",
        reply_markup=main_menu_markup(db, user_mode=mode_key)
    )


@bot.callback_query_handler(func=lambda call: call.data == "ageverify_yes")
def age_verify_yes_callback(call):
    db = load_db()
    user = get_user(db, call.from_user.id)
    user["age_verified"] = True
    user["mode"] = "random"
    save_db(db)
    bot.answer_callback_query(call.id, "✅ নিশ্চিত করা হলো।")
    bot.send_message(
        call.message.chat.id,
        "✅ ধন্যবাদ! 🎲 *র্যান্ডম ছবি মোড* চালু হয়েছে।\n"
        "নিচের '🎲 র্যান্ডম ছবি' বাটনে ট্যাপ করলেই একটা র্যান্ডম (নিরাপদ, সাধারণ বিষয়ের) ছবি পাবেন।",
        reply_markup=main_menu_markup(db, user_mode="random")
    )


@bot.callback_query_handler(func=lambda call: call.data == "ageverify_no")
def age_verify_no_callback(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "❌ ঠিক আছে, এই মোড ১৮+ ব্যবহারকারীদের জন্য, তাই চালু করা হলো না।"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("setimgapi_"))
def set_active_image_api_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    apis = db["config"].get("image_apis", [])
    if 0 <= idx < len(apis):
        db["config"]["active_image_api_index"] = idx
        save_db(db)
        bot.answer_callback_query(call.id, f"✅ '{apis[idx]['name']}' চালু করা হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ এখন থেকে বট ছবির জন্য *{apis[idx]['name']}* ব্যবহার করবে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delimgapi_"))
def delete_image_api_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    try:
        apis = db["config"].get("image_apis", [])
        removed = apis.pop(idx)
        if db["config"].get("active_image_api_index", 0) >= len(apis):
            db["config"]["active_image_api_index"] = 0
        db["config"]["image_apis"] = apis
        save_db(db)
        bot.answer_callback_query(call.id, "✅ রিমুভ হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ ইমেজ API *{removed['name']}* রিমুভ করা হয়েছে।")
    except IndexError:
        bot.answer_callback_query(call.id, "❌ ভুল হয়েছে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("setvisionapi_"))
def set_active_vision_api_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    apis = db["config"].get("vision_apis", [])
    if 0 <= idx < len(apis):
        db["config"]["active_vision_api_index"] = idx
        save_db(db)
        bot.answer_callback_query(call.id, f"✅ '{apis[idx]['name']}' চালু করা হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ এখন থেকে বট ছবি অ্যানালাইসিসের জন্য *{apis[idx]['name']}* ব্যবহার করবে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delvisionapi_"))
def delete_vision_api_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    try:
        apis = db["config"].get("vision_apis", [])
        removed = apis.pop(idx)
        if db["config"].get("active_vision_api_index", 0) >= len(apis):
            db["config"]["active_vision_api_index"] = 0
        db["config"]["vision_apis"] = apis
        save_db(db)
        bot.answer_callback_query(call.id, "✅ রিমুভ হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ ভিশন API *{removed['name']}* রিমুভ করা হয়েছে।")
    except IndexError:
        bot.answer_callback_query(call.id, "❌ ভুল হয়েছে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delch_"))
def delete_channel_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    try:
        removed = db["config"]["force_channels"].pop(idx)
        save_db(db)
        bot.answer_callback_query(call.id, "✅ রিমুভ হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ চ্যানেল *{removed['name']}* রিমুভ করা হয়েছে।")
    except IndexError:
        bot.answer_callback_query(call.id, "❌ ভুল হয়েছে।")


@bot.callback_query_handler(func=lambda call: call.data.startswith("delbtn_"))
def delete_button_callback(call):
    if not is_admin(call.from_user.id):
        return
    idx = int(call.data.split("_")[1])
    db = load_db()
    try:
        removed = db["config"]["buttons"].pop(idx)
        save_db(db)
        bot.answer_callback_query(call.id, "✅ রিমুভ হয়েছে।")
        bot.send_message(call.message.chat.id, f"✅ বাটন *{removed['text']}* রিমুভ করা হয়েছে।")
    except IndexError:
        bot.answer_callback_query(call.id, "❌ ভুল হয়েছে।")


@bot.message_handler(func=lambda m: m.from_user.id in admin_state, content_types=["text"])
def admin_input_handler(message):
    admin_id = message.from_user.id
    state = admin_state.get(admin_id)
    if not state:
        return
    db = load_db()
    step = state["step"]
    text = message.text.strip()

    # ---- নতুন API যুক্ত করার ধাপগুলো ----
    if step == "api_name":
        state["name"] = text
        state["step"] = "api_url"
        bot.send_message(message.chat.id, "🔗 এই API-র *URL* পাঠান:")

    elif step == "api_url":
        state["url"] = text
        state["step"] = "api_key"
        bot.send_message(message.chat.id, "🔑 API *Key* পাঠান (না থাকলে `none` লিখুন):")

    elif step == "api_key":
        state["key"] = "" if text.lower() == "none" else text
        state["step"] = "api_query_param"
        bot.send_message(message.chat.id, "❓ প্রশ্নের প্যারামিটার নাম কী? (ডিফল্টের জন্য `skip` লিখুন → `query`)")

    elif step == "api_query_param":
        state["query_param"] = "query" if text.lower() == "skip" else text
        state["step"] = "api_apikey_param"
        bot.send_message(message.chat.id, "🔑 API-কী প্যারামিটার নাম কী? (ডিফল্টের জন্য `skip` লিখুন → `apikey`)")

    elif step == "api_apikey_param":
        apikey_param = "apikey" if text.lower() == "skip" else text
        db["config"]["apis"].append({
            "name": state["name"],
            "url": state["url"],
            "key": state["key"],
            "query_param": state["query_param"],
            "apikey_param": apikey_param,
        })
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(
            message.chat.id,
            f"✅ API *{state['name']}* যুক্ত হয়েছে!\n\n"
            "📋 'API লিস্ট/সিলেক্ট' থেকে এটাকে চালু (active) করে দিন।"
        )

    # ---- নতুন ভিশন (ছবি অ্যানালাইসিস) API যুক্ত করার ধাপগুলো ----
    elif step == "vision_api_name":
        state["name"] = text
        state["step"] = "vision_api_url"
        bot.send_message(message.chat.id, "🔗 এই ভিশন API-র *URL* পাঠান:")

    elif step == "vision_api_url":
        state["url"] = text
        state["step"] = "vision_api_key"
        bot.send_message(message.chat.id, "🔑 API *Key* পাঠান (না থাকলে `none` লিখুন):")

    elif step == "vision_api_key":
        state["key"] = "" if text.lower() == "none" else text
        state["step"] = "vision_api_image_param"
        bot.send_message(message.chat.id, "🖼 ছবির URL পাঠানোর প্যারামিটার নাম কী? (ডিফল্টের জন্য `skip` লিখুন → `image_url`)")

    elif step == "vision_api_image_param":
        state["image_param"] = "image_url" if text.lower() == "skip" else text
        state["step"] = "vision_api_apikey_param"
        bot.send_message(message.chat.id, "🔑 API-কী প্যারামিটার নাম কী? (ডিফল্টের জন্য `skip` লিখুন → `apikey`)")

    elif step == "vision_api_apikey_param":
        apikey_param = "apikey" if text.lower() == "skip" else text
        db["config"].setdefault("vision_apis", []).append({
            "name": state["name"],
            "url": state["url"],
            "key": state["key"],
            "image_param": state["image_param"],
            "apikey_param": apikey_param,
        })
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(
            message.chat.id,
            f"✅ ভিশন API *{state['name']}* যুক্ত হয়েছে!\n\n"
            "📋 'ভিশন API লিস্ট/সিলেক্ট' থেকে এটাকে চালু (active) করে দিন।"
        )

    # ---- নতুন ইমেজ API যুক্ত করার ধাপগুলো ----
    elif step == "img_api_name":
        state["name"] = text
        state["step"] = "img_api_url"
        bot.send_message(message.chat.id, "🔗 এই ইমেজ API-র *URL* পাঠান:")

    elif step == "img_api_url":
        state["url"] = text
        state["step"] = "img_api_key"
        bot.send_message(message.chat.id, "🔑 API *Key* পাঠান (না থাকলে `none` লিখুন):")

    elif step == "img_api_key":
        state["key"] = "" if text.lower() == "none" else text
        state["step"] = "img_api_query_param"
        bot.send_message(message.chat.id, "❓ প্রম্পট/প্রশ্নের প্যারামিটার নাম কী? (ডিফল্টের জন্য `skip` লিখুন → `query`)")

    elif step == "img_api_query_param":
        state["query_param"] = "query" if text.lower() == "skip" else text
        state["step"] = "img_api_apikey_param"
        bot.send_message(message.chat.id, "🔑 API-কী প্যারামিটার নাম কী? (ডিফল্টের জন্য `skip` লিখুন → `apikey`)")

    elif step == "img_api_apikey_param":
        apikey_param = "apikey" if text.lower() == "skip" else text
        db["config"].setdefault("image_apis", []).append({
            "name": state["name"],
            "url": state["url"],
            "key": state["key"],
            "query_param": state["query_param"],
            "apikey_param": apikey_param,
        })
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(
            message.chat.id,
            f"✅ ইমেজ API *{state['name']}* যুক্ত হয়েছে!\n\n"
            "📋 'ইমেজ API লিস্ট/সিলেক্ট' থেকে এটাকে চালু (active) করে দিন।"
        )

    # ---- বাকি ধাপগুলো ----
    elif step == "channel_username":
        state["username"] = text
        state["step"] = "channel_name"
        bot.send_message(message.chat.id, "চ্যানেলের একটা সুন্দর *নাম* দিন (ইউজারদের দেখানোর জন্য):")

    elif step == "channel_name":
        db["config"]["force_channels"].append({"username": state["username"], "name": text})
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(
            message.chat.id,
            "✅ চ্যানেল যুক্ত করা হয়েছে!\n\n"
            "⚠️ *জরুরি*: বটকে ওই চ্যানেলে *এডমিন* বানিয়ে দিন, নাহলে জয়েন চেক কাজ করবে না।"
        )

    elif step == "limit":
        try:
            new_limit = int(text)
            db["config"]["daily_limit"] = new_limit
            save_db(db)
            del admin_state[admin_id]
            bot.send_message(message.chat.id, f"✅ দৈনিক লিমিট *{new_limit}* করা হয়েছে!")
        except ValueError:
            bot.send_message(message.chat.id, "❌ দয়া করে সঠিক একটি সংখ্যা দিন!")

    elif step == "refbonus":
        try:
            bonus = int(text)
            db["config"]["referral_bonus"] = bonus
            save_db(db)
            del admin_state[admin_id]
            bot.send_message(message.chat.id, f"✅ রেফার বোনাস *{bonus}* করা হয়েছে!")
        except ValueError:
            bot.send_message(message.chat.id, "❌ দয়া করে সঠিক একটি সংখ্যা দিন!")

    elif step == "button_text":
        db["config"]["buttons"].append({"text": text})
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(message.chat.id, "✅ নতুন বাটন যুক্ত করা হয়েছে! /start দিয়ে চেক করুন।")

    elif step == "emoji_id":
        db["config"]["premium_emoji_id"] = "" if text.lower() == "skip" else text
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(message.chat.id, "✅ প্রিমিয়াম ইমোজি সেটিং সেভ করা হয়েছে!")

    elif step == "broadcast":
        del admin_state[admin_id]
        sent, failed = 0, 0
        for uid in list(db["users"].keys()):
            try:
                bot.send_message(int(uid), f"📢 {text}")
                sent += 1
            except Exception:
                failed += 1
        bot.send_message(message.chat.id, f"✅ ব্রডকাস্ট সম্পন্ন!\n✔️ পাঠানো হয়েছে: {sent}\n❌ ফেইল: {failed}")


# ========================= ইউজারের পাঠানো ছবি অ্যানালাইসিস =========================
@bot.message_handler(func=lambda m: m.from_user.id not in admin_state, content_types=["photo"])
def photo_handler(message):
    user_id = message.from_user.id
    db = load_db()

    if not check_joined_channels(user_id):
        bot.reply_to(
            message,
            "⚠️ বট ব্যবহার করার আগে নিচের চ্যানেল(গুলো)-তে জয়েন করুন 👇",
            reply_markup=join_markup(db)
        )
        return

    user = get_user(db, user_id)
    if user.get("banned"):
        bot.reply_to(message, "⛔ আপনাকে বট থেকে ব্যান করা হয়েছে।")
        return

    limit = effective_limit(db, user)
    if user["requests_today"] >= limit:
        bot.reply_to(message, "⚠️ আজকের জন্য আপনার লিমিট শেষ! রেফার করে লিমিট বাড়িয়ে নিন।")
        return

    # ---- 'ইমেজ মোড' অন থাকলে: আপলোড করা ছবি + ক্যাপশনের প্রম্পট দিয়ে নতুন ছবি বানানো হবে ----
    if user.get("mode") == "image":
        active_image_api = get_active_image_api(db)
        if not active_image_api:
            bot.reply_to(message, "⚠️ কোনো ইমেজ API চালু নেই, এডমিনকে জানান।")
            return

        thinking_msg = bot.reply_to(message, "🎨 আপনার ছবি অনুযায়ী নতুন ছবি বানানো হচ্ছে...")
        try:
            file_id = message.photo[-1].file_id
            file_info = bot.get_file(file_id)
            base_image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
            prompt_text = (message.caption or "এই ছবিটা আরও সুন্দর করে বানাও").strip()

            params = build_api_params(active_image_api, active_image_api["query_param"], prompt_text)
            # রেফারেন্স ছবির URL — বেশিরভাগ ইমেজ API-তে এই প্যারামিটার নামটাই ব্যবহার হয়
            params.setdefault("image_url", base_image_url)

            res = api_get_with_retry(active_image_api["url"], params, timeout=600, retries=0)
            print(f"[DEBUG] IMAGE(edit) API status_code={res.status_code} content_type={res.headers.get('content-type')}")
            res.raise_for_status()

            content_type = res.headers.get("content-type", "")
            if content_type.startswith("image/") or looks_like_image_bytes(res.content):
                photo_data = res.content
            else:
                data = res.json()
                image_url = extract_image_url(data)
                if not image_url:
                    print(f"[DEBUG] extract_image_url FAILED to find url in: {data}")
                    bot.edit_message_text(
                        "❌ API থেকে কোনো ছবি পাওয়া যায়নি।",
                        chat_id=message.chat.id, message_id=thinking_msg.message_id
                    )
                    return
                photo_data = image_url if image_url.startswith("http") else base64.b64decode(image_url)

            user["requests_today"] += 1
            user["chat_history"].append({"role": "user", "content": f"[ছবি + প্রম্পট: {prompt_text}]", "ts": time.time()})
            user["chat_history"] = user["chat_history"][-20:]
            save_db(db)

            bot.delete_message(message.chat.id, thinking_msg.message_id)
            bot.send_photo(message.chat.id, photo_data, caption="🎨 আপনার নতুন ছবি তৈরি হয়েছে!")
        except Exception as e:
            print(f"[DEBUG] IMAGE(edit) API call exception: {e}")
            try:
                bot.edit_message_text(
                    f"❌ ছবি বানাতে সমস্যা হয়েছে।\n`Error: {e}`",
                    chat_id=message.chat.id, message_id=thinking_msg.message_id
                )
            except Exception:
                bot.send_message(message.chat.id, f"❌ ছবি বানাতে সমস্যা হয়েছে।\n`Error: {e}`")
        return

    # ---- অন্য মোডে থাকলে: আগের মতোই ছবি অ্যানালাইসিস (ভিশন API) ----
    active_vision_api = get_active_vision_api(db)
    if not active_vision_api:
        bot.reply_to(message, "⚠️ কোনো ভিশন (ছবি অ্যানালাইসিস) API চালু নেই, এডমিনকে জানান।")
        return

    thinking_msg = bot.reply_to(message, "🔍 ছবিটা অ্যানালাইসিস করা হচ্ছে, একটু অপেক্ষা করুন...")

    try:
        # টেলিগ্রামে সবচেয়ে বড় সাইজের ছবিটা নেওয়া হচ্ছে, তারপর তার পাবলিক URL বের করা হচ্ছে
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        image_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

        # যদি ইউজার ছবির সাথে ক্যাপশনে কিছু জিজ্ঞেস করে থাকে সেটাও পাঠানো হবে
        caption_text = (message.caption or "এই ছবিতে কী আছে বিস্তারিত বলো").strip()

        params = build_api_params(active_vision_api, active_vision_api["image_param"], image_url)
        params["query"] = caption_text
        res = api_get_with_retry(active_vision_api["url"], params, timeout=600, retries=0)
        print(f"[DEBUG] VISION API status_code={res.status_code} raw_response={res.text[:2000]}")
        res.raise_for_status()
        data = res.json()
        answer = extract_answer(data)
        if not answer:
            print(f"[DEBUG] extract_answer FAILED to find text in: {data}")
            answer = "❌ API থেকে ছবি সম্পর্কে কোনো বোধগম্য তথ্য পাওয়া যায়নি।"
    except Exception as e:
        print(f"[DEBUG] VISION API call exception: {e}")
        answer = f"❌ ছবি অ্যানালাইসিস করতে সমস্যা হয়েছে।\n`Error: {e}`"

    user["requests_today"] += 1
    user["chat_history"].append({"role": "user", "content": "[পাঠানো ছবি]", "ts": time.time()})
    user["chat_history"].append({"role": "assistant", "content": answer, "ts": time.time()})
    user["chat_history"] = user["chat_history"][-20:]
    save_db(db)

    try:
        bot.delete_message(message.chat.id, thinking_msg.message_id)
    except Exception:
        pass
    send_long_answer(message.chat.id, answer, reply_to_message_id=message.message_id)


# ========================= সাধারণ ইউজার মেসেজ (AI চ্যাট) =========================
@bot.message_handler(func=lambda m: m.from_user.id not in admin_state, content_types=["text"])
def general_text_handler(message):
    user_id = message.from_user.id
    text = message.text.strip()

    if text == "❓ হেল্প":
        bot.reply_to(
            message,
            "🤖 আমি *ZONE AI* বট।\n\n"
            "✅ আমাকে যা ইচ্ছা লিখে পাঠান, আমি সরাসরি উত্তর দিব।\n"
            "✅ প্রতিদিন একটা নির্দিষ্ট সংখ্যক প্রশ্ন করতে পারবেন।\n"
            "✅ বন্ধুকে রেফার করে লিমিট বাড়িয়ে নিন — '🔗 রেফার করুন' বাটনে চাপুন।"
        )
        return

    db = load_db()

    if text == "📊 আমার তথ্য":
        user = get_user(db, user_id)
        save_db(db)
        limit = effective_limit(db, user)
        remaining = max(0, limit - user["requests_today"])
        bot.reply_to(
            message,
            "👤 *আপনার তথ্য*\n\n"
            f"🆔 আইডি: `{user_id}`\n"
            f"📩 আজ ব্যবহার করেছেন: *{user['requests_today']}*\n"
            f"⚡ মোট দৈনিক লিমিট: *{limit}* (বেস {db['config']['daily_limit']} + বোনাস {user.get('bonus_limit', 0)})\n"
            f"🎯 বাকি আছে: *{remaining}*\n"
            f"🔗 রেফার করেছেন: *{user.get('referrals_count', 0)}* জনকে"
        )
        return

    if text == "🔗 রেফার করুন":
        user = get_user(db, user_id)
        save_db(db)
        link = referral_link(user_id)
        bonus = db["config"]["referral_bonus"]
        bot.reply_to(
            message,
            "🔗 *আপনার রেফার লিংক:*\n"
            f"`{link}`\n\n"
            f"🎁 এই লিংক দিয়ে কেউ বটে জয়েন করলে আপনার দৈনিক লিমিট *+{bonus}* বেড়ে যাবে!\n"
            f"👥 এ পর্যন্ত রেফার করেছেন: *{user.get('referrals_count', 0)}* জনকে"
        )
        return

    if text == "🎛 মোড পরিবর্তন":
        user = get_user(db, user_id)
        save_db(db)
        current = user.get("mode", "chat")
        bot.reply_to(
            message,
            f"🎛 বর্তমান মোড: *{MODE_LABELS.get(current, current)}*\n\n"
            "💬 *চ্যাট মোড* — সাধারণ প্রশ্ন-উত্তর\n"
            "🎨 *ইমেজ মোড* — অন থাকলে আপনি যা-ই লিখবেন সেটাই ছবির প্রম্পট হিসেবে ধরা হবে "
            "(কোনো 'ছবি দাও' লেখার দরকার নেই), আর ছবি পাঠালে সেটার সাথে ক্যাপশনে লেখা প্রম্পট "
            "অনুযায়ী নতুন ছবি বানিয়ে দিবে।\n"
            "💻 *কোড মোড* — অন থাকলে যেকোনো উত্তরই ফাইল আকারে পাঠানো হবে, ছোট হলেও।\n"
            "🎲 *র্যান্ডম ছবি মোড* — বয়স নিশ্চিতকরণ লাগবে, চালু হলে বাটনে চাপ দিলেই একটা "
            "র্যান্ডম (নিরাপদ বিষয়ের) ছবি পাবেন।\n\n"
            "নিচ থেকে মোড বেছে নিন:",
            reply_markup=mode_select_markup(current)
        )
        return

    if text == "🎲 র্যান্ডম ছবি":
        user = get_user(db, user_id)
        if not user.get("age_verified") or user.get("mode") != "random":
            bot.reply_to(message, "⚠️ আগে '🎛 মোড পরিবর্তন' থেকে র্যান্ডম ছবি মোড চালু করুন।")
            return
        limit = effective_limit(db, user)
        if user["requests_today"] >= limit:
            bot.reply_to(message, "⚠️ আজকের জন্য আপনার লিমিট শেষ! রেফার করে লিমিট বাড়িয়ে নিন।")
            return
        active_image_api = get_active_image_api(db)
        if not active_image_api:
            bot.reply_to(message, "⚠️ কোনো ইমেজ API চালু নেই, এডমিনকে জানান।")
            return

        thinking_msg = bot.reply_to(message, "🎲 একটা র্যান্ডম ছবি খোঁজা হচ্ছে...")
        try:
            subject = random.choice(SAFE_RANDOM_SUBJECTS)
            params = build_api_params(active_image_api, active_image_api["query_param"], subject)
            res = api_get_with_retry(active_image_api["url"], params, timeout=600, retries=0)
            res.raise_for_status()
            content_type = res.headers.get("content-type", "")
            if content_type.startswith("image/") or looks_like_image_bytes(res.content):
                photo_data = res.content
            else:
                data = res.json()
                image_url = extract_image_url(data)
                if not image_url:
                    bot.edit_message_text(
                        "❌ র্যান্ডম ছবি পাওয়া যায়নি, আবার চেষ্টা করুন।",
                        chat_id=message.chat.id, message_id=thinking_msg.message_id
                    )
                    return
                photo_data = image_url if image_url.startswith("http") else base64.b64decode(image_url)

            user["requests_today"] += 1
            save_db(db)
            bot.delete_message(message.chat.id, thinking_msg.message_id)
            bot.send_photo(message.chat.id, photo_data, caption=f"🎲 র্যান্ডম বিষয়: {subject}")
        except Exception as e:
            print(f"[DEBUG] RANDOM PICTURE exception: {e}")
            try:
                bot.edit_message_text(
                    "❌ র্যান্ডম ছবি আনতে সমস্যা হয়েছে, আবার চেষ্টা করুন।",
                    chat_id=message.chat.id, message_id=thinking_msg.message_id
                )
            except Exception:
                pass
        return

    if not check_joined_channels(user_id):
        bot.reply_to(
            message,
            "⚠️ বট ব্যবহার করার আগে নিচের চ্যানেল(গুলো)-তে জয়েন করুন 👇",
            reply_markup=join_markup(db)
        )
        return

    user = get_user(db, user_id)
    if user.get("banned"):
        bot.reply_to(message, "⛔ আপনাকে বট থেকে ব্যান করা হয়েছে।")
        return

    limit = effective_limit(db, user)
    if user["requests_today"] >= limit:
        bot.reply_to(
            message,
            "⏳ আপনার আজকের রিকোয়েস্ট লিমিট শেষ হয়ে গেছে!\n"
            "আগামীকাল আবার চেষ্টা করুন, অথবা বন্ধুকে রেফার করে লিমিট বাড়িয়ে নিন। 🔗"
        )
        return

    # ---- ইমেজ মোড অন থাকলে সব লেখাই প্রম্পট, নাহলে কীওয়ার্ড দেখে বোঝা হচ্ছে ----
    user_mode = user.get("mode", "chat")
    if user_mode == "image" or is_image_request(text):
        active_image_api = get_active_image_api(db)
        if not active_image_api:
            bot.reply_to(message, "⚠️ কোনো ইমেজ API চালু নেই, এডমিনকে জানান।")
            return

        thinking_msg = bot.reply_to(message, "🎨 ছবি বানানো হচ্ছে, একটু অপেক্ষা করুন...")

        try:
            params = {
                active_image_api["query_param"]: text,
                active_image_api["apikey_param"]: active_image_api["key"],
            }
            res = api_get_with_retry(active_image_api["url"], params, timeout=600, retries=0)
            print(f"[DEBUG] IMAGE API status_code={res.status_code} content_type={res.headers.get('content-type')}")
            res.raise_for_status()

            content_type = res.headers.get("content-type", "")
            if content_type.startswith("image/") or looks_like_image_bytes(res.content):
                photo_data = res.content  # API সরাসরি ছবির বাইট রিটার্ন করেছে
            else:
                try:
                    data = res.json()
                except ValueError:
                    # JSON ও না, ছবির বাইটও না — হয়তো প্লেইন টেক্সটে সরাসরি URL পাঠিয়েছে
                    body = res.text.strip()
                    if body.startswith("http"):
                        photo_data = body
                    else:
                        print(f"[DEBUG] IMAGE API returned unrecognized non-JSON body: {body[:300]}")
                        bot.edit_message_text(
                            "❌ ইমেজ API থেকে বোধগম্য কোনো রেসপন্স পাওয়া যায়নি।",
                            chat_id=message.chat.id, message_id=thinking_msg.message_id
                        )
                        return
                    user["requests_today"] += 1
                    user["chat_history"].append({"role": "user", "content": text, "ts": time.time()})
                    user["chat_history"] = user["chat_history"][-20:]
                    save_db(db)
                    bot.delete_message(message.chat.id, thinking_msg.message_id)
                    bot.send_photo(message.chat.id, photo_data, caption="🎨 আপনার ছবি তৈরি হয়েছে!")
                    return
                image_url = extract_image_url(data)
                if not image_url:
                    print(f"[DEBUG] extract_image_url FAILED to find url in: {data}")
                    bot.edit_message_text(
                        "❌ API থেকে কোনো ছবি পাওয়া যায়নি।",
                        chat_id=message.chat.id, message_id=thinking_msg.message_id
                    )
                    return
                if image_url.startswith("http"):
                    photo_data = image_url  # সরাসরি URL, send_photo নিজেই ডাউনলোড করে নেবে
                else:
                    photo_data = base64.b64decode(image_url)  # base64 হলে ডিকোড

            user["requests_today"] += 1
            user["chat_history"].append({"role": "user", "content": text, "ts": time.time()})
            user["chat_history"] = user["chat_history"][-20:]
            save_db(db)

            bot.delete_message(message.chat.id, thinking_msg.message_id)
            bot.send_photo(message.chat.id, photo_data, caption="🎨 আপনার ছবি তৈরি হয়েছে!")
        except Exception as e:
            print(f"[DEBUG] IMAGE API call exception: {e}")
            try:
                bot.edit_message_text(
                    f"❌ ছবি আনতে সমস্যা হয়েছে।\n`Error: {e}`",
                    chat_id=message.chat.id, message_id=thinking_msg.message_id
                )
            except Exception:
                bot.send_message(message.chat.id, f"❌ ছবি আনতে সমস্যা হয়েছে।\n`Error: {e}`")
        return

    # ---- সাধারণ টেক্সট প্রশ্ন — আগের টেক্সট API দিয়ে উত্তর ----
    active_api = get_active_api(db)
    if not active_api:
        bot.reply_to(message, "⚠️ কোনো API চালু নেই, এডমিনকে জানান।")
        return

    thinking_msg = bot.reply_to(message, "🤔 চিন্তা করছি, একটু অপেক্ষা করুন...")

    try:
        params = {
            active_api["query_param"]: text,
            active_api["apikey_param"]: active_api["key"],
        }
        res = api_get_with_retry(active_api["url"], params, timeout=600, retries=0)
        # ডিবাগের জন্য raw রেসপন্স Railway লগে প্রিন্ট হচ্ছে (সমস্যা হলে এখান থেকে কারণ বোঝা যাবে)
        print(f"[DEBUG] API status_code={res.status_code} raw_response={res.text[:2000]}")
        res.raise_for_status()
        data = res.json()
        answer = extract_answer(data)
        if not answer:
            print(f"[DEBUG] extract_answer FAILED to find text in: {data}")
            answer = "❌ API থেকে কোনো বোধগম্য উত্তর পাওয়া যায়নি।"
    except requests.exceptions.Timeout:
        print("[DEBUG] API call timed out after retries")
        answer = "⏳ API থেকে উত্তর আসতে অনেক সময় নিচ্ছে। একটু পর আবার চেষ্টা করুন।"
    except Exception as e:
        print(f"[DEBUG] API call exception: {e}")
        answer = f"❌ AI থেকে উত্তর আনতে সমস্যা হয়েছে।\n`Error: {e}`"

    user["requests_today"] += 1
    # চ্যাট হিস্ট্রি সেভ করা হচ্ছে (প্রতি ২ ঘণ্টা পরপর অটো-ক্লিয়ার হবে, নিচে দেখুন)
    user["chat_history"].append({"role": "user", "content": text, "ts": time.time()})
    user["chat_history"].append({"role": "assistant", "content": answer, "ts": time.time()})
    user["chat_history"] = user["chat_history"][-20:]
    save_db(db)

    emoji_char = db["config"].get("premium_emoji_char", "✨")

    # ---- বড় কোড/লম্বা উত্তর হলে, অথবা 'কোড মোড' অন থাকলে ফাইল আকারে পাঠানো হয় ----
    if should_send_as_file(answer) or user_mode == "code":
        try:
            bot.delete_message(message.chat.id, thinking_msg.message_id)
        except Exception:
            pass
        send_long_answer(message.chat.id, answer, reply_to_message_id=message.message_id, force=(user_mode == "code"))
        return

    reply_text = f"{emoji_char} {answer}"
    entities = build_emoji_entities(db, len(emoji_char))

    try:
        bot.edit_message_text(
            reply_text,
            chat_id=message.chat.id,
            message_id=thinking_msg.message_id,
            entities=entities
        )
    except Exception:
        bot.edit_message_text(
            reply_text,
            chat_id=message.chat.id,
            message_id=thinking_msg.message_id
        )


def clear_all_chat_histories():
    """
    শুধু প্রতিটা ইউজারের 'chat_history' খালি করে দেয় (মেমোরি/স্টোরেজ হালকা রাখতে)।
    requests_today, banned, bonus_limit, referred_by, referrals_count —
    এসব ডেটা একদম অক্ষত থাকে, শুধু চ্যাট হিস্ট্রি মুছে যায়। Telegram-এ আসল
    চ্যাট মেসেজগুলো যথারীতি থেকেই যাবে, এটা শুধু বটের নিজের ডেটাবেজ থেকে মোছে।
    """
    db = load_db()
    cleared = 0
    for uid, user in db["users"].items():
        if user.get("chat_history"):
            user["chat_history"] = []
            cleared += 1
    save_db(db)
    print(f"[INFO] {cleared} জন ইউজারের চ্যাট হিস্ট্রি ক্লিয়ার করা হলো (অন্য কোনো ডেটা মোছা হয়নি)।")


def chat_history_cleaner_loop():
    while True:
        time.sleep(2 * 60 * 60)  # প্রতি ২ ঘণ্টা পরপর
        try:
            clear_all_chat_histories()
        except Exception as e:
            print(f"[ERROR] চ্যাট হিস্ট্রি ক্লিয়ার করতে সমস্যা: {e}")


# ========================= বট চালু =========================
if __name__ == "__main__":
    try:
        BOT_USERNAME = bot.get_me().username
    except Exception as e:
        print(f"[WARN] get_me() ব্যর্থ হয়েছে: {e}")
        BOT_USERNAME = None

    print("🤖 ZONE AI Bot চালু হয়েছে...")

    # প্রতি ২ ঘণ্টা পরপর চ্যাট হিস্ট্রি অটো-ক্লিয়ার করার ব্যাকগ্রাউন্ড থ্রেড চালু করা হচ্ছে
    threading.Thread(target=chat_history_cleaner_loop, daemon=True).start()

    # নেটওয়ার্ক/কানেকশন এরর হলে যেন পুরো বট ক্র্যাশ করে বন্ধ না হয়ে যায়,
    # তাই polling-কে একটা রিট্রাই লুপে রাখা হয়েছে।
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"[ERROR] Bot polling ক্র্যাশ করেছে: {e}")
            print("[INFO] ৫ সেকেন্ড পর আবার চালু করা হচ্ছে...")
            time.sleep(5)
