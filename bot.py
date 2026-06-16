import os
import json
import time
import random
import threading
import logging
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# ==========================================
# ⚙️ CONFIGURATION (CHANGE THESE)
# ==========================================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Apna Bot Token Yahan Dalein
OWNER_ID = 123456789               # Apna Telegram User ID Yahan Dalein

# ==========================================
# 🚀 INITIALIZATION & SETUP
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")
DATA_FILE = "data.json"
db_lock = threading.Lock()

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
            return json.loads(json.dumps(default_data))  # deep copy
        try:
            with open(DATA_FILE, "r") as f:
                data = json.load(f)
                # Ensure all keys exist (safe migration)
                for key in default_data:
                    if key not in data:
                        data[key] = default_data[key]
                return data
        except Exception as e:
            logging.error(f"Error loading JSON: {e}")
            return json.loads(json.dumps(default_data))

def save_data(data):
    with db_lock:
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logging.error(f"Error saving JSON: {e}")

db = load_data()

# ==========================================
# 🛠️ HELPER FUNCTIONS
# ==========================================
def get_user(user_id):
    """Always returns user dict, creates if not exists."""
    uid = str(user_id)
    if uid not in db["users"]:
        db["users"][uid] = {
            "balance": 5.0,
            "referred_by": None,
            "referrals": 0,
            "upi": None,
            "joined": False
        }
        save_data(db)
    return db["users"][uid]

def mask_upi(upi):
    """Masks UPI visually without changing it — only for display."""
    try:
        if '@' in upi:
            user_part, bank_part = upi.split('@', 1)
            # Show only first 3 chars + stars, keep bank part
            visible = user_part[:3] + "***"
            return f"{visible}@{bank_part}"
        return f"{upi[:3]}***"
    except:
        return "***@***"

def check_fsub(user_id):
    """Returns True if user has joined channel, or if no channel is set."""
    channel_id = db["config"].get("channel_id", "")
    if not channel_id:
        return True
    try:
        status = bot.get_chat_member(channel_id, int(user_id)).status
        return status in ['member', 'administrator', 'creator']
    except Exception as e:
        logging.error(f"FSub check failed for {user_id}: {e}")
        return True  # BUG FIX: On API error, don't block user — fail open

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

        # BUG FIX: Check if user is NEW before calling get_user() which creates them
        is_new_user = user_id not in db["users"]

        user_data = get_user(user_id)  # Creates user if not exists

        # BUG FIX: Only process referral for genuinely new users
        if is_new_user and len(args) > 1:
            ref_id = str(args[1])
            if ref_id != user_id and ref_id in db["users"]:
                user_data["referred_by"] = ref_id
                save_data(db)

        # Force Subscribe Check
        if not check_fsub(message.from_user.id):
            bot.send_message(
                message.chat.id,
                "🛑 *Welcome to DhanSahi!*\n\nAapko bot use karne ke liye pehle hamara official channel join karna hoga.",
                reply_markup=fsub_keyboard()
            )
            return

        welcome_text = (
            f"👋 *Welcome to DhanSahi Premium Bot!*\n\n"
            f"🎉 Aapko *₹5 Signup Bonus* de diya gaya hai!\n"
            f"🚀 Apne doston ko invite karein aur per refer *₹10* kamayein.\n\n"
            f"Neeche diye gaye menu se options select karein 👇"
        )
        bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu())
    except Exception as e:
        logging.error(f"Error in start_command: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    try:
        user_id = str(call.from_user.id)
        if check_fsub(call.from_user.id):
            user_data = get_user(user_id)
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass

            # Reward Referrer (Only Once)
            if not user_data.get("joined", False):
                user_data["joined"] = True
                ref_id = user_data.get("referred_by")
                if ref_id and ref_id in db["users"]:
                    db["users"][ref_id]["balance"] += 10.0
                    db["users"][ref_id]["referrals"] += 1
                    try:
                        bot.send_message(
                            ref_id,
                            f"🎉 *New Referral!*\nAapke dost ne channel join kar liya hai. Aapke wallet me *₹10* add ho gaye hain! 💸"
                        )
                    except:
                        pass
                save_data(db)

            bot.send_message(
                call.message.chat.id,
                "✅ *Verification Successful!*\n\nAb aap DhanSahi bot ke sabhi features use kar sakte hain.",
                reply_markup=main_menu()
            )
        else:
            bot.answer_callback_query(call.id, "❌ Aapne abhi tak channel join nahi kiya hai! Pehle join karein.", show_alert=True)
    except Exception as e:
        logging.error(f"Error in check_join_callback: {e}")

@bot.message_handler(func=lambda m: m.text == "👤 My Profile")
def profile(message):
    try:
        user_id = str(message.from_user.id)
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        u = get_user(user_id)
        upi_display = f"`{u['upi']}`" if u['upi'] else "Not Bound Yet"
        text = (
            f"👤 *Your Profile Dashboard*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 *User ID:* `{user_id}`\n"
            f"💰 *Balance:* ₹{u['balance']:.2f}\n"
            f"👥 *Total Referrals:* {u['referrals']}\n"
            f"🏦 *Saved UPI:* {upi_display}\n"
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
            f"🚀 *Refer & Earn Program* 🚀\n\n"
            f"Apne doston ko invite karein aur kamayein *₹10* per valid refer!\n\n"
            f"🔗 *Your Referral Link:*\n`{ref_link}`\n\n"
            f"_(Note: Referral bonus tabhi milega jab aapka dost bot start karke channel join karega)_"
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

        # BUG FIX: Ensure user exists before UPI step
        get_user(str(message.from_user.id))

        msg = bot.reply_to(message, "🏦 *Apna valid UPI ID bhejiye:*\n_(Example: name@ybl, number@paytm)_")
        bot.register_next_step_handler(msg, save_upi)
    except Exception as e:
        logging.error(f"Error in ask_upi: {e}")

def save_upi(message):
    try:
        # BUG FIX: Skip if user sent a command or menu button instead of UPI
        if message.text and message.text.startswith('/'):
            bot.reply_to(message, "❌ UPI ID valid nahi hai. Phir se '🏦 Bind UPI' button dabayein.")
            return

        user_id = str(message.from_user.id)
        upi = message.text.strip()

        if len(upi) < 5 or "@" not in upi:
            bot.reply_to(message, "❌ Invalid UPI ID. Kripya sahi format mein bhejein (e.g. name@ybl). Phir se '🏦 Bind UPI' button dabayein.")
            return

        # BUG FIX: Use get_user() to ensure user exists before accessing
        user_data = get_user(user_id)
        user_data["upi"] = upi
        save_data(db)
        bot.reply_to(message, f"✅ *Success!* Aapka UPI ID `{upi}` successfully bind ho chuka hai.")
    except Exception as e:
        bot.reply_to(message, "❌ Error saving UPI. Please try again.")
        logging.error(f"Error in save_upi: {e}")

@bot.message_handler(func=lambda m: m.text == "🎁 Claim Promo")
def ask_promo(message):
    try:
        if not check_fsub(message.from_user.id):
            bot.reply_to(message, "🛑 Pehle channel join karein!", reply_markup=fsub_keyboard())
            return

        # BUG FIX: Ensure user exists
        get_user(str(message.from_user.id))

        msg = bot.reply_to(message, "🎁 *Promo Code enter karein:*")
        bot.register_next_step_handler(msg, claim_promo)
    except Exception as e:
        logging.error(f"Error in ask_promo: {e}")

def claim_promo(message):
    try:
        # BUG FIX: Skip if user sent a command or menu button
        if message.text and message.text.startswith('/'):
            bot.reply_to(message, "❌ Valid promo code bhejein. Phir se '🎁 Claim Promo' button dabayein.")
            return

        user_id = str(message.from_user.id)
        code = message.text.strip().upper()

        # BUG FIX: Use get_user() to ensure user dict exists
        user_data = get_user(user_id)

        if code in db["promos"]:
            promo = db["promos"][code]
            if user_id in promo["used_by"]:
                bot.reply_to(message, "❌ Aap yeh promo code pehle hi use kar chuke hain.")
                return
            if promo["uses"] > 0:
                db["promos"][code]["uses"] -= 1
                db["promos"][code]["used_by"].append(user_id)
                user_data["balance"] += promo["amount"]
                save_data(db)
                bot.reply_to(message, f"🎉 *Congratulations!*\nAapne promo code claim kar liya hai. *₹{promo['amount']}* aapke wallet mein add kar diye gaye hain!")
            else:
                bot.reply_to(message, "❌ Yeh promo code expire ho chuka hai ya iski limit khatam ho gayi hai.")
        else:
            bot.reply_to(message, "❌ Invalid Promo Code! Dobara check karein.")
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
            bot.reply_to(message, f"❌ *Minimum withdrawal ₹190 hai.*\nAapka current balance sirf ₹{u['balance']:.2f} hai.")
            return

        amount = u["balance"]
        tax = round(amount * 0.05, 2)
        final_amount = round(amount - tax, 2)
        upi_id = u["upi"]

        # BUG FIX: First notify admin, THEN deduct — so balance is safe if notification fails
        admin_text = (
            f"🚨 *New Withdrawal Alert!*\n\n"
            f"👤 User ID: `{user_id}`\n"
            f"💰 Total Amount: ₹{amount:.2f}\n"
            f"💳 To Pay (after 5% tax): ₹{final_amount:.2f}\n"
            f"🏦 UPI: `{upi_id}`\n\n"
            f"👇 Approve karne ke liye command:\n"
            f"`/pay {user_id} {final_amount:.2f} {upi_id}`"
        )
        try:
            bot.send_message(OWNER_ID, admin_text)
        except Exception as e:
            logging.error(f"Failed to send admin alert: {e}")
            bot.reply_to(message, "❌ System error aaya hai. Kripya thodi der baad try karein.")
            return  # BUG FIX: Don't deduct if admin can't be notified

        # Deduct balance only after successful admin notification
        db["users"][user_id]["balance"] = 0.0
        save_data(db)

        bot.reply_to(
            message,
            f"⏳ *Withdrawal Request Submitted!*\n\n"
            f"💰 *Amount Requested:* ₹{amount:.2f}\n"
            f"🧾 *Platform Tax (5%):* ₹{tax:.2f}\n"
            f"💳 *Receiving Amount:* ₹{final_amount:.2f}\n"
            f"🏦 *UPI ID:* `{upi_id}`\n\n"
            f"⚠️ _Aapka withdrawal pending hai. Isey cancel nahi kiya jaa sakta. Kripya wait karein._"
        )

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

        total_users = len(db["users"])
        total_balance = sum(u["balance"] for u in db["users"].values())
        pending_payouts = len(db.get("payouts", []))

        text = (
            f"👑 *DhanSahi Admin Panel* 👑\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👥 *Total Users:* {total_users}\n"
            f"💰 *Total Balance in System:* ₹{total_balance:.2f}\n"
            f"⏳ *Pending Payouts:* {pending_payouts}\n\n"
            f"🛠️ *Admin Commands:*\n"
            f"`/setchannel @username https://link` — Set FSub Channel\n"
            f"`/makepromo CODE AMOUNT USES` — Create a new promo\n"
            f"`/pay USER_ID AMOUNT UPI_ID` — Queue 110-min payout\n"
            f"`/listpayouts` — View all pending payouts\n"
            f"`/addbalance USER_ID AMOUNT` — Add balance to user\n"
            f"`/userinfo USER_ID` — View user details"
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
            bot.reply_to(message, "❌ Format: `/setchannel @yourchannel https://t.me/yourchannel`")
            return

        channel_id = args[1]
        channel_link = args[2]
        db["config"]["channel_id"] = channel_id
        db["config"]["channel_link"] = channel_link
        save_data(db)
        bot.reply_to(message, f"✅ Force Subscribe updated!\nID: `{channel_id}`\nLink: {channel_link}\n_(Make sure bot is admin in the channel)_")
    except Exception as e:
        logging.error(f"Error in setchannel: {e}")

@bot.message_handler(commands=['makepromo'])
def make_promo(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()
        if len(args) < 4:
            bot.reply_to(message, "❌ Format: `/makepromo CODE AMOUNT USES`\nExample: `/makepromo SAVE50 50 100`")
            return

        code = args[1].upper()
        try:
            amount = float(args[2])
            uses = int(args[3])
        except ValueError:
            bot.reply_to(message, "❌ AMOUNT aur USES numbers hone chahiye.")
            return

        # BUG FIX: Warn if overwriting existing promo
        if code in db["promos"]:
            bot.reply_to(message, f"⚠️ Promo `{code}` already exists. Overwriting...")

        db["promos"][code] = {
            "amount": amount,
            "uses": uses,
            "used_by": []
        }
        save_data(db)
        bot.reply_to(message, f"✅ *Promo Created!*\n🎟️ Code: `{code}`\n💰 Amount: ₹{amount}\n👥 Uses: {uses}")
    except Exception as e:
        logging.error(f"Error in makepromo: {e}")

@bot.message_handler(commands=['pay'])
def pay_user(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()

        if len(args) < 4:
            bot.reply_to(message, "❌ Format: `/pay USER_ID AMOUNT UPI_ID`\nExample: `/pay 123456 95.00 name@ybl`")
            return

        user_id = args[1]
        upi = args[3]

        try:
            amount = float(args[2])
        except ValueError:
            bot.reply_to(message, "❌ AMOUNT ek valid number hona chahiye.")
            return

        # BUG FIX: Check if user exists
        if user_id not in db["users"]:
            bot.reply_to(message, f"❌ User `{user_id}` database mein nahi mila.")
            return

        # BUG FIX: Prevent duplicate payouts for same user
        existing = [p for p in db.get("payouts", []) if p["user_id"] == user_id]
        if existing:
            bot.reply_to(message, f"⚠️ User `{user_id}` ka ek payout already queue mein hai. Pehle `/listpayouts` check karein.")
            return

        trigger_time = time.time() + 6600  # 110 minutes

        db["payouts"].append({
            "user_id": user_id,
            "amount": amount,
            "upi": upi,
            "trigger_time": trigger_time
        })
        save_data(db)

        bot.reply_to(
            message,
            f"✅ *Payment Queued!*\n"
            f"👤 User: `{user_id}`\n"
            f"💰 Amount: ₹{amount:.2f}\n"
            f"🏦 UPI: `{upi}`\n"
            f"⏱️ Success message 110 minutes mein jayega."
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        logging.error(f"Error in pay command: {e}")

@bot.message_handler(commands=['listpayouts'])
def list_payouts(message):
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        payouts = db.get("payouts", [])
        if not payouts:
            bot.reply_to(message, "✅ Koi pending payout nahi hai.")
            return

        current_time = time.time()
        lines = ["⏳ *Pending Payouts:*\n"]
        for i, p in enumerate(payouts, 1):
            remaining_mins = max(0, int((p["trigger_time"] - current_time) / 60))
            lines.append(
                f"{i}. User `{p['user_id']}` — ₹{p['amount']:.2f} — `{p['upi']}` — {remaining_mins} min baki"
            )
        bot.reply_to(message, "\n".join(lines))
    except Exception as e:
        logging.error(f"Error in listpayouts: {e}")

@bot.message_handler(commands=['addbalance'])
def add_balance(message):
    """Admin can manually add balance to any user."""
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()
        if len(args) < 3:
            bot.reply_to(message, "❌ Format: `/addbalance USER_ID AMOUNT`")
            return

        target_id = args[1]
        try:
            amount = float(args[2])
        except ValueError:
            bot.reply_to(message, "❌ AMOUNT valid number hona chahiye.")
            return

        if target_id not in db["users"]:
            bot.reply_to(message, f"❌ User `{target_id}` nahi mila.")
            return

        db["users"][target_id]["balance"] += amount
        save_data(db)
        new_bal = db["users"][target_id]["balance"]
        bot.reply_to(message, f"✅ `{target_id}` ko ₹{amount:.2f} add kiya gaya.\nNew Balance: ₹{new_bal:.2f}")

        try:
            bot.send_message(target_id, f"🎉 Admin ne aapke wallet mein *₹{amount:.2f}* add kar diye hain!\nNew Balance: ₹{new_bal:.2f}")
        except:
            pass
    except Exception as e:
        logging.error(f"Error in addbalance: {e}")

@bot.message_handler(commands=['userinfo'])
def user_info(message):
    """Admin can view any user's details."""
    try:
        if str(message.from_user.id) != str(OWNER_ID): return
        args = message.text.split()
        if len(args) < 2:
            bot.reply_to(message, "❌ Format: `/userinfo USER_ID`")
            return

        target_id = args[1]
        if target_id not in db["users"]:
            bot.reply_to(message, f"❌ User `{target_id}` nahi mila.")
            return

        u = db["users"][target_id]
        text = (
            f"👤 *User Info: `{target_id}`*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance: ₹{u['balance']:.2f}\n"
            f"👥 Referrals: {u['referrals']}\n"
            f"🔗 Referred By: `{u.get('referred_by', 'None')}`\n"
            f"🏦 UPI: `{u.get('upi', 'Not Bound')}`\n"
            f"✅ Channel Joined: {u.get('joined', False)}"
        )
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(f"Error in userinfo: {e}")

# ==========================================
# 🔄 BACKGROUND WORKER & BOT RUNNER
# ==========================================
def payout_worker():
    """Runs constantly to check for pending payouts, unaffected by bot crashes."""
    while True:
        try:
            # BUG FIX: Always reload from disk so we get updates even after restarts
            fresh_db = load_data()
            current_time = time.time()
            pending_payouts = fresh_db.get("payouts", [])
            remaining_payouts = []
            changes_made = False

            for payout in pending_payouts:
                if current_time >= payout["trigger_time"]:
                    user_id = payout["user_id"]
                    amount = payout["amount"]
                    upi = payout["upi"]
                    masked_upi = mask_upi(upi)

                    success_text = (
                        f"✅ *Withdrawal Successfully Completed!*\n\n"
                        f"Dear user, aapka *₹{amount:.2f}* ka withdrawal successfully process ho gaya hai.\n\n"
                        f"🏦 *Sent to:* `{masked_upi}`\n\n"
                        f"🎉 Keep referring and earning with DhanSahi!"
                    )
                    try:
                        bot.send_message(user_id, success_text)
                        bot.send_message(OWNER_ID, f"✅ Auto-Success MSG Sent to `{user_id}` for ₹{amount:.2f}.")
                    except Exception as e:
                        logging.error(f"Failed to send success msg to {user_id}: {e}")
                        try:
                            bot.send_message(OWNER_ID, f"❌ User `{user_id}` tak message nahi pahuncha (bot blocked?). Payout complete maana jaye.")
                        except:
                            pass

                    changes_made = True
                else:
                    remaining_payouts.append(payout)

            if changes_made:
                # BUG FIX: Update global db and save
                db["payouts"] = remaining_payouts
                fresh_db["payouts"] = remaining_payouts
                save_data(fresh_db)

        except Exception as e:
            logging.error(f"Worker Error: {e}")

        time.sleep(30)

if __name__ == "__main__":
    logging.info("🚀 Starting background payout worker...")
    worker_thread = threading.Thread(target=payout_worker, daemon=True)
    worker_thread.start()

    logging.info("🤖 DhanSahi Bot is Polling...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            logging.error(f"Polling crashed: {e}. Restarting in 5 seconds...")
            time.sleep(5)
