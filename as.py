import os
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional

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
TOKEN = "8545035071:AAEngg_8PeQ5B4KFrJzWfiBKBjIJxWlR4xc"
ADMIN_ID = 6762465157
DESTINATION_GROUP = "@Angren_Toshkent_Taksi_pochta_a"
PAYMENT_AMOUNT = 15000
PAYMENT_CARD = "9860356634199596"
PAYMENT_NAME = "TURGUNBOYEV Biloliddin"

# ====================== LOGGING ======================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ====================== DATABASE ======================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        cursor = self.conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                status TEXT DEFAULT 'inactive',
                balance INTEGER DEFAULT 0,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_banned INTEGER DEFAULT 0
            )
        ''')
        
        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                screenshot_id TEXT,
                status TEXT DEFAULT 'pending',
                admin_note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP,
                confirmed_by INTEGER
            )
        ''')
        
        # Channels table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                channel_username TEXT UNIQUE,
                channel_id TEXT,
                is_active INTEGER DEFAULT 1,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                forward_count INTEGER DEFAULT 0
            )
        ''')
        
        # Admin logs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
        logger.info("✅ Database tables created")
    
    def register_user(self, user_id: int, username: str, first_name: str):
        cursor = self.conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, username, first_name) 
                VALUES (?, ?, ?)
            ''', (user_id, username, first_name))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Register user error: {e}")
            return False
    
    def get_user(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            return {
                'user_id': row[0],
                'username': row[1],
                'first_name': row[2],
                'status': row[3],
                'balance': row[4],
                'registered_at': row[5],
                'expires_at': row[6],
                'is_banned': row[7]
            }
        return None
    
    def update_user_status(self, user_id: int, status: str, days: int = 30):
        cursor = self.conn.cursor()
        expires_at = datetime.now() + timedelta(days=days)
        cursor.execute('''
            UPDATE users 
            SET status = ?, expires_at = ?, is_banned = 0 
            WHERE user_id = ?
        ''', (status, expires_at.isoformat(), user_id))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def add_channel(self, user_id: int, channel_username: str):
        cursor = self.conn.cursor()
        try:
            channel_username = channel_username.replace('@', '').strip()
            cursor.execute('''
                INSERT OR REPLACE INTO channels (user_id, channel_username) 
                VALUES (?, ?)
            ''', (user_id, channel_username))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Add channel error: {e}")
            return False
    
    def get_user_channels(self, user_id: int):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT channel_username, added_at, forward_count 
            FROM channels 
            WHERE user_id = ? AND is_active = 1
        ''', (user_id,))
        return cursor.fetchall()
    
    def create_payment(self, user_id: int, screenshot_id: str = None):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO payments (user_id, amount, screenshot_id) 
            VALUES (?, ?, ?)
        ''', (user_id, PAYMENT_AMOUNT, screenshot_id))
        self.conn.commit()
        return cursor.lastrowid
    
    def confirm_payment(self, payment_id: int, admin_id: int):
        cursor = self.conn.cursor()
        
        # Get user_id from payment
        cursor.execute('SELECT user_id FROM payments WHERE id = ?', (payment_id,))
        result = cursor.fetchone()
        if not result:
            return False
        
        user_id = result[0]
        
        # Update payment status
        cursor.execute('''
            UPDATE payments 
            SET status = 'confirmed', 
                confirmed_at = ?,
                confirmed_by = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), admin_id, payment_id))
        
        # Activate user
        self.update_user_status(user_id, 'active', 30)
        
        # Add admin log
        cursor.execute('''
            INSERT INTO admin_logs (admin_id, action, target_id, details)
            VALUES (?, ?, ?, ?)
        ''', (admin_id, 'confirm_payment', user_id, f'Payment #{payment_id} confirmed'))
        
        self.conn.commit()
        return True
    
    def get_pending_payments(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT p.id, p.user_id, u.username, u.first_name, p.amount, p.screenshot_id, p.created_at
            FROM payments p
            JOIN users u ON p.user_id = u.user_id
            WHERE p.status = 'pending'
            ORDER BY p.created_at DESC
        ''')
        return cursor.fetchall()
    
    def get_channel_info(self, channel_username: str):
        cursor = self.conn.cursor()
        channel_username = channel_username.replace('@', '').strip()
        cursor.execute('''
            SELECT c.user_id, u.status, u.expires_at
            FROM channels c
            JOIN users u ON c.user_id = u.user_id
            WHERE c.channel_username = ? AND c.is_active = 1
        ''', (channel_username,))
        return cursor.fetchone()
    
    def update_channel_stats(self, channel_username: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE channels 
            SET forward_count = forward_count + 1 
            WHERE channel_username = ?
        ''', (channel_username,))
        self.conn.commit()
    
    def get_all_users(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT u.user_id, u.username, u.first_name, u.status, 
                   u.expires_at, COUNT(c.id) as channel_count
            FROM users u
            LEFT JOIN channels c ON u.user_id = c.user_id AND c.is_active = 1
            GROUP BY u.user_id
            ORDER BY u.registered_at DESC
        ''')
        return cursor.fetchall()
    
    def get_stats(self):
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE status = 'active'")
        active_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM channels WHERE is_active = 1")
        total_channels = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'confirmed'")
        total_income = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
        pending_payments = cursor.fetchone()[0]
        
        return {
            'total_users': total_users,
            'active_users': active_users,
            'total_channels': total_channels,
            'total_income': total_income,
            'pending_payments': pending_payments
        }

# Initialize database
db = Database()

# ====================== BOT HANDLERS ======================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    
    # Register user
    db.register_user(user.id, user.username or "", user.first_name)
    
    # Create menu
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
        "🤖 *Toshkent-Angren Taksi Xabar Forward Bot*\n\n"
        "📥 Sizning kanalingizdagi xabarlar avtomatik ravishda\n"
        f"📤 {DESTINATION_GROUP} guruhiga ko'chiriladi!\n\n"
        "⚡️ *Botdan foydalanish:*\n"
        "1️⃣ Botni kanalingizga ADMIN qiling\n"
        "2️⃣ Kanalni qo'shing\n"
        "3️⃣ To'lov qiling (15,000 so'm / oy)\n"
        "4️⃣ Xabarlar avtomatik ko'chiriladi!\n\n"
        "⚠️ *Diqqat:* Bot ADMIN bo'lmaguncha ishlamaydi!",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def add_channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add channel command"""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text(
            "📢 *Kanal qo'shish uchun:*\n\n"
            "Quyidagi formatda yozing:\n"
            "`/add @kanal_nomi`\n\n"
            "*Misol:* `/add @meningkanalim`\n\n"
            "⚠️ *Eslatma:* Botni avval kanalga ADMIN qiling!",
            parse_mode="Markdown"
        )
        return
    
    channel_username = context.args[0]
    success = db.add_channel(user.id, channel_username)
    
    if success:
        await update.message.reply_text(
            f"✅ *Kanal qo'shildi!*\n\n"
            f"📢 Kanal: @{channel_username.replace('@', '')}\n\n"
            "*Endi quyidagi amallarni bajaring:*\n"
            f"1. Botni @{channel_username.replace('@', '')} kanaliga *ADMIN* qiling\n"
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
    """Payment command"""
    keyboard = [
        [InlineKeyboardButton("💳 To'lov qildim", callback_data='payment_done')],
        [InlineKeyboardButton("📞 Admin bilan bog'lanish", callback_data='contact_admin')],
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
        "✅ *To'lov tasdiqlangach, kanalingiz 30 kun davomida faollashtiriladi!*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def my_channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """My channels command"""
    user = update.effective_user
    channels = db.get_user_channels(user.id)
    
    if not channels:
        await update.message.reply_text(
            "📭 *Sizda hali kanal mavjud emas!*\n\n"
            "Kanal qo'shish uchun: /add @kanal_nomi\n"
            "Yoki pastdagi tugmani bosing:",
            parse_mode="Markdown"
        )
        return
    
    # Check user status
    user_info = db.get_user(user.id)
    status_text = "🟢 Faol" if user_info and user_info['status'] == 'active' else "🔴 Faol emas"
    
    text = f"📊 *Mening kanallarim* ({len(channels)} ta)\n"
    text += f"📈 Holatim: {status_text}\n\n"
    
    for i, channel in enumerate(channels, 1):
        channel_name, added_at, forward_count = channel
        text += f"{i}. *{channel_name}*\n"
        text += f"   👁️ @{channel_name}\n"
        text += f"   📊 {forward_count} marta ko'chirilgan\n"
        text += f"   ⏰ Qo'shilgan: {added_at[:10]}\n\n"
    
    text += "🔧 *Sozlamalar:*\n"
    text += "• Kanal qo'shish: /add @kanal_nomi\n"
    text += "• To'lov qilish: /payment\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin panel"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ *Siz admin emassiz!*", parse_mode="Markdown")
        return
    
    stats = db.get_stats()
    pending_payments = db.get_pending_payments()
    
    # Create admin keyboard
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
        f"• 👥 Jami foydalanuvchilar: {stats['total_users']}\n"
        f"• ✅ Faol foydalanuvchilar: {stats['active_users']}\n"
        f"• 📢 Jami kanallar: {stats['total_channels']}\n"
        f"• 💰 Jami daromad: {stats['total_income']:,} so'm\n"
        f"• ⏳ Kutilayotgan to'lovlar: {len(pending_payments)} ta\n\n"
        f"🛠️ *Admin amallari:*",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def handle_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Forward messages from channels"""
    try:
        message = update.channel_post or update.message
        
        if not message:
            return
        
        # Get chat info
        chat = message.chat
        username = chat.username if hasattr(chat, 'username') else str(chat.id)
        
        logger.info(f"📨 Yangi xabar: {username} -> {message.message_id}")
        
        # Check channel access
        channel_info = db.get_channel_info(username)
        
        if channel_info:
            user_id, status, expires_at = channel_info
            
            # Check if user is active and not expired
            if status == 'active':
                if expires_at:
                    expires_date = datetime.fromisoformat(expires_at)
                    if datetime.now() > expires_date:
                        # Expired
                        db.update_user_status(user_id, 'expired')
                        logger.info(f"❌ Foydalanuvchi muddati tugagan: {user_id}")
                        return
                
                # Forward message
                await context.bot.forward_message(
                    chat_id=DESTINATION_GROUP,
                    from_chat_id=chat.id,
                    message_id=message.message_id
                )
                
                # Update stats
                db.update_channel_stats(username)
                
                logger.info(f"✅ Forward qilindi: {username} -> {DESTINATION_GROUP}")
            else:
                logger.info(f"❌ Foydalanuvchi faol emas: {user_id} - {status}")
        else:
            logger.info(f"❌ Kanal topilmadi: {username}")
            
    except Exception as e:
        logger.error(f"❌ Xatolik: {e}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment screenshots"""
    user = update.effective_user
    
    if not update.message.photo:
        return
    
    # Get the largest photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    
    # Create payment
    payment_id = db.create_payment(user.id, file.file_id)
    
    if payment_id:
        await update.message.reply_text(
            f"✅ *To'lov cheki qabul qilindi!*\n\n"
            f"📋 To'lov ID: *#{payment_id}*\n"
            f"👤 Siz: @{user.username or user.first_name}\n"
            f"💰 Summa: *{PAYMENT_AMOUNT:,} so'm*\n"
            f"📅 Muddati: *30 kun*\n\n"
            "⏳ *Admin tomonidan tekshirilmoqda...*\n"
            "Tasdiqlash uchun *24 soat* kuting.",
            parse_mode="Markdown"
        )
        
        # Notify admin
        try:
            user_channels = db.get_user_channels(user.id)
            channels_text = "\n".join([f"• @{ch[0]}" for ch in user_channels[:3]]) or "Kanal yo'q"
            
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
                       f"✅ Tasdiqlash: /confirm {payment_id}\n"
                       f"❌ Rad etish: /reject {payment_id}",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"❌ Adminga xabar yuborishda xatolik: {e}")
    else:
        await update.message.reply_text(
            "❌ *To'lov yaratishda xatolik!*\n\n"
            "Iltimos, qayta urinib ko'ring.",
            parse_mode="Markdown"
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
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
            "⚠️ *Eslatma:* Botni kanalga ADMIN qilishni unutmang!",
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
            f"💰 Karta: `{PAYMENT_CARD}`\n"
            f"👤 Ism: *{PAYMENT_NAME}*",
            parse_mode="Markdown"
        )
    
    elif data == 'my_channels':
        await my_channels_command(update, context)
    
    elif data == 'help':
        await query.edit_message_text(
            "❓ *Qo'llanma va Ko'p So'raladigan Savollar*\n\n"
            "🤔 *Bot nima qiladi?*\n"
            f"Bot sizning kanalingizdagi xabarlarni {DESTINATION_GROUP} guruhiga ko'chiradi.\n\n"
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
            "• Bir foydalanuvchi bir nechta kanal qo'shishi mumkin\n\n"
            f"📞 *Admin:* {ADMIN_ID}",
            parse_mode="Markdown"
        )
    
    elif data == 'admin_panel':
        await admin_command(update, context)
    
    elif data == 'pending_payments':
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        payments = db.get_pending_payments()
        
        if not payments:
            await query.edit_message_text("✅ *Kutilayotgan to'lovlar yo'q!*", parse_mode="Markdown")
            return
        
        text = "⏳ *Kutilayotgan to'lovlar:*\n\n"
        
        keyboard = []
        for payment in payments:
            payment_id, user_id, username, first_name, amount, screenshot_id, created_at = payment
            text += f"📋 ID: #{payment_id}\n"
            text += f"👤 Foydalanuvchi: @{username or first_name}\n"
            text += f"💰 Summa: {amount:,} so'm\n"
            text += f"⏰ Vaqt: {created_at[:16]}\n"
            text += "─" * 20 + "\n"
            
            keyboard.append([
                InlineKeyboardButton(f"✅ #{payment_id}", callback_data=f'confirm_{payment_id}'),
                InlineKeyboardButton(f"❌ #{payment_id}", callback_data=f'reject_{payment_id}')
            ])
        
        keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data='admin_panel')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    
    elif data.startswith('confirm_'):
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        payment_id = int(data.split('_')[1])
        success = db.confirm_payment(payment_id, user.id)
        
        if success:
            await query.edit_message_text(
                f"✅ *To'lov tasdiqlandi!*\n\n"
                f"📋 To'lov ID: #{payment_id}\n"
                f"✅ Foydalanuvchi 30 kun davomida faollashtirildi!",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "❌ *To'lovni tasdiqlashda xatolik!*",
                parse_mode="Markdown"
            )
    
    elif data == 'admin_stats':
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        stats = db.get_stats()
        
        text = "📊 *Bot Statistika:*\n\n"
        text += f"👥 Jami foydalanuvchilar: *{stats['total_users']}*\n"
        text += f"✅ Faol foydalanuvchilar: *{stats['active_users']}*\n"
        text += f"📢 Jami kanallar: *{stats['total_channels']}*\n"
        text += f"💰 Jami daromad: *{stats['total_income']:,} so'm*\n"
        text += f"⏳ Kutilayotgan to'lovlar: *{stats['pending_payments']} ta*\n\n"
        text += f"💳 Oyiga: *{PAYMENT_AMOUNT:,} so'm*\n"
        text += f"👑 Admin: *{ADMIN_ID}*"
        
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif data == 'all_users':
        if user.id != ADMIN_ID:
            await query.answer("Siz admin emassiz!", show_alert=True)
            return
        
        users = db.get_all_users()
        
        if not users:
            await query.edit_message_text("📭 *Foydalanuvchilar topilmadi!*", parse_mode="Markdown")
            return
        
        text = f"👥 *Barcha foydalanuvchilar* ({len(users)} ta)\n\n"
        
        for i, u in enumerate(users[:15], 1):
            user_id, username, first_name, status, expires_at, channel_count = u
            status_icon = "🟢" if status == 'active' else "🔴"
            text += f"{i}. {status_icon} @{username or first_name}\n"
            text += f"   📊 Holat: {status}\n"
            text += f"   📢 Kanallar: {channel_count} ta\n"
            if expires_at:
                text += f"   ⏰ Muddati: {expires_at[:10]}\n"
            text += "─" * 20 + "\n"
        
        if len(users) > 15:
            text += f"\n... va yana {len(users) - 15} ta foydalanuvchi"
        
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif data == 'main_menu':
        await start_command(update, context)
    
    elif data == 'contact_admin':
        await query.edit_message_text(
            f"📞 *Admin bilan bog'lanish:*\n\n"
            f"👤 Admin ID: `{ADMIN_ID}`\n"
            f"📨 Xabar yuborish uchun: @admin_username\n\n"
            "Yoki to'lov chekini shu yerga yuboring.",
            parse_mode="Markdown"
        )

async def confirm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm payment command"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ To'lov ID sini kiriting: /confirm 123")
        return
    
    try:
        payment_id = int(context.args[0])
        success = db.confirm_payment(payment_id, user.id)
        
        if success:
            await update.message.reply_text(f"✅ To'lov #{payment_id} tasdiqlandi!")
        else:
            await update.message.reply_text(f"❌ To'lov #{payment_id} topilmadi!")
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri ID format!")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast to all users"""
    user = update.effective_user
    
    if user.id != ADMIN_ID:
        await update.message.reply_text("❌ Siz admin emassiz!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Xabar matnini kiriting: /broadcast Salom!")
        return
    
    message = ' '.join(context.args)
    
    # Get all active users
    all_users = db.get_all_users()
    active_users = [u[0] for u in all_users if u[3] == 'active']
    
    sent = 0
    failed = 0
    
    for user_id in active_users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 *Admin xabari:*\n\n{message}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception as e:
            failed += 1
    
    await update.message.reply_text(
        f"✅ Reklama yuborildi!\n\n"
        f"✅ Muvaffaqiyatli: {sent}\n"
        f"❌ Xatolik: {failed}\n"
        f"📊 Jami: {len(active_users)}"
    )

# ====================== MAIN FUNCTION ======================
def main():
    """Start the bot"""
    print("=" * 50)
    print("🤖 TOSHKENT-ANGREN TAKSI BOT")
    print(f"🆔 Admin: {ADMIN_ID}")
    print(f"📤 Destination: {DESTINATION_GROUP}")
    print(f"💳 Payment: {PAYMENT_AMOUNT:,} so'm")
    print("=" * 50)
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("add", add_channel_command))
    application.add_handler(CommandHandler("payment", payment_command))
    application.add_handler(CommandHandler("channels", my_channels_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("confirm", confirm_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_forward))
    
    # Start the bot
    print("🚀 Bot ishga tushmoqda...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
