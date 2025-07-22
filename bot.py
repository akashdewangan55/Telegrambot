import logging import aiosqlite from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup from telegram.ext import ( Application, CommandHandler, CallbackQueryHandler, ContextTypes ) from datetime import datetime, timedelta import asyncio

logging.basicConfig( format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO )

--- Configuration Constants ---

BONUS_AMOUNT = 1 REFERRAL_REWARD = 5 WITHDRAW_THRESHOLD = 50 CHANNEL_LINK = "https://t.me/dailyearn11" CHECK_CHANNEL_ID = -1001441974665 DB_NAME = 'bot_data.db'

async def init_db(): async with aiosqlite.connect(DB_NAME) as conn: await conn.execute(''' CREATE TABLE IF NOT EXISTS users ( user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0, last_bonus TEXT, ref_by INTEGER ) ''') await conn.commit()

async def get_user_data(user_id: int): async with aiosqlite.connect(DB_NAME) as conn: conn.row_factory = aiosqlite.Row async with conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor: user_row = await cursor.fetchone() return dict(user_row) if user_row else None

async def add_user(user_id: int, referrer_id: int = None): async with aiosqlite.connect(DB_NAME) as conn: await conn.execute( 'INSERT OR IGNORE INTO users (user_id, ref_by) VALUES (?, ?)', (user_id, referrer_id) ) if referrer_id: await conn.execute( 'UPDATE users SET balance = balance + ? WHERE user_id = ?', (REFERRAL_REWARD, referrer_id) ) await conn.commit()

async def update_balance(user_id: int, amount: float): async with aiosqlite.connect(DB_NAME) as conn: await conn.execute( 'UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id) ) await conn.commit()

async def set_last_bonus(user_id: int): async with aiosqlite.connect(DB_NAME) as conn: now = datetime.utcnow().isoformat() await conn.execute( 'UPDATE users SET last_bonus = ? WHERE user_id = ?', (now, user_id) ) await conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = update.effective_user.id referrer_id = None

if context.args:
    try:
        referrer_id = int(context.args[0])
    except ValueError:
        pass

user = await get_user_data(user_id)
if not user:
    await add_user(user_id, referrer_id)

keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("Join Channel", url=CHANNEL_LINK)],
    [InlineKeyboardButton("Claim Bonus", callback_data='claim_bonus')]
])

await context.bot.send_message(
    chat_id=update.effective_chat.id,
    text="Welcome! Join our channel and claim your daily bonus.",
    reply_markup=keyboard
)

async def claim_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() user_id = query.from_user.id user = await get_user_data(user_id)

if not user:
    await context.bot.send_message(chat_id=user_id, text="User not found.")
    return

last_bonus = user.get('last_bonus')
if last_bonus:
    last_time = datetime.fromisoformat(last_bonus)
    if datetime.utcnow() - last_time < timedelta(days=1):
        await context.bot.send_message(chat_id=user_id, text="You have already claimed your bonus today.")
        return

await update_balance(user_id, BONUS_AMOUNT)
await set_last_bonus(user_id)
await context.bot.send_message(chat_id=user_id, text=f"You've received your daily bonus of ₹{BONUS_AMOUNT}!")

async def main(): await init_db() app = Application.builder().token("7950712207:AAHMIek-JXLy6fLrQMBHk-2hzFXdY1d0HG8").build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(claim_bonus, pattern='claim_bonus'))

await app.run_polling()

if name == 'main': asyncio.run(main())

