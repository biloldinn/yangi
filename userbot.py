from telethon import TelegramClient, events
import json
import os
import asyncio

# ---------------------------------------------------------
# SOZLAMALAR (CONFIG)
# ---------------------------------------------------------
CONFIG_FILE = 'channel_bot/config.json'

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    print(f"Xatolik: {CONFIG_FILE} topilmadi!")
    return None

config = load_config()

if not config:
    exit()

API_ID = config.get('api_id')
API_HASH = config.get('api_hash')
SOURCES = config.get('sources', [])
DESTINATIONS = config.get('destinations', [])

# Sessiya fayli yaratiladi (bir marta kirish kerak bo'ladi)
client = TelegramClient('channel_bot/userbot_session', API_ID, API_HASH)

print("Bot ishga tushmoqda...")

@client.on(events.NewMessage(chats=SOURCES))
async def handler(event):
    """
    Manba kanallardan yangi xabar kelsa ushlab oladi.
    """
    chat_title = event.chat.title if event.chat else "Noma'lum"
    print(f"📩 Yangi xabar: {chat_title}")

    # Har bir maqsad kanalga nusxasini yuborish
    for dest in DESTINATIONS:
        try:
            # Xabarni nusxalash (Forward emas, Copy)
            # Send message or media
            if event.message.media:
                await client.send_file(dest, event.message.media, caption=event.message.text)
            else:
                await client.send_message(dest, event.message.text)
            
            print(f"✅ Yuborildi: {dest}")
        except Exception as e:
            print(f"❌ Xatolik ({dest}): {e}")

async def main():
    print("Telefonga kod kelishi mumkin, terminalga qarang.")
    await client.start()
    print("Userbot ishga tushdi / Userbot is active.")
    
    # Doimiy ishlash
    await client.run_until_disconnected()

if __name__ == '__main__':
    with client:
        client.loop.run_until_complete(main())
