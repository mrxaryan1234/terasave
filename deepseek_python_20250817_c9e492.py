import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    CallbackQueryHandler
)
import pymongo
from bson.objectid import ObjectId

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Database setup
client = pymongo.MongoClient(os.getenv("MONGO_URI"))
db = client["terabot_db"]
users_col = db["users"]
downloads_col = db["downloads"]

# Bot configuration
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = "@botupdateshere"
ADMIN_ID = int(os.getenv("ADMIN_ID"))
TOKEN_DURATION = timedelta(hours=4)
REFERRAL_DURATION = timedelta(hours=8)

async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Check if user exists
    user = users_col.find_one({"user_id": user_id})
    
    if not user:
        # New user registration
        is_referred = len(context.args) > 0 and context.args[0].startswith("_tgr_")
        
        users_col.insert_one({
            "user_id": user_id,
            "chat_id": chat_id,
            "join_date": datetime.now(),
            "is_member": False,
            "token_expiry": None,
            "is_referred": is_referred,
            "referral_code": f"ref_{user_id}",
            "referral_count": 0,
            "download_count": 0
        })
        
        # Send channel join prompt
        keyboard = [
            [InlineKeyboardButton("Join Channel", url=f"https://t.me/{CHANNEL_ID[1:]}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚠️ बॉट का उपयोग करने के लिए कृपया हमारे चैनल से जुड़ें:",
            reply_markup=reply_markup
        )
    else:
        # Existing user - check membership
        if not user.get("is_member", False):
            await update.message.reply_text("कृपया चैनल से जुड़ने के बाद /start टाइप करें")
        else:
            await send_welcome_message(update, user)

async def send_welcome_message(update: Update, user):
    user_id = user["user_id"]
    now = datetime.now()
    
    if user.get("token_expiry") and now < user["token_expiry"]:
        # Token still valid
        expiry_time = user["token_expiry"].strftime("%d/%m/%Y %I:%M %p")
        await update.message.reply_text(
            f"🎉 आपका टोकन {expiry_time} तक वैध है\n\n"
            "📥 टेराबॉक्स लिंक भेजकर डाउनलोड शुरू करें"
        )
    else:
        # Generate new token
        duration = REFERRAL_DURATION if user.get("is_referred") else TOKEN_DURATION
        token_expiry = now + duration
        
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"token_expiry": token_expiry}}
        )
        
        expiry_time = token_expiry.strftime("%d/%m/%Y %I:%M %p")
        referral_link = f"https://t.me/{(await context.bot.get_me()).username}?start=ref_{user_id}"
        
        await update.message.reply_text(
            f"🔑 आपको {duration.hours} घंटे का टोकन मिला है (वैध तक: {expiry_time})\n\n"
            f"📤 अपना रेफरल लिंक: {referral_link}\n"
            "🚀 अब आप टेराबॉक्स लिंक भेजकर डाउनलोड कर सकते हैं"
        )

async def check_membership(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})
    
    if not user:
        await update.message.reply_text("कृपया पहले /start टाइप करें")
        return
    
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        if chat_member.status in ["member", "administrator", "creator"]:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"is_member": True}}
            )
            await send_welcome_message(update, user)
        else:
            await update.message.reply_text("❌ आप अभी भी चैनल मेंबर नहीं हैं")
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        await update.message.reply_text("मेंबरशिप चेक करने में त्रुटि, कृपया बाद में पुनः प्रयास करें")

async def handle_download(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user = users_col.find_one({"user_id": user_id})
    
    if not user or not user.get("is_member"):
        await update.message.reply_text("कृपया पहले चैनल से जुड़ें और /start टाइप करें")
        return
    
    if not user.get("token_expiry") or datetime.now() > user["token_expiry"]:
        await update.message.reply_text(
            "⚠️ आपका टोकन समाप्त हो गया है\n\n"
            "🔄 नया टोकन पाने के लिए /start टाइप करें"
        )
        return
    
    # Process download (simplified example)
    terabox_url = update.message.text
    download_url = "https://shrinkme.ink/XdxAjM"  # Replace with actual download logic
    
    # Save download record
    downloads_col.insert_one({
        "user_id": user_id,
        "terabox_url": terabox_url,
        "download_url": download_url,
        "timestamp": datetime.now()
    })
    
    # Send to admin
    await context.bot.send_message(
        ADMIN_ID,
        f"📥 नया डाउनलोड रिक्वेस्ट\n\n"
        f"👤 यूजर: {user_id}\n"
        f"🔗 लिंक: {terabox_url}"
    )
    
    # Send to user
    await update.message.reply_text(
        f"✅ डाउनलोड तैयार है:\n\n{download_url}\n\n"
        "⚠️ यह लिंक 24 घंटे तक वैध रहेगा"
    )

async def broadcast(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ अनधिकृत पहुंच")
        return
    
    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    
    users = users_col.find({})
    count = 0
    for user in users:
        try:
            await context.bot.send_message(user["chat_id"], message)
            count += 1
        except Exception as e:
            logger.error(f"Failed to send to {user['user_id']}: {e}")
    
    await update.message.reply_text(f"✅ ब्रॉडकास्ट {count} यूजर्स को भेजा गया")

def main():
    application = ApplicationBuilder().token(TOKEN).build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_membership))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_download))
    
    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()