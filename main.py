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

# Optional: cookie helper (not required). If you want auto-export from browser,
# install browser-cookie3 and add it to requirements. This code supports having cookies.txt present.
try:
    import browser_cookie3  # optional
    HAVE_BROWSER_COOKIE3 = True
except Exception:
    HAVE_BROWSER_COOKIE3 = False

# Telegram Bot library - we will use python-telegram-bot for sending messages back
from telegram import Bot, InlineKeyboardMarkup, InlineKeyboardButton

# ---------------------------
# Configuration (env)
# ---------------------------
LOG = logging.getLogger("smart-media")
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BASE_URL = os.getenv("BASE_URL", "https://ai-smart-media-downloader.onrender.com").rstrip("/")
COOKIE_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Timeouts / limits
YT_DLP_TIMEOUT = int(os.getenv("YT_DLP_TIMEOUT", "300"))  # seconds

# Setup bot object if token provided
bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None

# ---------------------------
# FastAPI app
# ---------------------------
app = FastAPI(
    title="Smart Media Downloader - Omni Chat Backend",
    description="Website / Telegram / WhatsApp / Instagram webhook backend with media downloader",
    version="1.0"
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------------------------
# Pydantic models
# ---------------------------
class ChatMessage(BaseModel):
    user: Optional[str] = "Guest"
    message: str

# ---------------------------
# Helper functions
# ---------------------------
def is_valid_cookie_file(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(200)
            return "Netscape HTTP Cookie File" in head or "Netscape" in head
    except Exception:
        return False

def auto_export_browser_cookies(target_path: str = COOKIE_FILE) -> bool:
    """Attempt to export cookies from Chrome/Edge/Firefox (if browser_cookie3 is installed).
       Returns True if written and appears valid.
    """
    if not HAVE_BROWSER_COOKIE3:
        LOG.warning("browser-cookie3 not available; skipping auto_export_browser_cookies")
        return False
    try:
        # tries chrome first, then firefox
        cookies = None
        for fn in (browser_cookie3.chrome, browser_cookie3.firefox, browser_cookie3.edge):
            try:
                cookies = fn(domain_name=".youtube.com")
                break
            except Exception:
                cookies = None
        if not cookies:
            LOG.warning("Could not extract cookies from browser")
            return False
        with open(target_path, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cookies:
                expires = int(getattr(c, "expires", 0) or 0)
                # Netscape cookie fields: domain, TRUE, path, secure?, expiry, name, value
                f.write(f"{c.domain}\tTRUE\t{c.path}\t{str(c.secure).upper()}\t{expires}\t{c.name}\t{c.value}\n")
        LOG.info("Cookies exported to %s", target_path)
        return is_valid_cookie_file(target_path)
    except Exception as e:
        LOG.exception("Failed to export cookies: %s", e)
        return False

def normalize_youtube_url(url: str) -> str:
    if "shorts/" in url:
        m = re.search(r"shorts/([A-Za-z0-9_-]+)", url)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    if "m.youtube.com" in url:
        return url.replace("m.youtube.com", "www.youtube.com")
    return url

def yt_dlp_get_info(url: str):
    """Get metadata (no download). Raises Exception on failure."""
    ydl_opts = {"quiet": True, "skip_download": True, "nocheckcertificate": True, "forcejson": False}
    if is_valid_cookie_file(COOKIE_FILE):
        ydl_opts["cookiefile"] = COOKIE_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def download_with_yt_dlp(url: str, out_dir: Path = DOWNLOAD_DIR, timeout: int = YT_DLP_TIMEOUT) -> Path:
    """Download video to out_dir and return full path to resulting mp4 file.
       This is synchronous — run in threadpool in endpoints.
    """
    url = normalize_youtube_url(url)
    out_template = str(out_dir / "%(id)s.%(ext)s")
    ydl_opts = {
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
    }
    if is_valid_cookie_file(COOKIE_FILE):
        ydl_opts["cookiefile"] = COOKIE_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # prepare_filename will reflect template used
        path = ydl.prepare_filename(info)
        if not path.endswith(".mp4"):
            base = os.path.splitext(path)[0]
            new_path = base + ".mp4"
            try:
                if os.path.exists(path) and not os.path.exists(new_path):
                    os.rename(path, new_path)
                path = new_path
            except Exception:
                pass
        return Path(path)

# ---------------------------
# ROUTES - Health + Chat + Download
# ---------------------------
@app.get("/")
async def root():
    return {"message": "Smart Media Downloader - backend online"}

@app.post("/chat")
async def website_chat(msg: ChatMessage):
    # Simple placeholder AI reply - replace with OpenAI call if you want
    user = msg.user or "Guest"
    reply = f"Hi {user}, I received: {msg.message}"
    return {"reply": reply}

@app.get("/download")
async def download_info(url: str):
    """Return metadata (no download). Good for showing thumbnail/title on web UI."""
    try:
        info = await asyncio.get_running_loop().run_in_executor(None, yt_dlp_get_info, url)
        return {
            "platform": info.get("extractor", "unknown"),
            "id": info.get("id"),
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or info.get("url"),
        }
    except Exception as e:
        LOG.exception("download_info error")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/file/{video_id}")
async def stream_file(video_id: str, background_tasks: BackgroundTasks):
    """Serve cached file if exists, otherwise download then serve.
       This endpoint is what Telegram/website 'Download' buttons should open.
       It returns the video as a FileResponse (Content-Disposition: attachment).
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,}", video_id):
        raise HTTPException(status_code=400, detail="Invalid video id")

    file_path = DOWNLOAD_DIR / f"{video_id}.mp4"
    if file_path.exists():
        return FileResponse(path=file_path, media_type="video/mp4", filename=file_path.name)

    # Not cached -> download synchronously in threadpool (so worker not blocked)
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, download_with_yt_dlp, url)
        # ensure correct name under video_id.mp4
        emerg = DOWNLOAD_DIR / f"{video_id}.mp4"
        # move/rename to standardized name
        try:
            shutil.move(str(path), str(emerg))
        except Exception:
            emerg = path
        return FileResponse(path=emerg, media_type="video/mp4", filename=emerg.name)
    except Exception as e:
        LOG.exception("Error downloading file")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------
# Telegram Webhook endpoints
# ---------------------------
@app.get("/telegram/set_webhook")
async def set_telegram_webhook():
    """Call this manually (or via CI) once to set webhook to BASE_URL/telegram/webhook."""
    if not bot:
        raise HTTPException(status_code=500, detail="BOT token not configured")
    webhook_url = f"{BASE_URL}/telegram/webhook"
    res = await bot.set_webhook(webhook_url)
    return {"success": res, "webhook": webhook_url}

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Telegram webhook receiver. We respond asynchronously by sending messages via Bot."""
    if not bot:
        return JSONResponse({"error": "Bot not configured"}, status_code=500)
    data = await request.json()
    message = data.get("message") or data.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    # /start
    if text.startswith("/start"):
        await bot.send_message(chat_id, "👋 Hi! Send a YouTube / Instagram / TikTok link to get the download link.")
        return JSONResponse({"ok": True})
    # otherwise handle link
    if not any(x in text for x in ["youtube", "youtu.be", "instagram", "tiktok", "facebook"]):
        await bot.send_message(chat_id, "⚠️ Please send a valid media URL (youtube, instagram, tiktok, facebook).")
        return JSONResponse({"ok": True})

    await bot.send_message(chat_id, "🔍 Fetching media info... please wait ⏳")

    # Get info
    try:
        # If instagram
        if "instagram.com" in text:
            shortcode = re.search(r"(?:reel|p)/([A-Za-z0-9_-]+)", text)
            if not shortcode:
                await bot.send_message(chat_id, "❌ Invalid Instagram URL")
                return JSONResponse({"ok": True})
            shortcode = shortcode.group(1)
            L = instaloader.Instaloader(download_videos=False, save_metadata=False)
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            title = post.caption or "Instagram post"
            download_link = post.video_url if post.is_video else post.url
            caption = f"📸 {title}\n🔗 Download link below"
            # send button with direct download link (external). If you want direct file upload, download then send.
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download MP4", url=download_link)]])
            await bot.send_photo(chat_id, post.url, caption=caption, reply_markup=kb)
            return JSONResponse({"ok": True})

        # Else assume yt-dlp supported
        info = await asyncio.get_running_loop().run_in_executor(None, yt_dlp_get_info, text)
        vid_id = info.get("id")
        title = info.get("title", "Untitled")
        thumb = info.get("thumbnail")
        download_url = f"{BASE_URL}/file/{vid_id}"
        caption = f"🎬 {title}\n🔗 {download_url}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download MP4", url=download_url)]])
        if thumb:
            await bot.send_photo(chat_id, thumb, caption=caption, reply_markup=kb)
        else:
            await bot.send_message(chat_id, caption, reply_markup=kb)
        return JSONResponse({"ok": True})
    except Exception as e:
        LOG.exception("telegram handler error")
        await bot.send_message(chat_id, f"❌ Error fetching media: {e}")
        return JSONResponse({"ok": True})

# ---------------------------
# WhatsApp & Instagram webhook stubs (Meta)
# ---------------------------
@app.get("/meta/verify")
def meta_verify(mode: str = None, verify_token: str = None, challenge: str = None):
    """Use the same endpoint or different as your Meta webhook verification.
       Call /meta/verify?mode=subscribe&verify_token=YOUR_TOKEN&challenge=123 to verify."""
    VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
    if mode == "subscribe" and verify_token == VERIFY_TOKEN:
        return JSONResponse(content=int(challenge or 0))
    return JSONResponse({"error": "Verification failed"}, status_code=403)

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request):
    """Handle WhatsApp webhook JSON. This is a simple echo example (Meta requires responses via Graph API)."""
    data = await request.json()
    # IMPORTANT: Meta requires you to POST back using Graph API - this is only a stub.
    LOG.info("Received WhatsApp webhook: %s", data)
    return JSONResponse({"ok": True})

@app.post("/instagram")
async def instagram_webhook(request: Request):
    data = await request.json()
    LOG.info("Received Instagram webhook: %s", data)
    return JSONResponse({"ok": True})

# ---------------------------
# Startup tasks
# ---------------------------
@app.on_event("startup")
async def startup_event():
    LOG.info("Starting Smart Media backend")
    # Try auto-export cookies (non-blocking)
    if not is_valid_cookie_file(COOKIE_FILE) and HAVE_BROWSER_COOKIE3:
        LOG.info("Attempting to auto-export cookies from local browser (if available in env)")
        try:
            ok = await asyncio.get_running_loop().run_in_executor(None, auto_export_browser_cookies, COOKIE_FILE)
            if ok:
                LOG.info("Cookie export successful")
            else:
                LOG.info("Cookie export failed or not present")
        except Exception:
            LOG.exception("Cookie export error")
    else:
        if is_valid_cookie_file(COOKIE_FILE):
            LOG.info("Using existing cookies.txt")
        else:
            LOG.info("No valid cookies available")

# End of file
