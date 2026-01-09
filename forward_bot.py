import telebot
import logging
import json
import os
import sqlite3
import time
from datetime import datetime
from telebot import types
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- Bot Configuration ---
TOKEN = "8417577678:AAH6RXAvwsaEuhKSCq6AsC83tG5QBtd0aJk"
ADMIN_ID = 6762465157
SOURCE_CHANNEL = "@TOSHKENTANGRENTAKSI"
DESTINATION_CHANNEL = "@Uski_kur"

# --- Bot Initialization ---
bot = telebot.TeleBot(TOKEN)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database File
DB_FILE = "user_data.db"

# --- Database Logic ---
def init_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        phone TEXT,
        first_seen TIMESTAMP,
        last_seen TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_msg_id INTEGER,
        user_id INTEGER,
        content_type TEXT,
        timestamp TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

def update_user_info(user, phone=None):
    if not user: return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user.id,))
    if cursor.fetchone():
        cursor.execute('''
        UPDATE users SET username=?, first_name=?, last_name=?, phone=COALESCE(?, phone), last_seen=?
        WHERE user_id=?''', (user.username, user.first_name, user.last_name, phone, now, user.id))
    else:
        cursor.execute('''
        INSERT INTO users (user_id, username, first_name, last_name, phone, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)''', (user.id, user.username, user.first_name, user.last_name, phone, now, now))
    conn.commit()
    conn.close()

def get_user_phone(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT phone FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

# --- Helper Functions ---
def format_info(user, phone=None):
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Noma'lum"
    info = f"👤 <b>Foydalanuvchi:</b> {name}\n"
    if user.username: info += f"🔗 <b>Username:</b> @{user.username}\n"
    if phone: info += f"📞 <b>Telefon:</b> {phone}\n"
    info += f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
    info += "─" * 15 + "\n"
    return info

# --- Stealth Forwarding Logic ---
def process_forward(message):
    try:
        # Check if message is from source
        chat_username = f"@{message.chat.username}" if message.chat.username else str(message.chat.id)
        if chat_username.lower() != SOURCE_CHANNEL.lower():
            return

        # Update user info if it's a message from a person (not always available in channel posts)
        user = message.from_user
        phone = None
        if user:
            update_user_info(user)
            phone = get_user_phone(user.id)

        info_text = format_info(user, phone) if user else f"📢 <b>Kanal:</b> {SOURCE_CHANNEL}\n" + "─" * 15 + "\n"
        
        if message.content_type == 'text':
            bot.send_message(DESTINATION_CHANNEL, info_text + message.text, parse_mode='HTML')
        elif message.content_type == 'photo':
            bot.send_photo(DESTINATION_CHANNEL, message.photo[-1].file_id, caption=info_text + (message.caption or ""), parse_mode='HTML')
        elif message.content_type == 'video':
            bot.send_video(DESTINATION_CHANNEL, message.video.file_id, caption=info_text + (message.caption or ""), parse_mode='HTML')
        elif message.content_type == 'voice':
            bot.send_voice(DESTINATION_CHANNEL, message.voice.file_id, caption=info_text)
        elif message.content_type == 'audio':
            bot.send_audio(DESTINATION_CHANNEL, message.audio.file_id, caption=info_text + (message.caption or ""), parse_mode='HTML')
        elif message.content_type == 'document':
            bot.send_document(DESTINATION_CHANNEL, message.document.file_id, caption=info_text + (message.caption or ""), parse_mode='HTML')
        else:
            bot.send_message(DESTINATION_CHANNEL, info_text + f"📎 <b>Turi:</b> {message.content_type}")
            
        logger.info(f"Yashirin forward bajarildi: {chat_username}")
    except Exception as e:
        logger.error(f"Forward xatosi: {e}")

# --- Handlers ---
@bot.message_handler(commands=['start'])
def start(message):
    update_user_info(message.from_user)
    bot.reply_to(message, "🤖 <b>Xabar Ko'chiruvchi Bot Ishchi Holatda!</b>\n\nBu bot xabarlarni yashirincha nusxalaydi.", parse_mode='HTML')

@bot.message_handler(content_types=['contact'])
def contact(message):
    if message.contact:
        update_user_info(message.from_user, message.contact.phone_number)
        bot.reply_to(message, "✅ Telefon raqamingiz saqlandi.")

@bot.channel_post_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def channel_msg(message):
    process_forward(message)

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def group_msg(message):
    process_forward(message)

# --- Render HTTP Server ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-type', 'text/plain'); self.end_headers()
        self.wfile.write(b'Bot is active!')
    def log_message(self, format, *args): pass

def run_server():
    port = int(os.environ.get('PORT', 10000))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

# --- Main ---
if __name__ == '__main__':
    init_database()
    if os.environ.get('RENDER') or os.environ.get('PORT'):
        Thread(target=run_server, daemon=True).start()
    logger.info("Bot ishga tushdi...")
    bot.infinity_polling()
