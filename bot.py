import os
import json
import time
import random
import threading
import logging
from datetime import datetime, timedelta
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ==========================================
# ⚙️ CONFIGURATION (ENVIRONMENT VARIABLES)
# ==========================================
# Railway Dashboard -> Variables tab me ye set karein
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
        "channel_link": "",
        "min_withdraw": 190.0,
        "signup_bonus": 5.0,
        "refer_bonus": 10.0
    },
    "pending_withdrawals": [] # New: Store withdrawal requests here
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
                "balance": db["config"]["signup_bonus"], 
                "referred_by": None,
                "referrals": 0,
                "upi": None,
                "joined": False, # Has passed FSub check?
                "last_daily_bonus": 0 # Timestamp for daily bonus
            }
            save_data(db)
    return db["users"][uid]

def check_fsub(user_id):
    channel_id = db["config"].get("channel_id", "")
    if not channel_id:
        return True # Bypass if admin hasn't set channel
    try:
        # User id must be integer for get_chat_member
        status = bot.get_chat_member(channel_id, int(user_id)).status
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.warning(f"FSub error for {user_id}: {e}. (Make sure bot is Admin in channel and ID is correct e.g., @channelname)")
        return False # Bug Fix: Agar error hai toh False return karo, join karna padega

def is_menu_button(text):
    buttons = ["👤 My Profile", "🔗 Refer & Earn", "🏦 Bind UPI", "💸 Withdraw", "🎁 Claim Promo", "🎁 Daily Bonus"]
    return text in buttons or text.startswith('/')

def process_referral_reward(user_id):
    """ Ek user ka refer reward ek hi baar dena """
    uid = str(user_id)
    notify_ref = False
    ref_id_to_notify = None
    refer_amount = db["config"]["refer_bonus"]
    
    with db_lock:
        u = get_user(uid)
        if not u.get("joined", False):
            u["joined"] = True # Mark as officially joined
            ref_id = u.get("referred_by")
            
            if ref_id and ref_id in db["users"]:
                db["users"][ref_id]["balance"] += refer_amount
                db["users"][ref_id]["referrals"] += 1
                notify_ref = True
                ref_id_to_notify = ref_id
            save_data(db)
            
    if notify_ref and ref_id_to_notify:
        try:
            bot.send_message(
                ref_id_to_notify, 
                f"🎉 **New Referral Counted!**\n\nAapke dost ne channel join kar liya hai. Aapke wallet me **₹{refer_amount}** add ho gaye hain! 💸\nCheck your profile."
            )
        except Exception as e:
            logging.error(f"Failed to notify referrer {ref_id_to_notify}: {e}")

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
        KeyboardButton("🎁 Claim Promo"),
        KeyboardButton("🎁 Daily Bonus")
    )
    return markup

def fsub_keyboard():
    markup = InlineKeyboardMarkup()
    link = db["config"].get("channel_link", "")
    if link:
        markup.add(InlineKeyboardButton("📢 Join Our Channel", url=link))
    markup.add(InlineKeyboardButton("✅ I Have Joined", callback_data="check_join"))
    return markup

def admin_main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📢 Set FSub Channel", callback_data="adm_fsub"),
        InlineKeyboardButton("💰 Edit User Balance", callback_data="adm_edit_bal")
    )
    markup.add(
        InlineKeyboardButton("💸 Pending Withdrawals", callback_data="adm_withdrawals"),
        InlineKeyboardButton("🎁 Create Promo", callback_data="adm_promo")
    )
    markup.add(
        InlineKeyboardButton("📣 Broadcast Message", callback_data="adm_broadcast")
    )
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

        # Save refer ID only if brand new user
        if is_new_user and len(args) > 1:
            ref_id = str(args[1])
            with db_lock:
                if ref_id != user_id and ref_id in db["users"]:
                    db["users"][user_id]["referred_by"] = ref_id
            save_data(db)

        # Check FSub status
        has_joined = check_fsub(message.from_user.id)
        
        if not has_joined:
            bot.send_message(
                message.chat.id, 
                "🛑 **Welcome to DhanSahi!**\n\nBot ko use karne aur apne ₹5 Bonus ko claim karne ke liye, pehle hamara official channel join karein👇", 
                reply_markup=fsub_keyboard()
            )
            return
        else:
            # Pura process verify hone ke baad refer reward do
            process_referral_reward(user_id)
            
            welcome_text = (
                f"👋 **Welcome to DhanSahi Premium!**\n\n"
                f"🎉 Aapko **₹{db['config']['signup_bonus']} Signup Bonus** mil chuka hai!\n"
                f"🚀 Apne doston ko invite karein aur per refer **₹{db['config']['refer_bonus']}** kamayein.\n\n"
                f"Neeche diye gaye menu se buttons dabayein 👇"
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
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            
            # Yahan par count hoga refer finally!
            process_referral_reward(user_id)
            
            bot.send_message(
                call.message.chat.id, 
                "✅ **Verification Successful!**\n\nAb aap bot ke sabhi features use kar sakte hain.", 
                reply_markup=main_menu()
            )
        else:
            bot.answer_callback_query(call.id, "❌ Aapne abhi tak channel join nahi kiya hai! Check failed.", show_alert=True)
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
            f"Apne doston ko invite karein aur kamayein **₹{db['config']['refer_bonus']}** per valid refer!\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
            f"*(Note: Bonus tabhi milega jab aapka dost bot start karke channel join karega)*"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Error in refer: {e}")

@bot.message_handler(func=lambda m: m.text == "🎁 Daily Bonus")
def daily_bonus(message):
    try:
        user_id = str(message.from_user.id)
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        u = get_user(user_id)
        last_claim = u.get("last_daily_bonus", 0)
        now = time.time()
        
        if now - last_claim >= 86400: # 24 hours
            bonus_amount = random.randint(1, 5) # Random bonus between Rs 1 to 5
            with db_lock:
                db["users"][user_id]["balance"] += bonus_amount
                db["users"][user_id]["last_daily_bonus"] = now
                save_data(db)
            bot.reply_to(message, f"🎁 **Daily Bonus Claimed!**\nAapko **₹{bonus_amount}** mile hain. Kal wapas aana! 💸")
        else:
            time_left = 86400 - (now - last_claim)
            hours = int(time_left // 3600)
            mins = int((time_left % 3600) // 60)
            bot.reply_to(message, f"⏳ Aap apna aaj ka bonus le chuke ho.\nNext bonus aayega: **{hours} ghante aur {mins} minute** baad.")
            
    except Exception as e:
        logging.error(f"Error in daily bonus: {e}")

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
        if not message.text: return
        if is_menu_button(message.text):
            bot.reply_to(message, "❌ Action Cancelled.")
            return

        user_id = str(message.from_user.id)
        upi = message.text.strip()
        if len(upi) < 5 or "@" not in upi:
            bot.reply_to(message, "❌ Invalid UPI ID. Kripya sahi UPI ID bhejein (Bind UPI button firse dabayein).")
            return

        with db_lock:
            db["users"][user_id]["upi"] = upi
            save_data(db)
            
        bot.reply_to(message, f"✅ **Success!** Aapka UPI ID `{upi}` save ho gaya hai.")
    except Exception as e:
        logging.error(f"Error in save_upi: {e}")

@bot.message_handler(func=lambda m: m.text == "💸 Withdraw")
def withdraw(message):
    try:
        user_id = str(message.from_user.id)
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        u = get_user(user_id)
        min_w = db["config"]["min_withdraw"]
        
        if not u["upi"]:
            bot.reply_to(message, "❌ Pehle apna UPI ID bind karein '🏦 Bind UPI' button se.")
            return
        
        if u["balance"] < min_w:
            bot.reply_to(message, f"❌ **Minimum withdrawal ₹{min_w} hai.**\nAapka current balance sirf ₹{u['balance']:.2f} hai.")
            return

        # Check if already has pending withdrawal
        for pending in db.get("pending_withdrawals", []):
            if pending["user_id"] == user_id:
                bot.reply_to(message, "⏳ Aapka ek withdrawal already pending hai. Please wait.")
                return

        amount = u["balance"]
        tax = amount * 0.05
        final_amount = amount - tax
        req_id = f"W_{int(time.time())}"

        with db_lock:
            db["users"][user_id]["balance"] = 0.0
            
            if "pending_withdrawals" not in db:
                db["pending_withdrawals"] = []
                
            db["pending_withdrawals"].append({
                "req_id": req_id,
                "user_id": user_id,
                "amount": amount,
                "final_amount": final_amount,
                "upi": u["upi"],
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            save_data(db)

        bot.reply_to(message, f"⏳ **Withdrawal Request Submitted!**\n\n"
                              f"💰 **Amount:** ₹{amount:.2f}\n"
                              f"💳 **Receiving:** ₹{final_amount:.2f} (After 5% Tax)\n"
                              f"🏦 **UPI:** `{u['upi']}`\n\n"
                              f"⚠️ *Aapki request admin ke paas bhej di gayi hai. Approve hote hi aapko message aayega.*")
                              
        # Notify Admin
        try:
            bot.send_message(OWNER_ID, f"🚨 **New Withdrawal Request!**\nUser: `{user_id}`\nAmount: ₹{final_amount:.2f}\nCheck Admin Panel -> Pending Withdrawals.")
        except:
            pass

    except Exception as e:
        logging.error(f"Error in withdraw: {e}")

# ==========================================
# 👑 INTERACTIVE ADMIN PANEL
# ==========================================
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if str(message.from_user.id) != str(OWNER_ID):
        return
    
    with db_lock:
        total_users = len(db["users"])
        total_balance = sum(u["balance"] for u in db["users"].values())
        pending_reqs = len(db.get("pending_withdrawals", []))
    
    text = (
        f"👑 **DhanSahi Premium Admin Panel** 👑\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 **Total Users:** {total_users}\n"
        f"💰 **Total Balances:** ₹{total_balance:.2f}\n"
        f"⏳ **Pending Withdrawals:** {pending_reqs}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👇 Options select karein:"
    )
    bot.reply_to(message, text, reply_markup=admin_main_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_callbacks(call):
    if str(call.from_user.id) != str(OWNER_ID):
        return
        
    action = call.data
    
    if action == "adm_fsub":
        msg = bot.send_message(call.message.chat.id, "📢 **Set FSub Channel**\n\nFormat bhejein (Space ke saath):\n`@channelusername https://t.me/channel`\n\n*(Type /cancel to abort)*")
        bot.register_next_step_handler(msg, admin_process_fsub)
        
    elif action == "adm_edit_bal":
        msg = bot.send_message(call.message.chat.id, "💰 **Edit Balance**\n\nFormat bhejein:\n`USER_ID AMOUNT`\n(e.g., `123456789 50` add karne ke liye, `123456789 -50` minus ke liye)\n\n*(Type /cancel to abort)*")
        bot.register_next_step_handler(msg, admin_process_edit_bal)
        
    elif action == "adm_promo":
        msg = bot.send_message(call.message.chat.id, "🎁 **Create Promo**\n\nFormat bhejein:\n`CODE AMOUNT USES`\n(e.g., `DIWALI50 50 10`)\n\n*(Type /cancel to abort)*")
        bot.register_next_step_handler(msg, admin_process_promo)
        
    elif action == "adm_broadcast":
        msg = bot.send_message(call.message.chat.id, "📣 **Broadcast Message**\n\nJo message sabko bhejna hai wo type karein.\n*(Text, Photo, etc supported nahi hai abhi, sirf Text bhejein)*\n\n*(Type /cancel to abort)*")
        bot.register_next_step_handler(msg, admin_process_broadcast)
        
    elif action == "adm_withdrawals":
        show_pending_withdrawals(call.message.chat.id)

def show_pending_withdrawals(chat_id):
    reqs = db.get("pending_withdrawals", [])
    if not reqs:
        bot.send_message(chat_id, "✅ Koi pending withdrawals nahi hain!")
        return
        
    bot.send_message(chat_id, f"👀 **Showing {len(reqs)} Pending Requests:**")
    for req in reqs:
        text = (
            f"🧾 **Req ID:** `{req['req_id']}`\n"
            f"👤 **User:** `{req['user_id']}`\n"
            f"💰 **Total:** ₹{req['amount']}\n"
            f"💳 **To Pay:** ₹{req['final_amount']}\n"
            f"🏦 **UPI:** `{req['upi']}`\n"
            f"📅 **Date:** {req['date']}"
        )
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Approve", callback_data=f"pay_approve_{req['req_id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_{req['req_id']}")
        )
        bot.send_message(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def process_payout_action(call):
    if str(call.from_user.id) != str(OWNER_ID):
        return
        
    parts = call.data.split("_")
    action = parts[1] # approve or reject
    req_id = parts[2]
    
    with db_lock:
        reqs = db.get("pending_withdrawals", [])
        target_req = next((r for r in reqs if r["req_id"] == req_id), None)
        
        if not target_req:
            bot.answer_callback_query(call.id, "❌ Request nahi mili (Already processed).", show_alert=True)
            bot.delete_message(call.message.chat.id, call.message.message_id)
            return
            
        user_id = target_req["user_id"]
        
        if action == "approve":
            # Mask UPI
            upi = target_req["upi"]
            try:
                if '@' in upi:
                    u_part, b_part = upi.split('@', 1)
                    masked = f"{u_part[:2]}***@{b_part}"
                else: masked = f"***@upi"
            except: masked = "***@upi"
            
            msg_to_user = f"✅ **Withdrawal Successful!**\n\nAapka **₹{target_req['final_amount']}** ka payment bhej diya gaya hai.\n🏦 **UPI:** `{masked}`"
            admin_resp = "✅ Approved & Notified user."
            
        elif action == "reject":
            # Refund money
            if user_id in db["users"]:
                db["users"][user_id]["balance"] += target_req["amount"]
            msg_to_user = f"❌ **Withdrawal Rejected!**\n\nAapka ₹{target_req['amount']} reject ho gaya hai aur balance waapas wallet me add kar diya gaya hai. Kripya valid UPI dalein."
            admin_resp = "❌ Rejected & Refunded to user."
            
        # Remove from pending list
        db["pending_withdrawals"] = [r for r in reqs if r["req_id"] != req_id]
        save_data(db)
        
    # Notify User
    try:
        bot.send_message(user_id, msg_to_user)
    except:
        admin_resp += " (User blocked bot, msg not sent)"
        
    bot.answer_callback_query(call.id, admin_resp)
    bot.edit_message_text(f"{call.message.text}\n\n**STATUS: {action.upper()}D**", call.message.chat.id, call.message.message_id)

# --- Admin Next Step Handlers ---
def admin_process_fsub(message):
    if message.text == '/cancel': return bot.reply_to(message, "❌ Cancelled")
    try:
        parts = message.text.split()
        with db_lock:
            db["config"]["channel_id"] = parts[0]
            db["config"]["channel_link"] = parts[1]
            save_data(db)
        bot.reply_to(message, "✅ FSub Settings Updated!")
    except:
        bot.reply_to(message, "❌ Invalid format.")

def admin_process_edit_bal(message):
    if message.text == '/cancel': return bot.reply_to(message, "❌ Cancelled")
    try:
        parts = message.text.split()
        uid = parts[0]
        amt = float(parts[1])
        with db_lock:
            if uid in db["users"]:
                db["users"][uid]["balance"] += amt
                save_data(db)
                bot.reply_to(message, f"✅ Balance of {uid} updated. New Balance: ₹{db['users'][uid]['balance']:.2f}")
            else:
                bot.reply_to(message, "❌ User not found in database.")
    except:
        bot.reply_to(message, "❌ Invalid format.")

def admin_process_promo(message):
    if message.text == '/cancel': return bot.reply_to(message, "❌ Cancelled")
    try:
        parts = message.text.split()
        code = parts[0].upper()
        amt = float(parts[1])
        uses = int(parts[2])
        with db_lock:
            db["promos"][code] = {"amount": amt, "uses": uses, "used_by": []}
            save_data(db)
        bot.reply_to(message, f"✅ Promo `{code}` created for ₹{amt} ({uses} uses).")
    except:
        bot.reply_to(message, "❌ Invalid format.")

def admin_process_broadcast(message):
    if message.text == '/cancel': return bot.reply_to(message, "❌ Cancelled")
    
    text = message.text
    bot.reply_to(message, "⏳ Broadcast started. This may take a while depending on users...")
    
    success = 0
    failed = 0
    
    with db_lock:
        users = list(db["users"].keys())
        
    for uid in users:
        try:
            bot.send_message(uid, f"📢 **Broadcast from Admin:**\n\n{text}")
            success += 1
            time.sleep(0.05) # Avoid Telegram rate limits
        except:
            failed += 1
            
    bot.send_message(message.chat.id, f"✅ **Broadcast Complete!**\nSuccess: {success}\nFailed/Blocked: {failed}")

# Promo Code User Handler (Kept outside admin block)
@bot.message_handler(func=lambda m: m.text == "🎁 Claim Promo")
def ask_promo(message):
    if not check_fsub(message.from_user.id): return bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
    msg = bot.reply_to(message, "🎁 **Promo Code enter karein:**")
    bot.register_next_step_handler(msg, claim_promo)

def claim_promo(message):
    if not message.text or is_menu_button(message.text): return bot.reply_to(message, "❌ Cancelled.")
    user_id = str(message.from_user.id)
    code = message.text.strip().upper()
    
    with db_lock:
        if code in db["promos"]:
            promo = db["promos"][code]
            if user_id in promo["used_by"]:
                bot.reply_to(message, "❌ Aap yeh promo code pehle hi use kar chuke hain.")
            elif promo["uses"] > 0:
                promo["uses"] -= 1
                promo["used_by"].append(user_id)
                db["users"][user_id]["balance"] += promo["amount"]
                save_data(db)
                bot.reply_to(message, f"🎉 **Congratulations!**\n**₹{promo['amount']}** aapke wallet mein add kar diye gaye hain!")
            else:
                bot.reply_to(message, "❌ Yeh promo code expire ho chuka hai.")
        else:
            bot.reply_to(message, "❌ Invalid Promo Code!")

# ==========================================
# 🚀 MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    logging.info("🚀 Starting DhanSahi Premium Bot v2...")
    
    try:
        bot.remove_webhook()
        logging.info("Cleared previous webhooks.")
    except Exception as e:
        pass

    while True:
        try:
            logging.info("🤖 Bot is Polling...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"Polling Network Exception: {e}. Reconnecting...")
            time.sleep(3)