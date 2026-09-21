"""Database: load / save / backup / restore (deadlock-free)."""

import asyncio, html, json, logging, math, os, platform, random, re, shutil
import signal as signal_module
import string, sys, time, urllib.error, urllib.request
from datetime import datetime
from urllib.parse import urlencode

import aiofiles
from pyrogram import Client, filters, enums, ContinuePropagation, idle
from pyrogram.raw import functions as raw_funcs
from pyrogram.errors import (FloodWait, SessionPasswordNeeded, PhoneCodeInvalid,
                             PhoneCodeExpired, UserNotParticipant, PasswordHashInvalid)
from pyrogram.types import (ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton,
                            Message, CallbackQuery, InputMediaPhoto,
                            BotCommand, BotCommandScopeChat, BotCommandScopeDefault)

from .config import *

# ================= DATABASE =================

DB_FILE = "id_store_db.json"
db_lock = asyncio.Lock()
_save_lock = asyncio.Lock()
db = {}

DEFAULT_DB = {
    "bot_name": None,
    "bot_username": None,
    "support_link": DEFAULT_SUPPORT,
    "buy_note": DEFAULT_BUY_NOTE,
    "default_tags": DEFAULT_TAGS,
    "terms": [
        "🔐 All IDs are checked & working at the time of delivery.",
        "👤 After delivery, YOU are 100% responsible for how the ID is used — the store is not responsible for your actions.",
        "🔒 Change the password / 2FA immediately after your first login.",
        "🤐 Never share your login codes, OTPs or 2FA with anyone.",
        "🚫 Spam, abuse or illegal activity can get the account banned — no refund / no replacement in that case.",
        "🧾 No refund / no replacement once the ID is delivered.",
        "💸 Payments once made cannot be reversed.",
        "📞 Facing any problem? Contact support BEFORE taking any action.",
    ],
    "admins": [],
    "fsub": [],
    "promos": [],
    "server_seq": 0,
    "server_order": [],
    "servers": {},
    "qrs": [],
    "min_deposit": 25,
    "dep_timeout_mins": 15,
    "verify_mode": "channel",
    "pay_group": None,
    "proof_channel": None,
    "announce_channel": None,     # price/stock announcements (default: proof channel)
    "low_stock": TGSHARK_LOW_STOCK,
    "coupons": {},                # CODE -> {type,value,uses,used,min_dep}
    "notify": {},                 # "code:country" -> [uid, ...] (restock alerts)
    "banned": [],                 # banned buyer ids
    "max_buy_day": MAX_BUY_PER_DAY,
    "auto_refund": AUTO_REFUND_ON_TIMEOUT,
    "ref_bonus": REF_BONUS_PCT,
    "sale_post": True,            # har sale par channel me SOLD update
    "welcome_text": None,         # custom welcome ({name} {balance})
    "motd": None,                 # notice of the day (har /start par dikhega)
    "currency": "₹",              # price symbol (/setcurrency $ , ₹ ...)
    "footer": None,               # custom line under every delivery message
    "otp_timeout_min": 15,        # OTP wait window in minutes
    "bulk": {},                   # {"3": 5, "5": 10} → qty → % discount
    "stock_view": "exact",        # exact | range | hidden
    "pending_deposits": {},
    "processed_deposits": {},
    "users": {},
    "sales": [],
    "deposit_log": [],
    "sold_sessions": {},
    "id_seq": 0,
    "api_creds": [],
    "api_idx": 0,
    # ---- v4.0: TGShark + premium emoji ----
    "tgshark": {
        "api_key": TGSHARK_API_KEY,
        "profit_pct": TGSHARK_PROFIT_PCT,
        "usd_inr": TGSHARK_USD_INR,
        "round_to": TGSHARK_ROUND_TO,
        "dry_run": TGSHARK_DRY_RUN,
        "server_code": "s1",
        "min_price": TGSHARK_MIN_PRICE,
        "mode": TGSHARK_PROFIT_MODE,
        "round_mode": TGSHARK_ROUND_MODE,
        "max_price": TGSHARK_MAX_PRICE,
        "charm": TGSHARK_CHARM,
        "margins": {},            # "code:country" -> {"add": ₹} ya {"pct": %}
        "tiers": json.loads(json.dumps(TGSHARK_PROFIT_TIERS)),
        "tiers_v61": False,       # naye profit rule ka migration flag
        "last_sync": 0,
        "last_balance": 0.0,
    },
    "emoji": {},   # {"crown": "5234...", ...} → Telegram custom (premium) emoji ids
}


async def load_db():
    global db
    async with db_lock:
        data = None
        if os.path.exists(DB_FILE):
            try:
                async with aiofiles.open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.loads(await f.read())
            except Exception as e:
                logging.error("DB load error: %s", e)
                data = None
        if not isinstance(data, dict):
            data = json.loads(json.dumps(DEFAULT_DB))
            data["admins"] = OWNER_IDS.copy()
        for key, default in DEFAULT_DB.items():
            if key not in data:
                data[key] = json.loads(json.dumps(default))
        # nested defaults (purani DB me naye keys add)
        for k, v in DEFAULT_DB["tgshark"].items():
            data["tgshark"].setdefault(k, v)
        db.clear()
        db.update(data)      # in-place: sab modules same dict dekhte hain


async def save_db():
    async with _save_lock:
        tmp = DB_FILE + ".tmp"
        async with aiofiles.open(tmp, "w", encoding="utf-8") as f:
            await f.write(json.dumps(db, indent=2, ensure_ascii=False))
        os.replace(tmp, DB_FILE)


user_states = {}
active_sign_ins = {}
_admin_menu_ok = set()
_admin_menu_pending = set()
_nudge_scheduled = set()
