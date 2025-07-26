from keep_alive import keep_alive
keep_alive()
import os
import json
import difflib
import re
import asyncio
from guessit import guessit
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from rapidfuzz import fuzz, process
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from fastapi import FastAPI, Request
import clean_text  # your custom text cleaner


# ---------- Load Environment ---------- #
load_dotenv(dotenv_path=".env")
BOT_TOKEN = os.getenv("OLD_MOVIES_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "webhook")
BASE_URL = os.getenv("RENDER_EXTERNAL_URL")  # e.g. https://your-bot.onrender.com
WEBHOOK_PATH = f"/{WEBHOOK_SECRET}"
ALLOWED_USER_IDS = {
    int(uid.strip()) for uid in os.getenv("ALLOWED_USER_IDS", "").split(",") if uid.strip().isdigit()
}
MOVIE_DB_FILE = "movies.json"
USER_LOG_FILE = "user_logs.json"

# ---------- Utility Functions ---------- #
def load_movies():
    if not os.path.exists(MOVIE_DB_FILE):
        with open(MOVIE_DB_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(MOVIE_DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_movies(data):
    with open(MOVIE_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def clean_title_text(raw_title):
    title_cleaned = re.sub(r"@[\w\d_]+[\s\-]*", "", raw_title)
    title_cleaned = re.sub(r"\s+", " ", title_cleaned)
    return title_cleaned.replace(".", " ").strip().lower()

async def delete_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    await asyncio.sleep(1800)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print("Delete failed:", e)

# ---------- Telegram Handlers ---------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 Welcome to Old Movie Bot!\nSend the movie name or upload file.")

async def handle_movie_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("❌ Not authorized.")
        return

    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith((".mkv", ".mp4", ".avi", ".webm")):
        await update.message.reply_text("❌ Upload .mkv, .mp4, .avi or .webm only.")
        return

    file_id = doc.file_id
    file_name = doc.file_name
    title_raw = os.path.splitext(file_name)[0]
    movie_title, year, seas_epi = await clean_text.get_cleantext(title_raw)

    title = f"{movie_title or ''} {year or ''} {seas_epi or ''}".strip().lower()
    movies = load_movies()
    matched = False

    for movie in movies:
        if movie["title"] == title:
            if not any(f["file_id"] == file_id for f in movie["files"]):
                movie["files"].append({"file_id": file_id, "file_name": file_name})
            matched = True
            break

    if not matched:
        movies.append({
            "title": title,
            "files": [{"file_id": file_id, "file_name": file_name}]
        })

    save_movies(movies)
    await update.message.reply_text(f"✅ *{title.title()}* added", parse_mode="Markdown")
    context.user_data["pending_file_id"] = file_id
    context.user_data["pending_file_name"] = file_name

async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip().lower()
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    movies = load_movies()

    results = process.extract(query, [m["title"] for m in movies], scorer=fuzz.token_set_ratio, score_cutoff=60)
    if not results:
        await update.message.reply_text("❌ Not found.")
        return

    for match, score, idx in results:
        for file in movies[idx]["files"]:
            try:
                sent = await update.message.reply_document(document=file["file_id"], filename=file["file_name"])
                asyncio.create_task(delete_after_delay(context, sent.chat_id, sent.message_id))
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error: {e}")

async def add_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    title = update.message.text.replace("/addmovie", "").strip()
    file_id = context.user_data.get("pending_file_id")
    file_name = context.user_data.get("pending_file_name")

    if not file_id:
        await update.message.reply_text("⚠️ Upload movie first.")
        return

    movies = load_movies()
    for movie in movies:
        if movie["title"] == title:
            movie["files"].append({"file_id": file_id, "file_name": file_name})
            save_movies(movies)
            await update.message.reply_text(f"✅ Added to *{title}*", parse_mode="Markdown")
            return

    movies.append({"title": title, "files": [{"file_id": file_id, "file_name": file_name}]})
    save_movies(movies)
    context.user_data.clear()
    await update.message.reply_text(f"🎉 File added to *{title}*", parse_mode="Markdown")

# ---------- FastAPI Setup for Render Web Service ---------- #
fastapi_app = FastAPI()
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()

@fastapi_app.post(WEBHOOK_PATH)
async def process_update(request: Request):
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}

@fastapi_app.get("/")
def root():
    return {"status": "bot running"}

@fastapi_app.on_event("startup")
async def startup():
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("addmovie", add_movie))
    telegram_app.add_handler(MessageHandler(filters.Document.ALL, handle_movie_upload))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
    
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(url=f"{BASE_URL}{WEBHOOK_PATH}")

@fastapi_app.on_event("shutdown")
async def shutdown():
    await telegram_app.bot.delete_webhook()
    await telegram_app.shutdown()
    await telegram_app.stop()


