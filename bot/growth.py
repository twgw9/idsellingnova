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


@app.on_message(filters.private & filters.regex(r"(?i)^/setserverkey\s+(\w+)\s+(\S+)\s*$"))
@admin_only
async def cmd_setserverkey(client, message):
    """Har server (new/old account) ki alag supplier key set karo."""
    code = message.matches[0].group(1).lower()
    key = message.matches[0].group(2).strip()
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(
            f"❌ Server <code>{esc(code)}</code> nahi mila. Servers: "
            f"{esc(', '.join(server_codes()))}")
    srv["api_key"] = key
    await save_db()
    res = await tg_api("getBalance", key=key)
    if res.get("status") == "ok":
        return await message.reply_text(
            f"{E('check')} <b>{esc(srv.get('name', code))}</b> key saved &amp; working! "
            f"Balance: <b>${res.get('balance')}</b>")
    await message.reply_text(
        f"⚠️ Key saved for <b>{esc(srv.get('name', code))}</b> par API boli: "
        f"<code>{esc(res.get('message', 'unknown'))}</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/serverkeys\b"))
@admin_only
async def cmd_serverkeys(client, message):
    rows = []
    for c in server_codes():
        s = db["servers"][c]
        k = (s.get("api_key") or "").strip()
        rows.append(f"• <b>{esc(s.get('name', c))}</b> (<code>{c}</code>): "
                    f"{'✅ set (' + k[:12] + '…)' if k else '❌ key nahi'}"
                    f" • countries: {len(s.get('countries', {}))}")
    await message.reply_text(
        "🔑 <b>SERVER KEYS</b>\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(rows) +
        "\n\nSet karne ke liye: <code>/setserverkey s1 &lt;key&gt;</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/shutdown\s*$"))
@admin_only
async def cmd_shutdown(client, message):
    """Owner: bot ko remote band kar do (keepalive dobara start nahi karega)."""
    if message.from_user.id not in OWNER_IDS:
        return await message.reply_text("❌ Sirf bot owner hi shutdown kar sakta hai.")
    await message.reply_text(
        "🛑 <b>Shutdown</b> — bot band ho raha hai…\n"
        "<i>Dobara start karne ke liye server par <code>bash run.sh</code> chalayein.</i>")
    await log_event(f"🛑 <b>Bot shutdown</b> requested by <code>{message.from_user.id}</code>")
    try:                                   # keepalive script ko rokne ka nishan
        open(os.path.join(os.getcwd(), "bot.stopped"), "w").write(now_str())
    except Exception:
        pass
    if not request_shutdown():
        await message.reply_text("⚠️ Stop event register nahi hua — server se process kill karein.")


@app.on_message(filters.private & filters.regex(r"(?i)^/addchannel\s+(.+)", flags=re.S))
@admin_only
async def cmd_addchannel(client, message):
    """Home screen par channel button lagao: /addchannel Sales Updates | https://t.me/xxx"""
    raw = (message.matches[0].group(1) or "").strip()
    if "|" in raw:
        title, url = raw.split("|", 1)
    elif " " in raw:
        title, url = raw.split(None, 1)
    else:
        title, url = "Channel", raw
    title, url = title.strip(), url.strip()
    if not url.startswith("http"):
        return await message.reply_text(
            "❌ Format: <code>/addchannel Sales Updates | https://t.me/yourchannel</code>")
    db.setdefault("home_channels", []).append({"title": title, "url": url})
    await save_db()
    await message.reply_text(
        f"{E('check')} Channel added on Home screen: <b>{esc(title)}</b>\n"
        f"Total: {len(db['home_channels'])} • Hatane ke liye <code>/channels</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/delchannel\s+(\d+)\s*$"))
@admin_only
async def cmd_delchannel(client, message):
    idx = int(message.matches[0].group(1)) - 1
    lst = db.get("home_channels") or []
    if not (0 <= idx < len(lst)):
        return await message.reply_text("❌ Galat number. List dekhne ke liye <code>/channels</code>")
    gone = lst.pop(idx)
    await save_db()
    await message.reply_text(f"{E('check')} Removed: <b>{esc(gone.get('title', '?'))}</b>")


@app.on_message(filters.private & filters.regex(r"(?i)^/channels\b"))
@admin_only
async def cmd_channels(client, message):
    lst = db.get("home_channels") or []
    body = ("\n".join(f"  {i}. <b>{esc(c.get('title'))}</b> — {esc(c.get('url'))}"
                      for i, c in enumerate(lst, 1)) or "   — koi channel set nahi —")
    await message.reply_text(
        f"📢 <b>HOME CHANNELS ({len(lst)})</b>\n━━━━━━━━━━━━━━━━━━\n{body}\n\n"
        f"Add: <code>/addchannel Sales Updates | https://t.me/xxx</code>\n"
        f"Remove: <code>/delchannel 1</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/syncall\b"))
@admin_only
async def cmd_syncall(client, message):
    """Dono servers (Server 1 = new, Server 2 = old) ek saath sync."""
    msg = await message.reply_text(f"{E('sync')} Syncing all servers…")
    try:
        cnt, out = await tg_sync_all()
        await msg.edit_text(f"{E('check')} <b>SYNC DONE</b> ({cnt} rows)\n━━━━━━━━━━━━━━━━━━\n{out}")
    except Exception as e:
        await msg.edit_text(f"❌ Sync failed: <code>{esc(str(e))}</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/setserversync\s+(\w+)\s+(on|off)\s*$"))
@admin_only
async def cmd_setserversync(client, message):
    """Server ka auto stock-sync on/off (Aged server manual reh sakta hai)."""
    code = message.matches[0].group(1).lower()
    on = message.matches[0].group(2).lower() == "on"
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{esc(code)}</code> nahi mila.")
    srv["sync"] = on
    await save_db()
    await message.reply_text(
        f"{E('check')} <b>{esc(srv.get('name', code))}</b> auto-sync "
        f"{'ON' if on else 'OFF'} — "
        + ("ab stock API se refresh hoga." if on else
           "ab admin manually IDs add karega: <code>/addcountry " + code + " Name</code> phir "
           "<code>/addids " + code + "</code>"))


@app.on_message(filters.private & filters.regex(r"(?i)^/setservermargin\s+(\w+)\s+(\S+)\s*$"))
@admin_only
async def cmd_setservermargin(client, message):
    """Server ka extra margin: /setservermargin s2 30%  |  s2 +30  |  s2 off"""
    code = message.matches[0].group(1).lower()
    arg = (message.matches[0].group(2) or "").strip().lower()
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{esc(code)}</code> nahi mila.")
    if arg in ("off", "0", "none"):
        srv["uplift_pct"], srv["uplift_add"] = 0.0, 0.0
    elif arg.endswith("%"):
        srv["uplift_pct"], srv["uplift_add"] = float(arg[:-1] or 0), 0.0
    elif arg.startswith("+"):
        srv["uplift_pct"], srv["uplift_add"] = 0.0, float(arg[1:] or 0)
    else:
        srv["uplift_pct"], srv["uplift_add"] = float(arg or 0), 0.0
    await recalc_all_prices()
    pct, add = server_uplift(code)
    await message.reply_text(
        f"{E('check')} <b>{esc(srv.get('name', code))}</b> extra margin: "
        + (f"<b>+{pct:g}%</b>" if pct else (f"<b>+₹{add:g}</b>" if add else "<b>off</b>"))
        + f"\nAb <code>/syncall</code> karke naye rates dekho.")


@app.on_message(filters.private & filters.regex(r"(?i)^/setloggroup\s*(\S+)?\s*$"))
@admin_only
async def cmd_setloggroup(client, message):
    """Owner group/channel jahan sab updates jayein: /setloggroup @iddatabase10"""
    arg = (message.matches[0].group(1) or "").strip()
    if not arg:
        cur = (LOG_GROUP or db.get("log_group") or "— set nahi —")
        return await message.reply_text(
            f"📋 <b>Log group:</b> <code>{esc(str(cur))}</code>\n\n"
            f"Set: <code>/setloggroup @iddatabase10</code> ya <code>/setloggroup -100123456789</code>\n"
            f"Bot ko us group me <b>admin</b> hona chahiye.")
    db["log_group"] = arg
    await save_db()
    ok = await log_event("✅ <b>Log group set</b> — ab se naye user, sales, deposits aur "
                         "OTP delivery ki copy yahan aayegi.")
    await message.reply_text(
        (f"{E('check')} Log group set: <code>{esc(arg)}</code> — test message bhej diya ✅"
         if ok else
         f"⚠️ Save ho gaya par message nahi gaya — bot ko us group me admin banao "
         f"(<code>{esc(arg)}</code>) aur dobara <code>/setloggroup {esc(arg)}</code> chalao."))


@app.on_message(filters.private & filters.regex(r"(?i)^/settgserver\s+(\w+)\s+(\d+)\s*$"))
@admin_only
async def cmd_settgserver(client, message):
    """Kaunsa bot-server kis supplier inventory se jude: /settgserver s2 2 (aged)"""
    code = message.matches[0].group(1).lower()
    num = int(message.matches[0].group(2))
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{esc(code)}</code> nahi mila.")
    srv["tg_server"] = num
    srv.pop("tg_server_ok", None)
    await save_db()
    await message.reply_text(
        f"{E('check')} <b>{esc(srv.get('name', code))}</b> ab supplier inventory "
        f"<code>server={num}</code> se chalega.\nAb <code>/syncall</code> chala kar stock dekho.")


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
