import logging
import os
from datetime import datetime, timedelta
import sqlite3

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.error import BadRequest

# --- Configuration Constants ---
BONUS_AMOUNT = 1
REFERRAL_REWARD = 5
WITHDRAW_THRESHOLD = 50
CHANNEL_LINK = "https://t.me/dailyearn11"
CHECK_CHANNEL_ID = -1001441974665  # Replace with your actual channel ID

# --- Database Configuration ---
DB_NAME = 'bot_data.db'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0,
                last_bonus TEXT,
                ref_by INTEGER
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER,
                referred_id INTEGER,
                PRIMARY KEY (referrer_id, referred_id),
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            )
        ''')
        conn.commit()

def get_user_data(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            user_data = dict(row)
            user_data['last_bonus'] = datetime.fromisoformat(user_data['last_bonus']) if user_data['last_bonus'] else None
            cursor.execute('SELECT referred_id FROM referrals WHERE referrer_id = ?', (user_id,))
            user_data['referrals'] = [r[0] for r in cursor.fetchall()]
            return user_data
        return None

def create_user(user_id: int, ref_by: int = None):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (user_id, balance, last_bonus, ref_by) VALUES (?, ?, ?, ?)',
                       (user_id, 0, None, ref_by))
        conn.commit()

def update_user_balance(user_id: int, balance: float):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (balance, user_id))
        conn.commit()

def update_user_last_bonus(user_id: int, time: datetime):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET last_bonus = ? WHERE user_id = ?', (time.isoformat(), user_id))
        conn.commit()

def add_referral(referrer_id: int, referred_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)',
                           (referrer_id, referred_id))
            conn.commit()
        except sqlite3.IntegrityError:
            logging.warning(f"Referral {referred_id} by {referrer_id} already exists.")

async def get_main_menu_keyboard(user_id: int):
    is_member = await is_user_member(user_id, CHECK_CHANNEL_ID)
    if not is_member:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Join Channel to Start", url=CHANNEL_LINK)],
            [InlineKeyboardButton("🔄 I have joined!", callback_data='check_membership')]
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data='show_balance'),
         InlineKeyboardButton("🎁 Daily Bonus", callback_data='claim_bonus')],
        [InlineKeyboardButton("👥 Referral Link", callback_data='show_referral'),
         InlineKeyboardButton("💸 Withdraw", callback_data='show_withdraw')],
        [InlineKeyboardButton("ℹ️ How to Earn", callback_data='show_info')]
    ])

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str = None):
    user_id = update.effective_user.id
    keyboard = await get_main_menu_keyboard(user_id)
    if not message_text:
        message_text = (
            f"👋 Welcome {update.effective_user.first_name}!\n\n"
            "💸 Earn ₹5 per referral.\n"
            "🎁 Claim daily bonus.\n"
            "💰 Withdraw at ₹50 minimum balance.\n\n"
            "👇 Choose an option:"
        )
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message_text, reply_markup=keyboard, parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                text=message_text, reply_markup=keyboard, parse_mode='Markdown'
            )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logging.warning("⚠️ Skipped editing: message identical.")
        else:
            raise

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if not user_data:
        ref_by_id = int(context.args[0]) if context.args and context.args[0].isdigit() else None
        create_user(user_id, ref_by=ref_by_id)
        if ref_by_id:
            referrer_data = get_user_data(ref_by_id)
            if referrer_data:
                update_user_balance(ref_by_id, referrer_data['balance'] + REFERRAL_REWARD)
                add_referral(ref_by_id, user_id)
    await send_main_menu(update, context)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user_data(user_id)
    if query.data in ['main_menu', 'check_membership']:
        await send_main_menu(update, context, "✅ Refreshed main menu.")
    elif query.data == 'show_balance':
        await safe_edit(query, f"💰 Balance: ₹{user['balance']}\n👥 Referrals: {len(user['referrals'])}")
    elif query.data == 'claim_bonus':
        now = datetime.now()
        if not user['last_bonus'] or now - user['last_bonus'] > timedelta(days=1):
            update_user_balance(user_id, user['balance'] + BONUS_AMOUNT)
            update_user_last_bonus(user_id, now)
            await safe_edit(query, "🎁 ₹1 daily bonus claimed!")
        else:
            delta = timedelta(days=1) - (now - user['last_bonus'])
            await safe_edit(query, f"⏳ Come back in {delta.seconds//3600}h {(delta.seconds//60)%60}m")
    elif query.data == 'show_referral':
        bot_username = context.bot.username
        link = f"https://t.me/{bot_username}?start={user_id}"
        await safe_edit(query, f"👥 Your referral link:\n`{link}`", markdown=True)
    elif query.data == 'show_withdraw':
        if user['balance'] >= WITHDRAW_THRESHOLD:
            update_user_balance(user_id, 0)
            await safe_edit(query, "✅ Withdrawal requested!")
        else:
            await safe_edit(query, f"❌ Need ₹{WITHDRAW_THRESHOLD}. Current: ₹{user['balance']}")

async def safe_edit(query, text, markdown=False):
    try:
        await query.edit_message_text(text=text, parse_mode='Markdown' if markdown else None)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logging.warning("⚠️ Skipped identical edit.")
        else:
            raise
