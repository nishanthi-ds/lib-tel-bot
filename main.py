import os
import json
import difflib
import re
import asyncio
from guessit  import guessit
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from rapidfuzz import fuzz, process
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)
import clean_text
import keep_alive

# Load environment variables
load_dotenv(dotenv_path=".env")
BOT_TOKEN = os.getenv("OLD_MOVIES_BOT_TOKEN")
user_ids_str = os.getenv("ALLOWED_USER_IDS", "")

ALLOWED_USER_IDS = {int(uid.strip()) for uid in user_ids_str.split(",") if uid.strip().isdigit()}
MOVIE_DB_FILE = "movies.json"
USER_LOG_FILE = "user_logs.json"

# ------------------ JSON Utility ------------------ #
def load_movies():
    if not os.path.exists(MOVIE_DB_FILE):
        with open(MOVIE_DB_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    with open(MOVIE_DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_movies(data):
    with open(MOVIE_DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ------------------ Helper Utilities ------------------ #
def clean_title_text(raw_title):
    title_cleaned = re.sub(r"@[\w\d_]+[\s\-]*", "", raw_title)
    title_cleaned = re.sub(r"\s+", " ", title_cleaned)
    title_cleaned = title_cleaned.replace(".", " ").strip()
    return title_cleaned.lower()

def log_user_activity(user_id, username, query, matched_movies):
    log = {
        "user_id": user_id,
        "username": username or "Unknown",
        "query": query,
        "matched_movie": matched_movies,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    logs = []
    if os.path.exists(USER_LOG_FILE):
        with open(USER_LOG_FILE, "r", encoding="utf-8") as f:
            try:
                logs = json.load(f)
            except json.JSONDecodeError:
                logs = []
    logs.append(log)
    with open(USER_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)

async def delete_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    await asyncio.sleep(1800)  # 30 mins
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print("⚠️ Failed to delete message:", e)

# ------------------ Handlers ------------------ #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruction = (
"👋 Welcome to Old Movie Tamil Bot!\n\n"
        "To search, type your movie like:\n"
        "• Leo \n"
        "• Leo 2023\n"
        "• Money Heist S01E03\n"
    )
    await update.message.reply_text(instruction)

async def handle_movie_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("❌ You are not authorized to upload files.")
        return

    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith((".mkv", ".mp4", ".avi", ".webm")):
        await update.message.reply_text("❌ Invalid file. Only .mkv, .mp4, .avi, or .webm allowed.")
        return

    file_id = doc.file_id
    file_name = doc.file_name
    title_raw = os.path.splitext(file_name)[0]
    
    movie_title, year, seas_epi  = await clean_text.get_cleantext(title_raw)

    title=''
    if movie_title is not None: title += movie_title 
    if year is not None: title = title + " " + str(year )
    if seas_epi is not None: title = title + " " + seas_epi

    title= title.lower()
    
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
    await update.message.reply_text(f" *{title.title()}*  added successfully!", parse_mode="Markdown")

    context.user_data["pending_file_id"] = file_id
    context.user_data["pending_file_name"] = file_name

async def add_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/addmovie", "").strip()
    if "|" not in text:
        await update.message.reply_text("❌ Use format:\n`/addmovie Title ", parse_mode="Markdown")
        return

    title = text
    file_id = context.user_data.get("pending_file_id")
    file_name = context.user_data.get("pending_file_name")

    if not file_id:
        await update.message.reply_text("⚠️ Please upload a movie file first.")
        return

    movies = load_movies()
    matched = False

    for movie in movies:
        if movie["title"] == title:
            movie["files"].append({"file_id": file_id, "file_name": file_name})
            matched = True
            break

    if not matched:
        movies.append({
            "title": title,
            "files": [{"file_id": file_id, "file_name": file_name}]
        })

    save_movies(movies)
    context.user_data.clear()
    await update.message.reply_text(f" *{title.title()}* File added", parse_mode="Markdown")

def find_similar_titles(query, movies, threshold=60):
            query = query.lower().strip()
            choices = [movie["title"] for movie in movies]
            
            matches = process.extract(query, choices, scorer=fuzz.token_set_ratio, score_cutoff=threshold)
            
            return matches  # List of (title, score, index)

def convert_season_episode(text):
    """
    Converts 'season 1 episode 2' in text to 'S01E02' and returns the modified text.
    """
    pattern = re.compile(r"(season\s*(\d+)\s*episode\s*(\d+))", re.IGNORECASE)
    match = pattern.search(text)
    if match:
        season = int(match.group(2))
        episode = int(match.group(3))
        formatted = f"S{season:02d}E{episode:02d}"
        # Replace the matched string with formatted season-episode code
        text = pattern.sub(formatted, text)

    return text


async def search_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # process user query and get user id
    query = update.message.text.strip().lower()
    query = convert_season_episode(query)  # # Convert query to season-episode code if possible for valid search

    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"

    movies = load_movies()
    results = []
    matches = find_similar_titles(query, movies)
    for title, score, index in matches:
        results.append(movies[index])

    if not results:
        log_user_activity(user_id, username, query, "NOT FOUND")
        await update.message.reply_text("❌ Movie not found.")
        return

    # Send matching documents
    for movie in results:
        for file in movie["files"]:
            try:
                sent = await update.message.reply_document(
                    document=file["file_id"],
                    filename=file["file_name"]
                )
                asyncio.create_task(delete_after_delay(context, sent.chat_id, sent.message_id))
            except Exception as e:
                await update.message.reply_text(f"⚠️ Error: {e}")
                

async def delete_movie_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ALLOWED_USER_IDS:
        await update.message.reply_text("❌ You are not authorized to delete files.")
        return

    text = update.message.text.replace("/delete", "").strip().lower()
    if not text:
        await update.message.reply_text("⚠️ Usage: `/delete movie title or filename`", parse_mode="Markdown")
        return

    movies = load_movies()
    deleted = False

    # Step 1: Try exact or fuzzy match on title using find_similar_titles
    similar_movies = find_similar_titles(text, movies, threshold=70)  # You can lower threshold if needed

    for _, _, idx in similar_movies:
        movie = movies[idx]
        original_files = list(movie["files"])

        movie["files"] = [
            f for f in movie["files"]
            if text not in f["file_name"].lower() and text not in movie["title"].lower()
        ]

        if len(movie["files"]) < len(original_files):
            deleted = True

        if not movie["files"]:
            movies.remove(movie)


    # Step 2: If not deleted by title, check inside file names across all movies
    if not deleted:
        for movie in movies[:]:
            original_files = list(movie["files"])
            movie["files"] = [
                f for f in movie["files"]
                if fuzz.token_set_ratio(text, f["file_name"].lower()) < 70
            ]
            if len(movie["files"]) < len(original_files):
                deleted = True
                if not movie["files"]:
                    movies.remove(movie)

    if deleted:
        save_movies(movies)
        await update.message.reply_text(f"✅ Deleted file(s) matching: `{text}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ No matching movie file found.")



# ------------------ Run App ------------------ #
async def run_bot():
    keep_alive.keep_alive()  # Keeps Replit alive

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addmovie", add_movie))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_movie_upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_movie))
    app.add_handler(CommandHandler("delete", delete_movie_file))


    print("Bot is live...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await asyncio.Event().wait()  # Keeps the bot alive

if __name__ == "__main__":
    asyncio.run(run_bot())


# Delete File - /delete


# activate venv_moviebot\
# python bot.py


