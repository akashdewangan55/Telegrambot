from flask import Flask, request
import asyncio
import os
import logging

from telegram import Update
from bot import application  # Import the bot Application instance

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Telegram bot is live on Render!"

@app.route("/webhook", methods=["POST"])
async def webhook():
    update = Update.de_json(request.get_json(force=True), application.bot)
    await application.process_update(update)
    return "OK", 200

async def main():
    PORT = int(os.environ.get("PORT", 10000))
    WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"
    
    # Start the bot with webhook
    await application.initialize()
    await application.bot.set_webhook(WEBHOOK_URL)
    await application.start()
    logging.info(f"🌐 Webhook set at {WEBHOOK_URL}")

    # Start Flask
    app.run(host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    asyncio.run(main())
