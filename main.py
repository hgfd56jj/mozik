import os
import subprocess
import requests
import asyncio
import re
import time
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# 🛠 הגדרת מפתח Gemini
# וודא שהגדרת את GEMINI_API_KEY במשתני הסביבה ב-Render
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("⚠️ אזהרה: GEMINI_API_KEY לא מוגדר. הבוט ייכשל בניסיון הקראה.")
else:
    genai.configure(api_key=GEMINI_API_KEY)

# 🛠 משתנים מ־Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")
YMOT_PATH = os.getenv("YMOT_PATH", "ivr2:/97")

def clean_text(text):
    """מנקה את הטקסט ממילים חסומות, קישורים וסימנים מיותרים"""
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
        "לשליחת חומרים",
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
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)

    # ❌ TTS יקרא רק עברית/ספרות/סימני פיסוק בסיסיים
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF:/]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text

def generate_audio_with_gemini(text, filename='output.pcm'):
    """
    שולח טקסט למודל Gemini TTS ומקבל קובץ PCM גולמי.
    *בוצע עדכון לבקש קצב קריאה מהיר (1.3) וטון דרמטי*
    """
    print(f"🎙️ שולח ל-Gemini TTS: {text[:30]}...")
    try:
        # שימוש במודל ה-TTS החדש
        model = genai.GenerativeModel("models/gemini-2.5-flash-preview-tts")
        
        # בניית הבקשה להקראה: שימוש בטקסט-לפרומפט (TTP) לבקשת מהירות
        prompt = (
            f"Please read the following news update in Hebrew clearly, dramatically, "
            f"and with a fast pace (like a 1.3 speed): {text}"
        )

        response = model.generate_content(
            prompt,
            generation_config={
                "response_modalities": ["AUDIO"],
                "speech_config": {
                    "voice_config": {
                        "prebuilt_voice_config": {
                            # הקול המבוקש
                            "voice_name": "Fenrir" 
                        }
                    }
                }
            }
        )

        # המודל מחזיר Raw PCM (L16) - שומרים לקובץ בינארי
        if response.candidates and response.candidates[0].content.parts:
            audio_data = response.candidates[0].content.parts[0].inline_data.data
            with open(filename, 'wb') as f:
                f.write(audio_data)
            print("✅ אודיו נוצר בהצלחה (PCM format) עם קול Fenrir וקצב מוגבר.")
        else:
            print("❌ לא התקבל מידע אודיו בתשובה.")
            raise Exception("Empty audio response from Gemini")

    except Exception as e:
        print(f"❌ שגיאה ביצירת אודיו עם Gemini: {e}")
        raise e

def convert_pcm_to_wav(input_file, output_file='output.wav'):
    """
    ממיר PCM גולמי (24kHz, 1 channel, s16le - ברירת המחדל של Gemini)
    לפורמט WAV שימות המשיח יודעים לקרוא (8kHz)
    """
    subprocess.run([
        'ffmpeg',
        '-f', 's16le',       # פורמט הקלט (Raw PCM Signed 16-bit Little Endian)
        '-ar', '24000',      # קצב דגימה של המודל (בד"כ 24k במודלים אלו)
        '-ac', '1',          # ערוץ אחד (מונו)
        '-i', input_file,    # קובץ הקלט
        '-ar', '8000',       # יעד: 8000Hz לימות המשיח
        '-ac', '1',          # יעד: מונו
        '-f', 'wav',         # יעד: פורמט WAV
        output_file, '-y'
    ])

def convert_regular_to_wav(input_file, output_file='output.wav'):
    """המרה רגילה לקבצי אודיו/וידאו שנשלחו (לא TTS)"""
    subprocess.run([
        'ffmpeg', '-i', input_file, '-ar', '8000', '-ac', '1', '-f', 'wav',
        output_file, '-y'
    ])

def upload_to_ymot(wav_file_path):
    url = 'https://call2all.co.il/ym/api/UploadFile'
    if not os.path.exists(wav_file_path):
        print("❌ הקובץ להעלאה לא נמצא:", wav_file_path)
        return

    with open(wav_file_path, 'rb') as f:
        files = {'file': (os.path.basename(wav_file_path), f, 'audio/wav')}
        data = {
            'token': YMOT_TOKEN,
            'path': YMOT_PATH,
            'convertAudio': '1',
            'autoNumbering': 'true'
        }
        try:
            response = requests.post(url, data=data, files=files)
            print("📞 תגובת ימות:", response.text)
        except Exception as e:
            print(f"❌ שגיאה בהעלאה לימות: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.channel_post
    if not message:
        return

    text = message.text or message.caption
    has_video = message.video is not None
    has_audio = message.voice or message.audio

    # טיפול בוידאו
    if has_video:
        try:
            video_file = await message.video.get_file()
            await video_file.download_to_drive("video.mp4")
            convert_regular_to_wav("video.mp4", "video.wav")
            upload_to_ymot("video.wav")
        except Exception as e:
            print(f"Error handling video: {e}")
        finally:
            if os.path.exists("video.mp4"): os.remove("video.mp4")
            if os.path.exists("video.wav"): os.remove("video.wav")

    # טיפול באודיו קיים
    if has_audio:
        try:
            audio_obj = message.voice or message.audio
            audio_file = await audio_obj.get_file()
            # מזהים סיומת
            ext = "ogg" if message.voice else "mp3"
            filename = f"audio.{ext}"
            
            await audio_file.download_to_drive(filename)
            convert_regular_to_wav(filename, "audio.wav")
            upload_to_ymot("audio.wav")
        except Exception as e:
            print(f"Error handling audio: {e}")
        finally:
            if os.path.exists(filename): os.remove(filename)
            if os.path.exists("audio.wav"): os.remove("audio.wav")

    # טיפול בטקסט -> המרה לדיבור (Gemini TTS)
    if text:
        cleaned_text = clean_text(text)
        # ניקוי נוסף עבור ה-TTS (השארת אותיות ומספרים בלבד)
        cleaned_for_tts = re.sub(r'[^0-9א-ת\s.,!?()\u0590-\u05FF]', '', cleaned_text)
        cleaned_for_tts = re.sub(r'\s+', ' ', cleaned_for_tts).strip()

        # הסרת מספרי טלפון (כפי שהיה בקוד המקורי)
        phone_number_regex = r'\b(\d[\s-]?){9,11}\d\b'
        cleaned_for_tts = re.sub(phone_number_regex, '', cleaned_for_tts)
        cleaned_for_tts = re.sub(r'\s+', ' ', cleaned_for_tts).strip()

        if cleaned_for_tts:
            try:
                # 1. יצירת אודיו עם Gemini (מקבלים PCM)
                generate_audio_with_gemini(cleaned_for_tts, "output.pcm")
                
                # 2. המרה מ-PCM ל-WAV של ימות
                convert_pcm_to_wav("output.pcm", "output.wav")
                
                # 3. העלאה
                upload_to_ymot("output.wav")
            except Exception as e:
                print(f"❌ כשל בתהליך ה-TTS: {e}")
            finally:
                if os.path.exists("output.pcm"): os.remove("output.pcm")
                if os.path.exists("output.wav"): os.remove("output.wav")

# שרת חי (Keep Alive) עבור Render
try:
    from keep_alive import keep_alive
    keep_alive()
except ImportError:
    pass

if not BOT_TOKEN:
    print("❌ שגיאה: BOT_TOKEN חסר.")
else:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_message))

    print("🚀 הבוט (Gemini TTS) מאזין לערוץ ומעלה לשלוחה 🎧")
    
    while True:
        try:
            app.run_polling(poll_interval=9.0, timeout=30, allowed_updates=Update.ALL_TYPES)
        except Exception as e:
            print("❌ שגיאה כללית:", e)
            time.sleep(20)
