"""Shared helpers: formatting, keyboards, catalog, announce, low-stock, branding."""

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

# ================= SMALL HELPERS =================

def esc(x):
    return html.escape(str(x))

def bot_name():
    return db.get("bot_name") or db.get("bot_username") or "ID Store"

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def pretty_ts(ts):
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y, %I:%M %p")

def gen_ref(uid):
    return f"dep-{uid}-{int(time.time())}{random.randint(100, 999)}"

def gen_sale_id():
    while True:
        sid = "ORD" + "".join(random.choices(string.digits, k=6))
        if sid not in db.get("sold_sessions", {}):
            return sid

def is_admin(uid):
    return uid in OWNER_IDS or uid in db.get("admins", [])

async def ack(query, text=None, alert=False, show_alert=None):
    try:
        await query.answer(text, show_alert=(alert if show_alert is None else show_alert))
    except Exception:
        pass

def next_api_cred():
    creds = db.get("api_creds") or MULTI_API_CREDENTIALS
    if not creds:
        return {"api_id": API_ID, "api_hash": API_HASH}
    idx = db.get("api_idx", 0) % len(creds)
    db["api_idx"] = idx + 1
    return creds[idx]

FLAG_MAP = {
    "india": "🇮🇳", "brazil": "🇧🇷", "usa": "🇺🇸", "united states": "🇺🇸", "us": "🇺🇸",
    "colombia": "🇨🇴", "venezuela": "🇻🇪", "uruguay": "🇺🇾", "fiji": "🇫🇯",
    "bangladesh": "🇧🇩", "nigeria": "🇳🇬", "indonesia": "🇮🇩", "pakistan": "🇵🇰",
    "russia": "🇷🇺", "uk": "🇬🇧", "united kingdom": "🇬🇧", "germany": "🇩🇪",
    "france": "🇫🇷", "spain": "🇪🇸", "mexico": "🇲🇽", "argentina": "🇦🇷",
    "philippines": "🇵🇭", "vietnam": "🇻🇳", "egypt": "🇪🇬", "turkey": "🇹🇷",
    "iraq": "🇮🇶", "iran": "🇮🇷", "morocco": "🇲🇦", "ethiopia": "🇪🇹",
    "kenya": "🇰🇪", "ghana": "🇬🇭", "cambodia": "🇰🇭", "myanmar": "🇲🇲",
    "nepal": "🇳🇵", "sri lanka": "🇱🇰", "malaysia": "🇲🇾", "thailand": "🇹🇭",
    "japan": "🇯🇵", "china": "🇨🇳", "australia": "🇦🇺", "canada": "🇨🇦",
    "italy": "🇮🇹", "portugal": "🇵🇹", "netherlands": "🇳🇱", "belgium": "🇧🇪",
    "sweden": "🇸🇪", "ukraine": "🇺🇦", "poland": "🇵🇱", "romania": "🇷🇴",
    "peru": "🇵🇪", "chile": "🇨🇱", "ecuador": "🇪🇨", "bolivia": "🇧🇴",
    "paraguay": "🇵🇾", "guatemala": "🇬🇹", "honduras": "🇭🇳", "dominican republic": "🇩🇴",
    "south africa": "🇿🇦", "saudi arabia": "🇸🇦", "uae": "🇦🇪", "uzbekistan": "🇺🇿",
    "kazakhstan": "🇰🇿", "azerbaijan": "🇦🇿", "zimbabwe": "🇿🇼",
}

def flag_of(country):
    return FLAG_MAP.get(str(country).strip().lower(), "🌍")

def mask_phone_confirm(num):
    d = re.sub(r"\D", "", str(num))
    if len(d) > 7:
        return d[:3] + "••••••" + d[-4:]
    if len(d) > 4:
        return d[:2] + "•••" + d[-2:]
    return d

def mask_phone_proof(num):
    d = re.sub(r"\D", "", str(num))
    if len(d) > 8:
        return "+" + d[:3] + "*****" + d[-3:]
    return "+" + d if d else "—"

def format_url(link):
    link = str(link).strip()
    return link if link.startswith("http") else f"https://t.me/{link.replace('@', '')}"


# ================= ANNOUNCE / LOW-STOCK / BRANDING (v5.0) =================







_low_stock_sent = {}          # "code:country" -> last alert time (spam-free)


async def safe_send(chat_id, text, **kw):
    """FloodWait-safe send: limit aane par wait karke retry (crash nahi)."""
    for _ in range(3):
        try:
            return await app.send_message(chat_id, text, **kw)
        except FloodWait as e:
            await asyncio.sleep(int(getattr(e, "value", 0) or 1) + 1)
        except Exception as e:
            logging.warning("safe_send(%s) failed: %s", chat_id, e)
            return None
    return None


def announce_target():
    """Price/stock announcements kahan jayengi (default: proof channel)."""
    return db.get("announce_channel") or db.get("proof_channel")


async def announce(text):
    ch = announce_target()
    if not ch:
        return False
    try:
        return bool(await safe_send(ch, text))
    except Exception as e:
        logging.warning("announce failed: %s", e)
        return False


async def announce_price_change(where, old_price, new_price, extra=""):
    """Price badalte hi group/channel me auto announcement."""
    if old_price == new_price:
        return False
    arrow = "📈" if new_price > old_price else "📉"
    txt = (f"{E('money')} <b>PRICE UPDATE</b> {arrow}\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"{E('tag')} <b>{esc(where)}</b>\n"
           f"💰 <s>₹{esc(old_price)}</s>  →  <b>₹{esc(new_price)}</b>\n"
           f"🕒 {now_str()}")
    if extra:
        txt += f"\n{extra}"
    return await announce(txt)


async def check_low_stock(code=None):
    """Stock khatam/kam ho to admins ko auto alert (har country 1 ghante me ek baar)."""
    thr = int(db.get("low_stock", TGSHARK_LOW_STOCK) or 0)
    if thr <= 0:
        return 0
    codes = [code] if code else server_codes()
    lines = []
    for c in codes:
        srv = get_server(c)
        if not srv:
            continue
        for n in country_list(srv):
            cnt = stock_count(srv["countries"][n])
            if cnt <= thr:
                key = f"{c}:{n}"
                if time.time() - _low_stock_sent.get(key, 0) < 3600:
                    continue
                _low_stock_sent[key] = time.time()
                status = f"{E('cross')} OUT OF STOCK" if cnt <= 0 else f"{E('warn')} LOW ({cnt} left)"
                lines.append(f"   {cflag(srv, n)} {esc(cname(srv, n))} — {status} — {esc(srv['name'])} ({c})")
    if not lines:
        return 0
    txt = (f"{E('warn')} <b>LOW STOCK ALERT</b>\n━━━━━━━━━━━━━━━━━━\n"
           + "\n".join(lines)
           + f"\n\n{E('box')} Threshold: {thr} numbers\n"
             f"👉 Refill: <code>/tgsync</code> (live server) ya <code>/addids s1</code> (manual server)")
    sent = 0
    for a in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
        try:
            if await safe_send(a, txt):
                sent += 1
        except Exception:
            pass
    return sent


def _bot_api_call(method, **params):
    """Bot API helper (naam/description branding ke liye)."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, data=urlencode(params).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


async def apply_branding():
    """Public bot ko premium branding do (in-bot name + Telegram profile)."""
    name = (db.get("bot_name") or BRAND_NAME).strip()
    db["bot_name"] = name          # in-bot branding works even if Telegram is rate-limited
    try:
        res = await asyncio.to_thread(_bot_api_call, "setMyName", name=name)
        if not res.get("ok"):
            logging.warning("setMyName rejected: %s", res)
    except urllib.error.HTTPError as e:
        if e.code == 400:                     # Telegram can demand a "Bot" suffix
            try:
                res = await asyncio.to_thread(_bot_api_call, "setMyName", name=f"{name} Bot")
                if res.get("ok"):
                    db["bot_name"] = f"{name} Bot"
            except Exception as e2:
                logging.warning("setMyName fallback failed: %s", e2)
        else:
            logging.info("setMyName skipped (HTTP %s — Telegram rate-limits name changes).", e.code)
    except Exception as e:
        logging.warning("setMyName failed: %s", e)
    for method, key, val in (("setMyShortDescription", "short_description", BRAND_SHORT),
                             ("setMyDescription", "description", BRAND_ABOUT)):
        try:
            await asyncio.to_thread(_bot_api_call, method, **{key: val})
        except Exception as e:
            logging.warning("%s failed: %s", method, e)


# ================= SERVER / STOCK HELPERS =================

def server_codes():
    return [c for c in db.get("server_order", []) if c in db.get("servers", {})]

def get_server(code):
    return db.get("servers", {}).get(code)

def country_list(server):
    return list(server.get("countries", {}).keys()) if server else []

def sold_ids(country_obj):
    if country_obj.get("api"):
        return []
    return [i for i in country_obj.get("ids", []) if i.get("sold", False)]

def unsold_ids(country_obj):
    """API country → LIVE stock se 1 virtual item (asli count alag field me)."""
    if country_obj.get("api"):
        n = int(country_obj.get("api_count", 0) or 0)
        if n <= 0:
            return []
        return [{
            "id": "api_" + str(country_obj.get("iso", "XX")),
            "number": "LIVE-NUMBER",
            "password": "None",
            "session_string": "",
            "price": country_price(country_obj),
            "label": f"{iso_flag(country_obj.get('iso', 'XX'))} {iso_name(country_obj.get('iso', 'XX'))} • Fresh",
            "api": True,
            "sold": False,
            "added": now_str(),
        }]
    return [i for i in country_obj.get("ids", []) if not i.get("sold", False)]

def support_url():
    """Support link hamesha clickable https URL me."""
    raw = (db.get("support_link") or DEFAULT_SUPPORT or "").strip()
    if raw.startswith("http"):
        return raw
    if raw.startswith("@"):
        return "https://t.me/" + raw[1:]
    if raw.startswith("t.me/"):
        return "https://" + raw
    return raw or "https://t.me/" + (DEFAULT_SUPPORT or "").lstrip("@")


def home_channel_kb():
    """Admin ke set kiye channels (sales updates, stock, offers…) ke buttons."""
    rows = []
    for ch in (db.get("home_channels") or []):
        url = (ch.get("url") or "").strip()
        title = (ch.get("title") or "").strip() or "Channel"
        if url:
            rows.append([InlineKeyboardButton(f"📢 {title}", url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


def server_uplift(code):
    """Is server ka extra margin (aged/premium servers ke liye) → (pct, add₹)."""
    srv = get_server(code) or {}
    pct = float(srv.get("uplift_pct", 0) or 0)
    add = float(srv.get("uplift_add", 0) or 0)
    return pct, add


def is_banned(uid):
    return int(uid) in [int(x) for x in (db.get("banned") or [])] and not is_admin(uid)


async def banned_gate(message=None, query=None):
    """Banned user ko bot use karne hi mat do — Contact Support button ke saath."""
    uid = (message.from_user.id if message is not None else
           (query.from_user.id if query is not None else None))
    if uid is None or not is_banned(uid):
        return False
    txt = (f"🚫 <b>You are banned</b>\n━━━━━━━━━━━━━━━━━━\n"
           f"Aapka account is store se <b>banned</b> hai — aap bot use nahi kar sakte.\n\n"
           f"Agar lagta hai ye galti se hua hai to support se baat karein.")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📞 Contact Support", url=support_url())]])
    try:
        if query is not None:
            await ack(query)
            await query.message.edit_text(txt, reply_markup=kb)
        else:
            await message.reply_text(txt, reply_markup=kb)
    except Exception:
        pass
    return True


async def log_event(text):
    """Owner ke private log group me event bhejo (set na ho to chupchap skip)."""
    target = (LOG_GROUP or db.get("log_group") or "").strip()
    if not target:
        return False
    try:
        return bool(await safe_send(target, text))
    except Exception:
        return False


def country_price(country_obj, key=None):
    """Price jo customer ko dikhega.
    Stored price hi use hoti hai (tier/override/margin sab usi me hai);
    sirf tab calculate karo jab stored price na ho."""
    if country_obj.get("api"):
        stored = int(country_obj.get("price", 0) or 0)
        return stored if stored > 0 else tg_sell_price(country_obj.get("api_cost", 0), key)
    return int(country_obj.get("price", 0) or 0)

def stock_count(country_obj):
    if country_obj.get("api"):
        return int(country_obj.get("api_count", 0) or 0)
    return len(unsold_ids(country_obj))

def server_stock_count(server):
    return sum(stock_count(c) for c in server.get("countries", {}).values())

def cname(srv, n):
    """Display name (API country me ISO ka readable naam)."""
    cobj = (srv.get("countries", {}) or {}).get(n, {}) if srv else {}
    return cobj.get("display") or n

def cflag(srv, n):
    cobj = (srv.get("countries", {}) or {}).get(n, {}) if srv else {}
    if cobj.get("api"):
        return iso_flag(cobj.get("iso") or n)
    return flag_of(n)

def user_record(uid, name=None):
    u = str(uid)
    if u not in db["users"]:
        db["users"][u] = {"joined": time.time(), "name": name or "Unknown",
                          "balance": 0, "deposited": 0, "spent": 0, "purchases": 0}
    elif name:
        db["users"][u]["name"] = name
    return db["users"][u]

def balance_of(uid):
    return db["users"].get(str(uid), {}).get("balance", 0)


# ================= KEYBOARDS =================

MAIN_LABELS = {"🛒 Products", "👤 Profile", "💳 Deposit", "📞 Support",
               "🛠️ Admin Panel", "📖 Admin Help"}

def main_kb(uid):
    kb = [
        ["🛒 Products"],
        ["👤 Profile", "💳 Deposit"],
        ["📞 Support"],
    ]
    if is_admin(uid):
        kb.append(["🛠️ Admin Panel", "📖 Admin Help"])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

SERVER_EMOJI = ["🟢", "🟣", "", "🔵", "🟡", "", "️", ""]

def server_emoji(idx):
    return SERVER_EMOJI[idx % len(SERVER_EMOJI)]
