import os
import json
import subprocess
import requests
import base64
import re
from datetime import datetime
import pytz

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from google.cloud import texttospeech

# 🟡 כתיבת קובץ מפתח Google מ־BASE64
key_b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
if not key_b64:
    raise Exception("❌ משתנה GOOGLE_APPLICATION_CREDENTIALS_B64 לא מוגדר או ריק")

with open("google_key.json", "wb") as f:
    f.write(base64.b64decode(key_b64))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_key.json"

# 🛠 משתנים מ־Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:97/")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # לדוגמה: https://musika-48ua.onrender.com

# 🔢 פונקציות עזר
def clean_text(text: str):
    BLOCKED_PHRASES = [
        "חדשות המוקד • בטלגרם: t.me/hamoked_il",
        "בוואטסאפ: https://chat.whatsapp.com/LoxVwdYOKOAH2y2kaO8GQ7",
        "לעדכוני הפרגוד בטלגרם"
    ]
    for phrase in BLOCKED_PHRASES:
        text = text.replace(phrase, "")
    text = re.sub(r"[^\w\s.,!?()\u0590-\u05FF:/]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def text_to_mp3(text, filename="output.mp3"):
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="he-IL",
        name="he-IL-Wavenet-B",
        ssml_gender=texttospeech.SsmlVoiceGender.MALE,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.2,
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    with open(filename, "wb") as out:
        out.write(response.audio_content)

def convert_to_wav(input_file, output_file="output.wav"):
    subprocess.run(
        ["ffmpeg", "-i", input_file, "-ar", "8000", "-ac", "1", "-f", "wav", output_file, "-y"]
    )

def upload_to_ymot(wav_file_path):
    url = "https://call2all.co.il/ym/api/UploadFile"
    with open(wav_file_path, "rb") as f:
        files = {"file": (os.path.basename(wav_file_path), f, "audio/wav")}
        data = {
            "token": YMOT_TOKEN,
            "path": YMOT_PATH,
            "convertAudio": "1",
            "autoNumbering": "true",
        }
        response = requests.post(url, data=data, files=files)
    print("📞 תגובת ימות:", response.text)

# 📥 טיפול בהודעות מהערוץ
async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return

    text = message.text or message.caption
    if text:
        cleaned = clean_text(text)
        text_to_mp3(cleaned, "output.mp3")
        convert_to_wav("output.mp3", "output.wav")
        upload_to_ymot("output.wav")
        os.remove("output.mp3")
        os.remove("output.wav")

    if message.voice or message.audio:
        audio_file = await (message.voice or message.audio).get_file()
        await audio_file.download_to_drive("audio.ogg")
        convert_to_wav("audio.ogg", "audio.wav")
        upload_to_ymot("audio.wav")
        os.remove("audio.ogg")
        os.remove("audio.wav")

    if message.video:
        video_file = await message.video.get_file()
        await video_file.download_to_drive("video.mp4")
        convert_to_wav("video.mp4", "video.wav")
        upload_to_ymot("video.wav")
        os.remove("video.mp4")
        os.remove("video.wav")

# ▶️ הפעלת האפליקציה
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, handle_channel_post))

print("🚀 הבוט מאזין לערוץ דרך Webhook 🎧")

# 🟡 רישום Webhook
def set_webhook():
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    webhook_url = f"{WEBHOOK_URL}/webhook"
    resp = requests.get(url, params={"url": webhook_url})
    print("📡 setWebhook response:", resp.text)

set_webhook()

# ▶️ הרצה עם Webhook
app.run_webhook(
    listen="0.0.0.0",
    port=int(os.environ.get("PORT", 8080)),
    url_path="webhook",
    webhook_url=f"{WEBHOOK_URL}/webhook"
)
