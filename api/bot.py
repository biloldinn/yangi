import os
import json
import logging
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Optional, Dict, List, Tuple

# Telegram kutubxonalari
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ====================== KONFIGURATSIYA ======================
TOKEN = os.getenv("TELEGRAM_TOKEN", "8545035071:AAEngg_8PeQ5B4KFrJzWfiBKBjIJxWlR4xc")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6762465157"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
PAYMENT_AMOUNT = int(os.getenv("PAYMENT_AMOUNT", "15000"))
PAYMENT_CARD = os.getenv("PAYMENT_CARD", "9860012345678901")
PAYMENT_NAME = os.getenv("PAYMENT_NAME", "TURGUNBOYEV Biloliddin")
DESTINATION_GROUP = "@Angren_Toshkent_Taksi_pochta_a"
DB_PATH = "bot_data.db"

# ====================== LOGGING ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====================== DATABASE FUNCTIONS ======================
async def init_database():
    """Ma'lumotlar bazasini yaratish"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Foydalanuvchilar jadvali
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                phone TEXT,
                status TEXT DEFAULT 'inactive',
                balance INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_banned INTEGER DEFAULT 0
            )
        ''')
        
        # To'lovlar jadvali
        await db.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                screenshot_id TEXT,
                status TEXT DEFAULT 'pending',  -- pending, confirmed, rejected
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                confirmed_by INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Kanalar jadvali
        await db.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_username TEXT,
                channel_id TEXT,
                channel_title TEXT,
                is_active INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_forwarded TIMESTAMP,
                forward_count INTEGER DEFAULT 0,
                UNIQUE(channel_username),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Admin amallari jadvali
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        await db.commit()
        logger.info("✅ Ma'lumotlar bazasi yaratildi/yuklandi")

async def register_user(user_id: int, username: str, first_name: str, last_name: str = "", phone: str = "") -> bool:
    """Yangi foydalanuvchini ro'yxatdan o'tkazish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT OR IGNORE INTO users 
                (user_id, username, first_name, last_name, phone, status, registered_at)
                VALUES (?, ?, ?, ?, ?, 'inactive', ?)
            ''', (user_id, username, first_name, last_name, phone, datetime.now().isoformat()))
            
            await db.commit()
            logger.info(f"✅ Foydalanuvchi ro'yxatdan o'tdi: {user_id} - {username}")
            return True
    except Exception as e:
        logger.error(f"❌ Ro'yxatdan o'tkazishda xatolik: {e}")
        return False

async def get_user(user_id: int) -> Optional[Dict]:
    """Foydalanuvchi ma'lumotlarini olish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT user_id, username, first_name, last_name, phone, status, 
                       balance, registered_at, expires_at, is_banned
                FROM users WHERE user_id = ?
            ''', (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'user_id': row[0],
                        'username': row[1],
                        'first_name': row[2],
                        'last_name': row[3],
                        'phone': row[4],
                        'status': row[5],
                        'balance': row[6],
                        'registered_at': row[7],
                        'expires_at': row[8],
                        'is_banned': bool(row[9])
                    }
    except Exception as e:
        logger.error(f"❌ Foydalanuvchi ma'lumotlarini olishda xatolik: {e}")
    return None

async def update_user_status(user_id: int, status: str, days: int = 30) -> bool:
    """Foydalanuvchi holatini yangilash"""
    try:
        expires_at = datetime.now() + timedelta(days=days)
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                UPDATE users 
                SET status = ?, expires_at = ?, is_banned = 0
                WHERE user_id = ?
            ''', (status, expires_at.isoformat(), user_id))
            
            await db.commit()
            logger.info(f"✅ Foydalanuvchi holati yangilandi: {user_id} -> {status}")
            return True
    except Exception as e:
        logger.error(f"❌ Holatni yangilashda xatolik: {e}")
        return False

async def add_channel(user_id: int, channel_username: str, channel_id: str = "", channel_title: str = "") -> bool:
    """Foydalanuvchiga yangi kanal qo'shish"""
    try:
        # @ belgisini olib tashlash
        channel_username = channel_username.replace('@', '').strip()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Kanal allaqachon mavjudligini tekshirish
            async with db.execute('SELECT id FROM channels WHERE channel_username = ?', (channel_username,)) as cursor:
                existing = await cursor.fetchone()
                if existing:
                    logger.warning(f"⚠️ Kanal allaqachon mavjud: {channel_username}")
                    return False
            
            # Yangi kanal qo'shish
            await db.execute('''
                INSERT INTO channels 
                (user_id, channel_username, channel_id, channel_title, added_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, channel_username, channel_id, channel_title, datetime.now().isoformat()))
            
            await db.commit()
            logger.info(f"✅ Kanal qo'shildi: {channel_username} -> user {user_id}")
            return True
    except Exception as e:
        logger.error(f"❌ Kanal qo'shishda xatolik: {e}")
        return False

async def get_user_channels(user_id: int) -> List[Dict]:
    """Foydalanuvchi kanallarini olish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT id, channel_username, channel_title, is_active, 
                       added_at, last_forwarded, forward_count
                FROM channels 
                WHERE user_id = ? AND is_active = 1
                ORDER BY added_at DESC
            ''', (user_id,)) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        'id': row[0],
                        'username': row[1],
                        'title': row[2],
                        'is_active': bool(row[3]),
                        'added_at': row[4],
                        'last_forwarded': row[5],
                        'forward_count': row[6]
                    }
                    for row in rows
                ]
    except Exception as e:
        logger.error(f"❌ Kanal ma'lumotlarini olishda xatolik: {e}")
        return []

async def create_payment(user_id: int, screenshot_id: str = None) -> Optional[int]:
    """Yangi to'lov yaratish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('''
                INSERT INTO payments (user_id, amount, screenshot_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (user_id, PAYMENT_AMOUNT, screenshot_id, datetime.now().isoformat()))
            
            payment_id = cursor.lastrowid
            await db.commit()
            
            logger.info(f"✅ To'lov yaratildi: ID {payment_id} -> user {user_id}")
            return payment_id
    except Exception as e:
        logger.error(f"❌ To'lov yaratishda xatolik: {e}")
        return None

async def confirm_payment(payment_id: int, admin_id: int, note: str = "") -> bool:
    """To'lovni tasdiqlash"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # To'lov ma'lumotlarini olish
            async with db.execute('SELECT user_id FROM payments WHERE id = ?', (payment_id,)) as cursor:
                payment = await cursor.fetchone()
                if not payment:
                    return False
                
                user_id = payment[0]
            
            # To'lovni tasdiqlash
            await db.execute('''
                UPDATE payments 
                SET status = 'confirmed', 
                    confirmed_at = ?,
                    confirmed_by = ?,
                    admin_note = ?
                WHERE id = ?
            ''', (datetime.now().isoformat(), admin_id, note, payment_id))
            
            # Foydalanuvchini faollashtirish
            await update_user_status(user_id, "active", 30)
            
            # Admin log
            await db.execute('''
                INSERT INTO admin_logs (admin_id, action, target_id, details)
                VALUES (?, ?, ?, ?)
            ''', (admin_id, "confirm_payment", user_id, f"Payment #{payment_id} confirmed"))
            
            await db.commit()
            
            logger.info(f"✅ To'lov tasdiqlandi: #{payment_id} by admin {admin_id}")
            return True
    except Exception as e:
        logger.error(f"❌ To'lovni tasdiqlashda xatolik: {e}")
        return False

async def get_pending_payments() -> List[Dict]:
    """Kutilayotgan to'lovlarni olish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT p.id, p.user_id, u.username, u.first_name, 
                       p.amount, p.screenshot_id, p.created_at
                FROM payments p
                JOIN users u ON p.user_id = u.user_id
                WHERE p.status = 'pending'
                ORDER BY p.created_at DESC
            ''') as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        'id': row[0],
                        'user_id': row[1],
                        'username': row[2],
                        'first_name': row[3],
                        'amount': row[4],
                        'screenshot_id': row[5],
                        'created_at': row[6]
                    }
                    for row in rows
                ]
    except Exception as e:
        logger.error(f"❌ To'lovlarni olishda xatolik: {e}")
        return []

async def update_channel_stats(channel_username: str):
    """Kanal statistikasini yangilash"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                UPDATE channels 
                SET last_forwarded = ?, forward_count = forward_count + 1
                WHERE channel_username = ?
            ''', (datetime.now().isoformat(), channel_username))
            
            await db.commit()
    except Exception as e:
        logger.error(f"❌ Statistikani yangilashda xatolik: {e}")

async def get_channel_by_username(channel_username: str) -> Optional[Dict]:
    """Kanal ma'lumotlarini username orqali olish"""
    try:
        channel_username = channel_username.replace('@', '').strip()
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT c.id, c.user_id, c.channel_username, c.is_active, 
                       u.status, u.expires_at
                FROM channels c
                JOIN users u ON c.user_id = u.user_id
                WHERE c.channel_username = ? AND c.is_active = 1
            ''', (channel_username,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'id': row[0],
                        'user_id': row[1],
                        'username': row[2],
                        'is_active': bool(row[3]),
                        'user_status': row[4],
                        'expires_at': row[5]
                    }
    except Exception as e:
        logger.error(f"❌ Kanal ma'lumotlarini olishda xatolik: {e}")
    return None

async def get_all_users() -> List[Dict]:
    """Barcha foydalanuvchilarni olish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT u.user_id, u.username, u.first_name, u.status, 
                       u.expires_at, COUNT(c.id) as channel_count
                FROM users u
                LEFT JOIN channels c ON u.user_id = c.user_id AND c.is_active = 1
                GROUP BY u.user_id
                ORDER BY u.registered_at DESC
            ''') as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        'user_id': row[0],
                        'username': row[1],
                        'first_name': row[2],
                        'status': row[3],
                        'expires_at': row[4],
                        'channel_count': row[5]
                    }
                    for row in rows
                ]
    except Exception as e:
        logger.error(f"❌ Foydalanuvchilarni olishda xatolik: {e}")
        return []

async def get_stats() -> Dict:
    """Bot statistikasini olish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Foydalanuvchilar soni
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            
            async with db.execute("SELECT COUNT(*) FROM users WHERE status = 'active'") as cursor:
                active_users = (await cursor.fetchone())[0]
            
            # Kanalar soni
            async with db.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1") as cursor:
                total_channels = (await cursor.fetchone())[0]
            
            # To'lovlar
            async with db.execute("SELECT SUM(amount) FROM payments WHERE status = 'confirmed'") as cursor:
                total_income = (await cursor.fetchone())[0] or 0
            
            async with db.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'") as cursor:
                pending_payments = (await cursor.fetchone())[0]
            
            return {
                'total_users': total_users,
                'active_users': active_users,
                'total_channels': total_channels,
                'total_income': total_income,
                'pending_payments': pending_payments
            }
    except Exception as e:
        logger.error(f"❌ Statistika olishda xatolik: {e}")
        return {}

# ====================== TELEGRAM HANDLERS ======================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komandasi"""
    user = update.effective_user
    
    # Foydalanuvchini ro'yxatdan o'tkazish
    await register_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name or ""
    )
    
    # Menyu tugmalari
    keyboard = [
        [InlineKeyboardButton("➕ Kanal qo'shish", callback_data='add_channel')],
        [InlineKeyboardButton("💳 To'lov qilish", callback_data='make_payment')],
        [InlineKeyboardButton("📊 Mening kanallarim", callback_data='my_channels')],
        [InlineKeyboardButton("ℹ️ Qo'llanma", callback_data='help')]
    ]
    
    if user.id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("👑 Admin Panel", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Salom *{user.first_name}*!\n\n"
        "🤖 *Toshkent-Angren Taksi Xabar Forward Botiga xush kelibsiz!*\n\n"
        "📥 Ushbu bot orqali siz o'z kanalingizdagi xabarlarni avtomatik ravishda\n"
        f"📤 {DESTINATION_GROUP} guruhiga ko'chirishingiz mumkin!\n\n"
        "⚡️ *Botdan foydalanish tartibi:*\n"
        "1️⃣ Botni kanalingizga *ADMIN* qiling\n"
        "2️⃣ Kanalni qo'shing\n"
        "3️⃣ To'lov qiling (*15,000 so'm / oy*)\n"
        "4️⃣ Xabarlar avtomatik ko'chiriladi!\n\n"
        "⚠️ *Diqqat:* Bot ADMIN bo'lmaguncha xabarlar ko'chirilmaydi!",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal qo'shish komandasi"""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "📢 *Kanal qo'shish uchun:*\n\n"
            "Quyidagi formatda yozing:\n"
            "`/add @kanal_nomi`\n\n"
            "*Misol:* `/add @meningkanalim`\n\n"
            "⚠️ *Eslatma:* Botni avval kanalga ADMIN qilishni unutmang!",
            parse_mode="Markdown"
        )
        return
    
    channel_username = context.args[0]
    
    # Kanal qo'shish
    success = await add_channel(user.id, channel_username)
    
    if success:
        await update.message.reply_text(
            f"✅ *Kanal qo'shildi!*\n\n"
            f"📢 Kanal: @{channel_username}\n\n"
            "*Endi quyidagi amallarni bajaring:*\n"
            f"1. Botni @{channel_username} kanaliga *ADMIN* qiling\n"
            "2. Botga quyidagi huquqlarni bering:\n"
            "   • Post joylash huquqi\n"
            "   • Xabarlarni o'qish huquqi\n"
            "3. To'lov qiling: /payment\n\n"
            "✅ To'lov tasdiqlangach, xabarlar avtomatik ko'chiriladi!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "❌ *Kanal qo'shilmadi!*\n\n"
            "Sabablari:\n"
            "• Kanal allaqachon qo'shilgan\n"
            "• Yoki xatolik yuz berdi\n\n"
            "Qayta urinib ko'ring yoki adminga murojaat qiling.",
            parse_mode="Markdown"
        )

async def payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """To'lov komandasi"""
    user = update.effective_user
    
    # To'lov tugmalari
    keyboard = [
        [InlineKeyboardButton("💳 To'lov qildim", callback_data='payment_done')],
        [InlineKeyboardButton("📞 Admin bilan bog'lanish", url=f"tg://user?id={ADMIN_ID}")],
        [InlineKeyboardButton("🔙 Orqaga", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "💳 *To'lov ma'lumotlari:*\n\n"
        f"🏦 Karta raqami: `{PAYMENT_CARD}`\n"
        f"👤 Karta egasi: *{PAYMENT_NAME}*\n"
        f"💰 To'lov summasi: *{PAYMENT_AMOUNT:,} so'm*\n"
        f"📅 Muddati: *30 kun*\n\n"
        "📱 *To'lov qilish tartibi:*\n"
        "1. Yuqoridagi karta raqamiga *15,000 so'm* o'tkazing\n"
        "2. To'lov chekini *skrinshot* qilib oling\n"
        "3. «To'lov qildim» tugmasini bosing va skrinshotni yuboring\n\n"
        "✅ *To'lov tasdiqlangach, kanalingiz 30 kun davomida faollashtiriladi!*\n\n"
        "⏳ Tasdiqlash vaqti: *24 soat ichida*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def my_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mening kanallarim komandasi"""
    user = update.effective_user
    
    channels = await get_user_channels(user.id)
    
    if not channels:
        await update.message.reply_text(
            "📭 *Sizda hali kanal mavjud emas!*\n\n"
            "Kanal qo'shish uchun: /add @kanal_nomi\n"
            "Yoki pastdagi tugmani bosing:",
            parse_mode="Markdown"
        )
        return
    
    # Foydalanuvchi holatini tekshirish
    user_info = await get_user(user.id)
    status_text = "🟢 Faol" if user_info and user_info['status'] == 'active' else "🔴 Faol emas"
    
    text = f"📊 *Mening kanallarim* ({len(channels)} ta)\n"
    text += f"📈 Holatim: {status_text}\n\n"
    
    for i, channel in enumerate(channels, 1):
        last_forward = channel['last_forwarded'] or "Hali yo'q"
        text += f"{i}. *{channel['title'] or channel['username']}*\n"
        text += f"   👁️ @{channel['username']}\n"
        text += f"   📊 {channel['forward_count']} marta ko'chirilgan\n"
        text += f"   ⏰ Oxirgi: {last_forward[:10]}\n\n"
    
    text += "🔧 *Sozlamalar:*\n"
    text += "• Kanal qo'shish: /add @kanal_nomi\n"
    text += "• To'lov qilish: /payment\n"
    text += "• Admin bilan bog'lanish: /contact"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel komandasi"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ *Siz admin emassiz!*", parse_mode="Markdown")
        return
    
    # Statistika olish
    stats = await get_stats()
    pending_payments = await get_pending_payments()
    
    # Admin panel tugmalari
    keyboard = []
    
    if pending_payments:
        keyboard.append([InlineKeyboardButton(f"⏳ To'lovlar ({len(pending_payments)} ta)", callback_data='pending_payments')])
    
    keyboard.extend([
        [InlineKeyboardButton("📊 Statistika", callback_data='admin_stats')],
        [InlineKeyboardButton("👥 Barcha foydalanuvchilar", callback_data='all_users')],
        [InlineKeyboardButton("📢 Reklama yuborish", callback_data='send_broadcast')],
        [InlineKeyboardButton("⚙️ Sozlamalar", callback_data='admin_settings')]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👑 *Admin Panel*\n\n"
        f"📈 Statistika:\n"
        f"• 👥 Jami foydalanuvchilar: {stats.get('total_users', 0)}\n"
        f"• ✅ Faol foydalanuvchilar: {stats.get('active_users', 0)}\n"
        f"• 📢 Jami kanallar: {stats.get('total_channels', 0)}\n"
        f"• 💰 Jami daromad: {stats.get('total_income', 0):,} so'm\n"
        f"• ⏳ Kutilayotgan to'lovlar: {len(pending_payments)} ta\n\n"
        f"🛠️ *Admin amallari:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xabarlarni forward qilish"""
    try:
        message = update.channel_post or update.message
        
        if not message:
            return
        
        # Chat ma'lumotlari
        chat = message.chat
        username = chat.username if hasattr(chat, 'username') else str(chat.id)
        
        # Kanal ma'lumotlarini olish
        channel_info = await get_channel_by_username(username)
        
        if not channel_info:
            logger.info(f"❌ Kanal topilmadi: {username}")
            return
        
        # Foydalanuvchi holatini tekshirish
        user_id = channel_info['user_id']
        user_status = channel_info['user_status']
        expires_at = channel_info['expires_at']
        
        # Muddati tugaganligini tekshirish
        if expires_at:
            expires_date = datetime.fromisoformat(expires_at)
            if datetime.now() > expires_date:
                await update_user_status(user_id, "expired")
                logger.info(f"❌ Foydalanuvchi muddati tugagan: {user_id}")
                return
        
        # Faol foydalanuvchilarga forward qilish
        if user_status == 'active':
            try:
                await context.bot.forward_message(
                    chat_id=DESTINATION_GROUP,
                    from_chat_id=chat.id,
                    message_id=message.message_id
                )
                
                # Statistikani yangilash
                await update_channel_stats(username)
                
                logger.info(f"✅ Forward qilindi: {username} -> {DESTINATION_GROUP}")
                
            except Exception as e:
                logger.error(f"❌ Forward qilishda xatolik: {e}")
                
        else:
            logger.info(f"❌ Foydalanuvchi faol emas: {user_id} - {user_status}")
            
    except Exception as e:
        logger.error(f"❌ Xabarni qayta ishlashda xatolik: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """To'lov cheki rasmini qabul qilish"""
    user = update.effective_user
    
    if not update.message.photo:
        return
    
    # Eng katta rasmni olish
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # To'lov yaratish
    payment_id = await create_payment(user.id, file.file_id)
    
    if payment_id:
        # Foydalanuvchiga xabar
        await update.message.reply_text(
            f"✅ *To'lov cheki qabul qilindi!*\n\n"
            f"📋 To'lov ID: *#{payment_id}*\n"
            f"👤 Siz: @{user.username or user.first_name}\n"
            f"💰 Summa: *{PAYMENT_AMOUNT:,} so'm*\n"
            f"📅 Muddati: *30 kun*\n\n"
            "⏳ *Admin tomonidan tekshirilmoqda...*\n"
            "Tasdiqlash uchun *24 soat* kuting.\n\n"
            "📞 Bog'lanish: @admin_username",
            parse_mode="Markdown"
        )
        
        # Adminga xabar
        try:
            user_info = await get_user(user.id)
            user_channels = await get_user_channels(user.id)
            channels_text = "\n".join([f"• @{ch['username']}" for ch in user_channels[:3]]) or "Kanal yo'q"
            
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=file.file_id,
                caption=f"🆕 *Yangi to'lov!*\n\n"
                       f"📋 ID: #{payment_id}\n"
                       f"👤 Foydalanuvchi: @{user.username or user.first_name}\n"
                       f"🆔 User ID: `{user.id}`\n"
                       f"💰 Summa: {PAYMENT_AMOUNT:,} so'm\n"
                       f"📅 Vaqt: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                       f"📢 Kanallari ({len(user_channels)} ta):\n{channels_text}\n\n"
                       f"✅ Tasdiqlash: /confirm_{payment_id}\n"
                       f"❌ Rad etish: /reject_{payment_id}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Adminga xabar yuborishda xatolik: {e}")
    else:
        await update.message.reply_text(
            "❌ *To'lov yaratishda xatolik!*\n\n"
            "Iltimos, adminga murojaat qiling: @admin_username",
            parse_mode="Markdown"
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback querylarni qayta ishlash"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user
    
    if data == 'add_channel':
        await query.edit_message_text(
            "📢 *Kanal qo'shish:*\n\n"
            "Kanal qo'shish uchun quyidagi formatda yozing:\n\n"
            "`/add @kanal_nomi`\n\n"
            "*Misol:* `/add @meningkanalim`\n\n"
            "⚠️ *Eslatma:* Botni kanalga ADMIN qilishni unutmang!\n"
            "Botga quyidagi huquqlar kerak:\n"
            "• ✏️ Post joylash huquqi\n"
            "• 👁️ Xabarlarni o'qish huquqi",
            parse_mode="Markdown"
        )
    
    elif data == 'make_payment':
        await payment_command(update, context)
    
    elif data == 'payment_done':
        await query.edit_message_text(
            "📸 *To'lov cheki skrinshotini yuboring:*\n\n"
            "Iltimos, bank to'lov chekining skrinshotini shu yerga yuboring.\n\n"
            "📎 Faqat rasm formatida (jpg, png)\n"
            "⏳ Tasdiqlash uchun 24 soat kuting\n\n"
            "💰 Karta ma'lumotlari:\n"
            f"`{PAYMENT_CARD}`\n"
            f"*{PAYMENT_NAME}*",
            parse_mode="Markdown"
        )
    
    elif data == 'my_channels':
        await my_channels_command(update, context)
    
    elif data == 'help':
        await query.edit_message_text(
            "❓ *Qo'llanma va Ko'p So'raladigan Savollar*\n\n"
            "🤔 *Bot nima qiladi?*\n"
            "Bot sizning kanalingizdagi xabarlarni "
            f"{DESTINATION_GROUP} guruhiga avtomatik ko'chiradi.\n\n"
            "💳 *To'lov qanday qilinadi?*\n"
            "1. /payment komandasini bosing\n"
            "2. Karta ma'lumotlariga 15,000 so'm o'tkazing\n"
            "3. To'lov chekini skrinshotini yuboring\n"
            "4. Admin tasdiqlagach, kanalingiz 30 kun faollashtiriladi\n\n"
            "📢 *Kanal qo'shish?*\n"
            "`/add @kanal_nomi` komandasidan foydalaning\n\n"
            "⚠️ *Muhim eslatmalar:*\n"
            "• Bot kanalda ADMIN bo'lishi kerak\n"
            "• Faqat to'lov qilgan foydalanuvchilar foydalana oladi\n"
            "• Har bir kanal alohida to'lov talab qilmaydi\n"
            "• Bir foydalanuvchi bir nechta kanal qo'shishi mumkin\n\n"
            "📞 *Qo'llab-quvvatlash:*\n"
            f"Admin: @admin_username yoki {ADMIN_ID}",
            parse_mode="Markdown"
        )
    
    elif data == 'admin_panel':
        await admin_command(update, context)
    
    elif data == 'pending_payments':
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        payments = await get_pending_payments()
        
        if not payments:
            await query.edit_message_text("✅ *Kutilayotgan to'lovlar yo'q!*", parse_mode="Markdown")
            return
        
        text = "⏳ *Kutilayotgan to'lovlar:*\n\n"
        
        keyboard = []
        for payment in payments:
            text += f"📋 ID: #{payment['id']}\n"
            text += f"👤 Foydalanuvchi: @{payment['username'] or payment['first_name']}\n"
            text += f"💰 Summa: {payment['amount']:,} so'm\n"
            text += f"⏰ Vaqt: {payment['created_at'][:16]}\n"
            text += "─" * 20 + "\n"
            
            keyboard.append([
                InlineKeyboardButton(f"✅ Tasdiqlash #{payment['id']}", callback_data=f'confirm_{payment["id"]}'),
                InlineKeyboardButton(f"❌ Rad etish #{payment['id']}", callback_data=f'reject_{payment["id"]}')
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data='admin_panel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    elif data.startswith('confirm_'):
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        payment_id = int(data.split('_')[1])
        success = await confirm_payment(payment_id, user.id, "Admin tomonidan tasdiqlandi")
        
        if success:
            await query.edit_message_text(
                f"✅ *To'lov tasdiqlandi!*\n\n"
                f"📋 To'lov ID: #{payment_id}\n"
                f"✅ Foydalanuvchi 30 kun davomida faollashtirildi!\n\n"
                "📩 Foydalanuvchiga xabar yuborildi.",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "❌ *To'lovni tasdiqlashda xatolik!*\n\n"
                "Iltimos, qayta urinib ko'ring.",
                parse_mode="Markdown"
            )
    
    elif data == 'admin_stats':
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        stats = await get_stats()
        
        text = "📊 *Bot Statistika:*\n\n"
        text += f"👥 Jami foydalanuvchilar: *{stats.get('total_users', 0)}*\n"
        text += f"✅ Faol foydalanuvchilar: *{stats.get('active_users', 0)}*\n"
        text += f"📢 Jami kanallar: *{stats.get('total_channels', 0)}*\n"
        text += f"💰 Jami daromad: *{stats.get('total_income', 0):,} so'm*\n"
        text += f"⏳ Kutilayotgan to'lovlar: *{stats.get('pending_payments', 0)} ta*\n\n"
        text += f"💳 Oyiga: *{PAYMENT_AMOUNT:,} so'm*\n"
        text += f"👑 Admin: *{ADMIN_ID}*"
        
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif data == 'all_users':
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        users = await get_all_users()
        
        if not users:
            await query.edit_message_text("📭 *Foydalanuvchilar topilmadi!*", parse_mode="Markdown")
            return
        
        text = f"👥 *Barcha foydalanuvchilar* ({len(users)} ta)\n\n"
        
        for i, u in enumerate(users[:20], 1):  # Faqat birinchi 20 tasi
            status_icon = "🟢" if u['status'] == 'active' else "🔴"
            text += f"{i}. {status_icon} @{u['username'] or u['first_name']}\n"
            text += f"   📊 Holat: {u['status']}\n"
            text += f"   📢 Kanallar: {u['channel_count']} ta\n"
            if u['expires_at']:
                text += f"   ⏰ Muddati: {u['expires_at'][:10]}\n"
            text += "─" * 20 + "\n"
        
        if len(users) > 20:
            text += f"\n... va yana {len(users) - 20} ta foydalanuvchi"
        
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif data == 'main_menu':
        await start_command(update, context)

async def confirm_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """To'lovni tasdiqlash komandasi (faqat admin)"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ To'lov ID sini kiriting: /confirm_123")
        return
    
    try:
        payment_id = int(context.args[0])
        success = await confirm_payment(payment_id, user.id, "Komanda orqali tasdiqlandi")
        
        if success:
            await update.message.reply_text(f"✅ To'lov #{payment_id} tasdiqlandi!")
        else:
            await update.message.reply_text(f"❌ To'lov #{payment_id} topilmadi!")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID format!")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reklama yuborish (faqat admin)"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Xabar matnini kiriting: /broadcast Salom hammaga!")
        return
    
    message = ' '.join(context.args)
    
    # Barcha faol foydalanuvchilarni olish
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users WHERE status = 'active' AND is_banned = 0") as cursor:
            users = await cursor.fetchall()
    
    sent_count = 0
    failed_count = 0
    
    for user_row in users:
        try:
            await context.bot.send_message(
                chat_id=user_row[0],
                text=f"📢 *Admin xabari:*\n\n{message}",
                parse_mode="Markdown"
            )
            sent_count += 1
            await asyncio.sleep(0.1)  # Rate limit uchun
        except Exception as e:
            failed_count += 1
            logger.error(f"Reklama yuborishda xatolik {user_row[0]}: {e}")
    
    await update.message.reply_text(
        f"✅ Reklama yuborildi!\n\n"
        f"✅ Muvaffaqiyatli: {sent_count}\n"
        f"❌ Xatolik: {failed_count}\n"
        f"📊 Jami: {sent_count + failed_count}"
    )

# ====================== MAIN APPLICATION ======================
async def setup_webhook():
    """Webhook sozlash"""
    if WEBHOOK_URL:
        try:
            await application.bot.set_webhook(
                url=f"{WEBHOOK_URL}/api/webhook",
                drop_pending_updates=True
            )
            logger.info(f"✅ Webhook sozlandi: {WEBHOOK_URL}")
        except Exception as e:
            logger.error(f"❌ Webhook sozlashda xatolik: {e}")

async def main():
    """Asosiy funksiya"""
    global application
    
    # Ma'lumotlar bazasini yaratish
    await init_database()
    
    # Application yaratish
    application = Application.builder().token(TOKEN).build()
    
    # Handlerlarni qo'shish
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add", add_channel_command))
    application.add_handler(CommandHandler("payment", payment_command))
    application.add_handler(CommandHandler("channels", my_channels_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("confirm", confirm_payment_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))
    
    # Webhook sozlash
    await setup_webhook()
    
    if not WEBHOOK_URL:
        # Polling rejimi (mahalliy ishlash uchun)
        logger.info("🚀 Bot polling rejimida ishga tushmoqda...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        
        # Doimiy ishlash
        while True:
            await asyncio.sleep(3600)

# ====================== VERCEL HANDLER ======================
async def vercel_handler(request):
    """Vercel serverless handler"""
    try:
        # JSON ma'lumotlarini olish
        body = await request.json()
        
        # Update yaratish
        update = Update.de_json(body, application.bot)
        
        # Update ni qayta ishlash
        await application.process_update(update)
        
        return {
            'statusCode': HTTPStatus.OK,
            'body': json.dumps({'ok': True})
        }
        
    except Exception as e:
        logger.error(f"Webhook xatosi: {e}")
        return {
            'statusCode': HTTPStatus.INTERNAL_SERVER_ERROR,
            'body': json.dumps({'error': str(e)})
        }

# ====================== ENTRY POINT ======================
if __name__ == "__main__":
    # Mahalliy ishlash uchun
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--polling":
        # Polling rejimida ishlatish
        asyncio.run(main())
    else:
        # Vercel uchun
        print("Bot ready for Vercel deployment")
