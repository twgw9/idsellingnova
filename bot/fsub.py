"""Force-join verification + timed promo channels."""

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

# ================= FORCE SUBSCRIBE =================

async def check_fsub(client, uid):
    if is_admin(uid):
        return True
    missing = []
    for ch in db.get("fsub", []):
        try:
            member = await client.get_chat_member(ch["chat_id"], uid)
            if member.status in (enums.ChatMemberStatus.BANNED,
                                 enums.ChatMemberStatus.RESTRICTED,
                                 enums.ChatMemberStatus.LEFT):
                missing.append(ch)
        except UserNotParticipant:
            missing.append(ch)
        except Exception:
            missing.append(ch)
    if not missing:
        return True
    btns = promo_rows()
    btns += [[InlineKeyboardButton(f"🔗 {m['name']}", url=m["link"])] for m in missing]
    btns.append([InlineKeyboardButton("✅ Verify & Continue", callback_data="fsub_verify")])
    return InlineKeyboardMarkup(btns)

# ================= PROMO CHANNELS (time-limited) =================

def active_promos():
    now = time.time()
    return [p for p in db.get("promos", []) if p.get("until", 0) > now]

def prune_promos():
    promos = db.get("promos", [])
    keep = [p for p in promos if p.get("until", 0) > time.time()]
    if len(keep) != len(promos):
        db["promos"] = keep
        return True
    return False

def promo_rows():
    rows = []
    for p in active_promos():
        if p.get("link"):
            rows.append([InlineKeyboardButton(f"📢 {p['title']}", url=p["link"])])
    return rows

def promo_text_block():
    act = active_promos()
    if not act:
        return ""
    t = ("\n📢 <b>Promo Channels</b> — join kar lo (support us, optional):\n")
    for p in act:
        left = int((p["until"] - time.time()) // 86400) + 1
        t += f"    • {esc(p['title'])} — {left} din bacha hai\n"
    return t + "\n"

async def send_promo_screen(msg_or_query):
    rows = promo_rows()
    text = (f"{E('gift')} <b>Promo Channels</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            "Support the store — join our promo channels (optional):\n")
    for p in active_promos():
        left = int((p["until"] - time.time()) // 86400) + 1
        text += f"    • <b>{esc(p['title'])}</b> — {left} day(s) left\n"
    if not rows:
        text += "\n<i>(No joinable links right now)</i>\n"
    rows.append([InlineKeyboardButton("✅ Continue", callback_data="promos_done")])
    if isinstance(msg_or_query, Message):
        await msg_or_query.reply_text(text, reply_markup=InlineKeyboardMarkup(rows))
    else:
        await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(rows))

@app.on_callback_query(filters.regex("^promos_done$"))
async def promos_done_cb(client, query):
    await ack(query)
    await query.message.reply_text(
        f"{E('sparkle')} <b>Welcome to {esc(bot_name())}!</b> {E('sparkle')}\n"
        f"{E('live')} <i>Auto Delivery Enabled</i>\n{E('gem')} Use the menu below:",
        reply_markup=main_kb(query.from_user.id))
    try:
        await query.message.delete()
    except Exception:
        pass

def terms_block():
    return "\n".join(f"• {esc(t)}" for t in db.get("terms", [])) or "• No terms set."
