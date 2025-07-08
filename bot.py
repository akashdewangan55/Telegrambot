import logging
import os
import sqlite3
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)
from telegram.error import BadRequest

# --- Configuration ---
BONUS_AMOUNT = 1
REFERRAL_REWARD = 5
WITHDRAW_THRESHOLD = 50
CHANNEL_LINK = "https://t.me/dailyearn11"
CHECK_CHANNEL_ID = -1001441974665
DB_NAME = "bot_data.db"

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# --- Database Functions ---
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance REAL DEFAULT 0,
                last_bonus TEXT,
                ref_by INTEGER
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                referrer_id INTEGER,
                referred_id INTEGER,
                PRIMARY KEY (referrer_id, referred_id)
            )
        """)
        conn.commit()

def get_user_data(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        user = cursor.fetchone()
        if user:
            data = dict(user)
            data['last_bonus'] = datetime.fromisoformat(data['last_bonus']) if data['last_bonus'] else None
            cursor.execute("SELECT referred_id FROM referrals WHERE referrer_id=?", (user_id,))
            data['referrals'] = [row[0] for row in cursor.fetchall()]
            return data
        return None

def create_user(user_id: int, ref_by: int = None):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, balance, last_bonus, ref_by) VALUES (?, ?, ?, ?)",
            (user_id, 0, None, ref_by)
        )
        conn.commit()

def update_user_balance(user_id: int, balance: float):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance=? WHERE user_id=?", (balance, user_id))
        conn.commit()

def update_last_bonus(user_id: int, timestamp: datetime):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_bonus=? WHERE user_id=?", (timestamp.isoformat(), user_id))
        conn.commit()

def add_referral(referrer_id: int, referred_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                (referrer_id, referred_id)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            logging.warning("Referral already exists.")

# --- Telegram Keyboard ---
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Balance", callback_data="show_balance"),
         InlineKeyboardButton("🎁 Daily Bonus", callback_data="claim_bonus")],
        [InlineKeyboardButton("👥 Referral Link", callback_data="show_referral"),
         InlineKeyboardButton("💸 Withdraw", callback_data="show_withdraw")],
        [InlineKeyboardButton("ℹ️ How to Earn", callback_data="show_info")]
    ])

def get_back_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="main_menu")]
    ])

# --- Telegram Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    if not user:
        ref_by = None
        if context.args:
            ref_by = int(context.args[0]) if context.args[0].isdigit() else None
            if ref_by == user_id: ref_by = None
        create_user(user_id, ref_by)
        if ref_by:
            ref_user = get_user_data(ref_by)
            if ref_user:
                update_user_balance(ref_by, ref_user['balance'] + REFERRAL_REWARD)
                add_referral(ref_by, user_id)
                try:
                    await context.bot.send_message(
                        chat_id=ref_by,
                        text=f"🎉 Your friend {update.effective_user.first_name} joined! You earned ₹{REFERRAL_REWARD}."
                    )
                except Exception as e:
                    logging.error(f"Error notifying referrer: {e}")
    await update.message.reply_text(
        "👋 Welcome! Use the menu below.",
        reply_markup=get_main_menu()
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user_data(user_id)

    if query.data == "main_menu":
        await safe_edit(query, "👋 Main Menu", get_main_menu())
    elif query.data == "show_balance":
        await safe_edit(query, f"💰 Balance: ₹{user['balance']}\n👥 Referrals: {len(user['referrals'])}", get_back_button())
    elif query.data == "claim_bonus":
        now = datetime.now()
        if not user['last_bonus'] or now - user['last_bonus'] > timedelta(days=1):
            update_user_balance(user_id, user['balance'] + BONUS_AMOUNT)
            update_last_bonus(user_id, now)
            await safe_edit(query, "🎁 Daily bonus claimed! ₹1 added.", get_back_button())
        else:
            remaining = timedelta(days=1) - (now - user['last_bonus'])
            await safe_edit(query, f"⏳ Come back in {remaining.seconds//3600}h {(remaining.seconds//60)%60}m.", get_back_button())
    elif query.data == "show_referral":
        link = f"https://t.me/{context.bot.username}?start={user_id}"
        await safe_edit(query, f"👥 Your referral link:\n`{link}`\nEarn ₹{REFERRAL_REWARD} per friend!", get_back_button(), parse_mode="Markdown")
    elif query.data == "show_withdraw":
        if user['balance'] >= WITHDRAW_THRESHOLD:
            update_user_balance(user_id, 0)
            await safe_edit(query, f"✅ Withdrawal of ₹{WITHDRAW_THRESHOLD} requested.", get_back_button())
        else:
            await safe_edit(query, f"❌ Minimum ₹{WITHDRAW_THRESHOLD} needed to withdraw.", get_back_button())
    elif query.data == "show_info":
        info = (
            "📖 *How to Earn:*\n"
            "🎁 Daily bonus ₹1\n"
            "👥 Refer friends ₹5 each\n"
            "💸 Withdraw at ₹50"
        )
        await safe_edit(query, info, get_back_button(), parse_mode="Markdown")

async def safe_edit(query, text, markup, **kwargs):
    """Avoids BadRequest when text & markup are unchanged."""
    try:
        await query.edit_message_text(text, reply_markup=markup, **kwargs)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            logging.info("Skipped edit: Message unchanged.")
        else:
            raise

# --- Initialize DB and App ---
init_db()
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("BOT_TOKEN not set in environment!")
    exit(1)

application = Application.builder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(handle_buttons))
