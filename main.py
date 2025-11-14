import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from http import HTTPStatus
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode

logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.environ['BOT_TOKEN']
WEBHOOK_PATH = f"/{BOT_TOKEN}"
WEBHOOK_URL = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', 'localhost:8000')}{WEBHOOK_PATH}"

ptb_app = Application.builder().token(BOT_TOKEN).read_timeout(7).get_updates_read_timeout(42).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Send a video URL!')

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['url'] = update.message.text
    keyboard = [[InlineKeyboardButton("Best", callback_data='best'), InlineKeyboardButton("720p", callback_data='720')], [InlineKeyboardButton("1080p", callback_data='1080')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Select quality:', reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    quality_map = {'best': 'best', '720': 'best[height<=720]', '1080': 'best[height<=1080]'}
    quality = quality_map[query.data]
    url = context.user_data['url']
    await query.edit_message_text('Downloading...')
    ydl_opts = {'format': quality, 'outtmpl': '%(title)s.%(ext)s', 'merge_output_format': 'mp4'}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
        with open(file_path, 'rb') as video:
            await query.message.reply_video(video=video, caption='Downloaded!')
        os.remove(file_path)
    except Exception as e:
        await query.edit_message_text(f'Error: {str(e)}')

ptb_app.add_handler(CommandHandler('start', start))
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
