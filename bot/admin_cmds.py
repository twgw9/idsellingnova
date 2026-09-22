"""Admin commands — servers, stock, payments, broadcast, reports, backup."""

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

# ================= ADMIN COMMANDS =================

def admin_only(fn):
    async def wrapper(client, message):
        uid = message.from_user.id
        if not is_admin(uid):
            return await message.reply_text("❌ Unknown command. Use /help to see what you can do.")
        if uid not in _admin_menu_ok:
            await _try_set_admin_commands(uid)
        return await fn(client, message)
    wrapper.__name__ = fn.__name__
    return wrapper

@app.on_message(filters.private & filters.regex(r"(?i)^/addserver\b"))
@admin_only
async def cmd_addserver(client, message):
    user_states[message.from_user.id] = {"state": "SRV_NAME"}
    await message.reply_text("🖥 <b>New Server [1/2]</b>\n\nSend the server <b>name</b> "
                             "(e.g. Main Server / Server 1):")

@app.on_message(filters.private & filters.regex(r"(?i)^/renameserver\s+(\S+)"))
@admin_only
async def cmd_renameserver(client, message):
    code = message.matches[0].group(1).lower()
    if not get_server(code):
        return await message.reply_text("❌ Server not found. Codes: " +
                                        ", ".join(f"<code>{c}</code>" for c in server_codes()))
    user_states[message.from_user.id] = {"state": f"SRV_RENAME_{code}"}
    await message.reply_text(f"✏️ Send the new name for server <code>{code}</code>:")

@app.on_message(filters.private & filters.regex(r"(?i)^/delserver\b"))
@admin_only
async def cmd_delserver(client, message):
    codes = server_codes()
    if not codes:
        return await message.reply_text("❌ No servers found.")
    btns = [[InlineKeyboardButton(f"🗑 {get_server(c)['name']} ({c})", callback_data=f"srvdel_{c}")]
            for c in codes]
    await message.reply_text("Select a server to delete:", reply_markup=InlineKeyboardMarkup(btns))

def _srv_arg(raw):
    raw = (raw or "").strip().lower().replace("server", "").strip()
    if not raw:
        return None
    if raw.isdigit():
        raw = f"s{raw}"
    if not (raw.startswith("s") and raw[1:].isdigit()):
        return None
    return raw if get_server(raw) else None

async def _country_flow(message, code, name):
    srv = get_server(code)
    if not srv:
        return await message.reply_text(
            f"❌ Server <code>{code}</code> not found. Create it with /addserver first.")
    if srv_is_api(srv):
        return await message.reply_text(
            f"{E('api')} <b>{esc(srv['name'])}</b> is the LIVE server.\n"
            f"Its countries, stock and prices are loaded from the supplier API — "
            f"run <code>/tgsync</code>.\n\n"
            f"Need manual countries? Create another server: <code>/addserver</code>")
    if name:
        if name in srv["countries"]:
            return await message.reply_text("⚠️ This country already exists in this server.")
        user_states[message.from_user.id] = {"state": "ACN_PRICE", "code": code, "name": name}
        return await message.reply_text(
            f"💰 Set the <b>fixed price (₹)</b> for <b>{esc(name)}</b>:\n"
            f"<i>Every ID added to this country will sell at this price.</i>")
    user_states[message.from_user.id] = {"state": f"ACN_NAME_{code}"}
    await message.reply_text(f"🌍 <b>Add country to {esc(srv['name'])} ({code})</b>\n\n"
                             f"Send the country name (e.g. Colombia, India, Brazil):")

def _pick_one_server(raw, cmd):
    codes = server_codes()
    if not codes:
        return None, "", "❌ No servers yet — create one with <code>/addserver</code> first."
    parts = (raw or "").strip().split(None, 1)
    if not parts:
        if len(codes) == 1:
            return codes[0], "", None
        return None, "", (f"Usage: <code>/{cmd} s1 ...</code> — servers: "
                          + ", ".join(f"<code>{c}</code>" for c in codes))
    code = _srv_arg(parts[0])
    rem = parts[1].strip() if len(parts) > 1 else ""
    if code:
        return code, rem, None
    if len(codes) == 1:
        return codes[0], " ".join(parts).strip(), None
    return None, "", ("❌ Server <code>" + esc(parts[0]) + "</code> not found. Options: "
                      + ", ".join(f"<code>{c}</code>" for c in codes))

@app.on_message(filters.private & filters.regex(r"(?i)^/addcountry\s*(.*)$", flags=re.S))
@admin_only
async def cmd_addcountry(client, message):
    code, name, err = _pick_one_server(message.matches[0].group(1) or "", "addcountry")
    if err:
        return await message.reply_text(err)
    await _country_flow(message, code, name)

@app.on_message(filters.private & filters.regex(r"(?i)^/delcountry\s*(.*)$", flags=re.S))
@admin_only
async def cmd_delcountry(client, message):
    code, _rem, err = _pick_one_server(message.matches[0].group(1) or "", "delcountry")
    if err:
        return await message.reply_text(err)
    srv = get_server(code)
    if srv_is_api(srv):
        return await message.reply_text(f"{E('api')} Countries on the live server are automatic "
                                        f"(/tgsync) and cannot be deleted.")
    if not srv or not srv["countries"]:
        return await message.reply_text("❌ No countries in this server.")
    btns = [[InlineKeyboardButton(
        f"🗑 {n} (₹{country_price(srv['countries'][n])} | {len(unsold_ids(srv['countries'][n]))} live)",
        callback_data=f"delcntry_{code}_{i}")] for i, n in enumerate(country_list(srv))]
    await message.reply_text("Select a country to DELETE (its unsold IDs will be removed):",
                             reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/addcountrys(\d+)(?:\s+(.+))?$"))
@admin_only
async def cmd_addcountrys(client, message):
    num = message.matches[0].group(1)
    name = (message.matches[0].group(2) or "").strip()
    code = f"s{num}"
    srv = get_server(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{code}</code> not found. Create it with /addserver first.")
    await _country_flow(message, code, name)

@app.on_message(filters.private & filters.regex(r"(?i)^/addids\s*(.*)$", flags=re.S))
@admin_only
async def cmd_addids_any(client, message):
    code, _rem, err = _pick_one_server(message.matches[0].group(1) or "", "addids")
    if err:
        return await message.reply_text(err)
    srv = get_server(code)
    if srv_is_api(srv):
        return await message.reply_text(
            f"{E('api')} <b>{esc(srv['name'])}</b> is the LIVE server — its IDs come from the "
            f"supplier API (/tgsync).\nFor manual IDs create another server: <code>/addserver</code>")
    if not srv["countries"]:
        return await message.reply_text(f"❌ <b>{esc(srv['name'])}</b> has no countries yet.\n"
                                        f"👉 Add one: <code>/addcountry {code} Colombia</code>")
    await start_addids(message, code)

@app.on_message(filters.private & filters.regex(r"(?i)^/delids\s*(.*)$", flags=re.S))
@admin_only
async def cmd_delids_any(client, message):
    code, _rem, err = _pick_one_server(message.matches[0].group(1) or "", "delids")
    if err:
        return await message.reply_text(err)
    srv = get_server(code)
    if srv_is_api(srv):
        return await message.reply_text(f"{E('api')} The live server has no manual IDs.")
    await start_delids(message, code)

@app.on_message(filters.private & filters.regex(r"(?i)^/delcountrys(\d+)\b"))
@admin_only
async def cmd_delcountrys(client, message):
    code = f"s{message.matches[0].group(1)}"
    srv = get_server(code)
    if not srv or not srv["countries"]:
        return await message.reply_text("❌ No countries in this server.")
    btns = [[InlineKeyboardButton(
        f"🗑 {n} (₹{country_price(srv['countries'][n])} | {len(unsold_ids(srv['countries'][n]))} live)",
        callback_data=f"delcntry_{code}_{i}")] for i, n in enumerate(country_list(srv))]
    await message.reply_text("Select a country to DELETE (its unsold IDs will be removed):",
                             reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/setprice\s*(.*)$", flags=re.S))
@admin_only
async def cmd_setprice(client, message):
    codes = [c for c in server_codes() if not srv_is_api(get_server(c))]
    if not codes:
        return await message.reply_text(f"{E('cross')} No manual servers found (live-server prices "
                                        "are calculated automatically — use /settiers).")
    btns = [[InlineKeyboardButton(f"{server_emoji(i)} {get_server(c)['name']}", callback_data=f"price_srv_{c}")]
            for i, c in enumerate(codes)]
    await message.reply_text("💰 <b>Change a country's fixed price</b>\nSelect server:",
                             reply_markup=InlineKeyboardMarkup(btns))

async def start_addids(msg_or_query, code):
    srv = get_server(code)
    if not srv:
        return await _edit_or_reply(msg_or_query, f"❌ Server <code>{code}</code> not found.", None)
    btns = [[InlineKeyboardButton(
        f"{flag_of(n)} {n} (₹{country_price(srv['countries'][n])} | {len(unsold_ids(srv['countries'][n]))})",
        callback_data=f"aid_c_{code}_{i}")] for i, n in enumerate(country_list(srv))]
    btns.append([InlineKeyboardButton("➕ New Country (name + price)", callback_data=f"aid_new_{code}")])
    btns.append([InlineKeyboardButton("🔙 Cancel", callback_data="noop")])
    await _edit_or_reply(msg_or_query,
                         f"📥 <b>Add IDs → {esc(srv['name'])} ({code})</b>\n"
                         f"Choose a country (price shown = fixed sell price):",
                         InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/addids(\d+)\b"))
@admin_only
async def cmd_addids(client, message):
    code = f"s{message.matches[0].group(1)}"
    srv = get_server(code)
    if not srv:
        return await message.reply_text(f"❌ Server <code>{code}</code> not found. Use /addserver first.")
    if srv_is_api(srv):
        return await message.reply_text(f"{E('api')} Live server — IDs are loaded with /tgsync.")
    if not srv["countries"]:
        return await message.reply_text(f"❌ <b>{esc(srv['name'])}</b> has no countries yet.\n"
                                        f"👉 Add one: <code>/addcountry {code} Colombia</code>")
    await start_addids(message, code)

async def start_delids(msg_or_query, code):
    srv = get_server(code)
    if not srv or not srv["countries"]:
        return await _edit_or_reply(msg_or_query, "❌ Nothing to delete in this server.", None)
    btns = [[InlineKeyboardButton(
        f"{flag_of(n)} {n} ({len(unsold_ids(srv['countries'][n]))} unsold / {len(srv['countries'][n]['ids'])} total)",
        callback_data=f"did_c_{code}_{i}")] for i, n in enumerate(country_list(srv))]
    btns.append([InlineKeyboardButton("🔙 Cancel", callback_data="noop")])
    await _edit_or_reply(msg_or_query, f"🗑 <b>Delete IDs → {esc(srv['name'])}</b>\nChoose a country:",
                         InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/delids(\d+)\b"))
@admin_only
async def cmd_delids(client, message):
    code = f"s{message.matches[0].group(1)}"
    await start_delids(message, code)

@app.on_message(filters.private & filters.regex(r"(?i)^/clearsold\b"))
@admin_only
async def cmd_clearsold(client, message):
    total = sum(len(sold_ids(c)) for s in db["servers"].values() for c in s["countries"].values())
    if not total:
        return await message.reply_text("❌ No sold IDs to clean up.")
    await message.reply_text(f"🧹 Remove <b>{total}</b> sold IDs from the database? "
                             f"(Purchase history, sessions & My IDs stay intact.)",
                             reply_markup=InlineKeyboardMarkup([
                                 [InlineKeyboardButton("🧹 Yes, Clean Up", callback_data="clearsold_yes")],
                                 [InlineKeyboardButton("❌ Cancel", callback_data="clearsold_no")]]))

@app.on_message(filters.private & filters.regex(r"(?i)^/settags\b"))
@admin_only
async def cmd_settags(client, message):
    codes = server_codes()
    if not codes:
        return await message.reply_text("❌ No servers yet.")
    btns = [[InlineKeyboardButton(get_server(c)["name"], callback_data=f"tags_srv_{c}")] for c in codes]
    await message.reply_text("🔍 Edit quality tags (Reliable / Spam / Bad Quality ...)\nSelect server:",
                             reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/addqr\b"))
@admin_only
async def cmd_addqr(client, message):
    user_states[message.from_user.id] = {"state": "QR_PHOTO"}
    await message.reply_text("📸 <b>Add Payment QR [1/3]</b>\n\nSend the QR code image:")

@app.on_message(filters.private & filters.regex(r"(?i)^/delqr\b"))
@admin_only
async def cmd_delqr(client, message):
    if not db.get("qrs"):
        return await message.reply_text("❌ No QRs saved.")
    btns = [[InlineKeyboardButton(f"🗑 {q.get('label', f'QR {i + 1}')} ({q.get('upi_id', '')})",
                                  callback_data=f"delqr_{i}")] for i, q in enumerate(db["qrs"])]
    await message.reply_text("Select a QR to delete:", reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/setmindeposit\s+(\d+)"))
@admin_only
async def cmd_setmindeposit(client, message):
    db["min_deposit"] = int(message.matches[0].group(1))
    await save_db()
    await message.reply_text(f"✅ Minimum deposit set to <b>₹{db['min_deposit']}</b>.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setdeptime\s+(\d+)"))
@admin_only
async def cmd_setdeptime(client, message):
    db["dep_timeout_mins"] = int(message.matches[0].group(1))
    await save_db()
    await message.reply_text(f"✅ Deposit/QR validity set to <b>{db['dep_timeout_mins']} minutes</b>.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setverify\s+(on|off)"))
@admin_only
async def cmd_setverify(client, message):
    mode = "channel" if message.matches[0].group(1) == "on" else "admins"
    if mode == "channel" and not db.get("pay_group"):
        return await message.reply_text("⚠️ No payment channel/group set yet.\n"
                                        "Set it first: <code>/setpaygroup -100XXXX</code> "
                                        "(or use <code>/setverify off</code> for admin DMs).")
    db["verify_mode"] = mode
    await save_db()
    if mode == "channel":
        await message.reply_text(f"✅ Verification <b>ON</b> — deposit requests will go to "
                                 f"<code>{esc(db['pay_group'])}</code>.\n"
                                 f"🛡 Only admins can approve/reject there.")
    else:
        await message.reply_text("✅ Verification <b>OFF</b> — deposit requests will go to "
                                 "<b>admins' DMs</b> only.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setname\s+(.+)$"))
@admin_only
async def cmd_setname(client, message):
    db["bot_name"] = message.matches[0].group(1).strip()
    await save_db()
    await apply_branding()
    await message.reply_text(
        f"{E('crown')} Store name set to <b>{esc(db['bot_name'])}</b> — \n"
        f"Telegram profile, welcome screen, deposits, proofs and profile updated.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setsupport\s+(\S+)"))
@admin_only
async def cmd_setsupport(client, message):
    db["support_link"] = message.matches[0].group(1).strip()
    await save_db()
    await message.reply_text(f"✅ Support set to {esc(db['support_link'])} "
                             f"(Support button + reject messages).")

@app.on_message(filters.private & filters.regex(r"(?i)^/setbuynote\s+(.+)$"))
@admin_only
async def cmd_setbuynote(client, message):
    db["buy_note"] = message.matches[0].group(1).strip()
    await save_db()
    await message.reply_text(f"✅ Buy note updated: {esc(db['buy_note'])}")

@app.on_message(filters.private & filters.regex(r"(?i)^/setpaygroup\s+(\S+)"))
@admin_only
async def cmd_setpaygroup(client, message):
    val = message.matches[0].group(1).strip()
    if val.lower() in ("off", "none"):
        db["pay_group"] = None
    else:
        try:
            val = int(val)
        except ValueError:
            pass
        db["pay_group"] = val
    await save_db()
    await message.reply_text(f"✅ Payment verification group set to <code>{esc(db['pay_group'])}</code>.\n"
                             f"Deposit screenshots will arrive there with Approve/Reject buttons "
                             f"(admins only). Use <code>/setverify on|off</code> to switch destination.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setproofchannel\s+(\S+)"))
@admin_only
async def cmd_setproofchannel(client, message):
    val = message.matches[0].group(1).strip()
    if val.lower() in ("off", "none"):
        db["proof_channel"] = None
    else:
        if val.startswith("http"):
            return await message.reply_text("❌ Send a chat ID (-100...) or @username, not an invite link.")
        try:
            val = int(val)
        except ValueError:
            pass
        db["proof_channel"] = val
    await save_db()
    await message.reply_text(f"✅ Proof channel set to <code>{esc(db['proof_channel'])}</code> "
                             f"(every sale posts a proof automatically).")

@app.on_message(filters.private & filters.regex(r"(?i)^/addapi\s+(\d+)\s+([0-9a-fA-F]+)"))
@admin_only
async def cmd_addapi(client, message):
    cred = {"api_id": int(message.matches[0].group(1)), "api_hash": message.matches[0].group(2)}
    if cred not in db["api_creds"]:
        db["api_creds"].append(cred)
        await save_db()
        await message.reply_text(f"✅ API credential <code>{cred['api_id']}</code> added. "
                                 f"Total: {len(db['api_creds'])} (rotated for temp sign-ins).")
    else:
        await message.reply_text("⚠️ This API ID is already added.")

@app.on_message(filters.private & filters.regex(r"(?i)^/listapi\b"))
@admin_only
async def cmd_listapi(client, message):
    creds = db.get("api_creds") or MULTI_API_CREDENTIALS
    text = "🔑 <b>API credentials (rotation):</b>\n"
    for i, c in enumerate(creds, 1):
        text += f"{i}. <code>{c['api_id']}</code> — {esc(c['api_hash'][:6])}...\n"
    text += f"\n➕ Add more: <code>/addapi &lt;api_id&gt; &lt;api_hash&gt;</code>"
    await message.reply_text(text)

@app.on_message(filters.private & filters.regex(r"(?i)^/addterm\s+(.+)$"))
@admin_only
async def cmd_addterm(client, message):
    db["terms"].append(message.matches[0].group(1).strip())
    await save_db()
    await message.reply_text("✅ Term added (shown in /start & verification message).")

@app.on_message(filters.private & filters.regex(r"(?i)^/delterm\b"))
@admin_only
async def cmd_delterm(client, message):
    if not db["terms"]:
        return await message.reply_text("❌ No terms.")
    btns = [[InlineKeyboardButton(f"🗑 {i + 1}. {t[:40]}", callback_data=f"delterm_{i}")]
            for i, t in enumerate(db["terms"])]
    await message.reply_text("Select a term to delete:", reply_markup=InlineKeyboardMarkup(btns))

@app.on_message(filters.private & filters.regex(r"(?i)^/fadd\b"))
@admin_only
async def cmd_fadd(client, message):
    user_states[message.from_user.id] = {"state": "FJ_ID"}
    await message.reply_text("🔗 <b>Force Join [1/3]</b>\n\nSend the channel/group ID (-100...) or @username:")

@app.on_message(filters.private & filters.regex(r"(?i)^/fdel\b"))
@admin_only
async def cmd_fdel(client, message):
    if not db.get("fsub"):
        return await message.reply_text("❌ No force-join chats set.")
    btns = [[InlineKeyboardButton(f"🗑 {ch['name']}", callback_data=f"fdel_{i}")]
            for i, ch in enumerate(db["fsub"])]
    await message.reply_text("Select to remove:", reply_markup=InlineKeyboardMarkup(btns))

# =====================================================================
#  🔥 TG SHARK — ADMIN COMMANDS (v4.0)
# =====================================================================

@app.on_message(filters.private & filters.regex(r"(?i)^/tgtest\b"))
@admin_only
async def cmd_tgtest(client, message):
    """Supplier API connection test — read-only calls, nothing is purchased."""
    await message.reply_text(f"{E('api')} Testing the supplier API... (read-only calls)")
    bal = await tg_api("getBalance")
    info = await tg_api("getInfo")
    cn = await tg_api("getCountrys")
    key = tg_cfg()["api_key"]
    masked = (key[:14] + "..." + key[-4:]) if len(key) > 20 else key
    if bal.get("status") == "ok":
        db["tgshark"]["last_balance"] = bal.get("balance", 0)
        await save_db()
    ok = "🟢" if bal.get("status") == "ok" else "🔴"
    ok2 = "🟢" if info.get("status") == "ok" else "🔴"
    ok3 = "🟢" if cn.get("status") == "ok" else "🔴"
    ncountries = len(cn.get("countries") or [])
    stock = sum(int(c.get("count", 0) or 0) for c in (cn.get("countries") or []))
    await message.reply_text(
        f"{E('api')} <b>SUPPLIER API TEST</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Key: <code>{esc(masked)}</code>\n"
        f"{ok} getBalance : <code>{esc(bal.get('message') or ('OK $%s' % bal.get('balance')))}</code>\n"
        f"{ok2} getInfo : <code>{esc(info.get('message') or ('OK @%s' % info.get('username')))}</code>\n"
        f"{ok3} getCountrys : <code>{esc(cn.get('message') or ('OK %s countries / %s numbers' % (ncountries, stock)))}</code>\n\n"
        f"{E('warn')} <b>getNumber was not tested</b> — it would reserve a real number.\n"
        f"To test the full purchase flow for free, turn on demo mode: "
        f"<code>/tgdry on</code>")

@app.on_message(filters.private & filters.regex(r"(?i)^/tgstatus\b"))
@admin_only
async def cmd_tgstatus(client, message):
    await message.reply_text("🔄 Fetching API status...")
    cfg = tg_cfg()
    bal = await tg_api("getBalance")
    info = await tg_api("getInfo")
    code = api_server_code()
    srv = get_server(code)
    live = sum(stock_count(c) for c in srv["countries"].values()) if srv else 0
    ncn = len(srv["countries"]) if srv else 0
    if bal.get("status") == "ok":
        db["tgshark"]["last_balance"] = bal.get("balance", 0)
        await save_db()
    rows = ""
    if srv:
        for n in country_list(srv)[:8]:
            cobj = srv["countries"][n]
            rows += (f"   {iso_flag(cobj.get('iso'))} {esc(iso_name(cobj.get('iso')))}: "
                     f"{stock_count(cobj)} pcs @ ₹{country_price(cobj)} (cost ${cobj.get('api_cost', 0)})\n")
    err_line = ((f"{E('warn')} <code>{esc(str(bal.get('message'))[:90])}</code>\n")
                if bal.get("status") != "ok" else "")
    await message.reply_text(
        f"{E('api')} <b>LIVE SERVER STATUS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E('money')} API balance: <b>${bal.get('balance', '?')}</b>\n"
        f"{E('user')} Account: {esc(info.get('username', '?'))} (rank {esc(info.get('rank', '?'))})\n"
        f"{E('key')} Key: <code>{esc(mask_key(srv_api_key()))}</code>\n"
        + err_line
        + f"{E('server')} API server: <code>{esc(code or '—')}</code>"
        f" ({esc(srv['name']) if srv else '—'})\n"
        f"{E('box')} Live stock: <b>{live}</b> numbers • {ncn} countries\n"
        f"{E('chart')} Profit: <b>{cfg['profit_pct']:.0f}%</b> • 1$ = ₹{cfg['usd_inr']}"
        f" • round ₹{cfg['round_to']}\n"
        f"{E('warn')} Mode: <b>{'DEMO (nothing is purchased)' if cfg['dry_run'] else 'LIVE (real numbers)'}</b>\n"
        f"🕒 Last sync: {pretty_ts(db['tgshark']['last_sync']) if db['tgshark'].get('last_sync') else '—'}\n\n"
        f"<b>Top countries:</b>\n{rows or '   (empty — /tgsync chalao)'}")

@app.on_message(filters.private & filters.regex(r"(?i)^/tgsync\b"))
@admin_only
async def cmd_tgsync(client, message):
    await message.reply_text("🔄 Syncing live stock and prices...")
    _n, msg = await tg_sync_stock()
    await check_low_stock()
    cfg = tg_cfg()
    srv = get_server(api_server_code())
    extra = ""
    if srv:
        rows = ""
        for n in country_list(srv)[:10]:
            cobj = srv["countries"][n]
            rows += (f"   {iso_flag(cobj.get('iso'))} {esc(iso_name(cobj.get('iso')))} — "
                     f"{stock_count(cobj)} pcs • ₹{country_price(cobj)} (cost ${cobj.get('api_cost', 0)}"
                     f" + {cfg['profit_pct']:.0f}%)\n")
        extra = f"\n\n{E('money')} <b>Live rate card:</b>\n{rows}"
    await message.reply_text(f"{E('sync')} {msg}{extra}")

@app.on_message(filters.private & filters.regex(r"(?i)^/tgserver\s+(\S+)"))
@admin_only
async def cmd_tgserver(client, message):
    code = message.matches[0].group(1).strip().lower()
    srv = get_server(code)
    if not srv:
        return await message.reply_text("❌ Server not found. Codes: " +
                                        ", ".join(f"<code>{c}</code>" for c in server_codes()))
    if srv_is_api(srv):
        srv["source"] = "manual"
        db["tgshark"]["server_code"] = None
        await save_db()
        return await message.reply_text(f"✅ <b>{esc(srv['name'])}</b> ab MANUAL server hai.")
    # purane api server ko manual kar do (ek hi api server)
    old = api_server_code()
    if old and old != code:
        get_server(old)["source"] = "manual"
    srv["source"] = "tgshark"
    srv["desc"] = srv.get("desc") or "Live API numbers"
    db["tgshark"]["server_code"] = code
    await save_db()
    _n, msg = await tg_sync_stock()
    await message.reply_text(
        f"{E('api')} <b>{esc(srv['name'])} ({code})</b> is now the LIVE server!\n"
        f"{msg}\n\n"
        f"💡 Its countries, stock and prices now come from the supplier API "
        f"(auto-refresh every {TGSHARK_SYNC_MINS} minutes).")

@app.on_message(filters.private & filters.regex(r"(?i)^/setapikey(?:\s|$)"))
@admin_only
async def cmd_setapikey(client, message):
    """/setapikey <key>  —  key me space/newline ho to khud saaf kar lega"""
    raw = (message.text or "").split(None, 1)
    if len(raw) > 1 and raw[1].strip():
        await _save_api_key(message, clean_key(raw[1]))
        return
    user_states[message.from_user.id] = {"state": "TG_KEY"}
    await message.reply_text(
        f"{E('api')} <b>New API key</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Key bhejo (jo <code>tgsharkapi-</code> se shuru hoti hai):\n\n"
        f"💡 <i>Agar key ke beech me line-break/space aa gaya ho to bhi chalega — "
        f"bot khud saaf kar dega.</i>\n"
        f"❌ <code>/cancel</code> se cancel karo.")


async def _save_api_key(message, key):
    """Key save karo → turant verify karo → result batao."""
    if not key.startswith("tgsharkapi-"):
        return await message.reply_text(
            f"❌ Ye key nahi lagti — key <code>tgsharkapi-</code> se shuru hoti hai.\n"
            f"Jo aapne bheja: <code>{esc(mask_key(key))}</code>")
    db["tgshark"]["api_key"] = key
    await save_db()
    res = await tg_api("getBalance")
    if res.get("status") == "ok":
        db["tgshark"]["last_balance"] = res.get("balance", 0)
        await save_db()
        await message.reply_text(
            f"✅ <b>API connect ho gaya!</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🔑 Key saved: <code>{esc(mask_key(key))}</code>\n"
            f"💰 Balance: <b>${res.get('balance')}</b>\n\n"
            f"Ab <code>/tgsync</code> chalao — stock aa jayega.")
        await log_event(f"{E('api')} <b>API key updated</b> by "
                        f"{esc(message.from_user.first_name or 'admin')} — connected ✅")
        return
    msg = str(res.get("message") or "")
    low = msg.lower()
    if "apikey" in low or "401" in low or "unauthor" in low:
        hint = ("🔑 Supplier ne key reject kar di.\n"
                "   • Dashboard se poora text ek hi line me copy karo\n"
                "   • Key expired/blocked ho sakti hai → nayi key banao\n"
                "   • Ek key sirf ek jagah (do bot mat chalao)")
    elif "403" in low or "ban" in low:
        hint = ("🚫 Key banned — do alag IPs se use hone par hota hai.\n"
                "   Nayi key banao aur sirf isi bot me chalao.")
    elif "certificate" in low or "ssl" in low:
        hint = ("🔒 SSL error — .env me <code>TGSHARK_VERIFY_SSL=false</code> "
                "daal kar restart karo.")
    elif "timed out" in low or "timeout" in low:
        hint = ("⏱ Timeout — .env me <code>TGSHARK_HTTP_TIMEOUT=40</code> "
                "daal kar restart karo.")
    else:
        hint = (f"❓ Supplier ka jawab: <code>{esc(msg[:100])}</code>\n"
                f"   Thodi der baad dobara try karo.")
    await message.reply_text(
        f"⚠️ <b>Key saved, par connect nahi hua</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Saved: <code>{esc(mask_key(key))}</code>\n"
        f"❌ API bola: <code>{esc(msg[:80])}</code>\n\n{hint}\n\n"
        f"🔍 <code>/apiprobe</code> se aur detail milegi.")


@app.on_message(filters.private & filters.regex(r"(?i)^/setprofit\s+(\d+(?:\.\d+)?)"))
@admin_only
async def cmd_setprofit(client, message):
    pct = float(message.matches[0].group(1))
    if pct < 0 or pct > 1000:
        return await message.reply_text(f"{E('cross')} Profit must be between 0 and 1000.")
    old_map = price_snapshot()
    db["tgshark"]["profit_pct"] = pct
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"flat profit set to {pct:.0f}%", old_map)
    sample = ""
    srv = get_server(api_server_code())
    if srv:
        for nm in country_list(srv)[:5]:
            cobj = srv["countries"][nm]
            sample += (f"   {iso_flag(cobj.get('iso'))} {esc(iso_name(cobj.get('iso')))}: "
                       f"${cobj.get('api_cost', 0)} → <b>₹{country_price(cobj)}</b>\n")
    await message.reply_text(
        f"{E('chart')} <b>Profit set to {pct:.0f}%</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n{sample}\n"
        f"{announce_note(changes)}\n"
        f"<i>Formula: cost(USD) × ₹{tg_cfg()['usd_inr']} × (1 + {pct:.0f}%)"
        f" → round-up ₹{tg_cfg()['round_to']}</i>\n"
        f"<i>Tier slabs (/settiers) pehle apply hote hain — flat % sirf fallback hai.</i>")

@app.on_message(filters.private & filters.regex(r"(?i)^/setinr\s+(\d+(?:\.\d+)?)"))
@admin_only
async def cmd_setinr(client, message):
    rate = float(message.matches[0].group(1))
    if rate <= 0:
        return await message.reply_text(f"{E('cross')} Rate must be greater than 0.")
    old_map = price_snapshot()
    db["tgshark"]["usd_inr"] = rate
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"USD rate changed to ₹{rate}", old_map)
    await message.reply_text(
        f"{E('check')} USD → INR rate set to <b>₹{rate}</b>.\n"
        f"All live prices were recalculated. {announce_note(changes)}")

@app.on_message(filters.private & filters.regex(r"(?i)^/setround\s+(\d+)"))
@admin_only
async def cmd_setround(client, message):
    r = int(message.matches[0].group(1))
    if r < 1:
        return await message.reply_text(f"{E('cross')} Minimum rounding is ₹1.")
    old_map = price_snapshot()
    db["tgshark"]["round_to"] = r
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"rounding changed to ₹{r}", old_map)
    await message.reply_text(
        f"{E('check')} Price rounding set to <b>₹{r}</b> (rounded up).\n"
        f"{announce_note(changes)}")

@app.on_message(filters.private & filters.regex(r"(?i)^/setminprice\s+(\d+)"))
@admin_only
async def cmd_setminprice(client, message):
    val = int(message.matches[0].group(1))
    if val < 1:
        return await message.reply_text(f"{E('cross')} Minimum price must be at least ₹1.")
    old_map = price_snapshot()
    db["tgshark"]["min_price"] = val
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"minimum price set to ₹{val}", old_map)
    await message.reply_text(
        f"{E('check')} Minimum selling price set to <b>₹{val}</b>.\n"
        f"No item can be cheaper than ₹{val}, even if supplier cost is zero.\n"
        f"{announce_note(changes)}")

def tiers_text():
    """Profit tiers ka formatted text (command + button dono use karte hain)."""
    c = tg_cfg()
    txt = f"{E('chart')} <b>PROFIT TIERS</b>\n━━━━━━━━━━━━━━━━━━\n"
    for t in c["tiers"]:
        upto = "∞" if float(t.get("upto", 0)) >= 10 ** 8 else f"₹{float(t.get('upto', 0)):.0f}"
        if t.get("add") is not None:
            txt += f"• cost up to {upto} → <b>+₹{float(t['add']):.0f}</b> profit\n"
        else:
            mn = float(t.get("min_add", 0) or 0)
            extra = f" (min +₹{mn:.0f})" if mn else ""
            txt += f"• cost up to {upto} → <b>+{float(t.get('pct', 0)):.0f}%</b> profit{extra}\n"
    txt += (f"\n{E('money')} USD→INR: ₹{c['usd_inr']}  •  round-up: ₹{c['round_to']}"
            f"  •  min price: ₹{c['min_price']}\n"
            f"Fallback flat profit: {c['profit_pct']:.0f}%\n\n"
            f"Change a slab: <code>/settier &lt;upto&gt; &lt;₹ or %&gt;</code>\n"
            f"• <code>/settier 50 15</code> → cost up to ₹50 = +₹15\n"
            f"• <code>/settier 100 10% min 5</code> → 10% with ₹5 minimum\n"
            f"• <code>/settier 50 off</code> → ye slab hata do\n"
            f"Reset sab kuch: <code>/settiers reset</code>")
    return txt


@app.on_message(filters.private & filters.regex(r"(?i)^/settiers\b(.*)"))
@admin_only
async def cmd_settiers(client, message):
    arg = (message.matches[0].group(1) or "").strip().lower()
    if arg == "reset":
        old_map = price_snapshot()
        db["tgshark"]["tiers"] = norm_tiers(TGSHARK_PROFIT_TIERS)
        await save_db()
        await tg_sync_stock()
        changes = await recalc_all_prices("profit tiers reset", old_map)
        return await message.reply_text(
            f"{E('check')} Profit tiers reset to defaults.\n{announce_note(changes)}")
    await message.reply_text(tiers_text())


@app.on_message(filters.private & filters.regex(r"(?i)^/settier\s+(\d+(?:\.\d+)?)\s+off\s*$"))
@admin_only
async def cmd_settier_off(client, message):
    """Koi slab hata do: /settier 50 off"""
    upto = float(message.matches[0].group(1))
    old_map = price_snapshot()
    cur = norm_tiers(db["tgshark"].get("tiers"))
    tiers = [t for t in cur if float(t.get("upto", 0)) != upto]
    if len(tiers) == len(cur):
        return await message.reply_text(f"{E('cross')} Koi slab ₹{upto:.0f} par nahi hai.")
    db["tgshark"]["tiers"] = tiers
    await save_db()
    await tg_sync_stock()
    changes = await recalc_all_prices(f"tier up to ₹{upto:.0f} removed", old_map)
    await message.reply_text(
        f"{E('check')} Slab <b>up to ₹{upto:.0f}</b> removed.\n{announce_note(changes)}")


@app.on_message(filters.private & filters.regex(
    r"(?i)^/settier\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*(%?)\s*(?:min\s*(\d+(?:\.\d+)?))?\s*$"))
@admin_only
async def cmd_settier(client, message):
    upto = float(message.matches[0].group(1))
    val = float(message.matches[0].group(2))
    is_pct = (message.matches[0].group(3) or "") == "%"
    min_add = float(message.matches[0].group(4) or 0)
    old_map = price_snapshot()
    entry = {"upto": upto, "pct": val} if is_pct else {"upto": upto, "add": val}
    if is_pct and min_add:
        entry["min_add"] = min_add
    tiers = [t for t in norm_tiers(db["tgshark"].get("tiers")) if float(t.get("upto", 0)) != upto]
    tiers.append(entry)
    tiers.sort(key=lambda t: t["upto"])
    db["tgshark"]["tiers"] = tiers
    await save_db()
    await tg_sync_stock()
    label = f"+{val:.0f}%" if is_pct else f"+₹{val:.0f}"
    if is_pct and min_add:
        label += f" (min +₹{min_add:.0f})"
    changes = await recalc_all_prices(f"tier up to ₹{upto:.0f} = {label}", old_map)
    await message.reply_text(
        f"{E('chart')} <b>Profit tier saved</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Cost up to <b>₹{upto:.0f}</b> → profit <b>{label}</b>\n"
        f"{announce_note(changes)}\n\nSee all slabs: <code>/settiers</code>")


@app.on_message(filters.private & filters.regex(r"(?i)^/setcost\s+(\S+)\s+(\d+(?:\.\d+)?)\s*(.*)$"))
@admin_only
async def cmd_setcost(client, message):
    """Manual server: cost set karo → sell price auto-calculate."""
    code = _srv_arg(message.matches[0].group(1))
    cost = float(message.matches[0].group(2))
    name = (message.matches[0].group(3) or "").strip()
    if not code:
        return await message.reply_text(f"{E('cross')} Usage: <code>/setcost s2 30 Colombia</code>")
    srv = get_server(code)
    if not srv:
        return await message.reply_text(f"{E('cross')} Server <code>{esc(code)}</code> not found.")
    if srv_is_api(srv):
        return await message.reply_text(
            f"{E('api')} The live server takes its cost from the supplier API — set your margin "
            f"with <code>/settiers</code> instead.")
    if not name:
        listing = ", ".join(f"<code>{esc(x)}</code>" for x in country_list(srv)[:20])
        return await message.reply_text(
            f"{E('cross')} Usage: <code>/setcost {code} &lt;cost₹&gt; &lt;country&gt;</code>\n"
            f"Countries: {listing}")
    match = next((x for x in country_list(srv) if x.lower() == name.lower()), None)
    if not match:
        return await message.reply_text(f"{E('cross')} Country <code>{esc(name)}</code> not found "
                                        f"in {esc(srv['name'])}.")
    cobj = srv["countries"][match]
    old = country_price(cobj)
    cobj["cost"] = cost
    cobj["price"] = calc_sell_price(cost)
    for it in cobj.get("ids", []):
        if not it.get("sold"):
            it["price"] = cobj["price"]
            it["label"] = f"{flag_of(match)} {match} (₹{cobj['price']})"
    await save_db()
    announced = await announce_price_change(f"{srv['name']} • {match}", old, cobj["price"],
                                            extra=f"Cost set to ₹{cost:.0f}")
    kind, val, mn = profit_rule(cost)
    await message.reply_text(
        f"{E('money')} <b>Cost set — price calculated automatically</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{E('globe')} {cflag(srv, match)} <b>{esc(match)}</b> — {esc(srv['name'])}\n"
        f"📥 Cost: ₹{cost:.0f}\n"
        f"📤 Profit: {'+₹%.0f' % val if kind == 'flat' else '+%.0f%%' % val}"
        f"{f' (min +₹{mn:.0f})' if mn else ''}\n"
        f"{E('tag')} Selling price: <b>₹{cobj['price']}</b>\n\n"
        f"{'<i>Announced in the updates channel.</i>' if announced else '<i>Tip: set /setannounce to auto-post price updates.</i>'}")


@app.on_message(filters.private & filters.regex(r"(?i)^/renamecountry\s*(\S*)"))
@admin_only
async def cmd_renamecountry(client, message):
    code, _rem, err = _pick_one_server(message.matches[0].group(1) or "", "renamecountry")
    if err:
        return await message.reply_text(err)
    srv = get_server(code)
    if srv_is_api(srv):
        return await message.reply_text(f"{E('api')} Live-server country names come from the "
                                        "supplier API and cannot be renamed.")
    if not srv["countries"]:
        return await message.reply_text(f"{E('cross')} This server has no countries yet.")
    btns = [[InlineKeyboardButton(f"{cflag(srv, x)} {cname(srv, x)} (₹{country_price(srv['countries'][x])})",
                                  callback_data=f"rencn_{code}_{i}")]
            for i, x in enumerate(country_list(srv))]
    await message.reply_text(f"{E('note')} Select the country to rename:",
                             reply_markup=InlineKeyboardMarkup(btns))


@app.on_message(filters.private & filters.regex(r"(?i)^/setannounce\s+(\S+)"))
@admin_only
async def cmd_setannounce(client, message):
    val = message.matches[0].group(1).strip()
    if val.lower() in ("off", "none"):
        db["announce_channel"] = None
        await save_db()
        return await message.reply_text(f"{E('check')} Announcements now fall back to the proof channel.")
    if val.startswith("http"):
        return await message.reply_text(f"{E('cross')} Send a chat ID (-100...) or @username, not a link.")
    try:
        val = int(val)
    except ValueError:
        pass
    db["announce_channel"] = val
    _auto = auto_fsub_add(str(val), name="Announcements",
                          link=("https://t.me/" + str(val)[1:]) if str(val).startswith("@") else "")
    await save_db()
    await announce(f"{E('sparkle')} <b>Announcements enabled</b>\n"
                   f"Price updates and low-stock alerts will be posted in this channel.")
    await message.reply_text(f"{E('check')} Announcement channel set to <code>{esc(val)}</code>."
                             + ("\n🔒 Force-join me bhi add ho gaya." if _auto else ""))


@app.on_message(filters.private & filters.regex(r"(?i)^/setlowstock\s+(\d+)"))
@admin_only
async def cmd_setlowstock(client, message):
    val = int(message.matches[0].group(1))
    db["low_stock"] = val
    await save_db()
    if val <= 0:
        return await message.reply_text(f"{E('check')} Low-stock alerts disabled.")
    await message.reply_text(
        f"{E('check')} Admins will be alerted whenever a country has <b>{val}</b> numbers or fewer.")


@app.on_message(filters.private & filters.regex(r"(?i)^/setbrandname\s+(.+)$"))
@admin_only
async def cmd_setbrandname(client, message):
    db["bot_name"] = message.matches[0].group(1).strip()
    await save_db()
    await apply_branding()
    await message.reply_text(
        f"{E('crown')} Brand name set to <b>{esc(db['bot_name'])}</b>\n"
        f"Telegram profile, welcome screen and menus updated.")


@app.on_message(filters.private & filters.regex(r"(?i)^/tgdry\s+(on|off)"))
@admin_only
async def cmd_tgdry(client, message):
    on = message.matches[0].group(1).lower() == "on"
    db["tgshark"]["dry_run"] = on
    await save_db()
    if on:
        await message.reply_text(
            f"{E('shield')} <b>DEMO MODE ON</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"No real number is purchased from the supplier.\n"
            f"Buyers get a sample number + sample OTP, and their bot balance is still "
            f"charged — perfect for testing the full flow for free.")
    else:
        await message.reply_text(
            f"{E('warn')} <b>LIVE MODE ON</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Every purchase now reserves a real number from the supplier.\n"
            f"{E('money')} Supplier balance: <b>${db['tgshark'].get('last_balance', 0)}</b>\n\n"
            f"Keep it topped up, otherwise orders are auto-refunded.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setemoji\s*(.*)$", flags=re.S))
@admin_only
async def cmd_setemoji(client, message):
    arg = (message.matches[0].group(1) or "").strip()
    if not arg:
        keys = ", ".join(f"<code>{k}</code>" for k in EMOJI.keys())
        return await message.reply_text(
            f"{E('sparkle')} <b>Set a premium (custom) emoji</b>\n\n"
            f"Usage: <code>/setemoji &lt;key&gt; &lt;numeric_id&gt;</code>\n"
            f"Hatao: <code>/setemoji &lt;key&gt; off</code>\n\n"
            f"Keys: {keys}\n\n"
            f"List: <code>/emojis</code>")
    parts = arg.split()
    key = parts[0]
    if key not in EMOJI:
        return await message.reply_text(f"❌ Unknown key <code>{esc(key)}</code>. "
                                        f"Valid keys: send <code>/setemoji</code> with no argument.")
    if len(parts) > 1:
        val = parts[1]
        if val.lower() in ("off", "none", "0", "reset", "clear"):
            db["emoji"].pop(key, None)
            await save_db()
            return await message.reply_text(f"✅ <b>{esc(key)}</b> reset → Unicode: {E(key)}")
        if not val.isdigit():
            return await message.reply_text("❌ Emoji ID sirf numeric hota hai.")
        db["emoji"][key] = val
        await save_db()
        return await message.reply_text(
            f"{E('sparkle')} <b>{esc(key)}</b> → custom emoji <code>{val}</code>\nPreview: {E(key)}")
    user_states[message.from_user.id] = {"state": f"TG_EMOJI_{key}"}
    await message.reply_text(f"🎨 <b>{esc(key)}</b> ke liye Telegram custom emoji ka "
                             f"<b>numeric ID</b> to use.\nCurrent: {E(key)}")

@app.on_message(filters.private & filters.regex(r"(?i)^/emojis\b"))
@admin_only
async def cmd_emojis(client, message):
    txt = f"{E('sparkle')} <b>PREMIUM EMOJI</b>\n━━━━━━━━━━━━━━━━━━\n"
    for k in EMOJI:
        cid = (db.get("emoji") or {}).get(k)
        state = f"custom <code>{cid}</code>" if cid else "Unicode"
        txt += f"{E(k)} <code>{k}</code> — {state}\n"
    txt += ("\n➕ Set: <code>/setemoji crown 5312...</code>\n"
            "➖ Reset: <code>/setemoji crown off</code>")
    await message.reply_text(txt)

# ---------- PROMO CHANNELS (time-limited) ----------

@app.on_message(filters.private & filters.regex(r"(?i)^/addpromo\b(.*)"))
@admin_only
async def cmd_addpromo(client, message):
    args = (message.matches[0].group(1) or "").strip()
    if not args:
        return await message.reply_text(
            "📢 <b>Add Promo Channel</b>\n\n"
            "Usage: <code>/addpromo &lt;channel&gt; &lt;days&gt;</code>\n\n"
            "Examples:\n"
            "• <code>/addpromo @mychannel 15</code> — public channel, 15 din\n"
            "• <code>/addpromo https://t.me/+AbCdEf 30</code> — invite link\n"
            "• <code>/addpromo -1001234567890 7</code> — <b>private channel ID</b> "
            "(bot us channel ka admin hona chahiye)\n\n"
            "Days na likho to default 30 din. Time khatam hone par promo "
            "auto-hide ho jata hai.")
    parts = args.split()
    target = parts[0]
    days = 30
    if len(parts) > 1:
        try:
            days = max(1, min(3650, int(parts[1])))
        except ValueError:
            days = 30
    link = None
    title = target
    if target.startswith("http"):
        link = target
        title = "Promo Channel"
    elif target.startswith("@"):
        link = f"https://t.me/{target[1:]}"
        title = target
    elif target.lstrip("-").isdigit():
        cid = int(target)
        title = "Promo Channel"
        try:
            chat = await client.get_chat(cid)
            title = chat.title or title
        except Exception:
            pass
        try:
            link = await client.export_chat_invite_link(cid)
        except Exception as e:
            logging.warning("export invite link for %s failed: %s", cid, e)
    else:
        link = f"https://t.me/{target}"
        title = "@" + target
    db.setdefault("promos", [])
    db["promos"] = [p for p in db["promos"] if p.get("target") != target]
    until = time.time() + days * 86400
    db["promos"].append({"target": target, "title": title, "link": link,
                         "days": days, "added_at": time.time(), "until": until})
    await save_db()
    reply = (f"✅ <b>Promo channel added!</b>\n"
             f"   📢 {esc(title)}\n"
             f"   ⏳ Valid: <b>{days} day(s)</b> — till {datetime.fromtimestamp(until).strftime('%d %b %Y, %H:%M')}\n")
    reply += ("   🔗 Join button: ✅ ready — users ko /start par dikhega"
              if link else
              "   ⚠️ Join link nahi mila (private channel me bot ko admin banao) — "
              "promo list me rahega bina button.")
    await message.reply_text(reply)

@app.on_message(filters.private & filters.regex(r"(?i)^/delpromo\b(.*)"))
@admin_only
async def cmd_delpromo(client, message):
    arg = (message.matches[0].group(1) or "").strip().lower()
    if arg == "all":
        n = len(db.get("promos", []))
        db["promos"] = []
        await save_db()
        return await message.reply_text(f"✅ All {n} promo channel(s) removed.")
    try:
        idx = int(arg) - 1
    except ValueError:
        idx = -99
    promos = db.get("promos", [])
    if 0 <= idx < len(promos):
        p = promos.pop(idx)
        await save_db()
        await message.reply_text(f"✅ Promo removed: <b>{esc(p['title'])}</b>")
    else:
        await message.reply_text("Usage: <code>/delpromo &lt;# from /promos&gt;</code> ya <code>/delpromo all</code>")

@app.on_message(filters.private & filters.regex(r"(?i)^/promos\b"))
@admin_only
async def cmd_promos(client, message):
    if prune_promos():
        await save_db()
    promos = db.get("promos", [])
    if not promos:
        return await message.reply_text(
            "📭 No promo channels.\n\nAdd: <code>/addpromo @channel 15</code> "
            "(private channel: <code>/addpromo -100... 30</code>)")
    text = ("📢 <b>Promo Channels</b>\n━━━━━━━━━━━━━━━━━━\n")
    for i, p in enumerate(promos, 1):
        left = p.get("until", 0) - time.time()
        if left > 0:
            days_left = int(left // 86400) + 1
            status = f"🟢 active — {days_left} day(s) left"
        else:
            status = "🔴 expired"
        text += (f"{i}. <b>{esc(p['title'])}</b>\n"
                 f"    {status} | join button: {'✅' if p.get('link') else '❌'}\n")
    text += "\nRemove: <code>/delpromo &lt;#&gt;</code> ya <code>/delpromo all</code>"
    await message.reply_text(text)

# ---------- ADMIN: SALES ACCESS + FREEZE CONTROL ----------

@app.on_message(filters.private & filters.regex(r"(?i)^/sales\b"))
@admin_only
async def cmd_sales(client, message):
    sales = db.get("sales", [])[-20:]
    if not sales:
        return await message.reply_text("📭 No sales yet.")
    text = "🧾 <b>LAST 20 SALES</b>\n━━━━━━━━━━━━━━━━━━\n"
    for s in reversed(sales):
        sd = db.get("sold_sessions", {}).get(s["sale_id"], {})
        if sd.get("api"):
            st = f"{E('api')} api {esc(sd.get('status', ''))}"
        elif sd.get("dead"):
            st = f"❄️ frozen ({sd['dead']})"
        elif sd.get("session_dead"):
            st = "⛔ bot-session killed"
        else:
            st = "🟢 active"
        text += (f"<code>{s['sale_id']}</code> {flag_of(s['country'])} {esc(s['country'])} "
                 f"₹{s['price']} | uid <code>{s['uid']}</code> | {st}\n")
    text += ("\n🛠 OTP fetch: <code>/otp &lt;sale_id&gt;</code>\n"
             "❄️ Freeze: <code>/freezeid &lt;sale_id&gt; [reason]</code>\n"
             "✅ Unfreeze: <code>/unfreezeid &lt;sale_id&gt;</code>")
    await message.reply_text(text)

@app.on_message(filters.private & filters.regex(r"(?i)^/otp\s+(\S+)"))
@admin_only
async def cmd_admin_otp(client, message):
    sale_id = message.matches[0].group(1).strip()
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd:
        return await message.reply_text(f"{E('cross')} Order not found. See <code>/sales</code>.")
    if sd.get("dead"):
        return await message.reply_text(
            f"❄️ This ID is frozen/logged out (<code>{esc(sd['dead'])}</code>) — OTP nahi milega.\n"
            f"Unfreeze: <code>/unfreezeid {sale_id}</code>")
    # ---- LIVE API order ----
    if sd.get("api"):
        await message.reply_text("⏳ Polling TGShark API for the code...")
        code = await api_poll_code(sd)
        twofa = sd.get("twofa") or ""
        if not code:
            return await message.reply_text(
                f"❌ Koi OTP nahi mila abhi.\n"
                f"{E('phone')} Number: <code>{esc(sd.get('number', ''))}</code>\n"
                f"Ask the buyer to request a login code on this number, then try again.")
        sd["otp"] = code
        await save_db()
        return await message.reply_text(
            f"{E('key')} <b>ADMIN OTP FETCH (API)</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Order: <code>{sale_id}</code>\n"
            f"{E('phone')} Number: <code>{esc(sd.get('number', ''))}</code>\n"
            f"👤 Buyer uid: <code>{sd.get('uid')}</code>\n"
            f"🌍 {esc(sd.get('country', ''))}\n\n"
            f"💬 OTP: <code>{esc(code)}</code>\n"
            f"🔐 2FA: {('<code>' + esc(twofa) + '</code>') if twofa else 'Not set'}")
    if not sd.get("session_string"):
        return await message.reply_text("❌ No session string for this order.")
    await message.reply_text("⏳ Fetching latest OTP...")
    code, full, mdate, dr = await fetch_otp(sd["session_string"], 0)
    if dr:
        await mark_id_dead(sale_id, dr)
        return await message.reply_text(f"🚨 This ID is DEAD (<code>{dr}</code>) — frozen, alerts bhej diye.")
    pwd = sd.get("password", "None")
    pwd_show = f"<code>{esc(pwd)}</code>" if pwd not in (None, "", "None") else "No password set"
    if code:
        await message.reply_text(
            f"🔑 <b>ADMIN OTP FETCH</b>\n━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Order: <code>{sale_id}</code>\n"
            f"📞 Number: <code>{esc(sd.get('number', ''))}</code>\n"
            f"👤 Buyer uid: <code>{sd.get('uid')}</code>\n\n"
            f"💬 OTP: <code>{esc(code)}</code>\n🔐 2FA: {pwd_show}")
    else:
        await message.reply_text(
            f"❌ Koi OTP nahi mila abhi (777000 me is number ka koi code nahi).\n"
            f"📞 <code>{esc(sd.get('number', ''))}</code>")

@app.on_message(filters.private & filters.regex(r"(?i)^/freezeid\s+(\S+)(.*)"))
@admin_only
async def cmd_freezeid(client, message):
    sale_id = message.matches[0].group(1).strip()
    reason = (message.matches[0].group(2) or "").strip() or "Manually frozen by admin"
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd:
        return await message.reply_text(f"{E('cross')} Order not found. See <code>/sales</code>.")
    if sd.get("dead"):
        return await message.reply_text("⚠️ Already frozen.")
    await mark_id_dead(sale_id, reason)
    await message.reply_text(f"✅ <code>{sale_id}</code> FROZEN — user ka OTP band, admin alerts gaye.")

@app.on_message(filters.private & filters.regex(r"(?i)^/unfreezeid\s+(\S+)"))
@admin_only
async def cmd_unfreezeid(client, message):
    sale_id = message.matches[0].group(1).strip()
    sd = db.get("sold_sessions", {}).get(sale_id)
    if not sd:
        return await message.reply_text("❌ Sale not found.")
    if not sd.get("dead"):
        return await message.reply_text("⚠️ Ye ID frozen hai hi nahi.")
    sd.pop("dead", None)
    sd.pop("dead_at", None)
    await save_db()
    await message.reply_text(f"✅ <code>{sale_id}</code> UNFROZEN — OTP delivery wapas chalu.")
    try:
        await app.send_message(sd.get("uid"),
                               f"✅ <b>ID Unfrozen</b>\n🆔 <code>{sale_id}</code>\n"
                               f"OTP delivery resumed — tap 🔄 Request New OTP.")
    except Exception:
        pass

@app.on_message(filters.private & filters.regex(r"(?i)^/addadmin\s+(\d+)"))
@admin_only
async def cmd_addadmin(client, message):
    new = int(message.matches[0].group(1))
    if new not in db["admins"]:
        db["admins"].append(new)
        await save_db()
        await refresh_command_menus()
        await message.reply_text(f"✅ Admin <code>{new}</code> added (multi-admin enabled). "
                                 f"Admin commands ab uske menu me bhi dikhenge.")
    else:
        await message.reply_text("⚠️ Already an admin.")

@app.on_message(filters.private & filters.regex(r"(?i)^/deladmin\s+(\d+)"))
@admin_only
async def cmd_deladmin(client, message):
    old = int(message.matches[0].group(1))
    if old in OWNER_IDS:
        return await message.reply_text("❌ Owners cannot be removed.")
    if old in db["admins"]:
        db["admins"].remove(old)
        await save_db()
        await reset_command_menu(old)
        await message.reply_text(f"✅ Admin <code>{old}</code> removed. "
                                 f"Uske command menu se admin commands hat gaye.")
    else:
        await message.reply_text("⚠️ Not an admin.")

@app.on_message(filters.private & filters.regex(r"(?i)^/dm\s+(\d+)\s+(.+)$", flags=re.S))
@admin_only
async def cmd_dm(client, message):
    uid = message.matches[0].group(1)
    txt = message.matches[0].group(2)
    try:
        await app.send_message(uid, f"💬 <b>Message from {esc(bot_name())} Support:</b>\n\n{esc(txt)}")
        await message.reply_text("✅ Sent.")
    except Exception as e:
        await message.reply_text(f"❌ Failed: <code>{esc(e)}</code>")

async def send_report(message):
    logs = db.get("deposit_log", [])
    sales = db.get("sales", [])
    today = datetime.now().strftime("%Y-%m-%d")
    appr = [l for l in logs if l["status"] == "approved"]
    rej = [l for l in logs if l["status"] == "rejected"]
    exp = [l for l in logs if l["status"] == "expired"]
    pend = list(db.get("pending_deposits", {}).values())
    appr_today = [l for l in appr if l.get("time", "")[:10] == today]
    sales_today = [s for s in sales if s.get("time", "")[:10] == today]
    new_today = [u for u in db["users"].values()
                 if datetime.fromtimestamp(u.get("joined", 0)).strftime("%Y-%m-%d") == today]
    cc = {}
    for s in sales:
        cc[s["country"]] = cc.get(s["country"], 0) + 1
    top = max(cc, key=cc.get) if cc else "—"
    text = (
        f"📊 <b>{esc(bot_name())} — BUSINESS REPORT</b>\n"
        f"🕒 {now_str()}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 <b>USERS</b>\n"
        f"   Total: <b>{len(db['users'])}</b>  |  New today: <b>{len(new_today)}</b>\n\n"
        f"💳 <b>DEPOSITS</b>\n"
        f"   ✅ Approved: <b>{len(appr)}</b> (₹{sum(l['amount'] for l in appr)})\n"
        f"   📅 Today: <b>{len(appr_today)}</b> (₹{sum(l['amount'] for l in appr_today)})\n"
        f"   ❌ Rejected: <b>{len(rej)}</b>  |  ⌛ Expired: <b>{len(exp)}</b>\n"
        f"   ⏳ Pending now: <b>{len(pend)}</b> (₹{sum(p['amount'] for p in pend)})\n\n"
        f"🛒 <b>SALES</b>\n"
        f"   Total: <b>{len(sales)}</b> (₹{sum(s['price'] for s in sales)})\n"
        f"   📅 Today: <b>{len(sales_today)}</b> (₹{sum(s['price'] for s in sales_today)})\n"
        f"   🏆 Top country: <b>{esc(top)}</b>\n"
        f"   💰 Wallet liability: ₹{sum(u.get('balance', 0) for u in db['users'].values())}\n\n"
        f"📦 <b>LIVE STOCK</b>\n"
    )
    for i, code in enumerate(server_codes()):
        srv = get_server(code)
        tag = f" {E('api')}LIVE" if srv_is_api(srv) else ""
        text += f"   {server_emoji(i)} <b>{esc(srv['name'])}</b> ({code}){tag} — {server_stock_count(srv)} live IDs\n"
        for n in country_list(srv):
            cobj = srv["countries"][n]
            u = stock_count(cobj)
            text += (f"      {cflag(srv, n)} {esc(cname(srv, n))}: {u} unsold / "
                     f"{len(cobj['ids'])} total @ ₹{country_price(cobj)}\n")
    text += "\n🧾 <b>LAST 5 SALES</b>\n"
    if sales:
        for s in sales[-5:][::-1]:
            text += (f"   • <code>{s['sale_id']}</code> {flag_of(s['country'])} {esc(s['country'])} "
                     f"₹{s['price']} — {esc(s['time'][5:16])}\n")
    else:
        text += "   • No sales yet\n"
    text += "\n💳 <b>LAST 5 DEPOSITS</b>\n"
    if logs:
        for l in logs[-5:][::-1]:
            emoji = {"approved": "✅", "rejected": "❌", "expired": "⌛",
                     "cancelled": "🚫"}.get(l["status"], "⏳")
            text += (f"   • {emoji} ₹{l['amount']} <code>{l['ref'][-12:]}</code> "
                     f"— by {esc(l.get('by', '?'))}\n")
    else:
        text += "   • No deposits yet\n"
    cfg = tg_cfg()
    text += (f"\n{E('api')} <b>TGSHARK:</b> ${db['tgshark'].get('last_balance', 0)} balance • "
             f"profit {cfg['profit_pct']:.0f}% • 1$ = ₹{cfg['usd_inr']} • "
             f"{'DRY-RUN' if cfg['dry_run'] else 'LIVE'}\n")
    text += (f"\n🛡 Verify mode: <b>{esc(db.get('verify_mode', 'channel'))}</b>"
             f"  |  🔑 APIs: {len(db.get('api_creds') or [])}"
             f"  |  🖥 {platform.system()}")
    if len(text) > 4000:
        with open("report.txt", "w", encoding="utf-8") as f:
            f.write(text)
        await message.reply_document("report.txt", caption="📊 Full business report")
        os.remove("report.txt")
    else:
        await message.reply_text(text)

@app.on_message(filters.private & filters.regex(r"(?i)^/report\b"))
@admin_only
async def cmd_report(client, message):
    await send_report(message)

@app.on_message(filters.private & filters.regex(r"(?i)^/broadcast\b"))
@admin_only
async def cmd_broadcast(client, message):
    user_states[message.from_user.id] = {"state": "BC_MSG"}
    await message.reply_text("📣 Send the message (text/photo/video) to broadcast:")

@app.on_message(filters.private & filters.regex(r"(?i)^/backup\b"))
@admin_only
async def cmd_backup(client, message):
    await save_db()
    snap = _snapshot("manual")
    await message.reply_document(DB_FILE, caption=(
        "📦 <b>Database backup</b>\n\n"
        "🔁 <b>Server change / update — data loss ZERO:</b>\n"
        "1️⃣ Nayi server par bot file (id_store_bot.py) daalo\n"
        "2️⃣ Ye <code>id_store_db.json</code> file bot ke saath same folder me rakho\n"
        "3️⃣ <code>python id_store_bot.py</code> — sab IDs, QR, users, sales wapas mil jayenge\n\n"
        "🛡 Auto-backup har 6 ghante me <code>backups/</code> folder me hota hai "
        "(last 10 snapshots). Restore se pehle bhi auto-snapshot banta hai."
        + (f"\n📁 Snapshot saved: <code>{snap}</code>" if snap else "")))

@app.on_message(filters.private & filters.regex(r"(?i)^/restore\b"))
@admin_only
async def cmd_restore(client, message):
    if not message.reply_to_message or not message.reply_to_message.document:
        return await message.reply_text("❌ Reply to a .json backup file with /restore")
    if not message.reply_to_message.document.file_name.endswith(".json"):
        return await message.reply_text("❌ Only .json backups allowed.")
    await save_db()
    snap = _snapshot("pre-restore")
    await message.reply_to_message.download(file_name=DB_FILE)
    await load_db()
    await refresh_command_menus()
    await message.reply_text(
        "✅ Database restored!\n"
        + (f"🛡 Purani DB ka safety snapshot: <code>{snap}</code>\n" if snap else "")
        + "All data (IDs, sales, users) was loaded from this backup.")

@app.on_message(filters.private & filters.regex(r"(?i)^/cancelstate\b"))
async def cmd_cancelstate(client, message):
    await abort_state(message.from_user.id, "❌ Current flow cancelled.")

# ================= ADMIN / IDENTITY SELF-CHECK =================

@app.on_message(filters.private & filters.regex(r"(?i)^/whoami\b"))
async def cmd_whoami(client, message):
    uid = message.from_user.id
    admin = is_admin(uid)
    if not admin:
        menu = "— (normal user menu)"
    elif uid in _admin_menu_ok:
        menu = "✅ set — type / in Telegram to see all admin commands"
    else:
        menu = "⚠️ pending — press /start once and it will be set instantly"
    await message.reply_text(
        f"🪪 <b>Your identity in {esc(bot_name())}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 Your Telegram user ID: <code>{uid}</code>\n"
        f"👑 Owner (config OWNER_IDS): <b>{'YES' if uid in OWNER_IDS else 'no'}</b>\n"
        f"🛡 Admin (bot's admin list): <b>{'YES' if admin else 'no'}</b>\n"
        f"📖 Admin command menu: {menu}\n\n"
        + ("<b>✅ Everything is fine.</b> Use the 🛠️ Admin Panel button, /adminpanel and all admin commands."
           if admin else
           f"❌ Aap admin nahi ho — panel isliye locked hai.\n"
           f"🔧 Fix #1: set <code>OWNER_IDS = [{uid}]</code> at the top of the file and restart.\n"
           f"🔧 Fix #2: kisi existing admin se bolo → <code>/addadmin {uid}</code>\n"
           f"🧪 Test build me: <code>/claimadmin</code> (AUTO_GRANT_OWNER=True hone par)."
           + ("\n\nℹ️ Dhyan rahe: OWNER_IDS me <b>Telegram USER ID</b> daalte hain, "
              "<b>bot ka token number nahi</b> — aksar yahin galti hoti hai." if not admin else "")))

@app.on_message(filters.private & filters.regex(r"(?i)^/claimadmin\b"))
async def cmd_claimadmin(client, message):
    uid = message.from_user.id
    if not AUTO_GRANT_OWNER:
        return await message.reply_text(
            "🔒 <b>Self-admin claim disabled.</b>\n"
            "Kisi existing admin se bolo: <code>/addadmin " + str(uid) + "</code>\n"
            "(For testing, set <code>AUTO_GRANT_OWNER = True</code> in the file.)")
    added = False
    async with db_lock:
        if uid not in db["admins"]:
            db["admins"].append(uid)
            added = True
        await save_db()
    if added:
        _admin_menu_ok.discard(uid)
        await set_admin_menu(uid)
    await message.reply_text(
        (f"✅ You (ID <code>{uid}</code>) ab ADMIN ho — 🛠️ Admin Panel unlock, "
         f"command menu: {'✅ set' if uid in _admin_menu_ok else '⚠️ press /start once'}.\n"
         if added else
         f"ℹ️ Aap (ID <code>{uid}</code>) pehle se admin the.\n")
        + "🧪 Test ke baad hatana ho: <code>/deladmin " + str(uid) + "</code> "
          "(owner list wale nahi hatenge) ya file me AUTO_GRANT_OWNER=False.")

@app.on_message(filters.private & filters.regex(r"(?i)^/setmenu\b"))
@admin_only
async def cmd_setmenu(client, message):
    uid = message.from_user.id
    m = re.match(r"(?i)^/setmenu\s+(\d+)", message.text or "")
    target = int(m.group(1)) if m else uid
    _admin_menu_ok.discard(target)
    ok = await _try_set_admin_commands(target)
    if ok:
        await message.reply_text(f"✅ Command menu force-refreshed for <code>{target}</code> — "
                                 f"app me '/' kholo, admin commands dikhenge.")
    else:
        await message.reply_text(
            "⚠️ Telegram ne mana kiya (PEER_ID_INVALID): us user ne abhi tak bot ko koi "
            "has not messaged the bot yet. Ask them to press <b>/start</b> once — the menu will "
            "ho jayega (aur bot ne nudge DM bhi bhej diya hai).")

@app.on_message(filters.private & filters.regex(r"(?i)^/admins\b"))
@admin_only
async def cmd_admins(client, message):
    ids = dict.fromkeys(list(db.get("admins", [])) + OWNER_IDS)
    text = ("👥 <b>ADMINS</b>\n━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ To know someone's user ID, ask them to send <code>/whoami</code>.\n\n")
    for a in ids:
        flags = []
        if a in OWNER_IDS:
            flags.append("👑 owner")
        if a in _admin_menu_ok:
            flags.append("✅ menu set")
        elif a in _admin_menu_pending:
            flags.append("📨 nudge bheja — /start ka wait")
        else:
            flags.append("⏳ menu not set yet")
        uname = db["users"].get(str(a), {}).get("name", "?")
        text += f"• <code>{a}</code> — {esc(uname)} — {', '.join(flags)}\n"
    text += "\n🛠 Menu not set? Ask that admin to press <b>/start</b> once, or use <code>/setmenu &lt;id&gt;</code>."
    await message.reply_text(text)

# ================= ADMIN PANEL / HELP =================

ADMIN_PANEL_TEXT = (
    "🛠️ <b>ADMIN CONTROL PANEL</b>\n━━━━━━━━━━━━━━━━━━\n"
    "<b>🔥 TGShark LIVE API (v4.0):</b>\n"
    "• /tgsync — live stock + prices API se lao\n"
    "• /tgstatus — API balance, stock, profit, mode\n"
    "• /tgtest — supplier API connection test (nothing is purchased)\n"
    "• /tgserver s1 — toggle a server between LIVE and MANUAL\n"
    "• /setapikey &lt;key&gt; — TGShark API key set karo\n"
    "• /setprofit 10 — profit % (server 1 pricing)\n"
    "• /settiers — profit slabs dekho (cost ₹30 → +₹10 …)\n"
    "• /settier 50 15 — slab badlo (₹ ya %)\n"
    "• /setinr 88 — 1 USD = how many ₹\n"
    "• /setround 5 — price round-up (₹5)\n"
    "• /setminprice 10 — minimum selling price\n"
    "• /tgdry on|off — DEMO (free tests) / LIVE (real selling)\n"
    "• /setcost s2 30 Colombia — cost set karo, price auto\n"
    "• /profitcalc 0.30 — price preview (change nahi hota)\n"
    "• /profitreport — margin + profit table\n"
    "• /setprofitmode tiers|pct  •  /setroundmode ceil|nearest|floor\n"
    "• /setcharm on|off (₹49/₹99)  •  /setmaxprice 500\n"
    "• /setmargin s1 MA 25 — ek country ka alag margin\n\n"
    "<b>🎨 Premium emoji:</b>\n"
    "• /setemoji &lt;key&gt; &lt;id&gt; — Telegram custom emoji lagao\n"
    "• /emojis — emoji list + status\n\n"
    "<b>🖥 Servers:</b>\n"
    "• /addserver — create server (name + description)\n"
    "• /renameserver s1 — rename server\n"
    "• /delserver — delete server (buttons)\n\n"
    "<b>🌍 Categories / countries:</b>\n"
    "• /addcountry s2 Colombia — add category, then set its price\n"
    "• /setprice — change a price later (unsold items update)\n"
    "• /setcost s2 30 Colombia — set cost → price auto-calculated\n"
    "• /renamecountry s2 — rename a category (buttons)\n"
    "• /delcountry s2 — delete category (buttons)\n"
    "• /settags — edit quality tags (Reliable / Spam ...)\n\n"
    "<b>📦 IDs:</b>\n"
    "• /addids s1 — country → batch size → number → OTP (retry) → 2FA (retry) → button text\n"
    "• /delids s1 — remove accounts by buttons (shows counts)\n"
    "• /clearsold — purge sold IDs from DB (history safe)\n\n"
    "<b>💳 Payments:</b>\n"
    "• /addqr , /delqr — UPI QRs (QR 1 / QR 2 switch for users)\n"
    "• /setmindeposit 25 — minimum deposit\n"
    "• /setdeptime 15 — payment validity minutes\n"
    "• /setpaygroup -100... — verification group\n"
    "• /setverify on|off — ON: requests to channel/group, OFF: admins' DMs\n"
    "• /setproofchannel @ch — har sale par SOLD post\n"
    "• /setannounce @ch — price/stock announcements channel\n"
    "• /setsalepost on|off — channel sale updates\n\n"
    "<b>⚙️ Bot settings:</b>\n"
    "• /setname , /setbrandname , /setsupport , /setbuynote\n"
    "• /setlowstock 5 — low-stock admin alert threshold\n"
    "• /setwelcome {name} • /motd • /setbrandname\n"
    "• /setcurrency $ • /setfooter <note> • /setdesc s1 BD <text>\n"
    "• /setbulk 3 5 • /setstockview exact|range|hidden\n"
    "• /coupons • /addcoupon CODE 10% 100 • /delcoupon CODE\n"
    "• /setrefbonus 5 • /ban <id> • /setmaxbuy 3 • /setautorefund on\n\n"
    "• /setwelcome {name} • /motd • /setbrandname\n\n"
    "• /addterm , /delterm — terms & conditions\n"
    "• /fadd , /fdel — force-join (real verification)\n"
    "• /addapi &lt;id&gt; &lt;hash&gt; , /listapi — multiple API IDs (rotation)\n\n"
    "<b>👥 Admins & tools:</b>\n"
    "• /addadmin , /deladmin — multi-admin\n"
    "• /report — full sales/deposits/users/stock report\n"
    "• /dm ID text — message a user\n"
    "• /broadcast — broadcast to all users\n"
    "• /backup , /restore — database backup\n"
    "• /whoami , /admins , /setmenu — admin identity & command-menu self-check\n"
    "• /cancelstate — cancel any running flow"
)

ADMIN_HELP_TEXT = (
    f"{E('crown')} <b>SETUP GUIDE — 5 MINUTES</b>\n━━━━━━━━━━━━━━━━━━\n"
    f"<b>1. Branding</b>\n"
    f"   /setbrandname Premium ID Store  →  /setsupport @your_support\n\n"
    f"<b>2. Live stock (supplier connected)</b>\n"
    f"   /addserver → Server 1 is the LIVE server by default\n"
    f"   /tgtest (connection check) → /tgsync (load stock + prices)\n"
    f"   Profit slabs: /settiers  •  Change: /settier 50 15\n"
    f"   Ya sirf % chahiye: /setprofitmode pct → /setprofit 15\n"
    f"   Preview: /profitcalc 0.3  •  Report: /profitreport\n"
    f"   Rule abhi: ₹0-30 → +₹5 • ₹30-100 → 10% (min ₹5) • ₹100+ → +₹15\n\n"
    f"<b>3. Manual stock (your own accounts)</b>\n"
    f"   /addserver → /addcountry s2 Colombia → /addids s2 (real Telegram OTP login)\n"
    f"   Cost-based pricing: /setcost s2 30 Colombia (price auto-calculated)\n"
    f"   Rename/delete: /renamecountry s2 • /delcountry s2 • /delids s2\n\n"
    f"<b>4. Payments</b>\n"
    f"   /addqr (photo → label → UPI ID)  •  /setmindeposit 25  •  /setdeptime 15\n"
    f"   /setpaygroup -100XXXX + /setverify on (or off for admin DMs)\n"
    f"   /setproofchannel @ch (sale proofs)  •  /setannounce @ch (price updates)\n"
    f"   /addcoupon WELCOME 10% 100 200 — deposit bonus coupons\n"
    f"   /setrefbonus 5 — referral bonus %  •  users: /ref\n"
    f"   /setautorefund on  •  /setmaxbuy 3  •  /ban <id>\n"
    f"   /setbulk 3 5 (bulk discount)  •  /setotptimeout 15\n\n"
    f"<b>5. Growth & safety</b>\n"
    f"   /fadd (force-join)  •  /addpromo @channel 15 (timed promos)\n"
    f"   /addadmin &lt;id&gt;  •  /broadcast  •  /report  •  /backup\n"
    f"   /setlowstock 5 → admins get an alert when stock runs low\n\n"
    f"{E('bolt')} <b>BUYER FLOW (live server):</b> Products → server → country →\n"
    f"   Buy → Confirm → number reserved → OTP delivered automatically (polls every 5s).\n"
    f"   If nothing is available, the order is <b>auto-refunded</b> instantly.\n"
    f"   OTP na aaye to bhi auto-refund (/setautorefund).\n\n"
    f"{E('bolt')} <b>BUYER FLOW (manual server):</b> same, plus session-string delivery,\n"
    f"   🔄 Request New OTP, and 📱 Manage Sessions (terminate other sessions).\n\n"
    f"🧾 /sales — last 20 orders  •  /otp &lt;order&gt; — fetch any OTP\n"
    f"❄️ Dead IDs (logout/ban) are detected automatically → OTP disabled + admin alert.\n"
    f"   Manual: /freezeid &lt;order&gt;  •  /unfreezeid &lt;order&gt;\n"
    f"💾 /backup (DB file) + auto-snapshots every 6h  •  /restore to roll back\n"
    f"🛡 Safety: 1 pending deposit per user, unique Ref IDs, double-approve blocked, auto-expiry.\n\n"
    f"🪪 Panel missing? /whoami → check your user ID is in OWNER_IDS (not the bot token ID).\n"
    f"   Then /setmenu to refresh the command menu."
)

def panel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{E('sync')} Sync Stock", callback_data="adm_act_tgsync"),
         InlineKeyboardButton(f"{E('chart')} Live Status", callback_data="tg_status")],
        [InlineKeyboardButton(f"{E('money')} Profit Tiers", callback_data="adm_act_tiers"),
         InlineKeyboardButton(f"{E('box')} Low Stock", callback_data="adm_act_lowstock")],
        [InlineKeyboardButton("➕ Server", callback_data="adm_act_addserver"),
         InlineKeyboardButton("🌍 Country", callback_data="srvpick_addcountry")],
        [InlineKeyboardButton("📥 Add IDs", callback_data="srvpick_addids"),
         InlineKeyboardButton("🗑 Delete IDs", callback_data="srvpick_delids")],
        [InlineKeyboardButton("💰 Set Price", callback_data="srvpick_price"),
         InlineKeyboardButton("📸 Add QR", callback_data="adm_act_addqr")],
        [InlineKeyboardButton("📢 Add Promo", callback_data="adm_act_promo"),
         InlineKeyboardButton("📋 Promos", callback_data="adm_act_promolist")],
        [InlineKeyboardButton("📊 Report", callback_data="adm_act_report")],
    ])

@app.on_message(filters.regex("^🛠️ Admin Panel$") & filters.private)
async def panel_handler(client, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("❌ Not authorized.")
    await message.reply_text(ADMIN_PANEL_TEXT, reply_markup=panel_kb())

@app.on_message(filters.regex("^📖 Admin Help$") & filters.private)
async def help_handler(client, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("❌ Not authorized.")
    await message.reply_text(ADMIN_HELP_TEXT, reply_markup=panel_kb())

@app.on_message(filters.private & filters.regex(r"(?i)^/(adminpanel|adminhelp)\b"))
@admin_only
async def cmd_adminhelp(client, message):
    cmd = message.matches[0].group(1).lower()
    await message.reply_text(ADMIN_PANEL_TEXT if cmd == "adminpanel" else ADMIN_HELP_TEXT,
                             reply_markup=panel_kb())
