"""Background loops: expiry, auto-sync, auto-backup, dead-ID checks."""

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

# ================= BACKGROUND TASKS =================

async def cleanup_signins():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        for uid in list(active_sign_ins.keys()):
            if now - active_sign_ins[uid].get("ts", now) > SIGNIN_TTL_SECS:
                try:
                    await active_sign_ins[uid]["client"].disconnect()
                except Exception:
                    pass
                active_sign_ins.pop(uid, None)

async def deposit_expiry_monitor():
    while True:
        await asyncio.sleep(60)
        now = time.time()
        ttl = db.get("dep_timeout_mins", 15) * 60
        expired = []
        async with db_lock:
            for ref, dep in list(db.get("pending_deposits", {}).items()):
                if now - dep["time"] > ttl:
                    expired.append((ref, dep))
                    del db["pending_deposits"][ref]
                    db["processed_deposits"][ref] = "expired"
                    db["deposit_log"].append({"ref": ref, "uid": dep["uid"],
                                              "amount": dep["amount"], "status": "expired",
                                              "time": now_str(), "by": "system"})
            if expired:
                await save_db()
        for ref, dep in expired:
            try:
                await app.edit_message_caption(
                    chat_id=dep["uid"], message_id=dep["msg_id"],
                    caption=f"⌛ <b>PAYMENT EXPIRED</b>\n🔖 Ref: <code>{ref}</code>\n"
                            f"💰 Amount: ₹{dep['amount']}\n\nThis request timed out. "
                            f"Start a new deposit from the 💳 Deposit menu.",
                    reply_markup=None)
            except Exception:
                pass
            for chat_id, msg_id in dep.get("group_msgs", {}).items():
                try:
                    await app.edit_message_caption(
                        chat_id=int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
                        message_id=msg_id,
                        caption=f"⌛ <b>EXPIRED</b> | Ref: <code>{ref}</code> | ₹{dep['amount']}",
                        reply_markup=None)
                except Exception:
                    pass
            try:
                await app.send_message(
                    dep["uid"],
                    f"⌛ <b>{esc(bot_name())} — Deposit Expired</b>\n"
                    f"💰 Amount: ₹{dep['amount']}\n🔖 Ref: <code>{ref}</code>\n\n"
                    f"If you already paid, contact {esc(db['support_link'])} with this Ref ID.")
            except Exception:
                pass

# ---------- v4.0: TGShark auto stock/price sync ----------
async def notify_restock(code, name, watchers):
    """Jab koi country wapas stock me aaye to subscribers ko DM."""
    srv = get_server(code)
    if not srv:
        return
    price = country_price(srv["countries"].get(name, {}))
    txt = (f"{E('bell' if 'bell' in EMOJI else 'sparkle')} <b>BACK IN STOCK!</b>\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"{E('globe')} <b>{esc(cname(srv, name))}</b> is available again.\n"
           f"{E('money')} Price: ₹{price}\n\n"
           f"🛒 Tap Products to buy before it sells out!")
    sent = 0
    for w in watchers[:200]:
        try:
            if await safe_send(int(w), txt):
                sent += 1
        except Exception:
            pass
    logging.info("Restock alert sent to %s user(s) for %s", sent, name)


async def tg_sync_stock():
    """API se countries + price + stock laakar API-server me daal do."""
    code = api_server_code()
    srv = get_server(code)
    if not srv:
        return 0, "❌ API server not found (create server 1 first: /addserver)"
    if not api_key_ok():
        return 0, api_key_missing_msg()
    res = await tg_api("getCountrys")
    if res.get("status") != "ok":
        msg = str(res.get("message", "unknown"))
        hint = ""
        if "apikey" in msg.lower() or "unauthor" in msg.lower():
            hint = (" — key galat/expired lag rahi hai: .env me TGSHARK_API_KEY check karo "
                    "ya bot me /setapikey &lt;nayi key&gt;")
        return 0, f"❌ API error: {esc(msg)}{hint}"
    countries = res.get("countries") or []
    added = updated = 0
    for c in countries:
        iso = str(c.get("iso") or c.get("country") or "").upper()
        if not iso:
            continue
        cnt = int(c.get("count", 0) or 0)
        cost = float(c.get("min_price", 0) or 0)
        cobj = srv["countries"].get(iso)
        old_cnt = int(cobj.get("api_count", 0)) if cobj else 0
        if cobj is None:
            cobj = {"api": True, "iso": iso, "display": iso_name(iso),
                    "tags": db.get("default_tags", DEFAULT_TAGS), "ids": []}
            srv["countries"][iso] = cobj
            added += 1
        else:
            updated += 1
        cobj["api"] = True
        cobj["iso"] = iso
        cobj["display"] = iso_name(iso)
        cobj["api_count"] = cnt
        cobj["api_cost"] = cost
        cobj["api_max"] = float(c.get("max_price", cost) or cost)
        cobj["price"] = tg_sell_price(cost, price_key(code, iso))
        if old_cnt <= 0 and cnt > 0:                      # restock -> alert subscribers
            watchers = (db.get("notify") or {}).pop(price_key(code, iso), [])
            if watchers:
                asyncio.create_task(notify_restock(code, iso, watchers))
    db["tgshark"]["last_sync"] = time.time()
    bal = await tg_api("getBalance")
    if bal.get("status") == "ok":
        db["tgshark"]["last_balance"] = bal.get("balance", 0)
    await save_db()
    return (added + updated), f"✅ Synced: <b>+{added}</b> new, <b>{updated}</b> updated (total {len(countries)} countries)"

async def tg_sync_loop():
    await asyncio.sleep(120)          # startup ke 2 min baad pehla sync
    while True:
        try:
            if api_server_code():
                n, msg = await tg_sync_stock()
                logging.info("Live-server auto-sync: %s", msg)
                await check_low_stock()
        except Exception as e:
            logging.warning("Live-server sync failed: %s", e)
        await asyncio.sleep(max(5, TGSHARK_SYNC_MINS) * 60)

BACKUP_DIR = "backups"

def _snapshot(tag):
    try:
        if not os.path.exists(DB_FILE):
            return None
        os.makedirs(BACKUP_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"id_store_db-{tag}-{ts}.json")
        shutil.copyfile(DB_FILE, dst)
        files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith(f"id_store_db-{tag}-"))
        for old in files[:-10]:
            try:
                os.remove(os.path.join(BACKUP_DIR, old))
            except Exception:
                pass
        return dst
    except Exception as e:
        logging.warning("snapshot(%s) failed: %s", tag, e)
        return None

async def auto_backup():
    await asyncio.sleep(90)
    while True:
        try:
            await save_db()
            dst = _snapshot("auto")
            if dst:
                logging.info("Auto backup: %s", dst)
        except Exception as e:
            logging.warning("Auto backup failed: %s", e)
        await asyncio.sleep(6 * 3600)
