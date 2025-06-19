
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
import sqlite3
import threading
import random

# ─── CONFIG ────────────────────────────────────────────────
BOT_TOKEN    = "8142905196:AAHsqCd1spxXLMFNcqY-htemEdyNwRucKoA"
ADMIN_ID     = 1193476710      # your Telegram ID
ADMIN_HANDLE = "@Ankush_Malik"

bot = telebot.TeleBot(BOT_TOKEN)

# ─── DATABASE SETUP & MIGRATION ─────────────────────────────
conn = sqlite3.connect("reward_data.db", check_same_thread=False)
cur  = conn.cursor()

# Create tables if not exist
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id INTEGER PRIMARY KEY
)""")
cur.execute("""
CREATE TABLE IF NOT EXISTS balances (
    telegram_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0
)""")
cur.execute("""
CREATE TABLE IF NOT EXISTS withdraws (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    amount REAL,
    status TEXT DEFAULT 'pending'
)""")
conn.commit()

# Add wallet_addr column if missing
columns = [col[1] for col in cur.execute("PRAGMA table_info(users)")]
if 'wallet_addr' not in columns:
    cur.execute("ALTER TABLE users ADD COLUMN wallet_addr TEXT DEFAULT NULL")
    conn.commit()

# ─── HELPERS ────────────────────────────────────────────────
def add_balance(uid, amt):
    cur.execute(
        "INSERT INTO balances(telegram_id, balance) VALUES (?, ?) "
        "ON CONFLICT(telegram_id) DO UPDATE SET balance = balance + ?",
        (uid, amt, amt)
    )
    conn.commit()

def get_balance(uid):
    cur.execute("SELECT balance FROM balances WHERE telegram_id = ?", (uid,))
    row = cur.fetchone()
    return row[0] if row else 0.0

def set_wallet(uid, addr):
    cur.execute(
        "INSERT OR REPLACE INTO users (telegram_id, wallet_addr) VALUES (?, ?)",
        (uid, addr)
    )
    conn.commit()

def get_wallet(uid):
    cur.execute("SELECT wallet_addr FROM users WHERE telegram_id = ?", (uid,))
    row = cur.fetchone()
    return row[0] if row else None

def create_withdraw_request(uid, amount):
    cur.execute("INSERT INTO withdraws (telegram_id, amount) VALUES (?, ?)", (uid, amount))
    conn.commit()
    return cur.lastrowid

def delete_later(chat_id, msg_id, delay=None):
    if delay is None:
        delay = random.randint(10, 15)
    threading.Timer(delay, lambda: bot.delete_message(chat_id, msg_id)).start()

# ─── KEYBOARDS ──────────────────────────────────────────────
def main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Balance",      callback_data="cmd_balance"),
        InlineKeyboardButton("🎟️ Redeem Code", callback_data="cmd_redeem"),
        InlineKeyboardButton("📤 Withdraw",     callback_data="cmd_withdraw"),
        InlineKeyboardButton("⚙️ Set Address", callback_data="cmd_setaddr"),
        InlineKeyboardButton("❓ Support",      callback_data="cmd_support"),
    )
    return kb

# ─── PRIVATE-CHAT HANDLERS ───────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(msg: Message):
    bot.send_message(
        msg.chat.id,
        "👋 Welcome to the POL Tip bot!",
        reply_markup=main_menu()
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("cmd_"))
def on_menu(cq):
    cmd = cq.data.split("_",1)[1]
    uid = cq.from_user.id
    bot.answer_callback_query(cq.id)

    if cmd == "balance":
        bal = get_balance(uid)
        bot.send_message(uid, f"💰 You have {bal:.3f} POL")

    elif cmd == "redeem":
        bot.send_message(uid,
            "🎟️ Redeem Code: Use /redeem <code> to apply a promo code."
        )

    elif cmd == "withdraw":
        bot.send_message(uid,
            "📤 Withdraw: Send /withdraw <amount> to request a withdrawal."
        )

    elif cmd == "setaddr":
        bot.send_message(uid,
            "⚙️ Set Address: Send /set <0xYourPolygonAddress>",
            )

    elif cmd == "support":
        bot.send_message(uid,
            (
                "❓ Support & Commands:\n"
                "/start – Main menu\n"
                "/set <address> – Link your Polygon address\n"
                "/balance – Check your POL balance\n"
                "/withdraw <amount> – Request withdrawal\n"
                "/redeem <code> – Redeem a promo code\n"
                "/tip <amount> – Tip another user in group (reply to them)\n\n"
                f"🛠️ Admin: {ADMIN_HANDLE}"
            )
        )

@bot.message_handler(commands=['set'])
def cmd_set(msg: Message):
    parts = msg.text.split()
    if len(parts)!=2 or not parts[1].startswith("0x") or len(parts[1])!=42:
        return bot.reply_to(msg, "❌ Invalid format. Usage: /set 0xYourPolygonAddress")
    set_wallet(msg.from_user.id, parts[1])
    bot.reply_to(msg, "✅ Wallet address saved!")

@bot.message_handler(commands=['balance'])
def cmd_balance(msg: Message):
    bal = get_balance(msg.from_user.id)
    bot.reply_to(msg, f"💰 Your POL balance: {bal:.3f}")

@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(msg: Message):
    parts = msg.text.split()
    if len(parts)!=2:
        return bot.reply_to(msg, "Usage: /withdraw <amount>")
    try:
        amt = float(parts[1])
    except:
        return bot.reply_to(msg, "❌ Invalid amount.")
    wallet = get_wallet(msg.from_user.id)
    if not wallet:
        return bot.reply_to(msg, "⚠️ No wallet on file. Use /set <address>.")
    # confirm
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_withdraw:{amt}"),
        InlineKeyboardButton("❌ Cancel",  callback_data="cancel_withdraw")
    ]])
    bot.reply_to(msg, f"📤 Confirm withdrawal of {amt:.3f} POL to {wallet}?", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_withdraw") or c.data=="cancel_withdraw")
def on_withdraw_confirm(cq):
    uid = cq.from_user.id
    data = cq.data
    bot.answer_callback_query(cq.id)
    if data.startswith("confirm_withdraw"):
        amt = float(data.split(":",1)[1])
        bal = get_balance(uid)
        if amt > bal:
            return bot.send_message(uid, "❌ Insufficient balance.")
        add_balance(uid, -amt)
        req_id = create_withdraw_request(uid, amt)
        bot.send_message(ADMIN_ID,
            f"📤 Withdrawal Request #{req_id}\n"
            f"User: {cq.from_user.first_name} (ID: {uid})\n"
            f"Amount: {amt:.3f} POL\n"
            f"Wallet: {get_wallet(uid)}"
        )
        bot.send_message(uid, "✅ Withdrawal request submitted.")
    else:
        bot.send_message(uid, "❌ Withdrawal cancelled.")

@bot.message_handler(commands=['redeem'])
def cmd_redeem(msg: Message):
    # promo logic stub
    bot.reply_to(msg, "🎟️ Feature coming soon.")

# ─── GROUP-CHAT HANDLERS ─────────────────────────────────────
@bot.message_handler(commands=['tip'])
def cmd_tip(msg: Message):
    if not msg.reply_to_message:
        return bot.reply_to(msg, "Reply to a user: /tip <amount>")
    parts = msg.text.split()
    if len(parts)!=2:
        return bot.reply_to(msg, "Usage: Reply + /tip <amount>")
    try:
        amt = float(parts[1])
    except:
        return bot.reply_to(msg, "❌ Invalid amount.")
    sender = msg.from_user.id
    target = msg.reply_to_message.from_user.id
    if get_balance(sender) < amt:
        return bot.reply_to(msg, "❌ Not enough balance.")
    add_balance(sender, -amt)
    add_balance(target, amt)
    bot.reply_to(msg,
        f"💸 {msg.from_user.first_name} tipped {amt:.3f} POL to {msg.reply_to_message.from_user.first_name}!"
    )

@bot.message_handler(content_types=['new_chat_members'])
def on_new_member(msg: Message):
    delete_later(msg.chat.id, msg.message_id)
    inviter = msg.from_user
    for member in msg.new_chat_members:
        add_balance(inviter.id, 0.005)
        add_balance(member.id, 0.01)
        sent = bot.send_message(msg.chat.id,
            f"🎉 {inviter.first_name} +0.005 POL\n"
            f"🎉 {member.first_name} +0.01 POL"
        )
        delete_later(sent.chat.id, sent.message_id)

# ─── RUN BOT ───────────────────────────────────────────────
print("🤖 Bot is up and running!")
bot.infinity_polling()
