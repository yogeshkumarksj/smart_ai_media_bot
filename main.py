import os
import logging
import traceback
from contextlib import asynccontextmanager
from http import HTTPStatus

import yt_dlp
from fastapi import FastAPI, Request, Response
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8000')}{WEBHOOK_PATH}"

ptb_app = Application.builder().token(BOT_TOKEN).read_timeout(7).get_updates_read_timeout(42).build()


# ----------------------------------------------------
# START
# ----------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me any public video URL (YouTube/FB/Insta).")


# ----------------------------------------------------
# HANDLE URL → extract details + show thumbnail
# ----------------------------------------------------
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    context.user_data["url"] = url

    # Try to extract metadata WITHOUT downloading
    try:
        ydl_opts_info = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)

        title = info.get("title", "Unknown Title")
        thumbnail = info.get("thumbnail")
        uploader = info.get("uploader", "")
        platform = info.get("extractor_key", "").replace("Generic", "Website")

        caption = f"📌 <b>{title}</b>\n" \
                  f"🌐 Platform: {platform}\n" \
                  f"👤 Uploader: {uploader}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬇ Download MP4", callback_data="download_mp4")]
        ])

        # Send thumb + caption
        await update.message.reply_photo(
            photo=thumbnail,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:
        print("Metadata ERROR:\n", traceback.format_exc())
        await update.message.reply_text("❌ Unable to get info. Only public videos work.")


# ----------------------------------------------------
# DOWNLOAD BUTTON HANDLER
# ----------------------------------------------------
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get("url")

    # Safe editing (photo caption → must use edit_message_caption)
    try:
        if query.message.photo:
            await query.edit_message_caption("⏳ Downloading… please wait.")
        else:
            await query.edit_message_text("⏳ Downloading… please wait.")
    except:
        await query.message.reply_text("⏳ Downloading… please wait.")

    # Download settings
    ydl_opts = {
        "format": "mp4/best",
        "outtmpl": "/tmp/%(title)s.%(ext)s",
        "noplaylist": True,

        # Simple user-agent (no cookies needed)
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if os.path.getsize(file_path) > 50 * 1024 * 1024:
            await query.message.reply_text("❌ File > 50MB. Try a shorter video.")
            os.remove(file_path)
            return

        with open(file_path, "rb") as f:
            await query.message.reply_video(
                video=f,
                caption="✅ Download complete!"
            )

        os.remove(file_path)

    except Exception as e:
        print("DOWNLOAD ERROR:\n", traceback.format_exc())
        await query.message.reply_text(
            "❌ Failed to download. Only public non-restricted videos can be downloaded."
        )


# ----------------------------------------------------
# FASTAPI + WEBHOOK
# ----------------------------------------------------
ptb_app.add_handler(CommandHandler("start", start))
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
