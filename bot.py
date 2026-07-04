# bot.py
# ZONE AI - বাংলা টেলিগ্রাম AI বট
# ফিচার: AI চ্যাট (একাধিক কাস্টম API), ফোর্স চ্যানেল জয়েন, দৈনিক রিকোয়েস্ট লিমিট,
#         রেফার সিস্টেম (রেফার করলে লিমিট বাড়ে), এডমিন প্যানেল (একাধিক API, চ্যানেল,
#         লিমিট, বাটন, প্রিমিয়াম ইমোজি, ব্রডকাস্ট, স্ট্যাটাস)

import json
import datetime

import requests
import telebot
from telebot import types

from database import load_db, save_db

# ========================= বেসিক সেটআপ =========================
BOT_TOKEN = "8861000790:AAGmJbbBTLDnN2LJdwfhD0xrh_AKBdQ1p_4"          # <-- @BotFather থেকে পাওয়া টোকেন এখানে দিন
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
        }
    user = db["users"][uid]
    if user.get("last_date") != today_str():
        user["requests_today"] = 0
        user["last_date"] = today_str()
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


def main_menu_markup(db):
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
    markup.row(types.KeyboardButton("❓ হেল্প"))
    return markup


def get_active_api(db):
    apis = db["config"]["apis"]
    idx = db["config"].get("active_api_index", 0)
    if not apis:
        return None
    if idx >= len(apis):
        idx = 0
    return apis[idx]


def extract_answer(data, keys=("text", "response", "answer", "result", "message", "output", "content")):
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
        res = requests.get(active_api["url"], params=params, timeout=30)
        res.raise_for_status()
        data = res.json()
        answer = extract_answer(data) or "❌ API থেকে কোনো বোধগম্য উত্তর পাওয়া যায়নি।"
    except Exception as e:
        answer = f"❌ AI থেকে উত্তর আনতে সমস্যা হয়েছে।\n`Error: {e}`"

    user["requests_today"] += 1
    save_db(db)

    emoji_char = db["config"].get("premium_emoji_char", "✨")
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


# ========================= বট চালু =========================
if __name__ == "__main__":
    try:
        BOT_USERNAME = bot.get_me().username
    except Exception:
        BOT_USERNAME = None
    print("🤖 ZONE AI Bot চালু হয়েছে...")
    bot.infinity_polling(skip_pending=True)
