import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from http import HTTPStatus

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

import yt_dlp
import traceback

# ----------------------------------------
# Logging
# ----------------------------------------
logging.basicConfig(level=logging.INFO)

# ----------------------------------------
# Environment Variables (Render)
# ----------------------------------------
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}{WEBHOOK_PATH}"

# Cookies file for YouTube login
COOKIES = "/app/cookies.txt"

# ----------------------------------------
# Telegram Application
# ----------------------------------------
ptb_app = Application.builder().token(BOT_TOKEN).build()

# ----------------------------------------
# /start command
# ----------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send any video link (YouTube, Instagram, FB, TikTok).")


# ----------------------------------------
# Handle incoming URL
# ----------------------------------------
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    ydl_opts_meta = {
        "quiet": True,
        "skip_download": True,
        "cookies": COOKIES,

        # Very important for YouTube
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },

        # YouTube now requires JS processing
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android"]
            }
        }
    }

    try:
        ydl = yt_dlp.YoutubeDL(ydl_opts_meta)
        info = ydl.extract_info(url, download=False)

    except Exception:
        print("Metadata ERROR:", traceback.format_exc())
        await update.message.reply_text("❌ Unable to fetch video details.")
        return

    title = info.get("title", "Untitled")
    thumbnail = info.get("thumbnail", None)
    platform = info.get("extractor_key")

    context.user_data["url"] = url

    keyboard = [
        [InlineKeyboardButton("⬇ Download MP4", callback_data="dl")],
    ]

    await update.message.reply_photo(
        photo=thumbnail,
        caption=f"🎬 *{title}*\n📌 Platform: {platform}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


# ----------------------------------------
# Handle Download Button
# ----------------------------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")
    await query.edit_message_caption("⏳ Downloading… Please wait...")

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": "/tmp/%(title)s.%(ext)s",
        "cookies": COOKIES,

        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        },

        "retries": 10,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if os.path.getsize(file_path) > 50 * 1024 * 1024:
            await query.message.reply_text("❌ File is larger than 50 MB. Telegram cannot send it.")
            return

        with open(file_path, "rb") as f:
            await query.message.reply_video(video=f)

        os.remove(file_path)

    except Exception:
        print("Download ERROR:", traceback.format_exc())
        await query.message.reply_text("❌ Download failed. Try another link.")


# ----------------------------------------
# Register Handlers
# ----------------------------------------
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
ptb_app.add_handler(CallbackQueryHandler(button))


# ----------------------------------------
# Webhook & FastAPI
# ----------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    await ptb_app.bot.set_webhook(WEBHOOK_URL)
    async with ptb_app:
        await ptb_app.start()
        yield
        await ptb_app.stop()


app = FastAPI(lifespan=lifespan)


@app.post(WEBHOOK_PATH)
async def webhook_handler(request: Request):
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)


@app.get("/")
def home():
    return {"status": "Bot running", "webhook": WEBHOOK_URL}
