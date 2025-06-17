import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import sqlite3
import re
from datetime import datetime
from web3 import Web3

# ---- CONFIG ----
TOKEN = 'xx'
POLYGON_RPC_URL = "https://polygon-rpc.com"
ADMIN_PRIVATE_KEY = "e2"
ADMIN_PASSWORD = 'h234'
MIN_WITHDRAW = 0.08
REFER_BONUS = 0.02
SIGNUP_BONUS = 0.05
PAYOUT_CHANNEL = '@tR_PayOutChannel'
SUPPORT_USER = "@Ankush_Malik"

# ---- INIT ----
conn = sqlite3.connect('referbot.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, referred_by INTEGER, wallet TEXT, joined INTEGER DEFAULT 0, got_signup_bonus INTEGER DEFAULT 0, signup_time TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS refs (user_id INTEGER PRIMARY KEY, refer_code TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS channels (channel_id TEXT PRIMARY KEY)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS withdraws (user_id INTEGER, amount REAL, wallet TEXT, tx_hash TEXT, time TEXT)''')
cursor.execute('''CREATE TABLE IF NOT EXISTS refer_rewards (user_id INTEGER PRIMARY KEY, rewarded INTEGER DEFAULT 0)''')
# Add wallet column if not exists
try: cursor.execute("ALTER TABLE users ADD COLUMN wallet TEXT")
except: pass
try: cursor.execute("ALTER TABLE withdraws ADD COLUMN wallet TEXT")
except: pass

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
web3 = Web3(Web3.HTTPProvider(POLYGON_RPC_URL))
ADMIN_ADDRESS = Web3.to_checksum_address(web3.eth.account.from_key(ADMIN_PRIVATE_KEY).address)
ADMIN_PANEL_USERS = set()

# ---- HELPERS ----
def get_refer_code(uid):
    return f"REF{uid}"

def get_channels():
    cursor.execute("SELECT channel_id FROM channels")
    return [x[0] for x in cursor.fetchall()]

def is_joined_all(user_id):
    channels = get_channels()
    joined = True
    not_joined = []
    for ch in channels:
        try:
            member = bot.get_chat_member(ch, user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                joined = False
                not_joined.append(ch)
        except:
            joined = False
            not_joined.append(ch)
    return joined, not_joined

def main_menu_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton('💸 Withdraw'), KeyboardButton('🎁 Refer & Earn'))
    markup.row(KeyboardButton('🏦 Set POL Wallet'), KeyboardButton('💰 Balance'))
    markup.row(KeyboardButton('📊 Stats'), KeyboardButton('🆘 Help'))
    markup.row(KeyboardButton('✨ Features'))
    return markup

def features_inline_markup():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💸 Withdraw Guide", callback_data="feature_withdraw"))
    markup.add(InlineKeyboardButton("🎁 Referral System", callback_data="feature_refer"))
    markup.add(InlineKeyboardButton("🔒 Security Info", callback_data="feature_security"))
    markup.add(InlineKeyboardButton("🏦 Polygon Wallet Info", callback_data="feature_wallet"))
    markup.add(InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_main_menu"))
    return markup

def admin_menu_markup():
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton('📊 Stats', callback_data='admin_stats'), InlineKeyboardButton('📢 Broadcast', callback_data='admin_broadcast'))
    markup.row(InlineKeyboardButton('➕ Set Channels', callback_data='admin_addch'), InlineKeyboardButton('➖ Remove Channels', callback_data='admin_rmch'))
    markup.row(InlineKeyboardButton('➕ Add Balance', callback_data='admin_addbal'), InlineKeyboardButton('➖ Remove Balance', callback_data='admin_rmbal'))
    markup.add(InlineKeyboardButton('⬅️ Admin Menu / Exit', callback_data='admin_back'))
    return markup

def join_channels_markup(user_id):
    markup = InlineKeyboardMarkup()
    for ch in get_channels():
        markup.add(InlineKeyboardButton(f"🔗 Join {ch}", url=f"https://t.me/{ch.replace('@','')}", callback_data='joinch'))
    markup.add(InlineKeyboardButton('✅ Joined All', callback_data='verify_join'))
    return markup

def set_wallet_markup(existing_wallet=None):
    markup = InlineKeyboardMarkup()
    if existing_wallet:
        markup.add(InlineKeyboardButton("✏️ Change Wallet", callback_data="change_wallet"))
    return markup

def give_bonus_and_referral_notify(user_id):
    cursor.execute("SELECT joined, got_signup_bonus, referred_by FROM users WHERE user_id=?", (user_id,))
    d = cursor.fetchone()
    if not d:
        return False
    joined, got_signup_bonus, referred_by = d
    if joined == 0 and got_signup_bonus == 0:
        joined, _ = is_joined_all(user_id)
        if joined:
            cursor.execute("UPDATE users SET joined=1, got_signup_bonus=1, balance=balance+? WHERE user_id=?", (SIGNUP_BONUS, user_id))
            # Only reward the referrer if not already rewarded for this user
            if referred_by and referred_by != user_id:
                cursor.execute("SELECT rewarded FROM refer_rewards WHERE user_id=?", (user_id,))
                already_rewarded = cursor.fetchone()
                if not already_rewarded:
                    cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (REFER_BONUS, referred_by))
                    cursor.execute("INSERT INTO refer_rewards (user_id, rewarded) VALUES (?, 1)", (user_id,))
                    conn.commit()
                    try:
                        bot.send_message(referred_by, f"🎉 <b>You earned {REFER_BONUS:.2f} POL Referral Bonus!</b>\nA new user joined all channels using your link. Keep sharing to earn more! 💸")
                    except:
                        pass
            conn.commit()
            return True
    return False

def send_main_menu(user_id, text):
    bot.send_message(user_id, text, reply_markup=main_menu_markup())

# ---- BOT HANDLERS ----
@bot.message_handler(commands=['start'])
def start(m):
    user_id = m.from_user.id
    args = m.text.split()
    referred_by = None
    if len(args) > 1:
        try:
            code = args[1]
            cursor.execute("SELECT user_id FROM refs WHERE refer_code=?", (code,))
            d = cursor.fetchone()
            if d and d[0] != user_id:
                referred_by = d[0]
        except: pass
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id, referred_by, balance, joined, got_signup_bonus, signup_time) VALUES (?, ?, 0, 0, 0, ?)", (user_id, referred_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        cursor.execute("INSERT INTO refs (user_id, refer_code) VALUES (?, ?)", (user_id, get_refer_code(user_id)))
        conn.commit()
    joined, notj = is_joined_all(user_id)
    if not joined:
        msg = f"🔒 <b>Join All Channels to Unlock Menu</b>:\n\n"
        for ch in get_channels():
            msg += f"🔗 {ch}\n"
        msg += "\nAfter joining all, tap <b>✅ Joined All</b>."
        bot.send_message(user_id, msg, reply_markup=join_channels_markup(user_id))
    else:
        give_bonus_and_referral_notify(user_id)
        send_main_menu(user_id, f"<b>Welcome to Polygon Auto Pay Bot!</b>\n\n🏆 Explore our Refer & Earn program!\n💎 Earn {REFER_BONUS} POL per referral\n🎉 Join, refer, and withdraw easily!\n")

@bot.callback_query_handler(func=lambda call: call.data == 'verify_join')
def verify_join(call):
    user_id = call.from_user.id
    joined, notj = is_joined_all(user_id)
    if joined:
        gave = give_bonus_and_referral_notify(user_id)
        bot.delete_message(user_id, call.message.message_id)
        if gave:
            bot.send_message(user_id, f"🎉 <b>Congrats! You received {SIGNUP_BONUS} POL Sign Up Bonus.</b>")
        send_main_menu(user_id, "✅ <b>All Done! Welcome to the Main Menu.</b>")
    else:
        msg = "⛔ <b>Please join ALL channels first!</b>\n"
        for ch in notj:
            msg += f"🔗 {ch}\n"
        bot.answer_callback_query(call.id, "Join all channels before proceeding.", show_alert=True)
        bot.edit_message_text(msg, user_id, call.message.message_id, reply_markup=join_channels_markup(user_id))

@bot.message_handler(func=lambda m: m.text == '🎁 Refer & Earn')
def send_refer(m):
    user_id = m.from_user.id
    code = get_refer_code(user_id)
    msg = f"🎁 <b>Your Referral Link:</b>\n\n👉 https://t.me/{bot.get_me().username}?start={code}\n\n💸 Earn {REFER_BONUS} POL per friend who joins and completes channel join!\n"
    bot.send_message(user_id, msg, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: m.text == '💰 Balance')
def bal(m):
    user_id = m.from_user.id
    cursor.execute("SELECT balance, wallet FROM users WHERE user_id=?", (user_id,))
    d = cursor.fetchone()
    if d:
        bal, wallet = d
        msg = f"💰 <b>Your Balance:</b> {bal:.2f} POL\n🏦 <b>Polygon Wallet:</b> {wallet or 'Not set'}"
        bot.send_message(user_id, msg, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: m.text == '🏦 Set POL Wallet')
def set_wallet(m):
    user_id = m.from_user.id
    cursor.execute("SELECT wallet FROM users WHERE user_id=?", (user_id,))
    user_wallet = cursor.fetchone()
    if user_wallet and user_wallet[0]:
        bot.send_message(user_id, f"⚠️ <b>Your Existing Polygon Wallet:</b> <code>{user_wallet[0]}</code>\n\nYou can change it below.", reply_markup=set_wallet_markup(user_wallet[0]))
        return
    msg = "🏦 <b>Send your Polygon (MATIC) Wallet Address</b>\n\nExample: <code>0x...</code>\n\nWallet must be a valid Polygon (MATIC) address and unique."
    bot.send_message(user_id, msg, reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(m, process_wallet)

@bot.callback_query_handler(func=lambda call: call.data == "change_wallet")
def change_wallet(call):
    user_id = call.from_user.id
    bot.send_message(user_id, "✏️ <b>Send your new Polygon Wallet Address</b>\n\n(Existing wallet will be replaced, must be unique)", reply_markup=ReplyKeyboardRemove())
    bot.register_next_step_handler(call.message, process_wallet)

def process_wallet(m):
    user_id = m.from_user.id
    wallet = m.text.strip()
    if not web3.is_address(wallet):
        bot.send_message(user_id, "❌ <b>Invalid Polygon wallet address. Try again:</b>")
        bot.register_next_step_handler(m, process_wallet)
        return
    wallet = Web3.to_checksum_address(wallet)
    cursor.execute("SELECT user_id FROM users WHERE wallet=?", (wallet,))
    exist = cursor.fetchone()
    if exist and exist[0] != user_id:
        bot.send_message(user_id, "🚫 <b>This wallet is already used by another user. Try another!</b>")
        bot.register_next_step_handler(m, process_wallet)
        return
    cursor.execute("UPDATE users SET wallet=? WHERE user_id=?", (wallet, user_id))
    conn.commit()
    bot.send_message(user_id, f"✅ <b>Your Polygon wallet is now:</b> <code>{wallet}</code>", reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: m.text == '💸 Withdraw')
def withdraw(m):
    user_id = m.from_user.id
    cursor.execute("SELECT balance, wallet FROM users WHERE user_id=?", (user_id,))
    d = cursor.fetchone()
    if d:
        bal, wallet = d
        if not wallet:
            bot.send_message(user_id, "🏦 <b>Set your Polygon wallet first using the menu!</b>", reply_markup=main_menu_markup())
            return
        if bal < MIN_WITHDRAW:
            bot.send_message(user_id, f"❌ <b>Insufficient balance (Min {MIN_WITHDRAW} POL)</b>", reply_markup=main_menu_markup())
            return
        msg = f"💸 <b>Enter amount to withdraw</b> (Min {MIN_WITHDRAW} POL, Max {bal:.2f} POL):"
        bot.send_message(user_id, msg, reply_markup=ReplyKeyboardRemove())
        bot.register_next_step_handler(m, lambda msg: process_withdraw(msg, bal, wallet))
    else:
        bot.send_message(user_id, "❌ <b>User not found</b>", reply_markup=main_menu_markup())

def process_withdraw(m, bal, wallet):
    user_id = m.from_user.id
    try:
        amt = float(m.text)
        if amt < MIN_WITHDRAW or amt > bal:
            bot.send_message(user_id, f"❌ <b>Enter valid amount (Min {MIN_WITHDRAW} POL, Max {bal:.2f} POL)</b>")
            bot.register_next_step_handler(m, lambda mm: process_withdraw(mm, bal, wallet))
            return
        tx_hash = send_polygon_payment(wallet, amt)
        # Ensure 0x prefix for hash
        if not tx_hash.startswith("0x"):
            tx_hash = "0x" + tx_hash
        cursor.execute("UPDATE users SET balance=balance-? WHERE user_id=?", (amt, user_id))
        cursor.execute("INSERT INTO withdraws (user_id, amount, wallet, tx_hash, time) VALUES (?, ?, ?, ?, ?)", (user_id, amt, wallet, tx_hash, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        msg = f"✅ <b>Withdraw processed:</b> {amt:.2f} POL\nWallet: <code>{wallet}</code>\n<a href='https://polygonscan.com/tx/{tx_hash}'>View Transaction</a>"
        bot.send_message(user_id, msg, reply_markup=main_menu_markup())
        admin_msg = f"💸 <b>NEW WITHDRAW (Polygon AutoPay)</b>\n\n👤 User: <a href='tg://user?id={user_id}'>{user_id}</a>\n💳 Wallet: <code>{wallet}</code>\n💰 Amount: {amt:.2f} POL\n🔗 <a href='https://polygonscan.com/tx/{tx_hash}'>Tx Hash</a>\n📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        bot.send_message(PAYOUT_CHANNEL, admin_msg, disable_web_page_preview=True)
    except Exception as e:
        bot.send_message(user_id, f"❌ <b>Error processing withdrawal: {str(e)}</b>")
        bot.register_next_step_handler(m, lambda mm: process_withdraw(mm, bal, wallet))

def send_polygon_payment(to_address, amount):
    value = web3.to_wei(amount, 'ether')
    nonce = web3.eth.get_transaction_count(ADMIN_ADDRESS)
    tx = {
        'to': Web3.to_checksum_address(to_address),
        'value': value,
        'gas': 21000,
        'gasPrice': web3.to_wei('35', 'gwei'),
        'nonce': nonce,
        'chainId': 137,
    }
    signed_tx = web3.eth.account.sign_transaction(tx, ADMIN_PRIVATE_KEY)
    tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)  # For web3.py v6+
    return tx_hash.hex()

@bot.message_handler(commands=['admin'])
def admin_login(m):
    bot.send_message(m.chat.id, "🔐 Send admin password:")
    bot.register_next_step_handler(m, process_admin_pw)

def process_admin_pw(m):
    user_id = m.from_user.id
    if m.text.strip() == ADMIN_PASSWORD:
        ADMIN_PANEL_USERS.add(user_id)
        bot.send_message(user_id, "✅ <b>Admin Panel Access Granted</b>", reply_markup=admin_menu_markup())
    else:
        bot.send_message(user_id, "❌ <b>Incorrect password!</b>")

@bot.message_handler(func=lambda m: m.text == '📊 Stats')
def stats(m):
    user_id = m.from_user.id
    if user_id in ADMIN_PANEL_USERS:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE joined=1")
        joined_users = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(balance) FROM users")
        total_bal = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM withdraws")
        total_withdraws = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(amount) FROM withdraws")
        total_withdraw_amt = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM channels")
        chs = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT wallet) FROM users WHERE wallet IS NOT NULL")
        unique_wallets = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM refer_rewards")
        refer_rewards = cursor.fetchone()[0]
        msg = f"""<b>📊 Deep Bot Stats (Admin)</b>
👥 Total Users: {total_users}
✅ Users Joined All: {joined_users}
💰 Total Balance: {total_bal:.2f} POL
💸 Total Withdraws: {total_withdraws} ({total_withdraw_amt:.2f} POL)
🔗 Channels: {chs}
🏦 Unique Polygon Wallets: {unique_wallets}
💎 Referral Rewards Given: {refer_rewards}
"""
        bot.send_message(user_id, msg, reply_markup=main_menu_markup())
    else:
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        bal = (cursor.fetchone() or [0])[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,))
        refs = cursor.fetchone()[0]
        msg = f"""<b>📊 Your Stats</b>
💰 Balance: {bal:.2f} POL
👫 Referrals: {refs}
"""
        bot.send_message(user_id, msg, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: m.text == '🆘 Help')
def help_cmd(m):
    msg = f"""<b>🆘 Bot Help</b>

🏆 <b>Refer & Earn Program</b>
• Earn {REFER_BONUS} POL per successful referral.
• Sign-up Bonus: {SIGNUP_BONUS} POL (after joining all channels).
• <b>Minimum Withdrawal:</b> {MIN_WITHDRAW} POL
• <b>Payment:</b> Automatic, direct to your Polygon wallet (no manual steps).
• <b>Polygon Wallet:</b> Must be unique and can be changed anytime.

<b>How to use</b>
1. Join all channels required.
2. Set your Polygon wallet (must be valid, can be changed).
3. Refer friends with your link.
4. Withdraw your earnings (auto Polygon pay).

<b>For more info or support:</b> {SUPPORT_USER}
"""
    bot.send_message(m.chat.id, msg, reply_markup=main_menu_markup())

@bot.message_handler(func=lambda m: m.text == '✨ Features')
def features(m):
    bot.send_message(m.from_user.id, "✨ <b>Bot Features</b>:\n\n• High Security\n• Instant Referral Rewards\n• Fast Polygon Auto Payments\n• Secure Wallet Validation\n• Admin Panel & Broadcast\n• Automatic Channel Join Check\n", reply_markup=features_inline_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith('feature_') or call.data == 'back_main_menu')
def features_info(call):
    if call.data == "feature_withdraw":
        txt = f"💸 <b>Withdraw Guide</b>\n\n• Minimum {MIN_WITHDRAW} POL required.\n• Set Polygon wallet (unique).\n• Withdrawals are paid instantly to your wallet."
    elif call.data == "feature_refer":
        txt = f"🎁 <b>Referral System</b>\n\n• Share your unique referral link.\n• Earn {REFER_BONUS} POL for every friend who joins all channels."
    elif call.data == "feature_security":
        txt = "🔒 <b>Security Info</b>\n\n• Each Polygon wallet can only be used by one user.\n• Channel join checks are automatic.\n• No one can bypass the system."
    elif call.data == "feature_wallet":
        txt = "🏦 <b>Polygon Wallet Info</b>\n\n• Your wallet must be a valid Polygon (MATIC) address.\n• You can change your wallet anytime from the menu."
    elif call.data == "back_main_menu":
        send_main_menu(call.from_user.id, "<b>Welcome to Polygon Auto Pay Bot!</b>")
        return
    bot.edit_message_text(txt, call.from_user.id, call.message.message_id, reply_markup=features_inline_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_actions(call):
    user_id = call.from_user.id
    if user_id not in ADMIN_PANEL_USERS:
        bot.answer_callback_query(call.id, "Admin only", show_alert=True)
        return
    if call.data == 'admin_stats':
        stats(call.message)
    elif call.data == 'admin_broadcast':
        bot.edit_message_text("📢 <b>Send broadcast message (HTML supported):</b>", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, admin_broadcast)
    elif call.data == 'admin_addch':
        bot.edit_message_text("➕ <b>Send channel username to add (with @):</b>", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, admin_add_channel)
    elif call.data == 'admin_rmch':
        chlist = get_channels()
        if not chlist:
            bot.answer_callback_query(call.id, "No channels to remove", show_alert=True)
            return
        markup = InlineKeyboardMarkup()
        for c in chlist:
            markup.add(InlineKeyboardButton(f"❌ {c}", callback_data=f'delch|{c}'))
        bot.edit_message_text("➖ <b>Select channel to remove:</b>", user_id, call.message.message_id, reply_markup=markup)
    elif call.data == 'admin_addbal':
        bot.edit_message_text("💰 <b>Send user_id and amount to add (user_id amount):</b>", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, admin_add_balance)
    elif call.data == 'admin_rmbal':
        bot.edit_message_text("💸 <b>Send user_id and amount to remove (user_id amount):</b>", user_id, call.message.message_id)
        bot.register_next_step_handler(call.message, admin_remove_balance)
    elif call.data == 'admin_back':
        bot.send_message(user_id, "Admin Menu Closed.", reply_markup=main_menu_markup())

def admin_broadcast(m):
    cursor.execute("SELECT user_id FROM users")
    for uid in cursor.fetchall():
        try:
            bot.send_message(uid[0], m.text, reply_markup=main_menu_markup())
        except: pass
    bot.send_message(m.from_user.id, "✅ <b>Broadcast sent!</b>", reply_markup=admin_menu_markup())

def admin_add_channel(m):
    ch = m.text.strip()
    if not ch.startswith('@'):
        bot.send_message(m.from_user.id, "❌ <b>Channel must start with @</b>")
        bot.register_next_step_handler(m, admin_add_channel)
        return
    cursor.execute("INSERT OR IGNORE INTO channels (channel_id) VALUES (?)", (ch,))
    conn.commit()
    bot.send_message(m.from_user.id, f"✅ <b>Added:</b> {ch}", reply_markup=admin_menu_markup())

@bot.callback_query_handler(func=lambda call: call.data.startswith('delch|'))
def del_channel(call):
    user_id = call.from_user.id
    if user_id not in ADMIN_PANEL_USERS:
        bot.answer_callback_query(call.id, "Admin only", show_alert=True)
        return
    ch = call.data.split('|')[1]
    cursor.execute("DELETE FROM channels WHERE channel_id=?", (ch,))
    conn.commit()
    bot.answer_callback_query(call.id, f"Removed {ch}", show_alert=True)
    bot.edit_message_text("✅ <b>Channel removed.</b>", user_id, call.message.message_id, reply_markup=admin_menu_markup())

def admin_add_balance(m):
    try:
        user_id, amount = m.text.split()
        user_id = int(user_id)
        amount = float(amount)
        cursor.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, user_id))
        conn.commit()
        bot.send_message(m.from_user.id, f"✅ Added {amount} POL to {user_id}", reply_markup=admin_menu_markup())
    except:
        bot.send_message(m.from_user.id, "❌ Usage: <code>user_id amount</code>", reply_markup=admin_menu_markup())

def admin_remove_balance(m):
    try:
        user_id, amount = m.text.split()
        user_id = int(user_id)
        amount = float(amount)
        cursor.execute("UPDATE users SET balance=MAX(0, balance-?) WHERE user_id=?", (amount, user_id))
        conn.commit()
        bot.send_message(m.from_user.id, f"✅ Removed {amount} POL from {user_id}", reply_markup=admin_menu_markup())
    except:
        bot.send_message(m.from_user.id, "❌ Usage: <code>user_id amount</code>", reply_markup=admin_menu_markup())

@bot.message_handler(func=lambda m: True)
def catch_all(m):
    user_id = m.from_user.id
    cursor.execute("SELECT joined FROM users WHERE user_id=?", (user_id,))
    d = cursor.fetchone()
    if not d or d[0]==0:
        joined, _ = is_joined_all(user_id)
        if not joined:
            msg = f"🔒 <b>Join All Channels to Unlock Menu</b>:\n\n"
            for ch in get_channels():
                msg += f"🔗 {ch}\n"
            msg += "\nAfter joining all, tap <b>✅ Joined All</b>."
            bot.send_message(user_id, msg, reply_markup=join_channels_markup(user_id))
            return
        else:
            give_bonus_and_referral_notify(user_id)
            send_main_menu(user_id, "<b>Welcome to Polygon Auto Pay Bot!</b>")
            return
    send_main_menu(user_id, "🔸 <b>Use the menu below to continue.</b>")

bot.infinity_polling()