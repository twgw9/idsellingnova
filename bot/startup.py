"""Post-start init: branding, admin menus, PEER_ID_INVALID nudge."""

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
from .db import *
from .emoji import *
from .pricing import *
from .supplier import *
from .helpers import *
from .fsub import *
from .user import *
from .deposit import *
from .purchase import *
from .otp import *
from .admin_cb import *
from .admin_cmds import *
from .pricing_cmds import *
from .growth import *
from .stateproc import *
from .callbacks import *
from .tasks import *
from .menus import *

# ================= STARTUP =================

async def post_start_init():
    me = await app.get_me()
    changed = False
    if not db.get("bot_username"):
        db["bot_username"] = me.username
        changed = True
    if not db.get("bot_name"):
        db["bot_name"] = BRAND_NAME
        changed = True
    for a in OWNER_IDS + EXTRA_ADMINS:
        if a not in db["admins"]:
            db["admins"].append(a)
            changed = True
    if not db.get("api_creds"):
        db["api_creds"] = json.loads(json.dumps(MULTI_API_CREDENTIALS))
        changed = True
    # v5.0: pehli run par Server 1 khud bana do (LIVE supplier server)
    if not server_codes():
        db["server_seq"] = 1
        db["server_order"] = ["s1"]
        db["servers"]["s1"] = {"name": "Server 1", "desc": "Live numbers • instant OTP",
                               "countries": {}, "source": "tgshark"}
        db["tgshark"]["server_code"] = "s1"
        changed = True
        logging.info("First run — Server 1 created as the LIVE supplier server.")
    if not db["tgshark"].get("tiers_v61"):
        db["tgshark"]["tiers"] = json.loads(json.dumps(TGSHARK_PROFIT_TIERS))
        db["tgshark"]["tiers_v61"] = True
        changed = True
        logging.info("Profit rule updated: ₹0-30 → +₹5 • ₹30-100 → 10%% (min ₹5) • ₹100+ → +₹15")
    code = tg_cfg()["server_code"]
    srv = get_server(code)
    if srv and not srv.get("source"):
        srv["source"] = "tgshark"
        srv["desc"] = srv.get("desc") or "Live numbers • instant OTP"
        changed = True
    OLD_TERMS_VERSIONS = [
        [
            "🔐 All IDs are checked before delivery.",
            "🚫 Do not share your login codes publicly.",
            "🧾 No refund / no replacement after delivery.",
            "💸 Payments once made cannot be reversed.",
        ],
        [
            "🔐 All IDs are verified & working at the time of delivery.",
            "👤 After delivery, YOU are fully responsible for how the ID is used — the store is not liable for your actions.",
            "🚫 Spam, abuse, scams or any illegal use can get the account banned — no refund / no replacement in that case.",
            "🔒 Change the password / 2FA immediately after your first login.",
            "🤐 Never share your login codes, OTPs or 2FA with anyone.",
            "🧾 No refund / no replacement once the ID is delivered.",
            "💸 Payments once made cannot be reversed.",
            "❄️ If an ID gets logged out or banned due to your usage, it will be frozen — contact support.",
        ],
    ]
    if db.get("terms") in OLD_TERMS_VERSIONS:
        db["terms"] = json.loads(json.dumps(DEFAULT_DB["terms"]))
        changed = True
    if changed:
        await save_db()
    await apply_branding()            # premium public profile: name + about
    await refresh_command_menus()
    await nudge_pending_admins()
    logging.info("Bot started as @%s | admin menus ready: %s | waiting /start: %s",
                 me.username, len(_admin_menu_ok), len(_admin_menu_pending))
    if _admin_menu_pending:
        print("ℹ️  Admin command menu ke liye admin ko ek baar bot ko /start karna zaroori hai.")
    # v4.0: startup par ek baar live stock sync (silent)
    try:
        if api_server_code():
            _n, msg = await tg_sync_stock()
            logging.info("TGShark startup sync: %s", msg)
    except Exception as e:
        logging.warning("TGShark startup sync failed: %s", e)
