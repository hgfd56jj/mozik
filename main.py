import os
import json
import subprocess
import requests
import base64
from datetime import datetime
import pytz
import re

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google.cloud import texttospeech

# 🟡 כתיבת קובץ מפתח Google מ־BASE64
key_b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
if not key_b64:
    raise Exception("❌ משתנה GOOGLE_APPLICATION_CREDENTIALS_B64 לא מוגדר או ריק")

with open("google_key.json", "wb") as f:
    f.write(base64.b64decode(key_b64))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_key.json"

# 🛠 משתני סביבה
BOT_TOKEN = os.getenv("BOT_TOKEN")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:97/")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # למשל: https://musika-48ua.onrender.com

# 🧹 ניקוי טקסט בסיסי
def clean_text(text):
    text = re.sub(r'[^\u0590-\u05FF\s.,!?()\-\d]', '', text)  # רק עברית, מספרים וסימני פיסוק
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# 🗣️ טקסט → MP3
def text_to_mp3(text, filename='output.mp3'):
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="he-IL",
        name="he-IL-Wavenet-B",
        ssml_gender=texttospeech.SsmlVoiceGender.MALE
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.2
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    with open(filename, "wb") as out:
        out.write(response.audio_content)

# 🎵 המרה ל־WAV
def convert_to_wav(input_file, output_file='output.wav'):
    subprocess.run([
        'ffmpeg', '-i', input_file, '-ar', '8000', '-ac', '1', '-f', 'wav',
        output_file, '-y'
    ])

# 📤 העלאה לימות
def upload_to_ymot(wav_file_path):
    url = 'https://call2all.co.il/ym/api/UploadFile'
    with open(wav_file_path, 'rb') as f:
        files = {'file': (os.path.basename(wav_file_path), f, 'audio/wav')}
        data = {
            'token': YMOT_TOKEN,
            'path': YMOT_PATH,
            'convertAudio': '1',
            'autoNumbering': 'true'
        }
        response = requests.post(url, data=data, files=files)
    print("📞 תגובת ימות:", response.text)

# 📨 טיפול בהודעות חדשות
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message or update.channel_post
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

# ♻️ keep alive (כמו שהיה לך)
from keep_alive import keep_alive
keep_alive()

# ▶️ יצירת אפליקציה
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_message))

print("🚀 הבוט מאזין בערוץ דרך Webhook 🎧")

# ▶️ הפעלה ב־Webhook
app.run_webhook(
    listen="0.0.0.0",
    port=int(os.environ.get("PORT", 8080)),
    url_path=BOT_TOKEN,  # הנתיב שבו טלגרם ישלח
    webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"  # הכתובת המלאה שטלגרם ישתמש בה
)
