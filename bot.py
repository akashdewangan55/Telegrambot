import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)
from datetime import datetime, timedelta
import asyncio
import sqlite3

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# --- Configuration Constants ---
BONUS_AMOUNT = 1
REFERRAL_REWARD = 5
WITHDRAW_THRESHOLD = 50
CHANNEL_LINK = "https://t.me/dailyearn11"
CHECK_CHANNEL_ID = -1001441974665  # Replace with your actual channel ID

# --- Database Configuration ---
DB_NAME = 'bot_data.db'


def init_db():
    """Initializes the SQLite database and creates tables if they don't exist."""
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
    """Retrieves user data from the database. Returns a dictionary or None."""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user_row = cursor.fetchone()

        if user_row:
            user_data = dict(user_row)
            if user_data['last_bonus']:
                user_data['last_bonus'] = datetime.fromisoformat(user_data['last_bonus'])
            else:
                user_data['last_bonus'] = None

            cursor.execute('SELECT referred_id FROM referrals WHERE referrer_id = ?', (user_id,))
            user_data['referrals'] = [row[0] for row in cursor.fetchall()]
            return user_data
        return None


def create_user(user_id: int, ref_by: int = None):
    """Creates a new user entry in the database."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (user_id, balance, last_bonus, ref_by) VALUES (?, ?, ?, ?)',
                       (user_id, 0, None, ref_by))
        conn.commit()


def update_user_balance(user_id: int, new_balance: float):
    """Updates a user's balance in the database."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET balance = ? WHERE user_id = ?', (new_balance, user_id))
        conn.commit()


def update_user_last_bonus(user_id: int, last_bonus_time: datetime):
    """Updates a user's last bonus timestamp in the database."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET last_bonus = ? WHERE user_id = ?',
                       (last_bonus_time.isoformat(), user_id))
        conn.commit()


def add_referral(referrer_id: int, referred_id: int):
    """Adds a referral entry to the database (ignores duplicates)."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)',
                       (referrer_id, referred_id))
        conn.commit()


# --- Keyboard Layouts ---

async def get_main_menu_keyboard(user_id: int):
    """Generates the main menu keyboard."""
    is_member = await is_user_member(user_id, CHECK_CHANNEL_ID)

    if not is_member:
        keyboard = [
            [InlineKeyboardButton("✅ Join Channel to Start", url=CHANNEL_LINK)],
            [InlineKeyboardButton("🔄 I have joined!", callback_data='check_membership')],
        ]
    else:
        keyboard = [
            [InlineKeyboardButton("💰 Balance", callback_data='show_balance'),
             InlineKeyboardButton("🎁 Daily Bonus", callback_data='claim_bonus')],
            [InlineKeyboardButton("👥 Referral Link", callback_data='show_referral'),
             InlineKeyboardButton("💸 Withdraw", callback_data='show_withdraw')],
            [InlineKeyboardButton("ℹ️ How to Earn", callback_data='show_info')]
        ]
    return InlineKeyboardMarkup(keyboard)


def get_back_button_keyboard():
    """Generates a keyboard with only a 'Back' button."""
    keyboard = [
        [InlineKeyboardButton("⬅️ Back to Main Menu", callback_data='main_menu')]
    ]
    return InlineKeyboardMarkup(keyboard)


# --- Helper Functions ---

async def is_user_member(user_id: int, chat_id: int) -> bool:
    """Checks if a user is a member of the specified channel."""
    try:
        member = await application.bot.get_chat_member(chat_id, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"Error checking channel membership for user {user_id}: {e}")
        return False


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str = None):
    """Sends or edits the message to display the main menu."""
    user_id = update.effective_user.id
    keyboard = await get_main_menu_keyboard(user_id)

    if message_text is None:
        message_text = (
            f"👋 Welcome {update.effective_user.first_name}!\n\n"
            "💸 Earn ₹5 per referral.\n"
            "🎁 Claim daily bonus.\n"
            "💰 Withdraw when balance ≥ ₹50.\n\n"
            "👇 Choose an option:"
        )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            message_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message_text,
            reply_markup=keyboard,
            parse_mode='Markdown'
        )


# --- Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_data = get_user_data(user_id)

    if not user_data:
        ref_by_id = None
        if context.args:
            ref_by_str = context.args[0]
            if ref_by_str.isdigit():
                possible_ref_by_id = int(ref_by_str)
                if possible_ref_by_id != user_id and get_user_data(possible_ref_by_id):
                    ref_by_id = possible_ref_by_id

        create_user(user_id, ref_by=ref_by_id)
        logging.info(f"New user {user_id} created. Referred by: {ref_by_id}")

        if ref_by_id:
            existing_referral = False
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM referrals WHERE referrer_id = ? AND referred_id = ?',
                               (ref_by_id, user_id))
                if cursor.fetchone():
                    existing_referral = True

            if not existing_referral:
                referrer_data = get_user_data(ref_by_id)
                if referrer_data:
                    new_referrer_balance = referrer_data['balance'] + REFERRAL_REWARD
                    update_user_balance(ref_by_id, new_referrer_balance)
                    add_referral(ref_by_id, user_id)
                    logging.info(f"Referral: {ref_by_id} earned ₹{REFERRAL_REWARD} for referring {user_id}")
                    try:
                        await application.bot.send_message(
                            chat_id=ref_by_id,
                            text=f"🎉 Congratulations! Your friend {update.effective_user.first_name} ({user_id}) joined using your link and you earned ₹{REFERRAL_REWARD}!"
                        )
                    except Exception as e:
                        logging.error(f"Could not send referral message to {ref_by_id}: {e}")

    await send_main_menu(update, context)


# --- Callback Query Handler ---

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    user = get_user_data(user_id)
    if not user:
        create_user(user_id)
        user = get_user_data(user_id)

    is_member = await is_user_member(user_id, CHECK_CHANNEL_ID)
    if not is_member and query.data != 'check_membership':
        keyboard = await get_main_menu_keyboard(user_id)
        await query.edit_message_text(
            "🛑 You must join our channel to use the bot features.",
            reply_markup=keyboard
        )
        return

    if query.data in ['main_menu', 'check_membership']:
        if query.data == 'check_membership':
            is_member_after_check = await is_user_member(user_id, CHECK_CHANNEL_ID)
            if not is_member_after_check:
                await query.edit_message_text(
                    "❌ Please join the channel and try again.",
                    reply_markup=await get_main_menu_keyboard(user_id)
                )
                return
            else:
                await send_main_menu(update, context, "✅ Thank you for joining! You can now use the bot.")
        else:
            await send_main_menu(update, context)

    elif query.data == 'show_balance':
        await query.edit_message_text(
            f"💰 Your balance: ₹{int(user['balance'])}\n\n"
            f"👥 Total Referrals: {len(user['referrals'])}\n",
            reply_markup=get_back_button_keyboard()
        )

    elif query.data == 'claim_bonus':
        now = datetime.now()
        if not user['last_bonus'] or now - user['last_bonus'] > timedelta(days=1):
            new_balance = user['balance'] + BONUS_AMOUNT
            update_user_balance(user_id, new_balance)
            update_user_last_bonus(user_id, now)
            await query.edit_message_text(
                "🎁 Bonus received! ₹1 added to your balance.",
                reply_markup=get_back_button_keyboard()
            )
        else:
            time_left = timedelta(days=1) - (now - user['last_bonus'])
            hours, remainder = divmod(int(time_left.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            await query.edit_message_text(
                f"⏳ Already claimed. Come back in {hours}h {minutes}m.",
                reply_markup=get_back_button_keyboard()
            )

    elif query.data == 'show_referral':
        link = f"https://t.me/{application.bot.username}?start={user_id}"
        await query.edit_message_text(
            f"👥 Share your referral link:\n`{link}`\n\n"
            f"Earn ₹{REFERRAL_REWARD} per referral!\n"
            f"You have referred {len(user['referrals'])} friend(s).",
            reply_markup=get_back_button_keyboard(),
            parse_mode='Markdown'
        )

    elif query.data == 'show_withdraw':
        if user['balance'] >= WITHDRAW_THRESHOLD:
            update_user_balance(user_id, 0)
            await query.edit_message_text(
                "✅ Withdrawal requested!\n"
                f"Your ₹{WITHDRAW_THRESHOLD} will be processed soon.",
                reply_markup=get_back_button_keyboard()
            )
            logging.info(f"Withdrawal requested by user {user_id}")
        else:
            await query.edit_message_text(
                f"❌ Minimum ₹{WITHDRAW_THRESHOLD} required to withdraw. Your balance: ₹{int(user['balance'])}",
                reply_markup=get_back_button_keyboard()
            )

    elif query.data == 'show_info':
        await query.edit_message_text(
            "📖 *How to Earn:*\n\n"
            "1️⃣ 🎁 Daily bonus (₹1/day)\n"
            "2️⃣ 👥 Refer friends (₹5 each)\n"
            "3️⃣ 💸 Withdraw when balance ≥ ₹50\n\n"
            "Tap buttons below to start earning.",
            reply_markup=get_back_button_keyboard(),
            parse_mode='Markdown'
        )


# --- Main Bot Runner ---

async def run_bot():
    global application

    init_db()  # Initialize DB
    application = Application.builder().token("7950712207:AAHMIek-JXLy6fLrQMBHk-2hzFXdY1d0HG8").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_buttons))

    print("🤖 Bot is running...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except RuntimeError as e:
        if "already running" in str(e):
            print("⚠️ Event loop already running. Using create_task().")
            asyncio.create_task(run_bot())
        else:
            raise
