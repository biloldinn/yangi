import telebot
import os
import time
import urllib.request
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- KONFIGURATSIYA ---
TOKEN = "8417577678:AAH6RXAvwsaEuhKSCq6AsC83tG5QBtd0aJk"
SOURCE_CHANNEL = "@TOSHKENTANGRENTAKSI"
DESTINATION_CHANNEL = "@Uski_kur"

bot = telebot.TeleBot(TOKEN)

def get_sender_info(message):
    user = message.from_user
    if not user:
        return "📢 <b>Kanal xabari</b>\n"
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Noma'lum"
    info = f"👤 <b>Foydalanuvchi:</b> {name}\n"
    if user.username:
        info += f"🔗 <b>Username:</b> @{user.username}\n"
    info += f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
    return info

def forward_logic(message):
    try:
        current_chat = f"@{message.chat.username}" if message.chat.username else str(message.chat.id)
        if current_chat.lower() != SOURCE_CHANNEL.lower():
            return
        header = get_sender_info(message)
        separator = "─" * 15 + "\n"
        full_header = header + separator

        if message.content_type == 'text':
            bot.send_message(DESTINATION_CHANNEL, full_header + message.text, parse_mode='HTML')
        elif message.content_type == 'photo':
            bot.send_photo(DESTINATION_CHANNEL, message.photo[-1].file_id, caption=full_header + (message.caption or ""), parse_mode='HTML')
        elif message.content_type == 'video':
            bot.send_video(DESTINATION_CHANNEL, message.video.file_id, caption=full_header + (message.caption or ""), parse_mode='HTML')
        elif message.content_type == 'voice':
            bot.send_voice(DESTINATION_CHANNEL, message.voice.file_id, caption=full_header)
        elif message.content_type == 'audio':
            bot.send_audio(DESTINATION_CHANNEL, message.audio.file_id, caption=full_header + (message.caption or ""), parse_mode='HTML')
        elif message.content_type == 'document':
            bot.send_document(DESTINATION_CHANNEL, message.document.file_id, caption=full_header + (message.caption or ""), parse_mode='HTML')
        else:
            bot.send_message(DESTINATION_CHANNEL, full_header + f"📎 <b>Xabar turi:</b> {message.content_type}")
        print(f"✅ Xabar muvaffaqiyatli ko'chirildi: {current_chat}")
    except Exception as e:
        print(f"❌ Xatolik yuz berdi: {e}")

@bot.channel_post_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def handle_channel_posts(message):
    forward_logic(message)

@bot.message_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def handle_group_messages(message):
    forward_logic(message)

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "✅ <b>Bot ishlamoqda!</b>\n\nMen @TOSHKENTANGRENTAKSI kanalidan xabarlarni @Uski_kur guruhiga yashirincha ko'chirib beraman.", parse_mode='HTML')

class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args): pass

def start_server():
    port = int(os.environ.get('PORT', 10000))
    httpd = HTTPServer(('0.0.0.0', port), HealthCheck)
    print(f"🌐 Server port {port} da ishlamoqda...")
    httpd.serve_forever()

def keep_awake():
    """Pings the bot's own URL every 10 minutes to prevent Render from sleeping"""
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if not url:
        print("⚠️ RENDER_EXTERNAL_URL topilmadi. Avtomatik uyg'oq tutish ishlamasligi mumkin.")
        return
    
    print(f"🚀 Avtomatik uyg'oq tutish boshlandi: {url}")
    while True:
        try:
            time.sleep(600)  # 10 daqiqa kutish
            with urllib.request.urlopen(url) as response:
                response.read()
            print(f"⏰ Self-ping muvaffaqiyatli: {time.ctime()}")
        except Exception as e:
            print(f"❌ Self-ping xatosi: {e}")

if __name__ == "__main__":
    if os.environ.get('PORT'):
        Thread(target=start_server, daemon=True).start()
    
    # Render'da bo'lsak, self-ping ni boshlaymiz
    if os.environ.get('RENDER') or os.environ.get('RENDER_EXTERNAL_URL'):
        Thread(target=keep_awake, daemon=True).start()
    
    print("🤖 Bot xabarlarni kutmoqda...")
    bot.infinity_polling()

