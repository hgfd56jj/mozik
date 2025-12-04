from flask import Flask
from threading import Thread

app = Flask('')

# --- החלק הקיים (לא שונה) ---
@app.route('/')
def home():
    return "הבוט חי!"

# --- החלק החדש עבור ימות המשיח ---
@app.route('/wakeup')
def wakeup_from_yemot():
    # מחזיר פקודה למערכת להקריא טקסט, כדי שלא תשמיע שגיאה
    return "id_list_message=t-השרת פעיל והקוד עובד"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()
