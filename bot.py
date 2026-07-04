# bot.py
# ZONE AI - বাংলা টেলিগ্রাম AI বট
# ফিচার: AI চ্যাট (কাস্টম API), ফোর্স চ্যানেল জয়েন, দৈনিক রিকোjয়েস্ট লিমিট,
#         এডমিন প্যানেল (API সেট, চ্যানেল, লিমিট, বাটন, প্রিমিয়াম ইমোজি, ব্রডকাস্ট, স্ট্যাটাস)

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


# ========================= হেল্পার ফাংশন =========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def today_str() -> str:
    return datetime.date.today().isoformat()


def get_user(db, user_id):
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {"requests_today": 0, "last_date": today_str(), "banned": False}
    user = db["users"][uid]
    if user.get("last_date") != today_str():
        user["requests_today"] = 0
        user["last_date"] = today_str()
    return user


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
            # বট চ্যানেলে এডমিন না থাকলে বা চ্যানেল ভুল হলেও এখানে এক্সেপশন আসতে পারে
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
    markup.row(types.KeyboardButton("📊 আমার তথ্য"), types.KeyboardButton("❓ হেল্প"))
    return markup


def extract_answer(db, data):
    """API রেসপন্স (dict/str) থেকে বুদ্ধিমানের মত উত্তর খুঁজে বের করা হচ্ছে।"""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in db["config"].get("response_keys", []):
            if key in data and data[key]:
                return str(data[key])
        return json.dumps(data, ensure_ascii=False)
    return str(data)


def build_emoji_entities(db, text_prefix_len):
    """
    প্রিমিয়াম কাস্টম ইমোজি এন্টিটি তৈরি করে (যদি এডমিন প্যানেল থেকে সেট করা থাকে)।
    এটা শুধু টেলিগ্রাম প্রিমিয়াম ইউজারদের কাছে আসলে কাস্টম ইমোজি হিসেবে দেখাবে,
    বাকিদের কাছে সাধারণ ইমোজি হিসেবে দেখাবে।
    """
    emoji_id = db["config"].get("premium_emoji_id")
    if not emoji_id:
        return None
    char = db["config"].get("premium_emoji_char", "✨")
    try:
        return [types.MessageEntity(
            type="custom_emoji",
            offset=0,
            length=len(char),
            custom_emoji_id=emoji_id
        )]
    except Exception:
        return None


# ========================= ইউজার কমান্ড =========================
@bot.message_handler(commands=["start"])
def start_handler(message):
    db = load_db()
    user_id = message.from_user.id
    get_user(db, user_id)
    save_db(db)

    if not check_joined_channels(user_id):
        bot.send_message(
            message.chat.id,
            "👋 স্বাগতম *ZONE AI* বটে!\n\n"
            "বট ব্যবহার করার আগে নিচের চ্যানেল(গুলো)-তে জয়েন করুন 👇",
            reply_markup=join_markup(db)
        )
        return

    bot.send_message(
        message.chat.id,
        "👋 স্বাগতম *ZONE AI* বটে!\n\n"
        "আমাকে যেকোনো প্রশ্ন লিখে পাঠান, আমি AI দিয়ে উত্তর দিব। 🤖✨\n\n"
        f"⚡ আপনার দৈনিক রিকোয়েস্ট লিমিট: *{db['config']['daily_limit']}* টি",
        reply_markup=main_menu_markup(db)
    )


@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    db = load_db()
    if check_joined_channels(call.from_user.id):
        bot.answer_callback_query(call.id, "✅ ধন্যবাদ! আপনি এখন বট ব্যবহার করতে পারবেন।")
        bot.send_message(
            call.message.chat.id,
            "🎉 এখন আমাকে যেকোনো প্রশ্ন লিখে পাঠান!",
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
        types.InlineKeyboardButton("🔗 API সেট করুন", callback_data="adm_set_api"),
        types.InlineKeyboardButton("📢 চ্যানেল যুক্ত করুন", callback_data="adm_add_channel"),
        types.InlineKeyboardButton("🗑 চ্যানেল রিমুভ", callback_data="adm_remove_channel"),
        types.InlineKeyboardButton("🔢 লিমিট পরিবর্তন", callback_data="adm_set_limit"),
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

    if action == "adm_set_api":
        admin_state[admin_id] = {"step": "api_url"}
        bot.send_message(call.message.chat.id, "🔗 নতুন *API URL* পাঠান:")

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
            "😎 প্রিমিয়াম ইমোজির *custom_emoji_id* পাঠান।\n\n"
            "💡 টিপস: যেকোনো প্রিমিয়াম ইমোজি একটি বটে ফরওয়ার্ড করে বা raw update দেখার "
            "টুল দিয়ে `custom_emoji_id` বের করতে পারবেন। না জানলে `skip` লিখুন।"
        )

    elif action == "adm_stats":
        total_users = len(db["users"])
        bot.send_message(
            call.message.chat.id,
            "📊 *বট স্ট্যাটাস*\n\n"
            f"👤 মোট ইউজার: *{total_users}*\n"
            f"🔢 দৈনিক লিমিট: *{db['config']['daily_limit']}*\n"
            f"📢 ফোর্স চ্যানেল সংখ্যা: *{len(db['config']['force_channels'])}*\n"
            f"🔘 কাস্টম বাটন সংখ্যা: *{len(db['config']['buttons'])}*"
        )

    elif action == "adm_broadcast":
        admin_state[admin_id] = {"step": "broadcast"}
        bot.send_message(call.message.chat.id, "📣 সব ইউজারকে যে মেসেজ পাঠাতে চান তা লিখুন:")


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

    if step == "api_url":
        state["api_url"] = text
        state["step"] = "api_key"
        bot.send_message(message.chat.id, "🔑 এখন *API Key* পাঠান (না থাকলে `none` লিখুন):")

    elif step == "api_key":
        db["config"]["api_url"] = state["api_url"]
        db["config"]["api_key"] = "" if text.lower() == "none" else text
        save_db(db)
        del admin_state[admin_id]
        bot.send_message(message.chat.id, "✅ API সফলভাবে আপডেট হয়েছে!")

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
            "✅ আমাকে যেকোনো প্রশ্ন লিখে পাঠান, আমি AI দিয়ে উত্তর দিব।\n"
            "✅ প্রতিদিন একটি নির্দিষ্ট সংখ্যক প্রশ্ন করতে পারবেন।\n"
            "✅ বট ব্যবহার করতে চ্যানেলে জয়েন থাকা বাধ্যতামূলক।"
        )
        return

    db = load_db()

    if text == "📊 আমার তথ্য":
        user = get_user(db, user_id)
        save_db(db)
        remaining = max(0, db["config"]["daily_limit"] - user["requests_today"])
        bot.reply_to(
            message,
            "👤 *আপনার তথ্য*\n\n"
            f"🆔 আইডি: `{user_id}`\n"
            f"📩 আজ ব্যবহার করেছেন: *{user['requests_today']}*\n"
            f"⚡ বাকি আছে: *{remaining}*"
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

    if user["requests_today"] >= db["config"]["daily_limit"]:
        bot.reply_to(
            message,
            "⏳ আপনার আজকের রিকোয়েস্ট লিমিট শেষ হয়ে গেছে!\n"
            "আগামীকাল আবার চেষ্টা করুন। 🙏"
        )
        return

    thinking_msg = bot.reply_to(message, "🤔 চিন্তা করছি, একটু অপেক্ষা করুন...")

    try:
        params = {
            db["config"]["query_param"]: text,
            db["config"]["apikey_param"]: db["config"]["api_key"],
        }
        res = requests.get(db["config"]["api_url"], params=params, timeout=30)
        res.raise_for_status()
        data = res.json()
        answer = extract_answer(db, data)
    except Exception as e:
        answer = f"❌ AI থেকে উত্তর আনতে সমস্যা হয়েছে।\n`Error: {e}`"

    user["requests_today"] += 1
    save_db(db)

    emoji_char = db["config"].get("premium_emoji_char", "✨")
    reply_text = f"{emoji_char} *ZONE AI উত্তর:*\n\n{answer}"
    entities = build_emoji_entities(db, len(emoji_char))

    try:
        bot.edit_message_text(
            reply_text,
            chat_id=message.chat.id,
            message_id=thinking_msg.message_id,
            entities=entities
        )
    except Exception:
        # entities দিয়ে fail করলে সাধারণভাবে পাঠানো হচ্ছে
        bot.edit_message_text(
            reply_text,
            chat_id=message.chat.id,
            message_id=thinking_msg.message_id
        )


# ========================= বট চালু =========================
if __name__ == "__main__":
    print("🤖 ZONE AI Bot চালু হয়েছে...")
    bot.infinity_polling(skip_pending=True)
