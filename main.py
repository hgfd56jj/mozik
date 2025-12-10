import os
import json
import subprocess
import requests
import base64
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio
import re
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, TypeHandler, CommandHandler
from google.cloud import texttospeech
import logging

# 🔧 הגדרת לוגים
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler("log.txt"),
        logging.StreamHandler()
    ]
)

# 🔒 מנעול לעיבוד הודעות
processing_lock = asyncio.Lock()

# ---------------------------------------------------------
# ⚙️ הגדרות הערוצים
# ---------------------------------------------------------
CHANNELS_CONFIG = {
    # ערוץ A
    -1003308764465: {  
        "path": "ivr2:11/",
        "intro_suffix": "בְּמִבְזָקִים-פְּלוּס,", 
        "merge_text": True  
    },
    # ערוץ B
    -1003387160676: {
        "path": "ivr2:22/",
        "intro_suffix": "בחדשות המגזר,",
        "merge_text": True
    },
    # ערוץ C
    -1003403882019: {
        "path": "ivr2:33/",
        "intro_suffix": None, 
        "merge_text": False 
    },
    # ערוץ D
    -1003427588105: { 
        "path": "ivr2:44/",
        "intro_suffix": "בחדשות המגזר,",
        "merge_text": True
    },
    # ערוץ E
    -1003036595355: { 
        "path": "ivr2:55/",
        "intro_suffix": "בעדכוני יְשִׁיבֶזֹוכֶר,",
        "merge_text": True
    }
}

# ---------------------------------------------------------
# 🟡 הגדרת Google TTS
# ---------------------------------------------------------
key_b64 = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_B64")
if not key_b64:
    logging.warning("⚠️ משתנה GOOGLE_APPLICATION_CREDENTIALS_B64 חסר! הבוט לא יוכל להמיר טקסט לקול.")
else:
    try:
        with open("google_key.json", "wb") as f:
            f.write(base64.b64decode(key_b64))
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_key.json"
    except Exception as e:
        logging.error(f"❌ נכשל בכתיבת קובץ מפתח גוגל: {e}")

# 🛠 משתנים מ־Render
BOT_TOKEN = os.getenv("BOT_TOKEN")
YMOT_TOKEN = os.getenv("YMOT_TOKEN")

# קבצי הגדרות
BLACKLIST_FILE = "blacklist.json"
REPLACEMENTS_FILE = "replacements.json"

# ---------------------------------------------------------
# 🛡️ ניהול רשימות (Blacklist & Replacements)
# ---------------------------------------------------------
def load_json_file(filename):
    if not os.path.exists(filename):
        return {} if filename == REPLACEMENTS_FILE else []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {} if filename == REPLACEMENTS_FILE else []

def save_json_file(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# --- פקודות לרשימה שחורה ---
async def add_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("usage: /addword [word]")
        return
    word = " ".join(context.args)
    words = load_json_file(BLACKLIST_FILE)
    if word not in words:
        words.append(word)
        save_json_file(BLACKLIST_FILE, words)
        await update.message.reply_text(f"המילה '{word}' נוספה לרשימה השחורה.")
    else:
        await update.message.reply_text("המילה כבר קיימת ברשימה.")

async def del_word(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("usage: /delword [word]")
        return
    word = " ".join(context.args)
    words = load_json_file(BLACKLIST_FILE)
    if word in words:
        words.remove(word)
        save_json_file(BLACKLIST_FILE, words)
        await update.message.reply_text(f"המילה '{word}' הוסרה מהרשימה.")
    else:
        await update.message.reply_text("המילה לא נמצאה ברשימה.")

async def list_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    words = load_json_file(BLACKLIST_FILE)
    if not words:
        await update.message.reply_text("הרשימה ריקה.")
    else:
        await update.message.reply_text("מילים חסומות:\n" + ", ".join(words))

# --- פקודות להחלפת מילים ---
async def add_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # שימוש: /addreplace מקור יעד
    # דוגמה: /addreplace ר' רבי
    if len(context.args) < 2:
        await update.message.reply_text("usage: /addreplace [source] [target]")
        return
    
    source = context.args[0]
    target = " ".join(context.args[1:])
    
    replacements = load_json_file(REPLACEMENTS_FILE)
    replacements[source] = target
    save_json_file(REPLACEMENTS_FILE, replacements)
    
    await update.message.reply_text(f"הוגדרה החלפה: '{source}' -> '{target}'")

async def del_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("usage: /delreplace [source]")
        return
    
    source = context.args[0]
    replacements = load_json_file(REPLACEMENTS_FILE)
    
    if source in replacements:
        del replacements[source]
        save_json_file(REPLACEMENTS_FILE, replacements)
        await update.message.reply_text(f"ההחלפה עבור '{source}' נמחקה.")
    else:
        await update.message.reply_text(f"לא נמצאה החלפה עבור '{source}'.")

async def list_replace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    replacements = load_json_file(REPLACEMENTS_FILE)
    if not replacements:
        await update.message.reply_text("רשימת ההחלפות ריקה.")
    else:
        msg = "רשימת החלפות:\n"
        for k, v in replacements.items():
            msg += f"{k} -> {v}\n"
        await update.message.reply_text(msg)

# ---------------------------------------------------------
# 🧹 פונקציות עזר לניקוי ועיבוד
# ---------------------------------------------------------
def clean_text(text):
    if not text: return ""
    
    # 1. ביצוע החלפות מילים (לפי הקובץ החדש)
    replacements = load_json_file(REPLACEMENTS_FILE)
    # ממיינים מהארוך לקצר כדי למנוע החלפות חלקיות שגויות
    sorted_keys = sorted(replacements.keys(), key=len, reverse=True)
    
    for src in sorted_keys:
        target = replacements[src]
        # החלפה פשוטה (case sensitive פחות קריטי בעברית, אבל נשאיר ככה)
        text = text.replace(src, target)

    # 2. ניקוי לפי רשימה שחורה דינמית
    blocked_words = load_json_file(BLACKLIST_FILE)
    for word in blocked_words:
        text = text.replace(word, '')

    # 3. ניקוי קבוע של קישורים ומספרים
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    text = re.sub(r'chat\.whatsapp\.com\S*', '', text)
    text = re.sub(r'wa\.me\S*', '', text)
    text = re.sub(r't\.me\S*', '', text)
    text = re.sub(r'[a-zA-Z0-9-]+\.(com|co\.il|net|org|me)\S*', '', text)
    text = re.sub(r'@\S+', '', text)
    text = re.sub(r'\d{2,3}[-\s]?\d{3}[-\s]?\d{4}', '', text)
    text = re.sub(r'[^\w\s.,!?()\u0590-\u05FF]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def has_audio_stream(file_path):
    """בודק האם יש ערוץ שמע, והאם הוא מכיל סאונד בעוצמה מינימלית"""
    try:
        # שלב 1: בדיקה טכנית לקיום ערוץ שמע
        cmd_streams = [
            "ffprobe", 
            "-v", "error", 
            "-select_streams", "a", 
            "-show_entries", "stream=codec_name", 
            "-of", "default=noprint_wrappers=1:nokey=1", 
            file_path
        ]
        result = subprocess.run(cmd_streams, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if not result.stdout.strip():
            logging.info("🔇 FFprobe: לא נמצא ערוץ שמע (Stream) בקובץ.")
            return False

        # שלב 2: בדיקת עוצמת שמע (Volume Detection)
        cmd_vol = [
            "ffmpeg",
            "-t", "20", 
            "-i", file_path,
            "-af", "volumedetect",
            "-vn", "-sn", "-dn", 
            "-f", "null", 
            "/dev/null"
        ]
        
        result_vol = subprocess.run(cmd_vol, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output = result_vol.stderr
        
        match = re.search(r"max_volume: ([\-\d\.]+) dB", output)
        if match:
            max_vol = float(match.group(1))
            logging.info(f"🔊 עוצמת שמע מקסימלית זוהתה: {max_vol} dB")
            
            if max_vol < -50.0:
                logging.info("🔇 עוצמת השמע נמוכה מדי (שקט), מדלג.")
                return False
            return True
        else:
            logging.warning("⚠️ לא הצלחתי לזהות עוצמת שמע, מניח שיש שמע.")
            return True 
            
    except Exception as e:
        logging.error(f"❌ שגיאה בבדיקת שמע: {e}")
        return False

# 🔢 המרת מספרים לעברית
def num_to_hebrew_words(hour, minute):
    hours_map = {
        1: "אחת", 2: "שתיים", 3: "שלוש", 4: "ארבע", 5: "חמש", 6: "שש",
        7: "שֶׁבַע", 8: "שמונה", 9: "תֵּשַׁע", 10: "עשר", 11: "אחת עשרה", 12: "שתים עשרה", 0: "שתים עשרה"
    }
    minutes_map = {
        0: "אפס", 1: "ודקה", 2: "ושתי דקות", 3: "ושלוש דקות", 4: "וארבע דקות",
        5: "וחמשה", 6: "ושש דקות", 7: "ושבע דקות", 8: "ושמונה דקות",
        9: "ותשע דקות", 10: "וַעֲשָׂרָה", 11: "ואחת עשרה דקות", 12: "ושתים עשרה דקות",
        13: "ושלוש עשרה דקות", 14: "וארבע עשרה דקות", 15: "ורבע", 
        16: "ושש עשרה דקות", 17: "ושבע עשרה דקות", 18: "ושמונה עשרה דקות", 19: "ותשע עשרה דקות",
        20: "ועשרים", 21: "עשרים ואחת", 22: "עשרים ושתיים", 23: "עשרים ושלוש",
        24: "עשרים וארבע", 25: "עשרים וחמש", 26: "עשרים ושש", 27: "עשרים ושבע",
        28: "עשרים ושמונה", 29: "עשרים ותשע", 30: "וחצי", 
        31: "שלושים ואחת", 32: "שלושים ושתיים", 33: "שלושים ושלוש", 34: "שלושים וארבע",
        35: "שלושים וחמש", 36: "שלושים ושש", 37: "שלושים ושבע", 38: "שלושים ושמונה", 39: "שלושים ותשע",
        40: "וארבעים דקות", 41: "ארבעים ואחת", 42: "ארבעים ושתיים", 43: "ארבעים ושלוש",
        44: "ארבעים וארבע", 45: "ארבעים וחמש", 46: "ארבעים ושש", 47: "ארבעים ושבע",
        48: "ארבעים ושמונה", 49: "ארבעים ותשע", 50: "וחמישים דקות", 
        51: "חמישים ואחת", 52: "חמישים ושתיים", 53: "חמישים ושלוש", 54: "חמישים וארבע",
        55: "חמישים וחמש", 56: "חמישים ושש", 57: "חמישים ושבע", 58: "חמישים ושמונה", 59: "חמישים ותשע"
    }
    
    hour_12 = hour % 12 or 12
    min_text = minutes_map.get(minute, f"ו{minute} דקות")
    
    if minute == 0:
        return f"השעה {hours_map[hour_12]} בדיוק"
        
    return f"{hours_map[hour_12]} {min_text}"

# 🎤 יצירת MP3
def text_to_mp3(text, filename='output.mp3'):
    if not text: return False
    try:
        client = texttospeech.TextToSpeechClient()
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(language_code="he-IL", name="he-IL-Wavenet-B", ssml_gender=texttospeech.SsmlVoiceGender.MALE)
        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3, speaking_rate=1.2)
        response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)
        with open(filename, "wb") as out:
            out.write(response.audio_content)
        return True
    except Exception as e:
        logging.error(f"שגיאה ביצירת TTS: {e}")
        return False

# 🎧 המרה ל־WAV
def convert_to_wav(input_file, output_file='output.wav'):
    subprocess.run(['ffmpeg', '-i', input_file, '-ar', '8000', '-ac', '1', '-f', 'wav', output_file, '-y'], stderr=subprocess.DEVNULL)

# 🔗 חיבור קבצים
def concat_wav_files(file_list, output_file="merged.wav"):
    valid_files = [f for f in file_list if os.path.exists(f)]
    if not valid_files:
        return False
    
    list_filename = "list.txt"
    with open(list_filename, "w", encoding="utf-8") as f:
        for file_path in valid_files:
            f.write(f"file '{file_path}'\n")
    
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_filename, "-c", "copy", output_file
    ], stderr=subprocess.DEVNULL)
    
    os.remove(list_filename)
    return True

# 📤 העלאה לימות
def upload_to_ymot(wav_file_path, target_path):
    url = 'https://call2all.co.il/ym/api/UploadFile'
    try:
        with open(wav_file_path, 'rb') as f:
            files = {'file': (os.path.basename(wav_file_path), f, 'audio/wav')}
            data = {'token': YMOT_TOKEN, 'path': target_path, 'convertAudio': '1', 'autoNumbering': 'true'}
            response = requests.post(url, data=data, files=files)
            logging.info(f"📞 הועלה ל-{target_path}: {response.text}")
    except Exception as e:
        logging.error(f"❌ שגיאה בהעלאה לימות: {e}")

# 📥 טיפול בהודעה
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    async with processing_lock:
        message = update.message or update.channel_post
        if not message: return

        chat_id = message.chat.id
        logging.info(f"📢 התקבלה הודעה מערוץ: {chat_id}")

        if chat_id not in CHANNELS_CONFIG:
            logging.info(f"⚠️ ערוץ {chat_id} לא מוגדר בקונפיגורציה. מתעלם.")
            return

        config = CHANNELS_CONFIG[chat_id]
        target_path = config["path"]
        intro_suffix = config["intro_suffix"]
        should_merge = config["merge_text"]

        text_content = message.text or message.caption or ""
        text_content = clean_text(text_content)

        video_file_path = None
        audio_file_path = None
        
        # 1. עיבוד מדיה (וידאו/אודיו)
        if message.video or message.animation: 
            media_obj = message.video or message.animation
            is_animation = message.animation is not None
            
            video_file = await media_obj.get_file()
            video_file_path = "temp_video.mp4"
            await video_file.download_to_drive(video_file_path)
            
            # בדיקת שמע משודרגת
            has_audio = has_audio_stream(video_file_path)
            
            if is_animation:
                 logging.info("🔇 זוהה קובץ אנימציה (GIF). נחשב כחסר שמע.")
                 has_audio = False 

            if not has_audio:
                logging.info("🔇 וידאו ללא שמע זוהה. מדלג על ההעלאה.")
                if os.path.exists(video_file_path):
                    os.remove(video_file_path)
                return 
            
            convert_to_wav(video_file_path, "media_raw.wav")
            audio_file_path = "media_raw.wav"
            if os.path.exists(video_file_path):
                os.remove(video_file_path)

        elif message.audio or message.voice:
            audio_obj = await (message.audio or message.voice).get_file()
            orig_path = "temp_audio.ogg"
            await audio_obj.download_to_drive(orig_path)
            convert_to_wav(orig_path, "media_raw.wav")
            audio_file_path = "media_raw.wav"
            if os.path.exists(orig_path):
                os.remove(orig_path)

        # 2. הכנת טקסטים (פתיח + גוף)
        files_to_merge = []
        
        need_intro = False
        if text_content: 
            need_intro = True 
        
        full_intro_text = ""
        if intro_suffix and need_intro:
            tz = ZoneInfo('Asia/Jerusalem')
            now = datetime.now(tz)
            hebrew_time_str = num_to_hebrew_words(now.hour, now.minute)
            full_intro_text = f"{hebrew_time_str} {intro_suffix}"

        text_wav_path = None

        # --- חיבור הטקסטים לפני המרה לקול ---
        if should_merge and full_intro_text and text_content:
            combined_text = f"{full_intro_text} {text_content}"
            if text_to_mp3(combined_text, "combined.mp3"):
                convert_to_wav("combined.mp3", "combined.wav")
                text_wav_path = "combined.wav"
        
        else:
            if full_intro_text:
                if text_to_mp3(full_intro_text, "intro.mp3"):
                    convert_to_wav("intro.mp3", "intro.wav")
                    files_to_merge.append("intro.wav")
            
            if text_content:
                if text_to_mp3(text_content, "body.mp3"):
                    convert_to_wav("body.mp3", "body.wav")
                    text_wav_path = "body.wav"

        # 3. העלאה
        if should_merge:
            if text_wav_path:
                files_to_merge.append(text_wav_path)
            if audio_file_path:
                files_to_merge.append(audio_file_path)
            
            if files_to_merge:
                concat_wav_files(files_to_merge, "final_upload.wav")
                upload_to_ymot("final_upload.wav", target_path)
        
        else:
            if audio_file_path:
                upload_to_ymot(audio_file_path, target_path)
            
            text_files_for_upload = []
            if "intro.wav" in files_to_merge: text_files_for_upload.append("intro.wav")
            if text_wav_path: text_files_for_upload.append(text_wav_path)
            
            if text_files_for_upload:
                concat_wav_files(text_files_for_upload, "text_upload.wav")
                upload_to_ymot("text_upload.wav", target_path)

        # 🧹 ניקוי
        for f in ["intro.mp3", "intro.wav", "body.mp3", "body.wav", "combined.mp3", "combined.wav",
                  "media_raw.wav", "final_upload.wav", "text_upload.wav", "temp_video.mp4", "temp_audio.ogg"]:
            if os.path.exists(f):
                try: os.remove(f)
                except: pass

# ---------------------------------------------------------
# 🚀 הפעלה
# ---------------------------------------------------------
from keep_alive import keep_alive
keep_alive()

if __name__ == '__main__':
    if not BOT_TOKEN:
        logging.error("❌ BOT_TOKEN חסר!")
        exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("addword", add_word))
    app.add_handler(CommandHandler("delword", del_word))
    app.add_handler(CommandHandler("listwords", list_words))
    
    # פקודות להחלפת מילים
    app.add_handler(CommandHandler("addreplace", add_replace))
    app.add_handler(CommandHandler("delreplace", del_replace))
    app.add_handler(CommandHandler("listreplace", list_replace))
    
    app.add_handler(TypeHandler(Update, handle_message))
    
    logging.info("🚀 הבוט התחיל לרוץ...")
    app.run_polling()
