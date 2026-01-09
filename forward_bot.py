import telebot
import os
import time
import urllib.request
import logging
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telebot import types

# --- KONFIGURATSIYA ---
TOKEN = "8417577678:AAH6RXAvwsaEuhKSCq6AsC83tG5QBtd0aJk"
SOURCE_CHANNEL = "@TOSHKENTANGRENTAKSI"
DESTINATION_CHANNEL = "@Uski_kur"  # Zakazlar va forwardlar shu yerga tushadi

bot = telebot.TeleBot(TOKEN)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Foydalanuvchi holatlarini saqlash
user_states = {}

# --- KEYBOARDS ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🚖 Taksi Chaqirish"))
    return markup

def get_cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("❌ Bekor qilish"))
    return markup

# --- HELPER FUNCTIONS ---
def get_sender_info(message):
    """Xabar yuborgan shaxs haqida ma'lumot tayyorlaydi (profil linki bilan)"""
    user = message.from_user
    if not user:
        return "📢 <b>KAMAL XABARI</b>\n"
    
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Foydalanuvchi"
    # Profilga havola: <a href="tg://user?id=ID">Ism</a>
    profile_link = f'<b><a href="tg://user?id={user.id}">{name}</a></b>'
    
    info = f"👤 <b>Yuboruvchi:</b> {profile_link}\n"
    if user.username:
        info += f"🔗 <b>Username:</b> @{user.username}\n"
    return info

# --- FORWARD LOGIC ---
def forward_logic(message):
    try:
        # Chat identifikatsiyasini yaxshilash
        chat = message.chat
        current_chat_username = f"@{chat.username}" if chat.username else None
        current_chat_id = str(chat.id)
        
        logger.info(f"📩 Yangi xabar keldi. Chat: {current_chat_username or current_chat_id}")

        # SOURCE_CHANNEL bilan solishtirish (registrga qaramaslik uchun lower() ishlatamiz)
        is_source = False
        if current_chat_username and current_chat_username.lower() == SOURCE_CHANNEL.lower():
            is_source = True
        elif current_chat_id == SOURCE_CHANNEL:
            is_source = True
        
        if not is_source:
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
        
        logger.info(f"✅ Xabar ko'chirildi (Manzil: {DESTINATION_CHANNEL})")

        # --- Xabarni o'chirish logikasi ---
        try:
            bot.delete_message(message.chat.id, message.message_id)
            logger.info(f"🗑 Xabar manba kanaldan o'chirildi: {message.message_id}")
        except Exception as del_e:
            logger.error(f"❌ Xabarni o'chirishda xato: {del_e}")

    except Exception as e:
        logger.error(f"❌ Forward xatosi: {e}")

# --- TAXI BOOKING FLOW ---
def check_membership(user_id):
    """Foydalanuvchi kanalga a'zo ekanligini tekshiradi"""
    try:
        member = bot.get_chat_member(SOURCE_CHANNEL, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
    except Exception as e:
        logger.error(f"Membership check error: {e}")
    return False

def get_join_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("A'zo bo'lish 📢", url=f"https://t.me/{SOURCE_CHANNEL.replace('@', '')}"))
    markup.add(types.InlineKeyboardButton("Tekshirish ✅", callback_data="check_join"))
    return markup

@bot.message_handler(func=lambda m: m.text == "🚖 Taksi Chaqirish")
def taxi_start(message):
    user_id = message.from_user.id
    if not check_membership(user_id):
        bot.send_message(user_id, (
            "⚠️ <b>Kanalga a'zo emassiz!</b>\n\n"
            "Taksi buyurtma berish uchun avval bizning rasmiy kanalimizga a'zo bo'ling. "
            "Keyin 'Tekshirish' tugmasini bosing."
        ), parse_mode='HTML', reply_markup=get_join_markup())
        return

    user_states[user_id] = {'step': 'WAIT_NAME', 'data': {}}
    bot.send_message(user_id, "🚖 <b>Taksi zakaz qilish boshlandi.</b>\n\nIsmingizni kiriting:", parse_mode='HTML', reply_markup=get_cancel_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def verify_join(call):
    user_id = call.from_user.id
    if check_membership(user_id):
        bot.answer_callback_query(call.id, "Tabriklaymiz! Endi zakaz berishingiz mumkin.")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        # Bookingni boshlash
        user_states[user_id] = {'step': 'WAIT_NAME', 'data': {}}
        bot.send_message(user_id, "🚖 <b>Taksi zakaz qilish boshlandi.</b>\n\nIsmingizni kiriting:", parse_mode='HTML', reply_markup=get_cancel_keyboard())
    else:
        bot.answer_callback_query(call.id, "Siz hali kanalga a'zo bo'lmagansiz! ❌", show_alert=True)

@bot.message_handler(func=lambda m: m.text == "❌ Bekor qilish")
def cancel_booking(message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    bot.send_message(user_id, "❌ Zakaz bekor qilindi.", reply_markup=get_main_keyboard())

def handle_taxi_steps(message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state: return False

    step = state['step']
    
    try:
        if step == 'WAIT_NAME':
            state['data']['name'] = message.text
            state['step'] = 'WAIT_PHONE'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📞 Telefon yuborish", request_contact=True))
            markup.add(types.KeyboardButton("❌ Bekor qilish"))
            bot.send_message(user_id, "Raxmat. Endi telefon raqamingizni yuboring:", reply_markup=markup)
            return True

        elif step == 'WAIT_PHONE':
            if message.content_type == 'contact':
                state['data']['phone'] = message.contact.phone_number
            else:
                state['data']['phone'] = message.text
            
            state['step'] = 'WAIT_DEST'
            bot.send_message(user_id, "Qayerga borasiz? (Manzilni yozing):", reply_markup=get_cancel_keyboard())
            return True

        elif step == 'WAIT_DEST':
            state['data']['dest'] = message.text
            state['step'] = 'WAIT_LOC'
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
            markup.add(types.KeyboardButton("📍 Lokatsiyani yuborish", request_location=True))
            markup.add(types.KeyboardButton("❌ Bekor qilish"))
            bot.send_message(user_id, "Lokatsiyangizni yuboring (tugmani bosing):", reply_markup=markup)
            return True

        elif step == 'WAIT_LOC':
            if message.content_type == 'location':
                data = state['data']
                # Profil linki yaratish
                user = message.from_user
                name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Foydalanuvchi"
                profile_link = f'<b><a href="tg://user?id={user.id}">{name}</a></b>'

                order_text = (
                    f"✨ <b>YANGI TAKSI BUYURTMASI</b> ✨\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 <b>Mijoz:</b> {profile_link}\n"
                    f"📞 <b>Telefon:</b> <code>{data['phone']}</code>\n"
                    f"📍 <b>Manzil:</b> <i>{data['dest']}</i>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🕒 <b>Vaqt:</b> <code>{time.strftime('%H:%M')}</code>\n"
                    f"🆔 <b>Mijoz ID:</b> <code>{user_id}</code>\n"
                    f"🚀 <i>3 daqiqada taksi chaqiring!</i>"
                )
                
                # Guruhga yuborish
                bot.send_message(DESTINATION_CHANNEL, order_text, parse_mode='HTML')
                bot.send_location(DESTINATION_CHANNEL, message.location.latitude, message.location.longitude)
                
                # Foydalanuvchiga tasdiqlash
                bot.send_message(user_id, "✅ <b>Buyurtmangiz qabul qilindi!</b>\nTez orada haydovchilarimiz aloqaga chiqishadi. Raxmat!", parse_mode='HTML', reply_markup=get_main_keyboard())
                
                logger.info(f"✅ Yangi zakaz: {user_id}")
                del user_states[user_id]
                return True
            else:
                bot.send_message(user_id, "Iltimos, lokatsiyani yuborish tugmasini bosing yoki bekor qiling.", reply_markup=get_cancel_keyboard())
                return True
    except Exception as e:
        logger.error(f"Booking flow error: {e}")
        bot.send_message(user_id, "❌ Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.", reply_markup=get_main_keyboard())
        if user_id in user_states: del user_states[user_id]
        return True
        
    return False

# --- HANDLERLAR ---
@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.from_user.id
    if user_id in user_states: del user_states[user_id]
    bot.send_message(message.chat.id, "✅ <b>Bot ishlamoqda!</b>\n\nTaksi chaqirish uchun tugmani bosing.", parse_mode='HTML', reply_markup=get_main_keyboard())

@bot.channel_post_handler(func=lambda m: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'voice'])
def channel_msg(message):
    forward_logic(message)

# --- NEW: WELCOME MESSAGE ---
@bot.chat_member_handler()
def handle_chat_member_update(message):
    new_member = message.new_chat_member
    if new_member.status == 'member':
        try:
            chat_id = message.chat.id
            user_name = new_member.user.first_name
            bot_username = bot.get_me().username
            
            welcome_text = (
                f"👋 <b>HUŞ KELIBSIZ, {user_name.upper()}!</b>\n\n"
                f"🚖 <b>TEZKOR TAKSI BUYURTMA QILISH:</b>\n"
                f"Pastdagi tugmani bosing va botni ishga tushiring.\n\n"
                f"✨ <i>3 daqiqada taksi eshigingiz oldida!</i>"
            )
            
            # Inline button qo'shish
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🚖 BUYURTMA BERISH (ZAKAZ)", url=f"https://t.me/{bot_username}?start=join"))
            
            bot.send_message(chat_id, welcome_text, parse_mode='HTML', reply_markup=markup)
            logger.info(f"👋 Yangi azo uchun welcome yuborildi: {user_name}")
        except Exception as e:
            logger.error(f"Welcome error: {e}")

@bot.message_handler(content_types=['text', 'contact', 'location'])
def handle_all_messages(message):
    # Taksi booking jarayonini tekshirish
    if handle_taxi_steps(message):
        return
    
    # Kanal forward logikasi (agar SOURCE_CHANNEL dan kelsa)
    forward_logic(message)

# --- RENDER SERVER & KEEP AWAKE ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
    def log_message(self, format, *args): pass

def keep_awake():
    url = os.environ.get('RENDER_EXTERNAL_URL')
    if not url:
        logger.warning("⚠️ RENDER_EXTERNAL_URL topilmadi.")
        return
    while True:
        try:
            time.sleep(600)
            urllib.request.urlopen(url).read()
            logger.info(f"⏰ Self-ping OK: {time.ctime()}")
        except Exception as e:
            logger.error(f"❌ Self-ping error: {e}")

# --- ADMIN PANEL ---
PROMO_ENABLED = True
ADMIN_IDS = [7901048491, 123456789] # Sizning ID va boshqa adminlar

def get_admin_markup():
    markup = types.InlineKeyboardMarkup()
    status = "✅ YONIQ" if PROMO_ENABLED else "❌ O'CHIK"
    markup.add(types.InlineKeyboardButton(f"Reklama holati: {status}", callback_data="toggle_promo"))
    return markup

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if message.from_user.id in ADMIN_IDS:
        bot.send_message(message.chat.id, "💎 <b>ADMIN PANEL</b>\n\nPastdagi tugma orqali reklamani boshqaring:", parse_mode='HTML', reply_markup=get_admin_markup())
    else:
        bot.send_message(message.chat.id, "❌ Siz admin emassiz.")

@bot.callback_query_handler(func=lambda call: call.data == "toggle_promo")
def toggle_promo_callback(call):
    global PROMO_ENABLED
    if call.from_user.id not in ADMIN_IDS:
        bot.answer_callback_query(call.id, "Ruxsat yo'q!", show_alert=True)
        return
    
    PROMO_ENABLED = not PROMO_ENABLED
    status = "Yoqildi ✅" if PROMO_ENABLED else "O'chirildi ❌"
    bot.answer_callback_query(call.id, f"Reklama {status}")
    bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_admin_markup())

# --- NEW: PERIODIC PROMO POST ---
def periodic_promo():
    """Har 3 daqiqada kanalga chiroyli reklama postini chiqaradi"""
    while True:
        try:
            time.sleep(180) # 3 daqiqa
            if not PROMO_ENABLED:
                continue
                
            promo_text = (
                f"⚡️ <b>TEZKOR TAKSI BUYURTMASI!</b> ⚡️\n\n"
                f"🏁 <b>3 daqiqada</b> manzilga yetib boramiz!\n"
                f"💎 <b>Premium sifat — Hamyonbop narx.</b>\n\n"
                f"👇 <b>BUYURTMA BERISH UCHUN:</b>\n"
                f"👉 @{(bot.get_me().username)} 👈\n"
                f"👉 @{(bot.get_me().username)} 👈\n\n"
                f"🏆 <i>Xizmatimizdan foydalaning va rohatlaning!</i>"
            )
            bot.send_message(SOURCE_CHANNEL, promo_text, parse_mode='HTML')
            logger.info("📢 Promo post kanalga yuborildi.")
        except Exception as e:
            logger.error(f"Promo error: {e}")

if __name__ == "__main__":
    if os.environ.get('PORT'):
        port = int(os.environ.get('PORT', 10000))
        Thread(target=lambda: HTTPServer(('0.0.0.0', port), HealthCheck).serve_forever(), daemon=True).start()
    
    if os.environ.get('RENDER_EXTERNAL_URL'):
        Thread(target=keep_awake, daemon=True).start()
    
    # Promo threadni boshlash
    Thread(target=periodic_promo, daemon=True).start()
    
    # --- WEBHOOK'NI OCHIRISH (409 Conflict xatosini oldini olish uchun) ---
    try:
        logger.info("🧹 Webhook tozalanmoqda...")
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        logger.warning(f"⚠️ Webhook tozalashda xato: {e}")
        
    logger.info("🤖 Bot ishga tushdi...")
    bot.infinity_polling(skip_pending=True)
