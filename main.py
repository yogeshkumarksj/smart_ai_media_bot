import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from http import HTTPStatus
import traceback
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8000')}{WEBHOOK_PATH}"

ptb_app = Application.builder().token(BOT_TOKEN).read_timeout(7).get_updates_read_timeout(42).build()


# --------------------------
# /start command
# --------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send a video URL from YouTube, FB, or Insta!\n"
        "Use /cookies to upload session cookies for private/age-restricted videos."
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

        await update.message.reply_text("Cookies uploaded successfully! Now send a URL.")
    else:
        await update.message.reply_text("Please upload a valid .txt cookies file.")


# --------------------------
# User sends URL
# --------------------------
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["url"] = update.message.text

    keyboard = [
        [InlineKeyboardButton("Best", callback_data="best"),
         InlineKeyboardButton("720p", callback_data="720")],
        [InlineKeyboardButton("1080p", callback_data="1080")]
    ]
    await update.message.reply_text("Select quality:", reply_markup=InlineKeyboardMarkup(keyboard))


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

    # Cookies are required for many YouTube videos now
    if ("youtube.com" in url or "youtu.be" in url) and not cookies_path:
        await query.edit_message_text(
            "This YouTube video requires cookies.\n"
            "Upload cookies via /cookies (use the 'Get cookies.txt' Chrome extension)."
        )
        return

    await query.edit_message_text("Downloading… please wait.")

    # Strongest yt-dlp bypass settings
    ydl_opts = {
        "format": quality,
        "merge_output_format": "mp4",
        "outtmpl": "/tmp/%(title)s.%(ext)s",

        # Browser impersonation
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

        # YouTube restriction bypass
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "android", "ios"],
                "no_check_certificate": ["True"],
                "max_comments": ["0"],
            }
        },

        # Cookies support
        "cookies": cookies_path,

        # Reduce throttling & failures
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 10,
        "sleep_interval": 3,
        "sleep_interval_subtitles": 2,

        # Timeout protection
        "socket_timeout": 30,

        # Avoid failures
        "ignoreerrors": False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        # Convert .webm/.m4a → .mp4
        if file_path.endswith(".webm") or file_path.endswith(".m4a"):
            file_path = file_path.rsplit(".", 1)[0] + ".mp4"

        # Telegram 50MB limit
        if os.path.getsize(file_path) > 50 * 1024 * 1024:
            await query.edit_message_text("Video too large (>50MB). Try 720p.")
            os.remove(file_path)
            return

        # Send file
        with open(file_path, "rb") as f:
            await query.message.reply_video(video=f, caption=f"Downloaded in {query.data}!")

        os.remove(file_path)

    except Exception as e:
        print("YT-DLP ERROR:\n", traceback.format_exc())
        await query.edit_message_text(
            f"❌ Download failed: {type(e).__name__}. Check logs.\n"
            "If YouTube shows CAPTCHA, upload NEW cookies via /cookies."
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
