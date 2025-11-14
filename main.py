import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from http import HTTPStatus
import traceback
import yt_dlp
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8000')}{WEBHOOK_PATH}"

ptb_app = Application.builder().token(BOT_TOKEN).read_timeout(7).get_updates_read_timeout(42).build()

# Regex to detect URLs
URL_REGEX = re.compile(r'https?://\S+')


# --------------------------
# /start command
# --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 Welcome to SmartAI Media Downloader!\n\n"
        "Send me ANY video link from YouTube, Instagram, Facebook, Twitter, etc.\n"
        "If the video is private or YouTube restricts it, upload cookies via:\n\n"
        "/cookies"
    )


# --------------------------
# Upload cookies
# --------------------------
async def handle_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document and update.message.document.file_name.endswith(".txt"):
        file = await context.bot.get_file(update.message.document.file_id)
        cookies_path = f"/tmp/{update.effective_user.id}_cookies.txt"
        await file.download_to_drive(cookies_path)
        context.user_data["cookies_path"] = cookies_path

        await update.message.reply_text("✅ Cookies uploaded! Now send a video URL.")
    else:
        await update.message.reply_text("❌ Please send a valid .txt cookies file.")


# --------------------------
# Handle incoming text (URL only)
# --------------------------
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # ❌ If it's not a URL → show helpful message
    if not URL_REGEX.search(text):
        await update.message.reply_text(
            "❌ That doesn't look like a valid video link.\n\n"
            "Send me a URL from YouTube, Instagram, Facebook, etc.\n"
            "Need cookies? Use /cookies"
        )
        return

    # ✔ Valid URL → store it
    context.user_data["url"] = text

    keyboard = [
        [InlineKeyboardButton("Best", callback_data="best"),
         InlineKeyboardButton("720p", callback_data="720")],
        [InlineKeyboardButton("1080p", callback_data="1080")]
    ]
    await update.message.reply_text(
        "🎥 Select download quality:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# --------------------------
# DOWNLOAD BUTTON HANDLER (FULL BYPASS VERSION)
# --------------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    quality_map = {
        "best": "bestvideo+bestaudio/best",
        "720": "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    }
    quality = quality_map.get(query.data, "best")

    url = context.user_data.get("url")
    cookies_path = context.user_data.get("cookies_path")

    # Cookies needed for YouTube
    if ("youtube.com" in url or "youtu.be" in url) and not cookies_path:
        await query.edit_message_text(
            "⚠️ This YouTube video requires cookies.\n"
            "Upload cookies via /cookies (use the 'Get cookies.txt' Chrome extension)."
        )
        return

    await query.edit_message_text("⏳ Downloading… please wait.")

    ydl_opts = {
        "format": quality,
        "merge_output_format": "mp4",
        "outtmpl": "/tmp/%(title)s.%(ext)s",

        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        },

        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android", "ios"],
                "no_check_certificate": ["True"],
                "max_comments": ["0"],
            }
        },

        "cookies": cookies_path,

        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 10,
        "sleep_interval": 3,
        "socket_timeout": 30,
        "ignoreerrors": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if file_path.endswith(".webm") or file_path.endswith(".m4a"):
            file_path = file_path.rsplit(".", 1)[0] + ".mp4"

        if os.path.getsize(file_path) > 50 * 1024 * 1024:
            await query.edit_message_text("⚠️ Video is too large (>50MB). Try 720p.")
            os.remove(file_path)
            return

        with open(file_path, "rb") as f:
            await query.message.reply_video(video=f, caption=f"✅ Downloaded in {query.data}!")

        os.remove(file_path)

    except Exception as e:
        print("YT-DLP ERROR:\n", traceback.format_exc())
        await query.edit_message_text(
            f"❌ Download failed: {type(e).__name__}\n"
            "Check logs & upload new cookies via /cookies."
        )


# --------------------------
# FastAPI + Telegram Webhook
# --------------------------
ptb_app.add_handler(CommandHandler("start", start))
ptb_app.add_handler(CommandHandler("cookies", handle_cookies))
ptb_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
ptb_app.add_handler(CallbackQueryHandler(button))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await ptb_app.bot.set_webhook(url=WEBHOOK_URL)
    async with ptb_app:
        await ptb_app.start()
        yield
        await ptb_app.stop()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Bot is running!"}


@app.post(WEBHOOK_PATH)
async def process_update(request: Request):
    req = await request.json()
    update = Update.de_json(req, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=HTTPStatus.OK)
