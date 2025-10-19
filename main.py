import os
import json
import subprocess
import requests
import base64
from datetime import datetime
import pytz
import asyncio
import re
import time

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from google.cloud import texttospeech

# 🟡 כתיבת קובץ מפתח Google מ־BASE64
key_b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
if not key_b64:
    raise Exception("❌ משתנה GOOGLE_APPLICATION_CREDENTIALS_B64 לא מוגדר או ריק")

try:
    with open("google_key.json", "wb") as f:
        f.write(base64.b64decode(key_b64))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_key.json"
except Exception as e:
    raise Exception("❌ נכשל בכתיבת קובץ JSON מ־BASE64: " + str(e))

# 🛠 משתנים מ־Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:/97")


def clean_text(text):
    import re

    BLOCKED_PHRASES = sorted([
        "חדשות המוקד • בטלגרם: t.me/hamoked_il",
        "בוואטסאפ: https://chat.whatsapp.com/LoxVwdYOKOAH2y2kaO8GQ7",
        "לעדכוני הפרגוד בטלגרם",
        "כל העדכונים בקבוצה",
        "https://chat.whatsapp.com/HRLme3RLzJX0WlaT1Fx9ol",
        "לשליחת חומר",
        "בוואצפ: 0526356326",
        "במייל",
        "r0527120704@gmail.com",
        "t.me/hamoked_il",
        "מיוזיק >>>> מה שמעניין",
        "הכי חם ברשת - ’הערינג’",
        "וואטצפ",
        "טלגרם",
        "מיוזיק",
        "מיוזיק 🎶🎧 >>",
        "בטלגרם",
        "כל העדכונים בקבוצה",
        "לשליחת חומר:",
        "בוואצפ: 0526356326",
        "במייל: r0527120704@gmail.com",
        "שמרו לעצמכם",
        "לצפייה ביוטיוב",
        "לצפיה",
        "ביוטיוב",
        "t.me/music_ms2",
        "https://chat.whatsapp.com/CD7EpONUdKm7z7rAhfa6ZV",
        "http://t.me/music_ms2",
        "בטלגרם",
        "חדשות המוקד",
        "שש",
        "לכל העדכונים, ולכתבות נוספות הצטרפו לערוץ דרך הקישור",
        "לכל העדכונים",
        "להצטרפות מלאה לקבוצה לחצו על הצטרף",
    ], key=len, reverse=True)

    for phrase in BLOCKED_PHRASES:
        text = text.replace(phrase, '')

    # ❌ הסרת קישורים
    text = re.sub(r'http\S+', '', text)   # מוחק http:// ו־https://
    text = re.sub(r'www\.\S+', '', text)  # מוחק www.

    # ❌ שמירת הודעה, אבל TTS יקרא רק עברית/ספרות/סימני פיסוק בסיסיים
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF:/]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text

# ✅ שינוי: החזרת טקסט נקי בלבד ללא שעה וכותרת
def create_full_text(text):
    return text

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
        speaking_rate=1.2  # 🔹 מהירות הקראה מוגברת
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    with open(filename, "wb") as out:
        out.write(response.audio_content)

def convert_to_wav(input_file, output_file='output.wav'):
    subprocess.run([
        'ffmpeg', '-i', input_file, '-ar', '8000', '-ac', '1', '-f', 'wav',
        output_file, '-y'
    ])

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return

    text = message.text or message.caption
    has_video = message.video is not None
    has_audio = message.voice or message.audio  # ✅ תוספת: גם אודיו

    if has_video:
        video_file = await message.video.get_file()
        await video_file.download_to_drive("video.mp4")
        convert_to_wav("video.mp4", "video.wav")
        upload_to_ymot("video.wav")
        os.remove("video.mp4")
        os.remove("video.wav")

    if has_audio:
        audio_file = await (message.voice or message.audio).get_file()
        await audio_file.download_to_drive("audio.ogg")
        convert_to_wav("audio.ogg", "audio.wav")
        upload_to_ymot("audio.wav")
        os.remove("audio.ogg")
        os.remove("audio.wav")

    if text:   # ✅ עכשיו הבדיקה בתוך הפונקציה
        cleaned_text = clean_text(text)
        cleaned_for_tts = re.sub(r'[^0-9א-ת\s.,!?()\u0590-\u05FF]', '', cleaned_text)
        cleaned_for_tts = re.sub(r'\s+', ' ', cleaned_for_tts).strip()

        if cleaned_for_tts:
            full_text = create_full_text(cleaned_for_tts)
            text_to_mp3(full_text, "output.mp3")
            convert_to_wav("output.mp3", "output.wav")
            upload_to_ymot("output.wav")
            os.remove("output.mp3")
            os.remove("output.wav")

from keep_alive import keep_alive
keep_alive()

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_message))

print("🚀 הבוט מאזין לערוץ ומעלה לשלוחה 🎧")

# ▶️ לולאת הרצה אינסופית
while True:
    try:
        app.run_polling(
            poll_interval=9.0,   # כל כמה שניות לבדוק הודעות חדשות
            timeout=30,          # כמה זמן לחכות לפני שנזרקת שגיאת TimedOut
            allowed_updates=Update.ALL_TYPES  # לוודא שכל סוגי ההודעות נתפסים
        )
    except Exception as e:
        print("❌ שגיאה כללית בהרצת הבוט:", e)
        time.sleep(20)  # לחכות 5 שניות ואז להפעיל מחדש את הבוט
