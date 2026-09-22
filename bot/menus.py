"""Scoped Telegram command menus (public vs admin)."""

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

# ================= BOT COMMAND MENUS (SCOPED) =================

USER_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("help", "How to use this bot"),
    BotCommand("terms", "Terms & conditions"),
    BotCommand("products", "Browse servers & countries"),
    BotCommand("profile", "Your profile & wallet"),
    BotCommand("myids", "Your purchased IDs + OTP"),
    BotCommand("deposit", "Add balance (UPI)"),
    BotCommand("support", "Contact support"),
    BotCommand("whoami", "Your ID & admin status"),
]
ADMIN_COMMANDS = USER_COMMANDS + [
    BotCommand("adminhelp", "Setup guide"),
    BotCommand("adminpanel", "All admin commands"),
    # ---- TGShark API (v4.0) ----
    BotCommand("tgtest", "Test TGShark API connection"),
    BotCommand("tgstatus", "API balance / stock / profit"),
    BotCommand("tgsync", "Sync live stock + prices"),
    BotCommand("tgserver", "/tgserver s1 — API/manual toggle"),
    BotCommand("setapikey", "Set TGShark API key"),
    BotCommand("setprofit", "/setprofit 10 — profit %"),
    BotCommand("setinr", "/setinr 88 — USD to INR rate"),
    BotCommand("setround", "/setround 5 — price rounding"),
    BotCommand("settiers", "Profit slabs (cost → +₹ profit)"),
    BotCommand("settier", "/settier 50 15 — set a slab"),
    BotCommand("setcost", "/setcost s2 30 Colombia"),
    BotCommand("renamecountry", "/renamecountry s2 — rename"),
    BotCommand("setannounce", "Announcement channel"),
    BotCommand("setlowstock", "/setlowstock 5 — alert level"),
    BotCommand("setbrandname", "Set public brand name"),
    BotCommand("profitcalc", "/profitcalc 0.30 — price preview"),
    BotCommand("profitreport", "Margin + profit report"),
    BotCommand("setprofitmode", "tiers | pct"),
    BotCommand("setroundmode", "ceil | nearest | floor"),
    BotCommand("setmaxprice", "Cap the maximum price"),
    BotCommand("setcharm", "₹49/₹99 charm pricing"),
    BotCommand("setmargin", "/setmargin s1 MA 25"),
    BotCommand("applyprofit", "Recalculate every price"),
    BotCommand("addcoupon", "/addcoupon WELCOME 10% 100"),
    BotCommand("coupons", "List coupons"),
    BotCommand("ref", "Your referral link & earnings"),
    BotCommand("setrefbonus", "/setrefbonus 5 (percent)"),
    BotCommand("setsalepost", "Channel SOLD updates on/off"),
    BotCommand("setautorefund", "Auto-refund if no OTP"),
    BotCommand("setmaxbuy", "Daily purchase limit"),
    BotCommand("ban", "/ban <user id>"),
    BotCommand("restock", "Restock watchlist"),
    BotCommand("stats", "7-day sales chart"),
    BotCommand("setwelcome", "Custom welcome text"),
    BotCommand("motd", "Notice shown on /start"),
    BotCommand("setcurrency", "/setcurrency $ or ₹"),
    BotCommand("setfooter", "Note under every delivery"),
    BotCommand("setdesc", "/setdesc s1 BD <text>"),
    BotCommand("setbulk", "/setbulk 3 5 = 3 pcs 5% off"),
    BotCommand("setstockview", "exact | range | hidden"),
    BotCommand("setminprice", "/setminprice 10 — min sell price"),
    BotCommand("tgdry", "/tgdry on|off — test/live mode"),
    BotCommand("setemoji", "/setemoji crown <id>"),
    BotCommand("emojis", "Premium emoji list"),
    # ---- servers / stock ----
    BotCommand("agedcat", "Aged category tiles (/agedcat list)"),
    BotCommand("addserver", "Create a new server"),
    BotCommand("renameserver", "/renameserver s1 NewName"),
    BotCommand("delserver", "Delete a server"),
    BotCommand("addcountry", "/addcountry s1 Colombia (+price)"),
    BotCommand("delcountry", "/delcountry s1 — delete country"),
    BotCommand("addids", "/addids s1 — add IDs to a server"),
    BotCommand("delids", "/delids s1 — delete IDs by buttons"),
    BotCommand("setprice", "Change a country's price"),
    BotCommand("settags", "Edit quality tags"),
    BotCommand("clearsold", "Purge sold IDs from DB"),
    BotCommand("addqr", "Add UPI QR"),
    BotCommand("delqr", "Delete a QR"),
    BotCommand("setmindeposit", "/setmindeposit 25"),
    BotCommand("setdeptime", "/setdeptime 15"),
    BotCommand("setverify", "/setverify on|off"),
    BotCommand("setpaygroup", "/setpaygroup -100..."),
    BotCommand("setproofchannel", "/setproofchannel @ch"),
    BotCommand("setname", "Set store name"),
    BotCommand("setsupport", "Set support handle"),
    BotCommand("setbuynote", "Set login note"),
    BotCommand("addterm", "Add a term"),
    BotCommand("delterm", "Delete a term"),
    BotCommand("fadd", "Add force-join channel"),
    BotCommand("fdel", "Remove force-join channel"),
    BotCommand("addpromo", "/addpromo @channel 15 (days)"),
    BotCommand("delpromo", "/delpromo <#|all>"),
    BotCommand("promos", "List promo channels"),
    BotCommand("addadmin", "/addadmin <user id>"),
    BotCommand("deladmin", "/deladmin <user id>"),
    BotCommand("report", "Full business report"),
    BotCommand("sales", "Last 20 sales + status"),
    BotCommand("otp", "/otp <sale_id> — fetch any ID's OTP"),
    BotCommand("freezeid", "/freezeid <sale_id> [reason]"),
    BotCommand("unfreezeid", "/unfreezeid <sale_id>"),
    BotCommand("dm", "/dm <user id> <message>"),
    BotCommand("broadcast", "Broadcast to all users"),
    BotCommand("addapi", "/addapi <api_id> <hash>"),
    BotCommand("serverkeys", "Per-server supplier keys"),
    BotCommand("backup", "Database backup"),
    BotCommand("restore", "Restore from backup"),
    BotCommand("admins", "Admin list + menu status"),
    BotCommand("syncall", "Sync Server 1 + Server 2"),
    BotCommand("addchannel", "/addchannel Title | https://t.me/x"),
    BotCommand("shutdown", "Stop the bot (owner only)"),
]

_peer_warned = set()          # jin admins ke liye PEER_ID_INVALID log ho chuka hai


async def _try_set_admin_commands(uid):
    """Admin ka chat-scope command menu set karne ki SAFE try (PEER_ID_INVALID-safe)."""
    try:
        await app.set_bot_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(uid))
        _admin_menu_ok.add(uid)
        _admin_menu_pending.discard(uid)
        return True
    except Exception as e:
        s = str(e)
        if "PEER_ID_INVALID" in s or "PEER_ID_NOT_FOUND" in s:
            _admin_menu_pending.add(uid)
            if uid not in _peer_warned:            # sirf ek baar log — spam nahi
                _peer_warned.add(uid)
                logging.info("Admin %s: DM peer abhi nahi bana (PEER_ID_INVALID) — "
                             "nudge DM ke baad /start par menu auto-set hoga.", uid)
            else:
                logging.debug("Admin %s: abhi tak DM peer nahi bana.", uid)
        else:
            logging.warning("set admin commands for %s: %s", uid, e)
        return False

async def set_admin_menu(uid):
    if uid in _admin_menu_ok:
        return True
    return await _try_set_admin_commands(uid)

async def _admin_nudge(uid):
    try:
        await app.send_message(
            uid,
            f"🛠 <b>{esc(bot_name())} — Admin access ready</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Tap <b>/start</b> once — your admin command menu, "
            f"🛠️ <b>Admin Panel</b> and 📖 <b>Admin Help</b> buttons unlock instantly.",
            reply_markup=main_kb(uid))
    except Exception as e:
        logging.warning("admin nudge to %s failed: %s", uid, e)
    await asyncio.sleep(1.5)
    if await set_admin_menu(uid):
        logging.info("Admin %s: nudge ke baad command menu set ho gaya ✅", uid)

async def nudge_pending_admins():
    pend = sorted(_admin_menu_pending)
    if not pend:
        return
    logging.info("PEER_ID_INVALID fix: %s admin(s) ko /start nudge DM bheja jaa raha hai...", len(pend))
    for uid in pend:
        if uid in _nudge_scheduled:
            continue
        _nudge_scheduled.add(uid)
        asyncio.create_task(_admin_nudge(uid))

async def refresh_command_menus():
    try:
        await app.set_bot_commands(USER_COMMANDS, scope=BotCommandScopeDefault())
    except Exception as e:
        logging.error("set default commands: %s", e)
    for adm in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
        await set_admin_menu(adm)

async def reset_command_menu(uid):
    try:
        await app.set_bot_commands(USER_COMMANDS, scope=BotCommandScopeChat(uid))
    except Exception:
        pass
