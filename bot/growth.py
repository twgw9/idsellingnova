"""Growth features: coupons, referrals, safety limits, stats, branding, customisation."""

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

# ================= COUPONS =================

@app.on_message(filters.private & filters.regex(
    r"(?i)^/addcoupon\s+(\S+)\s+(\d+(?:\.\d+)?)\s*(%?)\s*(\d+)?\s*(\d+)?\s*$"))
@admin_only
async def cmd_addcoupon(client, message):
    code = message.matches[0].group(1).upper()
    val = float(message.matches[0].group(2))
    is_pct = (message.matches[0].group(3) or "") == "%"
    uses = int(message.matches[0].group(4) or 0)
    min_dep = int(message.matches[0].group(5) or 0)
    db.setdefault("coupons", {})
    db["coupons"][code] = {"type": "pct" if is_pct else "flat", "value": val,
                           "uses": uses, "used": 0, "min_dep": min_dep}
    await save_db()
    bonus = f"{val:.0f}%" if is_pct else f"₹{val:.0f}"
    await message.reply_text(
        f"{E('gift')} <b>COUPON CREATED</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🎟️ Code: <code>{esc(code)}</code>\n"
        f"💝 Bonus: <b>{bonus}</b> extra balance on deposit\n"
        f"🔢 Uses: {'unlimited' if uses == 0 else uses}\n"
        f"💵 Min deposit: ₹{min_dep if min_dep else db['min_deposit']}\n\n"
        f"User deposit karte waqt <code>/start</code> → 💳 Deposit → 🎟️ Apply Coupon se lagayega.")


@app.on_message(filters.private & filters.regex(r"(?i)^/delcoupon\s+(\S+)"))
@admin_only
async def cmd_delcoupon(client, message):
    code = message.matches[0].group(1).upper()
    if db.get("coupons", {}).pop(code, None) is None:
        return await message.reply_text(f"{E('cross')} Coupon <code>{esc(code)}</code> not found.")
    await save_db()
    await message.reply_text(f"{E('check')} Coupon <code>{esc(code)}</code> deleted.")


@app.on_message(filters.private & filters.regex(r"(?i)^/coupons\b"))
@admin_only
async def cmd_coupons(client, message):
    cs = db.get("coupons") or {}
    if not cs:
        return await message.reply_text(
            f"{E('gift')} <b>NO COUPONS</b>\n\nBanao: "
            f"<code>/addcoupon WELCOME 10% 100 200</code>\n"
            f"(code, bonus, max uses, min deposit)")
    txt = f"{E('gift')} <b>COUPONS</b>\n━━━━━━━━━━━━━━━━━━\n"
    for code, c in cs.items():
        bonus = f"{c['value']:.0f}%" if c.get("type") == "pct" else f"₹{c['value']:.0f}"
        txt += (f"• <code>{esc(code)}</code> → <b>+{bonus}</b>  "
                f"[{c.get('used', 0)}/{c.get('uses', 0) or '∞'} used]"
                f"{f"  min ₹{c['min_dep']}" if c.get('min_dep') else ''}\n")
    await message.reply_text(txt)


# ================= REFERRALS =================

@app.on_message(filters.private & filters.regex(r"(?i)^/ref\b"))
async def cmd_ref(client, message):
    """Public: apna referral link + kamayi."""
    uid = message.from_user.id
    rec = user_record(uid, message.from_user.first_name)
    uname = db.get("bot_username") or ""
    link = f"https://t.me/{uname}?start=ref_{uid}" if uname else f"ref_{uid}"
    boost = float(db.get("ref_bonus", 0) or 0)
    await message.reply_text(
        f"{E('gift')} <b>INVITE &amp; EARN</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🔗 Your personal link:\n<code>{esc(link)}</code>\n\n"
        f"👥 Friends joined: <b>{len(rec.get('refs', []))}</b>\n"
        f"💰 Bonus earned: <b>₹{rec.get('ref_earned', 0)}</b>\n\n"
        f"🎁 Har friend ke <b>pehle deposit</b> par aapko <b>{boost:.0f}%</b> bonus milega.\n"
        f"💳 Wallet: ₹{rec.get('balance', 0)}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setrefbonus\s+(\d+(?:\.\d+)?)"))
@admin_only
async def cmd_setrefbonus(client, message):
    val = float(message.matches[0].group(1))
    db["ref_bonus"] = val
    await save_db()
    await message.reply_text(
        f"{E('check')} Referral bonus: <b>{val:.0f}%</b> of the referred user's first deposit.")


# ================= ORDERS / SAFETY =================

@app.on_message(filters.private & filters.regex(r"(?i)^/setsalepost\s+(on|off)"))
@admin_only
async def cmd_setsalepost(client, message):
    on = message.matches[0].group(1).lower() == "on"
    db["sale_post"] = on
    await save_db()
    ch = announce_target()
    await message.reply_text(
        f"{E('check')} Sale updates <b>{'ON' if on else 'OFF'}</b>.\n"
        + (f"Har sale par channel me SOLD post jayega: <code>{esc(ch)}</code>"
           if on and ch else "⚠️ Koi channel set nahi — /setannounce ya /setproofchannel karo."
           if on else ""))


@app.on_message(filters.private & filters.regex(r"(?i)^/setautorefund\s+(on|off)"))
@admin_only
async def cmd_setautorefund(client, message):
    on = message.matches[0].group(1).lower() == "on"
    db["auto_refund"] = on
    await save_db()
    await message.reply_text(
        f"{E('check')} Auto-refund <b>{'ON' if on else 'OFF'}</b> — "
        + ("OTP nahi mila to order cancel hokar paisa buyer ko wapas milega."
           if on else "Timeout par admin manually handle karega (/refund)."))


@app.on_message(filters.private & filters.regex(r"(?i)^/setmaxbuy\s+(\d+)"))
@admin_only
async def cmd_setmaxbuy(client, message):
    val = int(message.matches[0].group(1))
    db["max_buy_day"] = val
    await save_db()
    await message.reply_text(
        f"{E('check')} Daily purchase limit: "
        + (f"<b>{val}</b> item(s) per user per day." if val > 0 else "<b>unlimited</b>."))


@app.on_message(filters.private & filters.regex(r"(?i)^/ban\s+(\d+)"))
@admin_only
async def cmd_ban(client, message):
    uid = int(message.matches[0].group(1))
    db.setdefault("banned", [])
    if uid not in db["banned"]:
        db["banned"].append(uid)
        await save_db()
    try:
        await app.send_message(uid, "🚫 Purchases are disabled for your account. Contact support.")
    except Exception:
        pass
    await message.reply_text(f"{E('check')} Banned <code>{uid}</code> from purchasing.")


@app.on_message(filters.private & filters.regex(r"(?i)^/unban\s+(\d+)"))
@admin_only
async def cmd_unban(client, message):
    uid = int(message.matches[0].group(1))
    db["banned"] = [x for x in db.get("banned", []) if x != uid]
    await save_db()
    await message.reply_text(f"{E('check')} <code>{uid}</code> unbanned.")


@app.on_message(filters.private & filters.regex(r"(?i)^/banned\b"))
@admin_only
async def cmd_banned(client, message):
    lst = db.get("banned") or []
    await message.reply_text(
        f"🚫 <b>BANNED USERS ({len(lst)})</b>\n━━━━━━━━━━━━━━━━━━\n"
        + ("\n".join(f"   <code>{u}</code>" for u in lst) or "   — none —")
        + "\n\nBan: <code>/ban &lt;id&gt;</code> • Unban: <code>/unban &lt;id&gt;</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/restock\b"))
@admin_only
async def cmd_restock(client, message):
    nz = db.get("notify") or {}
    lines = ""
    for key, uids in nz.items():
        code, nm = key.split(":", 1)
        srv = get_server(code)
        lines += (f"   {cflag(srv, nm) if srv else ''} {esc(nm)} ({code}) — "
                  f"<b>{len(uids)}</b> waiting\n")
    await message.reply_text(
        f"{E('clock')} <b>RESTOCK WATCHLIST</b>\n━━━━━━━━━━━━━━━━━━\n"
        + (lines or "   — koi subscriber nahi —")
        + "\n\nJab ye countries wapas stock me aayengi, subscribers ko auto DM jayega.")


# ================= STATS =================

@app.on_message(filters.private & filters.regex(r"(?i)^/stats\b"))
@admin_only
async def cmd_stats(client, message):
    import datetime as _dt
    today = _dt.date.today()
    days, counts, revs = [], {}, {}
    for i in range(6, -1, -1):
        d = (today - _dt.timedelta(days=i)).strftime("%Y-%m-%d")
        days.append(d)
        counts[d] = 0
        revs[d] = 0
    for x in db.get("sales", []):
        d = str(x.get("time", ""))[:10]
        if d in counts:
            counts[d] += 1
            revs[d] += int(x.get("price", 0) or 0)
    chart = ""
    mx = max(counts.values()) or 1
    for d in days:
        bar = "█" * max(1, int(counts[d] / mx * 12)) if counts[d] else "░"
        chart += f"   {d[5:]} {bar} {counts[d]} • ₹{revs[d]}\n"
    top = {}
    for x in db.get("sales", []):
        top[x.get("item", "—")] = top.get(x.get("item", "—"), 0) + 1
    top_txt = "\n".join(f"   {esc(k)[:24]} — {v}" for k, v in
                         sorted(top.items(), key=lambda kv: -kv[1])[:5]) or "   —"
    new_today = sum(1 for u in db.get("users", {}).values() if str(u.get("joined", ""))[:5] == "")
    appr = [l for l in db.get("deposit_log", []) if l.get("status") == "approved"]
    appr_today = [l for l in appr if str(l.get("time", ""))[:10] == days[-1]]
    await message.reply_text(
        f"{E('chart')} <b>STORE STATS — last 7 days</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"{chart}\n"
        f"🛒 Total orders: <b>{sum(counts.values())}</b>\n"
        f"💰 Revenue: <b>₹{sum(revs.values())}</b>\n"
        f"💳 Deposits today: <b>{len(appr_today)}</b> (₹{sum(int(l['amount']) for l in appr_today)})\n"
        f"👥 Users: <b>{len(db.get('users', {}))}</b>\n\n"
        f"🏆 <b>Top items</b>\n{top_txt}")


# ================= BRANDING / WELCOME =================

@app.on_message(filters.private & filters.regex(r"(?i)^/setwelcome\s+(.+)"))
@admin_only
async def cmd_setwelcome(client, message):
    db["welcome_text"] = message.matches[0].group(1).strip()
    await save_db()
    await message.reply_text(
        f"{E('check')} Custom welcome saved.\n\n"
        f"<i>Placeholders: {{name}} {{balance}} {{bot}}</i>\n"
        f"Reset: <code>/clearwelcome</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/clearwelcome\b"))
@admin_only
async def cmd_clearwelcome(client, message):
    db["welcome_text"] = None
    await save_db()
    await message.reply_text(f"{E('check')} Welcome message reset to default.")


@app.on_message(filters.private & filters.regex(r"(?i)^/motd\s+(.+)"))
@admin_only
async def cmd_motd(client, message):
    db["motd"] = message.matches[0].group(1).strip()
    await save_db()
    await message.reply_text(f"📢 <b>MOTD set</b> — har /start par dikhega:\n{esc(db['motd'])}")


@app.on_message(filters.private & filters.regex(r"(?i)^/clearmotd\b"))
@admin_only
async def cmd_clearmotd(client, message):
    db["motd"] = None
    await save_db()
    await message.reply_text(f"{E('check')} MOTD cleared.")


# ================= CUSTOMISATION (v6.1) =================

@app.on_message(filters.private & filters.regex(r"(?i)^/setcurrency\s+(\S+)"))
@admin_only
async def cmd_setcurrency(client, message):
    val = (message.matches[0].group(1) or "₹").strip()[:3]
    db["currency"] = val
    await save_db()
    await message.reply_text(
        f"{E('check')} Currency set to <b>{esc(val)}</b>\n"
        f"Buyers will now see {esc(val)}30 instead of ₹30.\n"
        f"Wapas: <code>/setcurrency ₹</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/setfooter\s+(.+)"))
@admin_only
async def cmd_setfooter(client, message):
    db["footer"] = message.matches[0].group(1).strip()
    await save_db()
    await message.reply_text(
        f"{E('check')} <b>Delivery note set</b> — har delivery message ke end me:\n\n"
        f"{esc(db['footer'])}\n\nHataane ke liye: <code>/clearfooter</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/clearfooter\b"))
@admin_only
async def cmd_clearfooter(client, message):
    db["footer"] = None
    await save_db()
    await message.reply_text(f"{E('check')} Delivery note removed.")


@app.on_message(filters.private & filters.regex(r"(?i)^/setdesc\s+(\S+)\s+(\S+)\s+(.+)$"))
@admin_only
async def cmd_setdesc(client, message):
    """Har country ka apna description: /setdesc s1 BD Fresh numbers, instant OTP"""
    code = _srv_arg(message.matches[0].group(1))
    want = message.matches[0].group(2).strip()
    desc = message.matches[0].group(3).strip()
    srv = get_server(code)
    if not srv:
        return await message.reply_text(f"{E('cross')} Server <code>{esc(code)}</code> not found.")
    nm = next((x for x in country_list(srv) if x.lower() == want.lower()), None)
    if not nm:
        return await message.reply_text(
            f"{E('cross')} Country <code>{esc(want)}</code> not found.\n"
            f"Available: {', '.join(f'<code>{esc(x)}</code>' for x in country_list(srv)[:15])}")
    if desc.lower() == "off":
        srv["countries"][nm].pop("desc", None)
    else:
        srv["countries"][nm]["desc"] = desc
    await save_db()
    await message.reply_text(
        f"{E('check')} Description updated for {cflag(srv, nm)} <b>{esc(cname(srv, nm))}</b>:\n"
        f"{esc(desc) if desc.lower() != 'off' else '(removed)'}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setbulk\s*(off)?\s*(\d+)?\s*(\d+)?\s*$"))
@admin_only
async def cmd_setbulk(client, message):
    """Bulk/quantity discount: /setbulk 3 5  (3 pcs = 5% off)"""
    off = message.matches[0].group(1)
    qty = message.matches[0].group(2)
    pct = message.matches[0].group(3)
    if off:
        db["bulk"] = {}
        await save_db()
        return await message.reply_text(f"{E('check')} Bulk offers removed.")
    if qty and pct:
        db.setdefault("bulk", {})[str(int(qty))] = int(pct)
        await save_db()
        txt = f"{E('gift')} <b>BULK OFFERS</b>\n━━━━━━━━━━━━━━━━━━\n"
        for q, p in sorted(db["bulk"].items(), key=lambda kv: int(kv[0])):
            txt += f"• <b>{q}</b> accounts → <b>{p}%</b> off per account\n"
        txt += "\nBuyers will see these buttons on the confirm screen."
        return await message.reply_text(txt)
    bulk = db.get("bulk") or {}
    txt = f"{E('gift')} <b>BULK OFFERS</b>\n━━━━━━━━━━━━━━━━━━\n"
    txt += ("\n".join(f"• <b>{q}</b> accounts → <b>{p}%</b> off"
                       for q, p in sorted(bulk.items(), key=lambda kv: int(kv[0])))
            or "   — koi offer nahi —")
    txt += ("\n\nAdd: <code>/setbulk 3 5</code>  •  Remove all: <code>/setbulk off</code>")
    await message.reply_text(txt)


@app.on_message(filters.private & filters.regex(r"(?i)^/setotptimeout\s+(\d+)"))
@admin_only
async def cmd_setotptimeout(client, message):
    val = max(1, min(120, int(message.matches[0].group(1))))
    db["otp_timeout_min"] = val
    await save_db()
    await message.reply_text(
        f"{E('check')} OTP wait window: <b>{val} minutes</b>.\n"
        f"Iske baad order auto-refund ho jayega (/setautorefund on hone par).")


@app.on_message(filters.private & filters.regex(r"(?i)^/setstockview\s+(exact|range|hidden)"))
@admin_only
async def cmd_setstockview(client, message):
    val = message.matches[0].group(1).lower()
    db["stock_view"] = val
    await save_db()
    name = {"exact": "exact count (34)", "range": "range (10-49)",
            "hidden": "sirf 'in stock'"}[val]
    await message.reply_text(f"{E('check')} Stock display: <b>{name}</b>")
