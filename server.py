from flask import Flask, request
from telegram import Update
from bot import application
import asyncio

app = Flask(__name__)

@app.route("/")
def health():
    return "✅ Telegram bot is live on Render!"

@app.route("/webhook", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "OK"
