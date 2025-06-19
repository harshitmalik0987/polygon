import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    Message, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
import sqlite3
import threading
import random
from datetime import datetime
from web3 import Web3

# CONFIG
BOT_TOKEN = "bot"
ADMIN_ID = 1193476710  # your Telegram ID
ADMIN_HANDLE = "@Ankush_Malik"
POLYGON_RPC_URL = "https://polygon-rpc.com"
ADMIN_PRIVATE_KEY = "admin"
PAYOUT_CHANNEL = '@tR_PayOutChannel'

# Withdrawal settings
MIN_WITHDRAW = 0.08

# INIT
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
web3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
ADMIN_ADDRESS = Web3.to_checksum_address(
    web3.eth.account.from_key(ADMIN_PRIVATE_KEY).address
)

# DATABASE SETUP
conn = sqlite3.connect("reward_data.db", check_same_thread=False)
cur = conn.cursor()

# Base tables
cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        wallet_addr TEXT DEFAULT NULL
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS balances (
        telegram_id INTEGER PRIMARY KEY,
        balance REAL DEFAULT 0
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS withdraws (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        amount REAL,
        status TEXT,
        tx_hash TEXT,
        time TEXT
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id INTEGER PRIMARY KEY
    )
""")
# Fix: removed the extra NOT
cur.execute("""
    CREATE TABLE IF NOT EXISTS redeem_codes (
        code TEXT PRIMARY KEY,
        amount REAL
    )
""")
cur.execute("""
    CREATE TABLE IF NOT EXISTS redeem_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        code TEXT,
        time TEXT
    )
""")
conn.commit()

# HELPERS
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

def create_withdraw_request(uid, amount, tx_hash):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute(
        "INSERT INTO withdraws(telegram_id, amount, status, tx_hash, time) VALUES (?, ?, 'done', ?, ?)",
        (uid, amount, tx_hash, now)
    )
    conn.commit()
    return cur.lastrowid

# Redeem codes CRUD
def create_redeem_code(code, amount):
    cur.execute("INSERT INTO redeem_codes(code, amount) VALUES (?, ?)", (code, amount))
    conn.commit()

def get_redeem_amount(code):
    cur.execute("SELECT amount FROM redeem_codes WHERE code = ?", (code,))
    row = cur.fetchone()
    return row[0] if row else None

def delete_redeem_code(code):
    cur.execute("DELETE FROM redeem_codes WHERE code = ?", (code,))
    conn.commit()

def log_redeem(uid, code):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO redeem_history(telegram_id, code, time) VALUES (?, ?, ?)", (uid, code, now))
    conn.commit()

# Group management
def add_group(chat_id):
    cur.execute("INSERT OR IGNORE INTO groups (chat_id) VALUES (?)", (chat_id,))
    conn.commit()

def remove_group(chat_id):
    cur.execute("DELETE FROM groups WHERE chat_id = ?", (chat_id,))
    conn.commit()

def is_group_enabled(chat_id):
    cur.execute("SELECT 1 FROM groups WHERE chat_id = ?", (chat_id,))
    return cur.fetchone() is not None

def list_groups():
    cur.execute("SELECT chat_id FROM groups")
    return [row[0] for row in cur.fetchall()]

# UTILITIES
def delete_later(chat_id, msg_id, delay=None):
    if delay is None:
        delay = random.randint(10, 15)
    threading.Timer(delay, lambda: bot.delete_message(chat_id, msg_id)).start()

# KEYBOARDS
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row('💰 Balance', '🏦 Set Wallet')
    kb.row('💸 Withdraw', '🎟️ Redeem Code')
    kb.row('⚙️ Admin Panel')
    return kb

def admin_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton('➕ Add Balance', callback_data='admin_add_bal'),
        InlineKeyboardButton('➖ Remove Balance', callback_data='admin_rem_bal'),
        InlineKeyboardButton('📊 Stats', callback_data='admin_stats'),
        InlineKeyboardButton('👥 Manage Groups', callback_data='admin_manage_groups'),
        InlineKeyboardButton('🎟️ Create Code', callback_data='admin_create_code')
    )
    return kb

def manage_groups_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton('➕ Add Group', callback_data='admin_add_group_manual'),
        InlineKeyboardButton('➖ Remove Group', callback_data='admin_remove_group_manual'),
        InlineKeyboardButton('📋 List Groups', callback_data='admin_list_groups')
    )
    return kb

# SEND ON-CHAIN PAYMENT
def send_polygon_payment(to_address, amount):
    value = web3.to_wei(amount, 'ether')
    nonce = web3.eth.get_transaction_count(ADMIN_ADDRESS)
    tx = {
        'to': Web3.to_checksum_address(to_address),
        'value': value,
        'gas': 21000,
        'gasPrice': web3.to_wei('50', 'gwei'),
        'nonce': nonce,
        'chainId': 137,
    }
    signed_tx = web3.eth.account.sign_transaction(tx, ADMIN_PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
    return tx_hash.hex()

# PROCESS_WITHDRAW must come *before* cmd_withdraw
def process_withdraw(m: Message, bal: float, wallet: str):
    text = m.text.strip()
    if text.lower() == 'cancel':
        return bot.send_message(m.from_user.id, '❌ Cancelled.', reply_markup=main_menu())
    try:
        amt = float(text)
    except:
        return bot.send_message(m.from_user.id, '❌ Invalid amount.', reply_markup=main_menu())
    if amt < MIN_WITHDRAW or amt > bal:
        return bot.send_message(m.from_user.id, '❌ Amount out of range.', reply_markup=main_menu())
    try:
        tx_hash = send_polygon_payment(wallet, amt)
        cur.execute('UPDATE balances SET balance = balance - ? WHERE telegram_id = ?', (amt, m.from_user.id))
        create_withdraw_request(m.from_user.id, amt, tx_hash)
        bot.send_message(
            m.from_user.id,
            f'✅ Withdrawn {amt:.2f} POL.\nTx: https://polygonscan.com/tx/{("0x" + tx_hash) if not tx_hash.startswith("0x") else tx_hash}',
            reply_markup=main_menu()
        )
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        admin_msg = (
            f'💸 <b>NEW WITHDRAW</b>\n'
            f'👤 <a href="tg://user?id={m.from_user.id}">{m.from_user.first_name}</a>\n'
            f'🏦 Wallet: <code>{wallet}</code>\n'
            f'💰 Amount: {amt:.2f} POL\n'
            f'🔗 <a href="https://polygonscan.com/tx/{tx_hash}">Tx Hash</a>\n'
            f'⏱ {ts}'
        )
        bot.send_message(PAYOUT_CHANNEL, admin_msg, disable_web_page_preview=True)
    except Exception as e:
        bot.send_message(m.from_user.id, f'❌ Error: {e}', reply_markup=main_menu())

# HANDLERS
@bot.message_handler(commands=['start'], chat_types=['private'])
def cmd_start(msg: Message):
    bot.send_message(msg.chat.id, '👋 Welcome!', reply_markup=main_menu())

@bot.message_handler(chat_types=['private'], func=lambda m: m.text == '💰 Balance')
def cmd_balance(m):
    bal = get_balance(m.from_user.id)
    bot.send_message(m.from_user.id, f'💰 Balance: {bal:.2f} POL', reply_markup=main_menu())

@bot.message_handler(chat_types=['private'], func=lambda m: m.text == '🏦 Set Wallet')
def cmd_set_wallet(m):
    bot.send_message(m.from_user.id, '🏦 Send your Polygon wallet (0x...):', reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(m, process_wallet)

def process_wallet(m):
    addr = m.text.strip()
    if not web3.is_address(addr):
        return bot.send_message(m.from_user.id, '❌ Invalid address. Try /start', reply_markup=main_menu())
    set_wallet(m.from_user.id, Web3.to_checksum_address(addr))
    bot.send_message(m.from_user.id, '✅ Wallet saved.', reply_markup=main_menu())

@bot.message_handler(chat_types=['private'], func=lambda m: m.text == '💸 Withdraw')
def cmd_withdraw(m):
    bal = get_balance(m.from_user.id)
    wallet = get_wallet(m.from_user.id)
    if not wallet:
        return bot.send_message(m.from_user.id, '⚠️ Set wallet first.', reply_markup=main_menu())
    if bal < MIN_WITHDRAW:
        return bot.send_message(m.from_user.id, f'❌ Min withdraw {MIN_WITHDRAW}', reply_markup=main_menu())
    msg = bot.send_message(
        m.from_user.id,
        f'💸 Enter amount to withdraw (min {MIN_WITHDRAW}, max {bal:.2f}):',
        reply_markup=ReplyKeyboardRemove()
    )
    bot.register_next_step_handler(msg, lambda mm: process_withdraw(mm, bal, wallet))

@bot.message_handler(chat_types=['private'], func=lambda m: m.text == '🎟️ Redeem Code')
def cmd_redeem_ui(m):
    bot.send_message(m.from_user.id, '🎟️ Send your redeem code:', reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(m, process_redeem_ui)

def process_redeem_ui(m):
    code = m.text.strip()
    amt = get_redeem_amount(code)
    if not amt:
        return bot.send_message(m.from_user.id, '❌ Invalid or used code.', reply_markup=main_menu())
    add_balance(m.from_user.id, amt)
    delete_redeem_code(code)
    log_redeem(m.from_user.id, code)
    bot.send_message(m.from_user.id, f'✅ Redeemed {amt:.2f} POL!', reply_markup=main_menu())

@bot.message_handler(chat_types=['private'], func=lambda m: m.text == '⚙️ Admin Panel')
def cmd_admin(m):
    if m.from_user.id != ADMIN_ID:
        return bot.send_message(m.from_user.id, '❌ Unauthorized.', reply_markup=main_menu())
    bot.send_message(m.from_user.id, '🔧 Admin Panel:', reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda c: c.data.startswith('admin_'))
def on_admin(cq):
    data = cq.data
    uid = cq.from_user.id
    bot.answer_callback_query(cq.id)
    if uid != ADMIN_ID:
        return bot.send_message(uid, '❌ Unauthorized.')

    if data == 'admin_add_bal':
        msg = bot.send_message(uid, '➕ Send: <user_id> <amount>')
        bot.register_next_step_handler(msg, lambda mm: _modify_balance(mm, True))
    elif data == 'admin_rem_bal':
        msg = bot.send_message(uid, '➖ Send: <user_id> <amount>')
        bot.register_next_step_handler(msg, lambda mm: _modify_balance(mm, False))
    elif data == 'admin_stats':
        total_u = cur.execute('SELECT COUNT(*) FROM balances').fetchone()[0]
        total_pol = cur.execute('SELECT SUM(balance) FROM balances').fetchone()[0] or 0
        pending = cur.execute("SELECT COUNT(*) FROM withdraws WHERE status='pending'").fetchone()[0]
        gcount = len(list_groups())
        codes = cur.execute('SELECT COUNT(*) FROM redeem_codes').fetchone()[0]
        bot.send_message(
            uid,
            f'📊 Stats:\nUsers: {total_u}\nTotal POL: {total_pol:.2f}\nPending WDs: {pending}\nGroups: {gcount}\nCodes: {codes}'
        )
    elif data == 'admin_manage_groups':
        bot.send_message(uid, '👥 Manage Groups:', reply_markup=manage_groups_menu())
    elif data == 'admin_create_code':
        msg = bot.send_message(uid, '🎟️ Send code and amount (e.g. ABC123 0.05)')
        bot.register_next_step_handler(msg, process_admin_create_code)
    elif data == 'admin_add_group_manual':
        msg = bot.send_message(uid, '➕ Send group username (e.g. @mygroup)')
        bot.register_next_step_handler(msg, _process_add_group)
    elif data == 'admin_remove_group_manual':
        msg = bot.send_message(uid, '➖ Send group username to remove')
        bot.register_next_step_handler(msg, _process_remove_group)
    elif data == 'admin_list_groups':
        groups = list_groups()
        text = '\n'.join(str(g) for g in groups) or '(none)'
        bot.send_message(uid, f'📋 Enabled groups:\n{text}')

# ADMIN ACTIONS
def _modify_balance(msg: Message, add=True):
    try:
        uid_str, amt_str = msg.text.split()
        target = int(uid_str)
        amt = float(amt_str)
        if not add:
            amt = -amt
        add_balance(target, amt)
        action = 'Added' if add else 'Removed'
        bot.reply_to(msg, f'✅ {action} {abs(amt):.2f} POL to {target}')
    except:
        bot.reply_to(msg, '❌ Format: <user_id> <amount>')

def process_admin_create_code(msg: Message):
    try:
        code, amt_str = msg.text.strip().split()
        amt = float(amt_str)
        create_redeem_code(code, amt)
        bot.reply_to(msg, f'✅ Created code {code} = {amt:.2f} POL')
    except Exception as e:
        bot.reply_to(msg, f'❌ Error: {e}. Format: CODE AMOUNT')

def _process_add_group(msg: Message):
    try:
        chat = bot.get_chat(msg.text.strip())
        add_group(chat.id)
        bot.reply_to(msg, f'✅ Enabled: {msg.text}')
    except Exception as e:
        bot.reply_to(msg, f'❌ Could not add: {e}')

def _process_remove_group(msg: Message):
    try:
        chat = bot.get_chat(msg.text.strip())
        remove_group(chat.id)
        bot.reply_to(msg, f'❌ Disabled: {msg.text}')
    except Exception as e:
        bot.reply_to(msg, f'❌ Could not remove: {e}')

# GROUP INVITE REWARD
@bot.message_handler(content_types=['new_chat_members'])
def on_new_member(msg: Message):
    if not is_group_enabled(msg.chat.id):
        return
    inviter = msg.from_user
    for m in msg.new_chat_members:
        add_balance(inviter.id, 0.005)
        add_balance(m.id, 0.01)
        sent = bot.send_message(
            msg.chat.id,
            f'🎉 {inviter.first_name} +0.005 POL\n'
            f'🎉 {m.first_name} +0.01 POL'
        )
        delete_later(sent.chat.id, sent.message_id)

# RUN BOT
print('🤖 Bot is running...')
bot.infinity_polling()