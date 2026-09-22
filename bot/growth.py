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
    added_fsub = auto_fsub_add("", name=title, url=url)      # force-join me bhi auto
    await save_db()
    await message.reply_text(
        f"{E('check')} Channel added on Home screen: <b>{esc(title)}</b>\n"
        f"Total: {len(db['home_channels'])} • Hatane ke liye <code>/channels</code>\n"
        + (f"🔒 Force-join me bhi add ho gaya (har naye user ko join karna hoga)."
           if added_fsub else ""))


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


@app.on_message(filters.private & filters.regex(r"(?i)^/agedcat(?:\s+(\S+))?(?:\s+(.*))?\s*$"))
@admin_only
async def cmd_agedcat(client, message):
    """Aged pool ke category tiles: /agedcat list | preset | add 75 INDIA 2021 |
    price 2 120 | del 3 | clear | on | off"""
    what = (message.matches[0].group(1) or "list").strip().lower()
    rest = (message.matches[0].group(2) or "").strip()
    code = "s2" if "s2" in db.get("servers", {}) else next(
        (c for c, s in db.get("servers", {}).items() if int(s.get("tg_server") or 0) >= 2), "s2")
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text("❌ Aged server nahi mila.")
    srv.setdefault("aged_cats", [])
    if what in ("list", ""):
        if not srv["aged_cats"]:
            return await message.reply_text(
                f"🕰 <b>Aged category tiles</b> — abhi koi nahi hai.\n\n"
                f"<code>/agedcat preset</code> — supplier ke asli aged list se bhar do\n"
                f"<code>/agedcat add 75 INDIA 2021</code> — khud se ek tile add karo")
        lines = "\n".join(
            f"{i}. {esc(c.get('label'))} — <b>₹{c.get('price') or 'auto'}</b> "
            f"{'✅' if c.get('on', True) else '⏸'}"
            for i, c in enumerate(srv["aged_cats"], 1))
        return await message.reply_text(
            f"🕰 <b>Aged category tiles</b> ({esc(srv.get('name', code))})\n{lines}\n\n"
            f"<i>Sab ek hi real aged pool se kharidte hain — stock shared hai.</i>\n"
            f"<code>/agedcat add 75 INDIA 2021</code> • <code>/agedcat del 3</code> • "
            f"<code>/agedcat clear</code>")
    if what == "preset":
        srv["aged_cats"] = [{"label": lb, "cost": usd, "price": 0, "on": True}
                            for lb, usd in AGED_CAT_PRESETS]
        srv["aged_cats_on"] = True
    elif what == "add":
        parts = rest.split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            return await message.reply_text("❌ Format: <code>/agedcat add 75 INDIA 2021</code>")
        srv["aged_cats"].append({"label": parts[1].strip(), "price": int(parts[0]), "on": True})
        srv["aged_cats_on"] = True
    elif what == "price":
        parts = rest.split()
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            return await message.reply_text("❌ Format: <code>/agedcat price 2 120</code>")
        n, val = int(parts[0]) - 1, int(parts[1])
        if not (0 <= n < len(srv["aged_cats"])):
            return await message.reply_text("❌ Galat number — <code>/agedcat list</code> dekho.")
        srv["aged_cats"][n]["price"] = val
    elif what == "del":
        if not rest.isdigit() or not (1 <= int(rest) <= len(srv["aged_cats"])):
            return await message.reply_text("❌ Format: <code>/agedcat del 3</code>")
        srv["aged_cats"].pop(int(rest) - 1)
    elif what == "flat":                     # sabhi tiles ek hi price
        if not rest.isdigit():
            return await message.reply_text("❌ Format: <code>/agedcat flat 70</code>")
        for c in srv["aged_cats"]:
            c["price"] = int(rest)
        srv["aged_cats_on"] = True
    elif what == "step":                     # har agla tile itna ₹ mehnga
        if not rest.isdigit():
            return await message.reply_text("❌ Format: <code>/agedcat step 10</code>")
        base = tg_sell_price(0.0, price_key(code, "CAT:0")) if False else 0
        for i, c in enumerate(srv["aged_cats"]):
            c["price"] = 0                   # sync me pool price + step lagega
        srv["aged_cats_step"] = int(rest)
        srv["aged_cats_on"] = True
    elif what == "clear":
        srv["aged_cats"] = []
    elif what in ("on", "off"):
        srv["aged_cats_on"] = (what == "on")
    else:
        return await message.reply_text("❌ <code>/agedcat list | preset | add | price | del | "
                                        "clear | on | off</code>")
    await save_db()
    n, msg = await tg_sync_stock(code)          # tiles turant ban jayein
    tiles = len([k for k in srv["countries"] if str(k).startswith("CAT:")])
    await message.reply_text(
        f"{E('check')} <b>Aged categories updated</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕰 Tiles on server: <b>{tiles}</b>\n"
        f"📦 {msg}")


@app.on_message(filters.private & filters.regex(r"(?i)^/setminprofit\s+(\d+(?:\.\d+)?)\s*$"))
@admin_only
async def cmd_setminprofit(client, message):
    """Har sale me kam se kam itna ₹ profit pakka: /setminprofit 5"""
    val = float(message.matches[0].group(1))
    db.setdefault("tgshark", {})["min_profit"] = val
    await save_db()
    await recalc_all_prices(reason="min_profit")
    await message.reply_text(
        f"{E('check')} <b>Minimum profit</b> = <b>₹{val:g}</b> har sale par\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Ab koi bhi number (asli cost + ₹{val:g}) se kam par nahi bikega.\n"
        f"Saare prices dobara calculate ho gaye.")


@app.on_message(filters.private & filters.regex(r"(?i)^/lossguard\s*(on|off)?\s*$"))
@admin_only
async def cmd_lossguard(client, message):
    """Loss guard on/off: kharcha zyada ho to stock freeze + alert  |  /lossguard on"""
    arg = (message.matches[0].group(1) or "").strip().lower()
    if arg in ("on", "off"):
        db.setdefault("tgshark", {})["loss_guard"] = (arg == "on")
        await save_db()
    on = loss_guard_on()
    await message.reply_text(
        f"{E('shield')} <b>Loss guard</b>: {'<b>ON</b> ✅' if on else '<b>OFF</b> ⚠️'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Sale se pehle: price < cost → sale block\n"
        f"• Sale ke baad: asli kharcha zyada → us country ka stock freeze + alert\n"
        f"• Min profit floor: ₹{min_profit_inr():g} per sale\n\n"
        f"<code>/lossguard on|off</code> • <code>/setminprofit 5</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/serveroff\s+(\w+)\s*$"))
@admin_only
async def cmd_serveroff(client, message):
    """/serveroff s2 — server buyers se chhup jayega + sync band (baad me /serveron s2)"""
    code = message.matches[0].group(1).lower()
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{esc(code)}</code> nahi mila.")
    srv["off"], srv["sync"] = True, False
    await save_db()
    await message.reply_text(
        f"{E('check')} <b>{esc(srv.get('name', code))}</b> ab <b>BAND</b> hai.\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• Buyers ko nahi dikhega\n• Stock sync band\n\n"
        f"Wapas chalana ho to: <code>/serveron {esc(code)}</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/serveron\s+(\w+)\s*$"))
@admin_only
async def cmd_serveron(client, message):
    """/serveron s2 — server wapas chalu (buyers ko dikhega + sync)"""
    code = message.matches[0].group(1).lower()
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{esc(code)}</code> nahi mila.")
    srv["off"] = False
    if srv.get("source") == "tgshark":
        srv["sync"] = True
    await save_db()
    n, msg = (await tg_sync_stock(code)) if srv.get("sync") else (0, "manual server")
    await message.reply_text(
        f"{E('check')} <b>{esc(srv.get('name', code))}</b> wapas <b>CHALU</b> ho gaya.\n"
        f"━━━━━━━━━━━━━━━━━━\n{msg}")


@app.on_message(filters.private & filters.regex(r"(?i)^/servers\s*$"))
@admin_only
async def cmd_servers(client, message):
    """/servers — sab servers ki status (chalu / band)"""
    if not server_codes():
        return await message.reply_text("❌ Koi server nahi hai.")
    lines = []
    for c in server_codes():
        s = db["servers"][c]
        state = "🔴 BAND" if server_is_off(s) else "🟢 CHALU"
        kind = "API" if srv_is_api(s) else "manual"
        lines.append(f"• <code>{esc(c)}</code> — {esc(s.get('name', c))} "
                     f"({len(s.get('countries', {}))} countries, {kind}) — <b>{state}</b>")
    await message.reply_text(
        f"{E('box')} <b>Servers</b>\n━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) +
        f"\n\n<code>/serveroff s2</code> • <code>/serveron s2</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/hidemix\s+(\w+)\s*(on|off)?\s*$"))
@admin_only
async def cmd_hidemix(client, message):
    """/hidemix s1 on — random pool (Global Mix / XX) us server me chhup jayega"""
    code = message.matches[0].group(1).lower()
    arg = (message.matches[0].group(2) or "").strip().lower()
    srv = db["servers"].get(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{esc(code)}</code> nahi mila.")
    if arg in ("on", "off"):
        srv["hide_mix"] = (arg == "on")
        await save_db()
    hidden = bool(srv.get("hide_mix"))
    await message.reply_text(
        f"{E('check')} <b>{esc(srv.get('name', code))}</b> me random pool "
        f"{'<b>CHHUPA DIYA</b> 🎲🚫' if hidden else '<b>DIKH RAHA HAI</b> 🎲'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Buyers ko ab {len(buyer_country_list(srv))} countries dikhenge "
        f"(kul {len(country_list(srv))}).\n\n"
        f"<code>/hidemix {esc(code)} on|off</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/precheck\s*(on|off)?\s*$"))
@admin_only
async def cmd_precheck(client, message):
    """/precheck on|off — kharidne se pehle API se bhav dobara check (nuksan se bachav)"""
    arg = (message.matches[0].group(1) or "").strip().lower()
    if arg in ("on", "off"):
        db.setdefault("tgshark", {})["precheck"] = (arg == "on")
        await save_db()
    await message.reply_text(
        f"{E('shield')} <b>Pre-buy cost check</b>: "
        f"{'<b>ON</b> ✅' if precheck_on() else '<b>OFF</b> ⚠️'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Har kharidari se pehle API se bhav dobara check hota hai — agar bhav "
        f"badh gaya hai to sale rok kar price refresh kar dete hain, taaki aapko "
        f"kabhi nuksan na ho.\n\n<code>/precheck on|off</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/autofsub\s*(on|off)?\s*$"))
@admin_only
async def cmd_autofsub(client, message):
    """/autofsub on|off — naya channel/GC add hote hi force-join me bhi daal do"""
    arg = (message.matches[0].group(1) or "").strip().lower()
    if arg in ("on", "off"):
        db["auto_fsub"] = (arg == "on")
        await save_db()
    on = db.get("auto_fsub", True)
    await message.reply_text(
        f"{E('check')} <b>Auto force-join</b>: {'<b>ON</b> ✅' if on else '<b>OFF</b>'}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"ON = jab bhi aap naya channel/group add karein (/addchannel, /setloggroup, "
        f"/setannounce), wo apne aap force-join list me bhi aa jayega.\n\n"
        f"<code>/autofsub on|off</code> • <code>/fsubmode lenient|strict</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/fsubmode\s*(lenient|strict)?\s*$"))
@admin_only
async def cmd_fsubmode(client, message):
    """/fsubmode lenient|strict — pending join request wale ko bhi andar aane dein?"""
    arg = (message.matches[0].group(1) or "").strip().lower()
    if arg in ("lenient", "strict"):
        db["fsub_mode"] = arg
        db.pop("fsub_ok", None)           # sabko dobara verify karana hoga
        await save_db()
    mode = "lenient" if fsub_lenient() else "strict"
    await message.reply_text(
        f"{E('shield')} <b>Force-join mode</b>: <b>{mode.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        + ("<b>LENIENT</b> — join request pending hai to bhi Verify ke baad user andar "
           "aa jayega (recommended).\n" if mode == "lenient" else
           "<b>STRICT</b> — sirf pakka member ko andar milega (bot ko channel ka admin "
           "hona chahiye warna sab block honge).\n")
        + "\n<code>/fsubmode lenient|strict</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/lossreport\s*$"))
@admin_only
async def cmd_lossreport(client, message):
    """/lossreport — kitna profit, kitna nuksan, kaun si cheez khatre me hai"""
    sales = db.get("sales", [])
    revenue = sum(int(s.get("price", 0) or 0) for s in sales)
    cost = 0.0
    for s in sales:
        sd = (db.get("sold_sessions") or {}).get(s.get("sale_id")) or {}
        cost += float(sd.get("cost_usd") or 0) * float(tg_cfg()["usd_inr"] or 0)
    losses = [d for d in db.get("deposit_log", []) if "banned" in str(d.get("status", ""))]
    guard = "ON ✅" if loss_guard_on() else "OFF ⚠️"
    pre = "ON ✅" if precheck_on() else "OFF ⚠️"
    refund = "ON ⚠️ (supplier ka paisa gaya + buyer ko refund = NUKSAN)" \
        if db.get("auto_refund", True) else "OFF ✅"
    await message.reply_text(
        f"{E('chart')} <b>PROFIT / LOSS REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Revenue: <b>₹{revenue}</b>\n"
        f"💸 Supplier cost: <b>₹{cost:.0f}</b>\n"
        f"📈 Profit: <b>₹{revenue - cost:.0f}</b>\n"
        f"🧾 Sales: <b>{len(sales)}</b>\n\n"
        f"{E('shield')} <b>Safety</b>\n"
        f"• Loss guard: {guard} (kharcha zyada → stock freeze + alert)\n"
        f"• Pre-buy cost check: {pre} (bhav badha → sale block)\n"
        f"• Min profit floor: ₹{min_profit_inr():g} per sale\n"
        f"• Auto-refund (OTP timeout): {refund}\n"
        f"• 1$ = ₹{tg_cfg()['usd_inr']:g}\n\n"
        f"<code>/setminprofit 5</code> • <code>/lossguard on</code> • "
        f"<code>/precheck on</code> • <code>/setautorefund off</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/credit\s+(\d+)\s+(\d+)\s*$"))
@admin_only
async def cmd_credit(client, message):
    """/credit <user id> <amount> — user ko manually balance do (bina deposit ke)"""
    uid = int(message.matches[0].group(1))
    amt = int(message.matches[0].group(2))
    if amt <= 0 or amt > 100000:
        return await message.reply_text("❌ Amount 1 se 100000 ke beech ho.")
    async with db_lock:
        rec = user_record(uid)
        rec["balance"] = int(rec.get("balance", 0)) + amt
        rec["deposited"] = int(rec.get("deposited", 0)) + amt
        bal = rec["balance"]
        await save_db()
    try:
        await app.send_message(
            uid, f"💰 <b>₹{amt} credited</b> by admin.\nNew balance: <b>₹{bal}</b>")
    except Exception:
        pass
    await log_event(f"💰 <b>Manual credit</b> ₹{amt} → <code>{uid}</code> "
                    f"by {esc(message.from_user.first_name or 'admin')}")
    await message.reply_text(f"{E('check')} ₹{amt} credited to <code>{uid}</code> • "
                             f"balance ₹{bal}")


@app.on_message(filters.private & filters.regex(r"(?i)^/apiprobe\s*$"))
@admin_only
async def cmd_apiprobe(client, message):
    """/apiprobe — API call kyun fail ho rahi hai, asli wajah batao (read-only)"""
    await message.reply_text("🔍 Probing the supplier API (3 read-only calls)...")
    rows, errs = [], []
    for act in ("getBalance", "getInfo", "getCountrys"):
        t0 = time.time()
        res = await tg_api(act)
        ms = int((time.time() - t0) * 1000)
        ok = res.get("status") == "ok"
        if ok:
            rows.append(f"🟢 <code>{act}</code> — ok ({ms} ms)")
        else:
            errs.append(str(res.get("message") or "unknown"))
            rows.append(f"🔴 <code>{act}</code> — {esc(str(res.get('message'))[:70])} ({ms} ms)")
    hint = ""
    joined = " ".join(errs).lower()
    if not errs:
        hint = "✅ Sab theek hai — API connect ho raha hai."
    elif "apikey" in joined or "401" in joined or "unauthor" in joined:
        hint = ("🔑 <b>Key galat/expired</b> — .env me TGSHARK_API_KEY check karo "
                "ya <code>/setapikey &lt;nayi key&gt;</code>.")
    elif "certificate" in joined or "ssl" in joined:
        hint = ("🔒 <b>SSL error</b> — .env me <code>TGSHARK_VERIFY_SSL=false</code> "
                "daal kar restart karo.")
    elif "timed out" in joined or "timeout" in joined:
        hint = ("⏱ <b>Timeout</b> — .env me <code>TGSHARK_HTTP_TIMEOUT=40</code> aur "
                "<code>TGSHARK_HTTP_RETRIES=4</code> karke restart karo.")
    elif "name or service not known" in joined or "dns" in joined or "resolve" in joined:
        hint = "🌐 <b>DNS/Network block</b> — hosting se outbound HTTPS allow karwao."
    else:
        hint = ("❓ Upar wala error supplier ki taraf se hai — thodi der baad "
                "<code>/apiprobe</code> dobara chalao (502 kabhi-kabhi aata hai).")
    await message.reply_text(
        f"{E('api')} <b>API PROBE</b>\n━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(rows) + f"\n\n{hint}")


@app.on_message(filters.private & filters.regex(r"(?i)^/report\s*$"))
@admin_only
async def cmd_report(client, message):
    """/report — kitna sell hua, kitna profit, stock, deposits (poora report)"""
    sales = list(db.get("sales", []))
    rate = float(tg_cfg()["usd_inr"] or 0)
    revenue = sum(int(s.get("price", 0) or 0) for s in sales)
    cost = 0.0
    for s in sales:
        sd = (db.get("sold_sessions") or {}).get(s.get("sale_id")) or {}
        c = float(sd.get("cost_usd") or 0)
        if not c and s.get("api"):
            c_key = str(s.get("code") or "")
        cost += c * rate
    profit = revenue - cost
    today = now_str()[:10]
    t_sales = [s for s in sales if str(s.get("time", ""))[:10] == today]
    t_rev = sum(int(s.get("price", 0) or 0) for s in t_sales)
    top = {}
    for s in sales:
        k = str(s.get("country") or s.get("label") or "—")
        top[k] = top.get(k, 0) + 1
    top_rows = "".join(
        f"   {esc(k)} — <b>{v}</b> sold\n"
        for k, v in sorted(top.items(), key=lambda kv: -kv[1])[:5]) or "   (abhi koi sale nahi)\n"
    users = len(db.get("users", {}))
    pend = len(db.get("pending_deposits", {}))
    stock = 0
    for c in server_codes():
        srv = get_server(c)
        if srv and not server_is_off(srv):
            stock += sum(stock_count(x) for x in srv["countries"].values())
    bal = db["tgshark"].get("last_balance", 0)
    await message.reply_text(
        f"{E('chart')} <b>STORE REPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Aaj</b> — {len(t_sales)} sales • ₹{t_rev}\n"
        f"🧾 <b>Kul</b> — {len(sales)} sales\n"
        f"💰 Revenue: <b>₹{revenue}</b>\n"
        f"💸 Cost: <b>₹{cost:.0f}</b>\n"
        f"📈 Profit: <b>₹{profit:.0f}</b>"
        + (f"  ({profit / revenue * 100:.0f}% margin)" if revenue else "") + "\n\n"
        f"<b>🔥 Top items</b>\n{top_rows}\n"
        f"👥 Users: <b>{users}</b>\n"
        f"📦 Live stock: <b>{stock}</b> numbers\n"
        f"⏳ Pending deposits: <b>{pend}</b>\n"
        f"💳 Supplier balance: <b>${bal}</b>\n"
        f"💱 1$ = ₹{rate:g}\n\n"
        f"<code>/lossreport</code> safety flags • <code>/apiprobe</code> API check")


@app.on_message(filters.private & filters.regex(r"(?i)^/lossreport\s*$"))
@admin_only
async def _lossreport_alias(client, message):
    message.matches = [re.match(r"(?i)^/lossreport\s*$", "/lossreport")]
    await cmd_lossreport(client, message)
