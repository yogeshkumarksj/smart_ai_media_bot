import os
import logging
import re
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from http import HTTPStatus

import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = (
    f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8000')}{WEBHOOK_PATH}"
)

ptb_app = (
    Application.builder()
    .token(BOT_TOKEN)
    .read_timeout(7)
    .get_updates_read_timeout(42)
    .build()
)

# URL validation regex
URL_REGEX = re.compile(r'https?://\S+')


# ================================
# /start command
# ================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎉 *Welcome to SmartAI Media Downloader!*\n\n"
        "Send me ANY video link from:\n"
        "YouTube, Instagram, Facebook, Twitter, etc.\n\n"
        "If the video is private or restricted, upload cookies:\n"
        "`/cookies`\n\n"
        "I'm ready whenever you are 😊"
    )


# ================================
# Handle cookies upload
# ================================
async def handle_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.document and update.message.document.file_name.endswith(".txt"):
        file = await context.bot.get_file(update.message.document.file_id)
        cookies_path = f"/tmp/{update.effective_user.id}_cookies.txt"
        await file.download_to_drive(cookies_path)
        context.user_data["cookies_path"] = cookies_path

        await update.message.reply_text("✅ Cookies uploaded successfully! Now send your URL.")
    else:
        await update.message.reply_text("❌ Please upload a valid `.txt` cookies file.")


# ================================
# Handle incoming URL
# ================================
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # Validate URL
    if not URL_REGEX.search(text):
        await update.message.reply_text(
            "❌ That doesn't look like a valid video link.\n\n"
            "Send me a link from YouTube, Instagram, Facebook, etc."
        )
        return

    context.user_data["url"] = text

    # Extract metadata
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(text, download=False)

        title = info.get("title", "Unknown Title")
        platform = info.get("extractor_key", "Unknown").replace("Youtube", "YouTube")
        thumbnail_url = info.get("thumbnail")

        context.user_data["title"] = title

        keyboard = [
            [InlineKeyboardButton("⬇ Download Video", callback_data="download")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if thumbnail_url:
            await update.message.reply_photo(
                photo=thumbnail_url,
                caption=(
                    f"🎬 *{title}*\n"
                    f"📌 Platform: *{platform}*\n\n"
                    "Ready to download?"
                ),
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                f"🎬 *{title}*\n📌 Platform: *{platform}*\n\nReady to download?",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )

    except Exception:
        print("Metadata ERROR:\n", traceback.format_exc())
        await update.message.reply_text("❌ Could not fetch video details. Try again later.")


# ================================
# DOWNLOAD BUTTON
# ================================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data != "download":
        await query.edit_message_text("❌ Invalid action.")
        return

    url = context.user_data.get("url")
    cookies_path = context.user_data.get("cookies_path")

    # YouTube cookies needed
    if ("youtube.com" in url or "youtu.be" in url) and not cookies_path:
        await query.edit_message_text(
            "⚠️ This YouTube video requires cookies.\n"
            "Upload cookies via /cookies (use Get cookies.txt extension)."
        )
        return

    await query.edit_message_text("⏳ Downloading… please wait.")

    # Full bypass yt-dlp config
    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
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

        # Convert formats
        if file_path.endswith(".webm") or file_path.endswith(".m4a"):
            file_path = file_path.rsplit(".", 1)[0] + ".mp4"

        # Telegram 50MB limit
        if os.path.getsize(file_path) > 50 * 1024 * 1024:
            await query.edit_message_text(
                "⚠️ Video too large (>50MB). I cannot upload it. Try a smaller resolution."
            )
            os.remove(file_path)
            return

        # Upload to Telegram
        with open(file_path, "rb") as f:
            await query.message.reply_video(video=f, caption="✅ Download complete!")

        os.remove(file_path)

    except Exception:
        print("YT-DLP ERROR:\n", traceback.format_exc())
        await query.edit_message_text(
            "❌ Download failed. Check logs or upload new cookies via /cookies."
        )


# ================================
# Webhook + FastAPI Integration
# ================================
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

