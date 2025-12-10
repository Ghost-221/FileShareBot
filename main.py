import os
import string
import random
import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from motor.motor_asyncio import AsyncIOMotorClient
from aiohttp import web

# ================= CONFIGURATION =================
API_ID = 34833810
API_HASH = "6b16568fca91a646a2e2e1cae94f5bb6"
BOT_TOKEN = "8501752321:AAFmSLnhtO0jdlLyyrtPKdPFnL1nVPUkdDk"

# অ্যাডমিন লিস্ট
ADMIN_IDS = [6872143322, 8363437161]

# MongoDB URL
MONGO_URL = "mongodb+srv://atkcyber5_db_user:adminabir221@cluster0.4iwef3e.mongodb.net/?appName=Cluster0"

# ⚠️ চ্যানেল আইডি (আপনার দেওয়া)
LOG_CHANNEL = -1003455503034

# ================= BOT CLIENT =================
app = Client(
    "my_bot", 
    api_id=API_ID, 
    api_hash=API_HASH, 
    bot_token=BOT_TOKEN,
    workers=10,
    in_memory=True
)

# গ্লোবাল ভেরিয়েবল
temp_data = {}
mongo_client = None
collection = None

# ================= HELPER FUNCTIONS =================
def generate_id():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def generate_pass(length=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=6))

def get_file_id(msg: Message):
    if msg.media:
        for message_type in ("photo", "video", "audio", "document", "voice", "animation"):
            obj = getattr(msg, message_type)
            if obj:
                if message_type == "photo":
                    return obj[-1].file_id
                return obj.file_id
    return None

# ================= DATABASE CONNECTION =================
async def init_db():
    global mongo_client, collection
    print("⏳ Connecting to MongoDB...", flush=True)
    try:
        mongo_client = AsyncIOMotorClient(MONGO_URL)
        db = mongo_client["FileShareBot"]
        collection = db["files"]
        print("✅ MongoDB Connected Successfully!", flush=True)
    except Exception as e:
        print(f"❌ MongoDB Connection Failed: {e}", flush=True)

# ================= BOT COMMANDS =================

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    user_id = message.from_user.id
    
    if collection is None:
        await message.reply_text("❌ Database Error! Admin check logs.")
        return

    if len(message.command) > 1:
        unique_id = message.command[1]
        file_data = await collection.find_one({"_id": unique_id})
        
        if file_data:
            limit = file_data.get("limit", 0)
            used = file_data.get("used", 0)

            if limit > 0 and used >= limit:
                await message.reply_text("❌ **দুঃখিত! এই লিংকের মেয়াদ শেষ।**")
                return

            await message.reply_text(
                "🔒 **ফাইলটি লক করা!**\n\n👇 নিচে পাসওয়ার্ডটি লিখুন:", 
                quote=True
            )
            temp_data[f"wait_pass_{user_id}"] = unique_id
        else:
            await message.reply_text("❌ ফাইলটি পাওয়া যায়নি।")
        return

    if user_id in ADMIN_IDS:
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data="stats")]
        ])
        await message.reply_text(
            f"⚡ **অ্যাডমিন প্যানেল**\n\nফাইল সেভ করতে ফাইল সেন্ড করুন।",
            reply_markup=buttons
        )
    else:
        await message.reply_text(f"হ্যালো {message.from_user.first_name}! 👋")

# ================= ADMIN HANDLER =================
@app.on_message(filters.private & (filters.document | filters.video | filters.audio | filters.photo) & filters.user(ADMIN_IDS))
async def handle_file_upload(client, message: Message):
    user_id = message.from_user.id
    status_msg = await message.reply_text("⏳ **ফাইল প্রসেস হচ্ছে...**", quote=True)
    
    try:
        log_msg = await message.copy(chat_id=LOG_CHANNEL)
        file_id = get_file_id(log_msg)
        
        if not file_id:
            await status_msg.edit_text("❌ ফাইল আইডি পাওয়া যায়নি!")
            return

        temp_data[f"setup_{user_id}"] = {
            "file_id": file_id,
            "caption": message.caption or ""
        }
        
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ কাস্টম পাস", callback_data="set_custom_pass"), 
             InlineKeyboardButton("🎲 অটো পাস", callback_data="set_auto_pass")],
            [InlineKeyboardButton("❌ বাতিল", callback_data="cancel_process")]
        ])
        await status_msg.edit_text("✅ **ফাইল আপলোড হয়েছে!**\nপাসওয়ার্ড সেট করুন:", reply_markup=buttons)

    except Exception as e:
        await status_msg.edit_text(f"❌ এরর: {e}\nচ্যানেল আইডি চেক করুন এবং বটকে অ্যাডমিন করুন।")

# ================= CALLBACK HANDLERS =================
@app.on_callback_query()
async def callback_handler(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if user_id not in ADMIN_IDS: return

    if data == "set_custom_pass":
        temp_data[f"mode_{user_id}"] = "waiting_custom_pass"
        await callback_query.message.edit_text("✍️ **পাসওয়ার্ড লিখুন:**")

    elif data == "set_auto_pass":
        temp_data[f"setup_{user_id}"]["password"] = generate_pass()
        await ask_limit(callback_query.message)

    elif data.startswith("limit_"):
        if data == "limit_custom":
            temp_data[f"mode_{user_id}"] = "waiting_custom_limit"
            await callback_query.message.edit_text("🔢 **কতজন? (সংখ্যা):**")
        else:
            limit_val = int(data.split("_")[1])
            await finalize_upload(client, callback_query.message, user_id, limit_val)

    elif data == "cancel_process":
        temp_data.pop(f"setup_{user_id}", None)
        await callback_query.message.delete()

    elif data == "stats":
        total = await collection.count_documents({})
        await callback_query.answer(f"📊 মোট ফাইল: {total}", show_alert=True)

async def ask_limit(message):
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("∞ আনলিমিটেড", callback_data="limit_0"), 
         InlineKeyboardButton("১ জন", callback_data="limit_1"),
         InlineKeyboardButton("✏️ কাস্টম", callback_data="limit_custom")]
    ])
    await message.edit_text("🚧 **লিমিট কত?**", reply_markup=buttons)

async def finalize_upload(client, message, user_id, limit):
    if collection is None: return
    setup = temp_data.get(f"setup_{user_id}")
    if not setup: return

    unique_id = generate_id()
    await collection.insert_one({
        "_id": unique_id,
        "file_id": setup["file_id"],
        "caption": setup["caption"],
        "password": setup["password"],
        "limit": limit,
        "used": 0
    })
    del temp_data[f"setup_{user_id}"]
    
    bot_username = (await client.get_me()).username
    link = f"https://t.me/{bot_username}?start={unique_id}"
    await message.edit_text(f"✅ **Done!**\n🔗 `{link}`\n🔑 `{setup['password']}`")

# ================= TEXT HANDLER =================
@app.on_message(filters.text & filters.private)
async def handle_text(client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    if temp_data.get(f"mode_{user_id}") == "waiting_custom_pass":
        temp_data[f"setup_{user_id}"]["password"] = text
        del temp_data[f"mode_{user_id}"]
        await ask_limit(message)
        return

    if temp_data.get(f"mode_{user_id}") == "waiting_custom_limit":
        if text.isdigit():
            del temp_data[f"mode_{user_id}"]
            await finalize_upload(client, message, user_id, int(text))
        return

    if f"wait_pass_{user_id}" in temp_data:
        unique_id = temp_data[f"wait_pass_{user_id}"]
        file_data = await collection.find_one({"_id": unique_id})
        
        if not file_data:
            await message.reply_text("❌ ফাইল নেই।")
            del temp_data[f"wait_pass_{user_id}"]
            return

        limit = file_data.get("limit", 0)
        used = file_data.get("used", 0)
        if limit > 0 and used >= limit:
            await message.reply_text("❌ মেয়াদ শেষ!")
            del temp_data[f"wait_pass_{user_id}"]
            return

        if text == file_data['password']:
            del temp_data[f"wait_pass_{user_id}"]
            await collection.update_one({"_id": unique_id}, {"$inc": {"used": 1}})
            await message.reply_text("✅ সঠিক পাসওয়ার্ড!")
            await client.send_cached_media(message.chat.id, file_data['file_id'], caption=file_data.get('caption', ""))
        else:
            await message.reply_text("❌ ভুল পাসওয়ার্ড!")

# ================= RUNNER =================
async def main():
    async def handle(request): return web.Response(text="Bot Live")
    app_web = web.Application()
    app_web.router.add_get("/", handle)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()

    await init_db()
    print("🤖 Bot Starting...", flush=True)
    await app.start()
    await idle()
    await app.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
