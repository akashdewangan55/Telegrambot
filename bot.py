import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from datetime import datetime, timedelta
import sqlite3
import os
from flask import Flask
import threading

# Flask app for Render health check
app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Telegram bot and Flask app are running on Render!"

# Set up logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Configuration ---
BONUS_AMOUNT = 1
REFERRAL_REWARD = 5
WITHDRAW_THRESHOLD = 50
CHANNEL_LINK = "https://t.me/dailyearn11"
CHECK_CHANNEL_ID = -1001441974665
DB_NAME = "bot_data.db"

# --- Database ---
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
                PRIMARY KEY (referrer_id, referred_id)
            )
        ''')
        conn.commit()
    logger.info("📦 Database initialized.")

def get_user_data(user_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            data = dict(row)
            if data['last_bonus']:
                data['last_bonus'] = datetime.fromisoformat(data['last_bonus'])
            else:
                data['last_bonus'] = None
            cursor.execute('SELECT referred_id FROM referrals WHERE referrer_id = ?', (user_id,))
            data['referrals'] = [r[0] for r in cursor.fetchall()]
            return data
        return None

def create_user(user_id: int, ref_by: int = None):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (user_id, balance, last_bonus, ref_by) VALUES (?, ?, ?, ?)',
                       (user_id, 0, None, ref_by))
        conn.commit()

def update_user_balance(user_id: int, amount: float):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (amount, user_id))
        conn.commit()

def update_user_last_bonus(user_id: int, last_bonus: datetime):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET last_bonus = ? WHERE user_id = ?', (last_bonus.isoformat(), user_id))
        conn.commit()

def add_referral(referrer_id: int, referred_id: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)', (referrer_id, referred_id))
            conn.commit()
        except sqlite3.IntegrityError:
            logger.warning(f"Referral already exists: {referrer_id} -> {referred_id}")

# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    if not user_data:
        ref_by = None
        if context.args and context.args[0].isdigit():
            ref_by_id = int(context.args[0])
            if ref_by_id != user_id and get_user_data(ref_by_id):
                ref_by = ref_by_id
        create_user(user_id, ref_by)
        if ref_by:
            ref_data = get_user_data(ref_by)
            if ref_data:
                update_user_balance(ref_by, ref_data['balance'] + REFERRAL_REWARD)
                add_referral(ref_by, user_id)
                await context.bot.send_message(
                    chat_id=ref_by,
                    text=f"🎉 Your friend {update.effective_user.first_name} joined! You earned ₹{REFERRAL_REWARD}!"
                )
    await send_main_menu(update, context)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user_data(user_id)
    if not user:
        create_user(user_id)
        user = get_user_data(user_id)

    if query.data == "show_balance":
        await query.edit_message_text(f"💰 Balance: ₹{user['balance']}\n👥 Referrals: {len(user['referrals'])}")
    elif query.data == "claim_bonus":
        now = datetime.now()
        if not user['last_bonus'] or now - user['last_bonus'] > timedelta(days=1):
            update_user_balance(user_id, user['balance'] + BONUS_AMOUNT)
            update_user_last_bonus(user_id, now)
            await query.edit_message_text("🎁 Bonus claimed! ₹1 added to your balance.")
        else:
            await query.edit_message_text("⏳ Bonus already claimed today. Come back later.")

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("💰 Balance", callback_data="show_balance"),
                 InlineKeyboardButton("🎁 Claim Bonus", callback_data="claim_bonus")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.callback_query:
        await update.callback_query.edit_message_text("Main Menu:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Main Menu:", reply_markup=reply_markup)

# --- Start Telegram Bot ---
def start_telegram_bot():
    init_db()
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable not set.")
        exit(1)
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_buttons))
    logger.info("🤖 Telegram bot is starting...")
    application.run_polling()

# --- Main ---
if __name__ == "__main__":
    threading.Thread(target=start_telegram_bot).start()
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🌐 Flask app starting on port {port}")
    app.run(host="0.0.0.0", port=port)
