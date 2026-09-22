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

async def fsub_state(client, chat_id, uid):
    """member | pending | left | banned | restricted | unknown"""
    try:
        m = await client.get_chat_member(chat_id, uid)
        st = str(getattr(m, "status", "")).upper()
        if "BANNED" in st:
            return "banned"
        if "RESTRICTED" in st:
            return "restricted"
        if "LEFT" in st:
            return "left"
        return "member"
    except UserNotParticipant:
        pass
    except Exception:
        return "unknown"
    # join REQUEST pending hai? (naye pyrogram me hi milta hai)
    getter = getattr(client, "get_chat_join_requests", None)
    if getter:
        try:
            async for u in getter(chat_id, limit=200):
                if int(getattr(u, "id", 0)) == int(uid):
                    return "pending"
            return "left"
        except Exception:
            return "unknown"
    return "unknown"          # confirm nahi kar sakte → Verify click par chhod do


async def bot_api(method, **params):
    """Seedha Telegram Bot API call (pyrogram me pending-request ka raw nahi hai)."""
    token = (BOT_TOKEN or "").strip()
    if not token:
        return None
    try:
        url = f"https://api.telegram.org/bot{token}/{method}"
        data = urlencode({k: v for k, v in params.items() if v is not None}).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


async def try_join_requests(chat_id, uid):
    """Pending join request ho to approve kar do.

    True   → pending request thi, ab member hai (ya pehle se member)
    False  → koi pending request nahi (abhi join nahi kiya)
    None   → bot admin nahi / pata nahi chala
    """
    res = await bot_api("approveChatJoinRequest", chat_id=chat_id, user_id=uid)
    if res is None:
        return None
    if res.get("ok"):
        return True
    desc = str(res.get("description") or "")
    low = desc.lower()
    if "already" in low or "participant" in low and "missing" not in low:
        return True                                   # pehle se member hai
    if "hide_requester_missing" in low or "requester missing" in low:
        return False                                  # koi pending request nahi
    if "chat_admin_required" in low or "not enough rights" in low or "forbidden" in low:
        return None                                   # bot admin nahi
    return None


def fsub_lenient():
    """lenient = join request pending ho (ya confirm na ho paye) to bhi andar aane do."""
    return str(db.get("fsub_mode") or "lenient").lower() != "strict"


def fsub_mark_ok(uid):
    db.setdefault("fsub_ok", {})[str(uid)] = time.time()


FSUB_CACHE_TTL = 6 * 3600          # 6 ghante tak baar baar check na karo


async def check_fsub(client, uid):
    if is_admin(uid):
        return True
    if not db.get("fsub") or client is None:
        return True
    if time.time() - float((db.get("fsub_ok") or {}).get(str(uid)) or 0) < FSUB_CACHE_TTL:
        return True                                   # haal hi me verify ho chuka
    missing = []
    for ch in db["fsub"]:
        state = await fsub_state(client, ch["chat_id"], uid)
        if state in ("left", "banned"):
            missing.append(ch)
        elif state in ("restricted", "unknown"):
            missing.append(ch)                        # Verify click par decide hoga
        # member / pending → theek hai
    if not missing:
        fsub_mark_ok(uid)
        return True
    btns = promo_rows()
    btns += [[InlineKeyboardButton(f"🔗 {m['name']}", url=m["link"])]
             for m in missing if m.get("link")]
    btns.append([InlineKeyboardButton("✅ Verify & Continue", callback_data="fsub_verify")])
    return InlineKeyboardMarkup(btns)


# ================= AUTO FORCE-JOIN (naya channel/GC add hote hi) =================

def _chat_ref_from_url(url):
    """https://t.me/xxx  →  @xxx  (private +links chhod do)"""
    u = (url or "").strip().rstrip("/")
    if "t.me/" not in u:
        return ""
    tail = u.split("t.me/", 1)[1].split("?")[0].strip("/")
    if not tail or tail.startswith("+"):
        return ""
    return "@" + tail.lstrip("@")


def auto_fsub_add(chat_ref, name=None, link=None, url=None):
    """Naya channel/GC jab bhi add ho → force-join me bhi daal do (AUTO_FSUB on ho to)."""
    if not db.get("auto_fsub", True):
        return False
    ref = (chat_ref or "").strip() or _chat_ref_from_url(url or "")
    if not ref:
        return False
    link = (link or "").strip()
    if not link and ref.startswith("@"):
        link = "https://t.me/" + ref[1:]
    lst = db.setdefault("fsub", [])
    for c in lst:
        if str(c.get("chat_id")) == ref or (link and c.get("link") == link):
            return False                             # pehle se hai
    lst.append({"chat_id": ref, "link": link, "name": (name or ref).strip(), "auto": True})
    return True


# ================= GATE: normal click par, kharidari ke beech me nahi =================

NAV_PREFIXES = ("home", "products", "profile", "deposit", "support", "myids",
                "terms", "help", "srv_", "cpg_", "cid_", "ratecard_", "chan_",
                "ref", "coupon", "promos", "buy_menu")
SKIP_PREFIXES = ("buy_", "otp_", "dep_", "adm", "fsub", "noop", "accept_terms",
                 "close", "cancel", "del", "edit", "tags_", "price_", "did_", "aid_")


def in_purchase_flow(uid):
    """Abhi koi number kharid raha hai ya OTP ka intezaar chal raha hai?"""
    now = time.time()
    for sd in (db.get("sold_sessions") or {}).values():
        if int(sd.get("uid") or 0) == int(uid) and sd.get("status") in ("pending", "waiting_otp"):
            if now - float(sd.get("sold_at") or 0) < 1800:          # 30 min
                return True
    return bool((db.get("user_states") or {}).get(uid) or (user_states or {}).get(uid))


def fsub_gate_needed(uid, data=""):
    if is_admin(uid) or not db.get("fsub"):
        return False
    d = str(data or "")
    if not d:
        return False
    if d.startswith(SKIP_PREFIXES):
        return False
    if not d.startswith(NAV_PREFIXES):
        return False
    if in_purchase_flow(uid):                 # buy/OTP ke beech me kabhi nahi
        return False
    if time.time() - float((db.get("fsub_ok") or {}).get(str(uid)) or 0) < FSUB_CACHE_TTL:
        return False
    return True


async def fsub_gate(client, uid):
    """(text, markup) ya None — None ka matlab gate dikhane ki zarurat nahi."""
    res = await check_fsub(client, uid)
    if res is True:
        return None
    return (f"🔒 <b>Join first to continue</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Join our channel(s), phir <b>✅ Verify &amp; Continue</b> dabayein.\n\n"
            f"<i>Join request pending hai? Verify dabane ke baad bhi aap andar aa jayenge.</i>",
            res)

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
        home_header(uid) + "\n"
        f"{E('live')} <i>Auto delivery enabled</i>\n{E('gem')} Use the menu below:",
        reply_markup=main_kb(query.from_user.id))
    try:
        await query.message.delete()
    except Exception:
        pass

def terms_block():
    return "\n".join(f"• {esc(t)}" for t in db.get("terms", [])) or "• No terms set."
