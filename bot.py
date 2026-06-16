import os
import json
import time
import random
import threading
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ==========================================
# ⚙️ CONFIGURATION (ENVIRONMENT VARIABLES)
# ==========================================
# Railway Dashboard -> Variables tab me ye dono set karein
BOT_TOKEN = os.environ.get("BOT_TOKEN") 
OWNER_ID_STR = os.environ.get("OWNER_ID")

if not BOT_TOKEN or not OWNER_ID_STR:
    raise ValueError("❌ ERROR: Please set BOT_TOKEN and OWNER_ID in your Railway Environment Variables!")

OWNER_ID = int(OWNER_ID_STR)

# ==========================================
# 🚀 INITIALIZATION & SETUP
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
DATA_FILE = "data.json"

db_lock = threading.RLock() 

default_data = {
    "users": {},
    "promos": {},
    "config": {
        "channel_id": "", 
        "channel_link": ""
    },
    "payouts": [] 
}

def load_data():
    with db_lock:
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w") as f:
                json.dump(default_data, f, indent=4)
            return default_data.copy()
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading JSON: {e}")
            return default_data.copy()

def save_data(data):
    """ Atomic save to prevent JSON corruption during Railway restarts """
    with db_lock:
        try:
            temp_file = DATA_FILE + ".tmp"
            with open(temp_file, "w") as f:
                json.dump(data, f, indent=4)
            os.replace(temp_file, DATA_FILE)
        except Exception as e:
            logging.error(f"Error saving JSON: {e}")

db = load_data()

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================
def get_user(user_id):
    uid = str(user_id)
    with db_lock:
        if uid not in db["users"]:
            db["users"][uid] = {
                "balance": 5.0, # 🎉 Signup Bonus ₹5
                "referred_by": None,
                "referrals": 0,
                "upi": None,
                "joined": False
            }
            save_data(db)
    return db["users"][uid]

def mask_upi(upi):
    try:
        if '@' in upi:
            u_part, b_part = upi.split('@', 1)
            random_digits = str(random.randint(1000, 9999))
            return f"{u_part}{random_digits}@{b_part}"
        return f"{upi}{random.randint(1000, 9999)}"
    except:
        return f"***@bank"

def check_fsub(user_id):
    channel_id = db["config"].get("channel_id", "")
    if not channel_id:
        return True # Bypass if admin hasn't configured it
    try:
        status = bot.get_chat_member(channel_id, int(user_id)).status
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.warning(f"FSub error (Allowing bypass to avoid blocking): {e}")
        return True 

def is_menu_button(text):
    buttons = ["👤 My Profile", "🔗 Refer & Earn", "🏦 Bind UPI", "💸 Withdraw", "🎁 Claim Promo"]
    return text in buttons or text.startswith('/')

def process_referral_reward(user_id):
    """ Centralized function to reward referrer exactly once """
    uid = str(user_id)
    notify_ref = False
    ref_id_to_notify = None
    
    with db_lock:
        u = get_user(uid)
        if not u.get("joined", False):
            u["joined"] = True
            ref_id = u.get("referred_by")
            if ref_id and ref_id in db["users"]:
                db["users"][ref_id]["balance"] += 10.0
                db["users"][ref_id]["referrals"] += 1
                notify_ref = True
                ref_id_to_notify = ref_id
            save_data(db)
            
    if notify_ref and ref_id_to_notify:
        try:
            bot.send_message(ref_id_to_notify, f"🎉 **New Referral!**\nAapke dost ne bot/channel join kar liya hai. Aapke wallet me **₹10** add ho gaye hain! 💸")
        except:
            pass

# ==========================================
# 🎛️ KEYBOARDS
# ==========================================
def main_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("👤 My Profile"), 
        KeyboardButton("🔗 Refer & Earn")
    )
    markup.add(
        KeyboardButton("🏦 Bind UPI"), 
        KeyboardButton("💸 Withdraw")
    )
    markup.add(
        KeyboardButton("🎁 Claim Promo")
    )
    return markup

def fsub_keyboard():
    markup = InlineKeyboardMarkup()
    link = db["config"].get("channel_link", "")
    if link:
        markup.add(InlineKeyboardButton("📢 Join Our Channel", url=link))
    markup.add(InlineKeyboardButton("✅ I Have Joined", callback_data="check_join"))
    return markup

# ==========================================
# 👤 USER COMMANDS
# ==========================================
@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        user_id = str(message.from_user.id)
        args = message.text.split()
        
        with db_lock:
            is_new_user = user_id not in db["users"]
        
        get_user(user_id) 

        # Save refer ID if genuinely new user
        if is_new_user and len(args) > 1:
            ref_id = str(args[1])
            with db_lock:
                if ref_id != user_id and ref_id in db["users"]:
                    db["users"][user_id]["referred_by"] = ref_id
            save_data(db)

        # Check FSub status
        has_joined = check_fsub(message.from_user.id)
        
        if not has_joined:
            bot.send_message(message.chat.id, "🛑 **Welcome to DhanSahi!**\n\nAapko bot use karne ke liye pehle hamara official channel join karna hoga.", reply_markup=fsub_keyboard())
            return
        else:
            # Bug Fix: If already joined or no FSub set, give refer reward immediately
            process_referral_reward(user_id)
            
            welcome_text = (
                f"👋 **Welcome to DhanSahi Premium Bot!**\n\n"
                f"🎉 Aapko **₹5 Signup Bonus** de diya gaya hai!\n"
                f"🚀 Apne doston ko invite karein aur per refer **₹10** kamayein.\n\n"
                f"Neeche diye gaye menu se options select karein 👇"
            )
            bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu())
            
    except Exception as e:
        logging.error(f"Error in start: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    try:
        user_id = str(call.from_user.id)
        
        if check_fsub(call.from_user.id):
            try:
                bot.answer_callback_query(call.id, "✅ Verification Successful!")
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            
            process_referral_reward(user_id)
            bot.send_message(call.message.chat.id, "✅ **Verification Successful!**\n\nAb aap DhanSahi bot ke sabhi features use kar sakte hain.", reply_markup=main_menu())
        else:
            bot.answer_callback_query(call.id, "❌ Aapne abhi tak channel join nahi kiya hai! Pehle join karein.", show_alert=True)
    except Exception as e:
        logging.error(f"Error in check_join: {e}")

@bot.message_handler(func=lambda m: m.text == "👤 My Profile")
def profile(message):
    try:
        user_id = str(message.from_user.id)
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        u = get_user(user_id)
        text = (
            f"👤 **Your Profile Dashboard**\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 **User ID:** `{user_id}`\n"
            f"💰 **Balance:** ₹{u['balance']:.2f}\n"
            f"👥 **Total Referrals:** {u['referrals']}\n"
            f"🏦 **Saved UPI:** `{u['upi'] if u['upi'] else 'Not Bound Yet'}`\n"
            f"━━━━━━━━━━━━━━━━━━"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Error in profile: {e}")

@bot.message_handler(func=lambda m: m.text == "🔗 Refer & Earn")
def refer(message):
    try:
        user_id = str(message.from_user.id)
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        bot_info = bot.get_me()
        ref_link = f"https://t.me/{bot_info.username}?start={user_id}"
        text = (
            f"🚀 **Refer & Earn Program** 🚀\n\n"
            f"Apne doston ko invite karein aur kamayein **₹10** per valid refer!\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
            f"*(Note: Referral bonus tabhi milega jab aapka dost bot start karke channel join karega)*"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Error in refer: {e}")

@bot.message_handler(func=lambda m: m.text == "🏦 Bind UPI")
def ask_upi(message):
    try:
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        msg = bot.reply_to(message, "🏦 **Apna valid UPI ID bhejiye:**\n*(Example: name@ybl, number@paytm)*")
        bot.register_next_step_handler(msg, save_upi)
    except Exception as e:
        logging.error(f"Error in ask_upi: {e}")

def save_upi(message):
    try:
        if not message.text: 
            bot.reply_to(message, "❌ Invalid text format. Try again.")
            return
            
        if is_menu_button(message.text):
            bot.reply_to(message, "❌ Action Cancelled.")
            return

        user_id = str(message.from_user.id)
        get_user(user_id) 
        
        upi = message.text.strip()
        if len(upi) < 5 or "@" not in upi:
            bot.reply_to(message, "❌ Invalid UPI ID. Kripya sahi UPI ID bhejein. Phir se '🏦 Bind UPI' button dabayein.")
            return

        with db_lock:
            db["users"][user_id]["upi"] = upi
            save_data(db)
            
        bot.reply_to(message, f"✅ **Success!** Aapka UPI ID `{upi}` successfully bind ho chuka hai.")
    except Exception as e:
        logging.error(f"Error in save_upi: {e}")

@bot.message_handler(func=lambda m: m.text == "🎁 Claim Promo")
def ask_promo(message):
    try:
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        msg = bot.reply_to(message, "🎁 **Promo Code enter karein:**")
        bot.register_next_step_handler(msg, claim_promo)
    except Exception as e:
        logging.error(f"Error in ask_promo: {e}")

def claim_promo(message):
    try:
        if not message.text: 
            bot.reply_to(message, "❌ Invalid text format.")
            return
            
        if is_menu_button(message.text):
            bot.reply_to(message, "❌ Action Cancelled.")
            return

        user_id = str(message.from_user.id)
        get_user(user_id) 
        
        code = message.text.strip().upper()
        success = False
        amount = 0
        error_msg = ""
        
        with db_lock:
            if code in db["promos"]:
                promo = db["promos"][code]
                if user_id in promo["used_by"]:
                    error_msg = "❌ Aap yeh promo code pehle hi use kar chuke hain."
                elif promo["uses"] > 0:
                    promo["uses"] -= 1
                    promo["used_by"].append(user_id)
                    db["users"][user_id]["balance"] += promo["amount"]
                    success = True
                    amount = promo["amount"]
                    save_data(db)
                else:
                    error_msg = "❌ Yeh promo code expire ho chuka hai ya limit khatam ho gayi hai."
            else:
                error_msg = "❌ Invalid Promo Code!"
                
        if success:
            bot.reply_to(message, f"🎉 **Congratulations!**\nAapne promo code claim kar liya hai. **₹{amount}** aapke wallet mein add kar diye gaye hain!")
        else:
            bot.reply_to(message, error_msg)
            
    except Exception as e:
        logging.error(f"Error in claim_promo: {e}")

@bot.message_handler(func=lambda m: m.text == "💸 Withdraw")
def withdraw(message):
    try:
        user_id = str(message.from_user.id)
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        u = get_user(user_id)
        
        if not u["upi"]:
            bot.reply_to(message, "❌ Pehle apna UPI ID bind karein '🏦 Bind UPI' button se.")
            return
        
        if u["balance"] < 190:
            bot.reply_to(message, f"❌ **Minimum withdrawal ₹190 hai.**\nAapka current balance sirf ₹{u['balance']:.2f} hai.")
            return

        amount = u["balance"]
        tax = amount * 0.05
        final_amount = amount - tax
        upi_id = u["upi"]

        admin_text = (
            f"🚨 **New Withdrawal Alert!**\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"💰 Total Amount: ₹{amount:.2f}\n"
            f"💳 To Pay (after tax): ₹{final_amount:.2f}\n"
            f"🏦 UPI: `{upi_id}`\n\n"
            f"👇 Approve (Starts 110-min countdown):\n"
            f"`/pay {user_id} {final_amount:.2f} {upi_id}`"
        )
        
        try:
            bot.send_message(OWNER_ID, admin_text)
        except Exception as admin_err:
            bot.reply_to(message, "❌ Server busy hai (Admin Notification Failed). Aapka balance safe hai, kripya thodi der mein try karein.")
            logging.error(f"Admin notify failed: {admin_err}")
            return

        with db_lock:
            db["users"][user_id]["balance"] = 0.0
            save_data(db)

        bot.reply_to(message, f"⏳ **Withdrawal Request Submitted!**\n\n"
                              f"💰 **Amount Requested:** ₹{amount:.2f}\n"
                              f"🧾 **Platform Tax (5%):** ₹{tax:.2f}\n"
                              f"💳 **Receiving Amount:** ₹{final_amount:.2f}\n"
                              f"🏦 **UPI ID:** `{upi_id}`\n\n"
                              f"⚠️ *Aapka withdrawal pending hai. Isey cancel nahi kiya jaa sakta. Kripya wait karein.*")

    except Exception as e:
        logging.error(f"Error in withdraw: {e}")

# ==========================================
# 👑 ADMIN PANEL COMMANDS
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID):
            return
        
        with db_lock:
            total_users = len(db["users"])
            total_balance = sum(u["balance"] for u in db["users"].values())
        
        text = (
            f"👑 **DhanSahi Admin Panel** 👑\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 **Total Users:** {total_users}\n"
            f"💰 **Total Balance in System:** ₹{total_balance:.2f}\n\n"
            f"🛠️ **Admin Commands:**\n"
            f"`/setchannel @username https://link` - Set FSub Channel\n"
            f"`/makepromo CODE AMOUNT USES` - Create a new promo\n"
            f"`/pay USER_ID AMOUNT UPI` - Start 110m delay payout timer"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Error in admin_panel: {e}")

@bot.message_handler(commands=['setchannel'])
def set_channel(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "❌ Format Error. Use:\n`/setchannel @yourchannel https://t.me/yourchannel`")
            return

        channel_id = args[1]
        channel_link = args[2]
        with db_lock:
            db["config"]["channel_id"] = channel_id
            db["config"]["channel_link"] = channel_link
            save_data(db)
        bot.reply_to(message, f"✅ Force Subscribe updated!\nID: {channel_id}\nLink: {channel_link}\n*(Make sure bot is admin in the channel)*")
    except Exception as e:
        logging.error(f"Error in setchannel: {e}")

@bot.message_handler(commands=['makepromo'])
def make_promo(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()
        if len(args) < 4:
            bot.reply_to(message, "❌ Format Error. Use:\n`/makepromo CODE AMOUNT USES`")
            return

        code = args[1].upper()
        amount = float(args[2])
        uses = int(args[3])
        
        with db_lock:
            db["promos"][code] = {
                "amount": amount,
                "uses": uses,
                "used_by": []
            }
            save_data(db)
        bot.reply_to(message, f"✅ **Promo Created!**\n🎟️ Code: `{code}`\n💰 Amount: ₹{amount}\n👥 Uses: {uses}")
    except Exception as e:
        logging.error(f"Error in makepromo: {e}")

@bot.message_handler(commands=['pay'])
def pay_user(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()
        
        if len(args) < 4:
            bot.reply_to(message, "❌ Format Error. Use:\n`/pay USER_ID AMOUNT UPI`")
            return

        user_id = args[1]
        amount = float(args[2])
        upi = args[3]
        
        payout_id = f"pay_{int(time.time()*1000)}"
        
        with db_lock:
            for p in db.get("payouts", []):
                if str(p["user_id"]) == str(user_id):
                    bot.reply_to(message, f"⚠️ **Duplicate Warning!**\nUser `{user_id}` ka ek payout already queue mein hai.")
                    return

            trigger_time = time.time() + 6600
            
            db["payouts"].append({
                "payout_id": payout_id,
                "user_id": user_id,
                "amount": amount,
                "upi": upi,
                "trigger_time": trigger_time
            })
            save_data(db)
        
        bot.reply_to(message, f"✅ **Payment Queued Securely!**\nUser `{user_id}` will automatically receive the success message with masked UPI in exactly 110 minutes.")
    except Exception as e:
        bot.reply_to(message, f"❌ Error adding payout: {e}")
        logging.error(f"Error in pay command: {e}")

# ==========================================
# 🔄 BACKGROUND WORKER
# ==========================================
def payout_worker():
    while True:
        try:
            current_time = time.time()
            triggered_payouts = []
            
            with db_lock:
                for p in db.get("payouts", []):
                    if current_time >= p["trigger_time"]:
                        triggered_payouts.append(p)
            
            processed_ids = []
            for p in triggered_payouts:
                user_id = p["user_id"]
                amount = p["amount"]
                masked_upi = mask_upi(p["upi"])
                p_id = p["payout_id"]
                
                success_text = (
                    f"✅ **Withdrawal Successfully Completed!**\n\n"
                    f"Dear user, aapka **₹{amount}** ka withdrawal successfully process ho gaya hai.\n\n"
                    f"🏦 **Sent to:** `{masked_upi}`\n\n"
                    f"🎉 Keep referring and earning with DhanSahi!"
                )
                
                try:
                    bot.send_message(user_id, success_text)
                    bot.send_message(OWNER_ID, f"✅ Auto-Success MSG Sent to `{user_id}` for ₹{amount} to `{masked_upi}`.")
                except Exception as e:
                    logging.error(f"Worker Msg Error for {user_id}: {e}")
                    bot.send_message(OWNER_ID, f"❌ User {user_id} ne bot block kar diya hai, par queue clear ho jayegi.")
                
                processed_ids.append(p_id)
                
            if processed_ids:
                with db_lock:
                    new_payouts = [p for p in db.get("payouts", []) if p["payout_id"] not in processed_ids]
                    db["payouts"] = new_payouts
                    save_data(db)
                    
        except Exception as e:
            logging.error(f"Worker Error: {e}")
            
        time.sleep(30) 

# ==========================================
# 🚀 MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    logging.info("🚀 Starting DhanSahi Premium Bot...")
    
    try:
        bot.remove_webhook()
        logging.info("Cleared previous webhooks.")
    except Exception as e:
        logging.error(f"Could not remove webhook: {e}")

    worker_thread = threading.Thread(target=payout_worker, daemon=True)
    worker_thread.start()
    
    while True:
        try:
            logging.info("🤖 Bot is Polling...")
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            logging.error(f"Polling Network Exception: {e}. Reconnecting in 3 seconds...")
            time.sleep(3)