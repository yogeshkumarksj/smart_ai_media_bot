import os
import re
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import instaloader
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

# ---------- CONFIG ----------
LOG = logging.getLogger("smart-media")
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "https://ai-smart-media-downloader.onrender.com").rstrip("/")
COOKIE_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

# ---------- FASTAPI ----------
app = FastAPI(
    title="Smart Media Downloader",
    description="Website + Telegram + WhatsApp + Instagram backend",
    version="4.0"
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- HELPERS ----------
def normalize_youtube_url(url: str) -> str:
    if "shorts/" in url:
        m = re.search(r"shorts/([A-Za-z0-9_-]+)", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    if "m.youtube.com" in url:
        return url.replace("m.youtube.com", "www.youtube.com")
    return url


def get_cookiefile() -> Optional[str]:
    return COOKIE_FILE if os.path.exists(COOKIE_FILE) else None


def yt_dlp_get_info(url: str):
    url = normalize_youtube_url(url)
    opts = {"quiet": True, "skip_download": True, "nocheckcertificate": True, "format": "best"}
    cookie = get_cookiefile()
    if cookie:
        opts["cookiefile"] = cookie
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def yt_dlp_download(url: str, out_dir: Path) -> Path:
    url = normalize_youtube_url(url)
    outtmpl = str(out_dir / "%(id)s.%(ext)s")
    opts = {
        "outtmpl": outtmpl,
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "nocheckcertificate": True,
    }
    cookie = get_cookiefile()
    if cookie:
        opts["cookiefile"] = cookie

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        if not file_path.endswith(".mp4"):
            new_path = os.path.splitext(file_path)[0] + ".mp4"
            os.rename(file_path, new_path)
            file_path = new_path
        return Path(file_path)


# ---------- MODELS ----------
class ChatMessage(BaseModel):
    user: str
    message: str


# ---------- ROUTES ----------
@app.get("/")
async def root():
    return {"message": "✅ Smart Media Downloader + AI Backend is live!"}


@app.post("/chat")
async def website_chat(msg: ChatMessage):
    """Simple echo for website chatbot"""
    reply = f"🤖 Hi {msg.user}, you said: {msg.message}"
    return {"reply": reply}


@app.get("/download")
async def get_info(url: str):
    try:
        info = await asyncio.get_running_loop().run_in_executor(None, yt_dlp_get_info, url)
        return {
            "id": info.get("id"),
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "platform": info.get("extractor", "unknown"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/file/{video_id}")
async def serve_video(video_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{5,}", video_id):
        raise HTTPException(status_code=400, detail="Invalid video id")

    path = DOWNLOAD_DIR / f"{video_id}.mp4"
    if not path.exists():
        url = f"https://www.youtube.com/watch?v={video_id}"
        path = await asyncio.get_running_loop().run_in_executor(None, yt_dlp_download, url, DOWNLOAD_DIR)
    return FileResponse(path, media_type="video/mp4", filename=path.name)


# ---------- TELEGRAM ----------
@app.get("/telegram/set_webhook")
async def set_webhook():
    if not bot:
        raise HTTPException(status_code=500, detail="Bot token missing")
    webhook = f"{BASE_URL}/telegram/webhook"
    res = await bot.set_webhook(webhook)
    return {"success": res, "webhook": webhook}


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    msg = data.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        await bot.send_message(chat_id, "👋 Send me a YouTube, Instagram, or TikTok link!")
        return {"ok": True}

    if not any(p in text for p in ["youtube", "youtu.be", "instagram", "tiktok", "facebook"]):
        await bot.send_message(chat_id, "⚠️ Please send a valid video URL.")
        return {"ok": True}

    await bot.send_message(chat_id, "🔍 Fetching video info...")

    try:
        info = await asyncio.get_running_loop().run_in_executor(None, yt_dlp_get_info, text)
        vid_id = info.get("id")
        title = info.get("title")
        thumb = info.get("thumbnail")
        link = f"{BASE_URL}/file/{vid_id}"
        caption = f"🎬 {title}\n📥 [Download MP4]({link})"
        buttons = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download Now", url=link)]])
        if thumb:
            await bot.send_photo(chat_id, photo=thumb, caption=caption, parse_mode="Markdown", reply_markup=buttons)
        else:
            await bot.send_message(chat_id, caption, parse_mode="Markdown", reply_markup=buttons)
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Error: {e}")

    return {"ok": True}
