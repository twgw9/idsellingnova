"""Auto OTP delivery + session management (manual servers)."""

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

# ================= AUTO OTP DELIVERY + SESSIONS =================

def owns_sale(uid, sale_id):
    return is_admin(uid) or any(s["sale_id"] == sale_id and s["uid"] == uid
                                for s in db.get("sales", []))

def extract_otp_code(text):
    m = re.search(r"\b(\d{5,6})\b", text or "")
    return m.group(1) if m else None

DEAD_SESSION_ERRORS = ("AUTH_KEY_UNREGISTERED", "USER_DEACTIVATED", "SESSION_REVOKED",
                       "AUTH_KEY_INVALID", "AUTH_KEY_PERM_EMPTY")

def dead_reason_from_exc(e):
    s = str(e)
    for k in DEAD_SESSION_ERRORS:
        if k in s:
            return k
    return None

async def fetch_otp(session_string, min_ts=0):
    temp = None
    try:
        cred = next_api_cred()
        temp = Client(f"otpf_{random.randint(1000, 9999)}",
                      api_id=cred["api_id"], api_hash=cred["api_hash"],
                      session_string=session_string, in_memory=True)
        await temp.connect()
        async for msg in temp.get_chat_history(777000, limit=5):
            if msg.date and msg.date < min_ts:
                continue
            if msg.text and any(ch.isdigit() for ch in msg.text):
                try:
                    await temp.disconnect()
                except Exception:
                    pass
                return extract_otp_code(msg.text), msg.text, msg.date, None
        try:
            await temp.disconnect()
        except Exception:
            pass
        return None, None, 0, None
    except Exception as e:
        dr = dead_reason_from_exc(e)
        if dr:
            logging.warning("OTP fetch: session DEAD (%s)", dr)
        else:
            logging.error("OTP fetch error: %s", e)
        if temp:
            try:
                await temp.disconnect()
            except Exception:
                pass
        return None, None, 0, dr

def otp_kb(sale_id, api=False):
    rows = [[InlineKeyboardButton(f"{E('sync')} Request New OTP", callback_data=f"newotp_{sale_id}")]]
    if not api:
        rows.append([InlineKeyboardButton("📱 Manage Sessions", callback_data=f"sessions_{sale_id}")])
    rows.append([InlineKeyboardButton(f"{E('box')} My IDs", callback_data="myids")])
    rows.append([InlineKeyboardButton("🏠 Back to Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)

async def send_otp_acquired(uid, sale_id, code=None, full=None):
    sd = db.get("sold_sessions", {}).get(sale_id, {})
    country = sd.get("country", "")
    # ---- v4.0: LIVE API order ----
    if sd.get("api"):
        twofa = sd.get("twofa") or ""
        if not code:
            text = (f"{E('clock')} <b>OTP on the way!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E('globe')} Country: {iso_flag(sd.get('iso'))} {esc(country)}\n"
                    f"{E('phone')} Number: <code>{esc(sd.get('number', ''))}</code>\n\n"
                    f"No OTP arrived yet.\nEnter this number in Telegram and request a "
                    f"<b>login code</b>, then tap <b>🔄 Request New OTP</b>.")
        else:
            twofa_show = (f"<code>{esc(twofa)}</code>"
                          if twofa and str(twofa).lower() not in ("none", "null", "") else "Not set")
            test_note = ("\n\n🧪 <i>Demo mode — this is a sample OTP.</i>"
                         if tg_cfg()["dry_run"] else "")
            text = (f"{E('star')} <b>Number Acquired — OTP!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{E('globe')} Country: {iso_flag(sd.get('iso'))} {esc(country)}\n"
                    f"{E('phone')} Number: <code>{esc(sd.get('number', ''))}</code>\n\n"
                    f"{E('key')} OTP Code: <code>{esc(code)}</code>\n"
                    f"{E('lock')} 2FA: {twofa_show}\n"
                    f"{E('money')} Paid: ₹{sd.get('price_inr', 0)}\n"
                    f"{test_note}")
        return await app.send_message(uid, text, reply_markup=otp_kb(sale_id, api=True))
    # ---- manual (session) order ----
    if not code:
        text = (f"⏳ <b>OTP on the way!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🌍 Country: {flag_of(country)} {esc(country)}\n"
                f"📞 Number: <code>{esc(sd.get('number', ''))}</code>\n\n"
                f"No OTP found yet. Request a login code in Telegram for this number, "
                f"then press <b>🔄 Request New OTP</b>.")
    else:
        pwd = sd.get("password", "None")
        pwd_show = f"<code>{esc(pwd)}</code>" if pwd not in (None, "", "None") else "No password set"
        text = (f"{E('star')} <b>Number Acquired!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🌍 Country: {flag_of(country)} {esc(country)}\n"
                f"📞 Number: <code>{esc(sd.get('number', ''))}</code>\n\n"
                f"💬 OTP Code: <code>{esc(code)}</code>\n"
                f"🔐 2FA Password: {pwd_show}\n\n"
                f"✅ Thank you for purchasing!")
    await app.send_message(uid, text, reply_markup=otp_kb(sale_id))

async def mark_id_dead(sale_id, reason):
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or sd.get("dead"):
        return
    sd["dead"] = reason
    sd["dead_at"] = time.time()
    try:
        await save_db()
    except Exception:
        pass
    uid = sd.get("uid")
    uname = db["users"].get(str(uid), {}).get("name", "?")
    sold_at = datetime.fromtimestamp(sd.get("sold_at", 0)).strftime("%d %b %Y %H:%M")
    alert = (
        f"🚨 <b>ID LOGGED OUT / FROZEN</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Order: <code>{sale_id}</code>\n"
        f"📞 Number: <code>{esc(sd.get('number', '?'))}</code>\n"
        f"🌍 Country: {esc(sd.get('country', '?'))}\n"
        f"🏷 Label: {esc(sd.get('label', '-'))}\n"
        f"👤 Buyer: {esc(uname)} (uid <code>{uid}</code>)\n"
        f"💸 Sold: {sold_at}\n"
        f"❄️ Reason: <code>{esc(reason)}</code>\n"
        f"🕒 Detected: {now_str()}\n\n"
        f"🔒 Is ID ka OTP delivery user ke liye DISABLED kar diya gaya.\n"
        f"🛠 /otp {sale_id} • /freezeid • /unfreezeid • /sales"
    )
    for a in dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS):
        try:
            await app.send_message(a, alert)
        except Exception as e:
            logging.warning("dead-ID alert to %s failed: %s", a, e)
    try:
        await app.send_message(
            uid,
            f"❄️ <b>ID Frozen</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Order: <code>{sale_id}</code>\n"
            f"📞 Number: <code>{esc(sd.get('number', ''))}</code>\n\n"
            f"⚠️ This account has been <b>logged out / banned</b> "
            f"(<code>{esc(reason)}</code>).\n"
            f"🔒 OTP delivery is now disabled for this ID.\n"
            f"📞 Contact support: {esc(db.get('support_link') or DEFAULT_SUPPORT)}")
    except Exception:
        pass

async def auto_otp_delivery(sale_id, uid):
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd:
        return
    # v4.0: API order → API OTP watcher
    if sd.get("api"):
        return await api_otp_watcher(sale_id, uid, delay=AUTO_OTP_DELAY)
    await asyncio.sleep(AUTO_OTP_DELAY)
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or not sd.get("session_string") or sd.get("session_dead") or sd.get("dead"):
        return
    min_ts = sd.get("otp_after", sd.get("sold_at", 0))
    code, full, mdate, dr = await fetch_otp(sd["session_string"], min_ts)
    if dr:
        await mark_id_dead(sale_id, dr)
        return
    if code:
        sd["otp_after"] = (mdate or time.time()) + 1
        try:
            await save_db()
        except Exception:
            pass
    try:
        await send_otp_acquired(uid, sale_id, code, full)
    except Exception as e:
        logging.error("Auto OTP send failed: %s", e)

async def show_sessions(query, sale_id):
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or not sd.get("session_string"):
        return await ack(query, "❌ Session not available for this order.", show_alert=True)
    if sd.get("session_dead"):
        return await ack(query, "🚫 The bot session for this order was terminated — "
                                "OTP delivery is disabled for it.", show_alert=True)
    if sd.get("dead"):
        return await ack(query, f"❄️ This ID is frozen/logged out ({sd['dead']}).",
                         show_alert=True)
    await ack(query, "⏳ Loading sessions...")
    temp = None
    try:
        cred = next_api_cred()
        temp = Client(f"sess_{random.randint(1000, 9999)}",
                      api_id=cred["api_id"], api_hash=cred["api_hash"],
                      session_string=sd["session_string"], in_memory=True)
        await temp.connect()
        res = await temp.invoke(raw_funcs.account.GetAuthorizations())
        await temp.disconnect()
        lines, btns = [], []
        for i, a in enumerate(res.authorizations, 1):
            cur = "🟢 Current (bot)" if a.current else "⚪️ Old"
            when = datetime.fromtimestamp(a.date_created).strftime("%d %b %Y")
            dev = esc(getattr(a, "device", "?")) or "?"
            place = esc(getattr(a, "country", "?")) or "?"
            lines.append(f"{i}. {cur} — {dev} • {place} • {when}")
            btns.append([InlineKeyboardButton(
                f"⛔ Terminate #{i} ({dev} • {when})",
                callback_data=f"ksess_{sale_id}_{a.hash}")])
        text = (f"📱 <b>Active Sessions</b> — <code>{sale_id}</code>\n"
                f"━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) +
                f"\n\n⛔ Tap a terminate button to kill that exact session.\n"
                f"⚠️ <b>Warning:</b> terminating the bot (current) session will stop "
                f"OTP delivery for this order permanently.")
        btns.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"sessions_{sale_id}"),
                     InlineKeyboardButton("🔙 Back", callback_data="myids")])
        btns.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(btns))
    except Exception as e:
        dr = dead_reason_from_exc(e)
        if dr:
            await mark_id_dead(sale_id, dr)
            return await query.message.reply_text(
                "❄️ <b>This ID has been logged out / banned.</b>\n"
                "OTP and session management are now disabled for it — admins have been notified.")
        await query.message.reply_text(f"❌ Sessions fetch failed: <code>{esc(e)}</code>\n"
                                       f"(If the buyer logged in elsewhere, this session may be dead.)")

async def confirm_kill_session(query, sale_id, h):
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or sd.get("session_dead"):
        return await ack(query, "🚫 Session already terminated for this order.", show_alert=True)
    await ack(query)
    await query.message.reply_text(
        f"⛔ <b>Terminate this session?</b> (<code>{sale_id}</code>)\n\n"
        f"⚠️ <b>Warning:</b> if you terminate the <b>bot (current) session</b>, "
        f"OTP will <b>no longer be delivered</b> for this order — it cannot be undone.\n",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⛔ Confirm Terminate", callback_data=f"ksessc_{sale_id}_{h}")],
            [InlineKeyboardButton("🔙 Back", callback_data=f"sessions_{sale_id}")]]))

async def kill_session(query, sale_id, h):
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or not sd.get("session_string") or sd.get("session_dead"):
        return await ack(query, "🚫 Session not available / already terminated.", show_alert=True)
    await ack(query, "⏳ Terminating...")
    temp = None
    was_current = False
    try:
        cred = next_api_cred()
        temp = Client(f"kill_{random.randint(1000, 9999)}",
                      api_id=cred["api_id"], api_hash=cred["api_hash"],
                      session_string=sd["session_string"], in_memory=True)
        await temp.connect()
        res = await temp.invoke(raw_funcs.account.GetAuthorizations())
        target = next((a for a in res.authorizations if a.hash == h), None)
        if target is None:
            await temp.disconnect()
            return await query.message.reply_text("❌ That session no longer exists.",
                                                  reply_markup=InlineKeyboardMarkup([
                                                      [InlineKeyboardButton("🔄 Refresh",
                                                                            callback_data=f"sessions_{sale_id}")]]))
        was_current = bool(target.current)
        await temp.invoke(raw_funcs.account.ResetAuthorization(hash=h))
        try:
            await temp.disconnect()
        except Exception:
            pass
        if was_current:
            sd["session_dead"] = True
            await save_db()
            await query.message.reply_text(
                f"✅ Bot session terminated for <code>{sale_id}</code>.\n"
                f"🚫 <b>OTP delivery is now disabled for this order</b> — "
                f"new OTPs can no longer be fetched.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📦 My IDs", callback_data="myids"),
                     InlineKeyboardButton("🏠 Home", callback_data="home")]]))
        else:
            await query.message.reply_text(
                f"✅ Session terminated for <code>{sale_id}</code>.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Refresh Sessions", callback_data=f"sessions_{sale_id}"),
                     InlineKeyboardButton("🔙 Back", callback_data="myids")]]))
    except Exception as e:
        await query.message.reply_text(f"❌ Terminate failed: <code>{esc(e)}</code>")

async def kill_other_sessions(query, sale_id):
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd or not sd.get("session_string"):
        return await ack(query, "❌ Session not available.", show_alert=True)
    await ack(query, "⏳ Terminating...")
    temp = None
    try:
        cred = next_api_cred()
        temp = Client(f"kill_{random.randint(1000, 9999)}",
                      api_id=cred["api_id"], api_hash=cred["api_hash"],
                      session_string=sd["session_string"], in_memory=True)
        await temp.connect()
        res = await temp.invoke(raw_funcs.account.GetAuthorizations())
        killed = 0
        for a in res.authorizations:
            if not a.current:
                try:
                    await temp.invoke(raw_funcs.account.ResetAuthorization(hash=a.hash))
                    killed += 1
                except Exception:
                    pass
        await temp.disconnect()
        await query.message.reply_text(f"✅ Terminated {killed} old session(s) for <code>{sale_id}</code>.")
    except Exception as e:
        await query.message.reply_text(f"❌ Failed: <code>{esc(e)}</code>")

async def send_my_ids(msg_or_query):
    uid = msg_or_query.from_user.id
    mine = [s for s in db.get("sales", []) if s["uid"] == uid]
    if not mine:
        text = (f"{E('box')} <b>My Purchased IDs</b>\n\n"
                f"You haven't purchased anything yet.\n"
                f"{E('cart')} Buy your first item from Products!")
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Products", callback_data="home_products"),
                                        InlineKeyboardButton("🏠 Home", callback_data="home")]])
        return await _edit_or_reply(msg_or_query, text, markup)
    text = f"{E('box')} <b>My Purchased IDs</b> ({len(mine)})\n━━━━━━━━━━━━━━━━━━\n"
    btns = []
    for s in mine[-10:]:
        sd0 = db.get("sold_sessions", {}).get(s["sale_id"], {})
        frozen = "  ❄️ <b>FROZEN</b>" if (sd0.get("dead") or sd0.get("session_dead")) else ""
        api_tag = f" {E('api')}" if s.get("api") else ""
        srv = get_server_by_name(s.get("server"))
        text += (f"🆔 <code>{s['sale_id']}</code> | {cflag(srv, s['country'])} "
                 f"{esc(s['country'])}{api_tag}{frozen}\n"
                 f"📞 <code>{esc(s['number'])}</code> | ₹{s['price']} | {esc(s['time'][:10])}\n\n")
        btns.append([InlineKeyboardButton(f"🔢 OTP {s['sale_id'][-4:]}",
                                          callback_data=f"newotp_{s['sale_id']}")])
    btns.append([InlineKeyboardButton("👤 Profile", callback_data="home_profile"),
                 InlineKeyboardButton("🏠 Home", callback_data="home")])
    await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(btns))

async def show_my_ids(query, uid):
    mine = [s for s in db.get("sales", []) if s["uid"] == uid]
    if not mine:
        return await ack(query, "❌ You haven't purchased any ID yet.", show_alert=True)
    await ack(query)
    text = f"{E('box')} <b>My Purchased IDs</b> ({len(mine)})\n━━━━━━━━━━━━━━━━━━\n"
    btns = []
    for s in mine[-10:]:
        sd0 = db.get("sold_sessions", {}).get(s["sale_id"], {})
        frozen = "  ❄️ <b>FROZEN</b>" if (sd0.get("dead") or sd0.get("session_dead")) else ""
        api_tag = f" {E('api')}" if s.get("api") else ""
        srv = get_server_by_name(s.get("server"))
        text += (f"🆔 <code>{s['sale_id']}</code> | {cflag(srv, s['country'])} "
                 f"{esc(s['country'])}{api_tag}{frozen}\n"
                 f"📞 <code>{esc(s['number'])}</code> | ₹{s['price']} | {esc(s['time'][:10])}\n\n")
        btns.append([InlineKeyboardButton(f"🔢 OTP {s['sale_id'][-4:]}",
                                          callback_data=f"newotp_{s['sale_id']}")])
    if len(mine) > 10:
        text = (f"📦 <b>My Purchased IDs</b> (last 10 of {len(mine)})\n━━━━━━━━━━━━━━━━━━\n"
                + text.split("━━\n", 1)[1])
    btns.append([InlineKeyboardButton("👤 Profile", callback_data="home_profile"),
                 InlineKeyboardButton("🏠 Home", callback_data="home")])
    try:
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(btns))
    except Exception:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(btns))

def get_server_by_name(name):
    """Sale record me server name hota hai — usse server object dhoondho."""
    if not name:
        return None
    for c in server_codes():
        srv = get_server(c)
        if srv.get("name") == name:
            return srv
    return None
