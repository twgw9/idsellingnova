"""User screens & commands: /start, products, profile, support."""

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

# ================= /start + VERIFY =================

@app.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    uid = message.from_user.id
    user_states.pop(uid, None)
    if await banned_gate(message=message):
        return
    uid_str = str(uid)
    existed = uid_str in db["users"]
    old_name = db["users"].get(uid_str, {}).get("name")
    rec = user_record(uid, message.from_user.first_name)
    payload = (message.text or "").split(maxsplit=1)[1].strip() if len((message.text or "").split()) > 1 else ""
    if payload.startswith("ref_") and not existed:
        ref_uid = payload[4:].strip()
        if ref_uid.isdigit() and int(ref_uid) != uid and ref_uid in db["users"]:
            rec["ref_by"] = ref_uid
            rrec = user_record(int(ref_uid))
            rrec.setdefault("refs", [])
            if uid_str not in rrec["refs"]:
                rrec["refs"].append(uid_str)
    if not existed or old_name != rec.get("name") or payload:
        await save_db()
    if not existed:
        await log_event(f"🆕 <b>New user</b>\n"
                        f"👤 {esc(message.from_user.first_name or '-')} • <code>{uid}</code>\n"
                        f"👥 Total users: <b>{len(db.get('users', {}))}</b>")
    if is_admin(uid):
        _admin_menu_ok.discard(uid)
        await _try_set_admin_commands(uid)
    if not rec.get("accepted", False):
        await message.reply_text(
            f"{E('sparkle')} <b>{esc(bot_name())}</b> {E('sparkle')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📜 <b>Terms &amp; Conditions</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{terms_block()}\n\n"
            f"{E('live')} <i>Auto Delivery Enabled</i>\n\n"
            f"👇 <b>Please accept the terms to continue:</b>",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I Accept & Continue", callback_data="accept_terms")]]),
            reply_to_message_id=None)
        return
    fsub = await check_fsub(client, uid)
    if fsub is not True:
        return await message.reply_text(
            f"{E('warn')} <b>Verification required to unlock the menu.</b>" + promo_text_block(),
            reply_markup=fsub)
    if prune_promos():
        await save_db()
    if active_promos():
        return await send_promo_screen(message)
    wt = db.get("welcome_text")
    if wt:
        try:
            text = wt.format(name=esc(message.from_user.first_name or "there"),
                             balance=rec.get("balance", 0), bot=esc(bot_name()))
        except Exception:
            text = esc(wt)
    else:
        text = (f"{E('crown')} <b>Welcome to {esc(bot_name())}!</b> {E('crown')}\n"
                f"{E('live')} <i>Auto Delivery Enabled</i>  •  {E('bolt')} <i>Instant OTP</i>\n"
                f"{E('gem')} Use the menu below:")
    if db.get("motd"):
        text += f"\n\n📢 <b>{esc(db['motd'])}</b>"
    await message.reply_text(text, reply_markup=main_kb(uid))

@app.on_message(filters.private & filters.regex(r"(?i)^/terms\b"))
async def cmd_terms(client, message):
    rec = user_record(message.from_user.id)
    status = "✅ Accepted" if rec.get("accepted") else "❌ Not accepted yet"
    await message.reply_text(
        f"{E('note')} <b>Terms &amp; Conditions — {esc(bot_name())}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n{terms_block()}\n\nStatus: {status}",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ I Accept & Continue", callback_data="accept_terms")]]
            if not rec.get("accepted") else [[InlineKeyboardButton("🏠 Home", callback_data="home")]]))

@app.on_callback_query(filters.regex("^accept_terms$"))
async def accept_terms_cb(client, query):
    uid = query.from_user.id
    rec = user_record(uid, query.from_user.first_name)
    rec["accepted"] = True
    await save_db()
    await ack(query)
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    fsub = await check_fsub(client, uid)
    if fsub is not True:
        return await query.message.reply_text(
            f"{E('warn')} <b>Verification required to unlock the menu.</b>" + promo_text_block(),
            reply_markup=fsub)
    if active_promos():
        return await send_promo_screen(query.message)
    await query.message.reply_text(
        f"{E('crown')} <b>Welcome to {esc(bot_name())}!</b> {E('crown')}\n"
        f"{E('live')} <i>Auto Delivery Enabled</i>\n{E('gem')} Use the menu below:",
        reply_markup=main_kb(uid))

@app.on_callback_query(filters.regex("^fsub_verify$"))
async def fsub_verify_cb(client, query):
    uid = query.from_user.id
    fsub = await check_fsub(client, uid)
    if fsub is True:
        uid_str = str(uid)
        existed = uid_str in db["users"]
        user_record(uid, query.from_user.first_name)
        if not existed:
            await save_db()
        await ack(query)
        if active_promos():
            return await send_promo_screen(query.message)
        try:
            await query.message.delete()
        except Exception:
            pass
        await query.message.reply_text(
            f"{E('crown')} <b>Welcome to {esc(bot_name())}!</b> {E('crown')}\n"
            f"{E('live')} <i>Auto Delivery Enabled</i>\n{E('gem')} Use the menu below:",
            reply_markup=main_kb(uid))
    else:
        await ack(query, "❌ You haven't joined yet! Join first, then press Verify.", show_alert=True)

# ================= PRODUCTS FLOW =================

@app.on_message(filters.regex("^🛒 Products$") & filters.private)
async def products_handler(client, message):
    user_states.pop(message.from_user.id, None)
    await send_server_list(message)

async def send_server_list(msg_or_query):
    codes = server_codes()
    home = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="home")]])
    if not codes:
        return await _edit_or_reply(
            msg_or_query,
            f"{E('cart')} <b>Products — {esc(bot_name())}</b>\n\n❌ No servers are live right now. "
            f"Please check back later!", home)
    text = (f"{E('cart')} <b>Products</b> — server choose karo:\n"
            f"━━━━━━━━━━━━━━━━━━\n")
    btns = []
    for i, code in enumerate(codes):
        srv = get_server(code)
        if srv_is_api(srv):
            label = f"{E('api')} {esc(srv['name'])} {E('live')}"
        else:
            label = f"{server_emoji(i)} {esc(srv['name'])}"
        stock = server_stock_count(srv)
        btns.append([InlineKeyboardButton(f"{label} • {stock} pcs", callback_data=f"srv_{code}")])
    btns.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(btns))

async def _edit_or_reply(msg_or_query, text, markup):
    text = money(text)
    if isinstance(msg_or_query, Message):
        await msg_or_query.reply_text(text, reply_markup=markup)
    else:
        await msg_or_query.message.edit_text(text, reply_markup=markup)

async def send_country_page(msg_or_query, code, page):
    srv = get_server(code)
    if not srv:
        return await _edit_or_reply(msg_or_query, "❌ Server not found.", None)
    names = [n for n in country_list(srv) if stock_count(srv["countries"][n]) > 0]
    if not names:
        if country_list(srv):
            hint = (f"📦 Countries exist but no IDs in stock.\n"
                    f"👉 Admin: add IDs with <code>/addids {code}</code>"
                    if not srv_is_api(srv) else
                    f"📦 Live stock is empty right now.\n"
                    f"👉 Admin: <code>/tgsync</code> to refresh")
        else:
            hint = (f"📦 This server has no countries yet.\n"
                    f"👉 Admin: add one with <code>/addcountry {code}</code>"
                    if not srv_is_api(srv) else
                    f"📦 No countries loaded — run <code>/tgsync</code>")
        return await _edit_or_reply(
            msg_or_query,
            f"📦 <b>{esc(srv['name'])}</b> ({code})\n\n❌ No stock available in this server right now.\n\n{hint}",
            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Servers", callback_data="home_products"),
                                   InlineKeyboardButton("🏠 Home", callback_data="home")]]))
    per_page = max(5, int(COUNTRIES_PER_PAGE))
    total_pages = max(1, (len(names) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = names[page * per_page:(page + 1) * per_page]

    head = (f"{E('bolt')} <b>LIVE STOCK</b> — instant delivery, auto OTP\n"
            if srv_is_api(srv) else "")
    text = (f"{head}"
            f"{E('globe')} <b>{esc(srv['name'])}</b> — country choose karo\n"
            f"{E('money')} Rates in ₹ (INR) • tap for stock &amp; price\n"
            f"📄 Page {page + 1}/{total_pages} • {len(names)} countries")
    btns = [[InlineKeyboardButton("📋 Rate Card (all countries)", callback_data=f"ratecard_{code}_{page}")]]
    row = []
    zero = [x for x in country_list(srv) if stock_count(srv["countries"][x]) <= 0]
    if zero:
        btns.append([InlineKeyboardButton(f"🔔 Restock Alerts ({len(zero)} sold out)",
                                          callback_data=f"restock_{code}")])
    for n in chunk:
        idx = names.index(n)
        price = country_price(srv["countries"][n])
        cnt = stock_count(srv["countries"][n])
        iso = (srv["countries"][n].get("iso") or n).upper()
        dial = f"+{iso_dial(iso)} " if iso_dial(iso) else ""
        label = (f"{cflag(srv, n)} {iso} {dial}• {cur()}{price} ({stock_label(cnt, short=True)})"
                 if iso != "XX" else
                 f"🎲 Global Mix • {cur()}{price} ({stock_label(cnt, short=True)})")
        row.append(InlineKeyboardButton(label, callback_data=f"cid_{code}_{idx}_{page}"))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"cpg_{code}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"cpg_{code}_{page + 1}"))
    if nav:
        btns.append(nav)
    if srv_is_api(srv):
        btns.append([InlineKeyboardButton(f"{E('sync')} Refresh Live Stock",
                                          callback_data=f"tgsync_now_{code}_{page}")])
    btns.append([InlineKeyboardButton("🏠 Back to Home", callback_data="home")])
    await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(btns))

async def send_country_info(msg_or_query, code, cidx, page):
    srv = get_server(code)
    if not srv:
        return await _edit_or_reply(msg_or_query, "❌ Server not found.", None)
    names = [n for n in country_list(srv) if stock_count(srv["countries"][n]) > 0]
    if cidx >= len(names):
        return await send_country_page(msg_or_query, code, page)
    name = names[cidx]
    cobj = srv["countries"][name]
    price = country_price(cobj)
    cnt = stock_count(cobj)
    tags = cobj.get("tags") or db.get("default_tags", DEFAULT_TAGS)
    if srv_is_api(srv):
        cfg = tg_cfg()
        text = (
            f"{E('bolt')} <b>Telegram Account — Instant Delivery</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E('globe')} Country : {iso_flag(cobj.get('iso'))} {esc(iso_name(cobj.get('iso')))}\n"
            f"{E('money')} Price : ₹{price} per number\n"
            f"{E('box')} Available : <b>{stock_label(cnt)}</b>\n"
            f"{E('shield')} {esc(tags)}\n"
            + (f"📝 {esc(cobj.get('desc'))}\n" if cobj.get("desc") else "")
            + (f"🎲 <i>{esc(GLOBAL_MIX_NOTE)}</i>\n" if cobj.get("iso") == "XX" else "")
            + "\n"
            f"{E('warn')} <b>Important:</b> {esc(db.get('buy_note', DEFAULT_BUY_NOTE))}\n"
            f"🚫 We are not responsible for any freeze/ban"
        )
    else:
        text = (
            f"{E('bolt')} <b>Telegram Account Info</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{E('globe')} Country : {cflag(srv, name)} {esc(cname(srv, name))}\n"
            f"{E('money')} Price : ₹{price} (fixed)\n"
            f"{E('box')} Available : <b>{stock_label(cnt)}</b>\n"
            f"🔍 {esc(tags)}\n"
            + (f"📝 {esc(cobj.get('desc'))}\n" if cobj.get("desc") else "")
            + "\n"
            f"{E('warn')} <b>Important:</b> {esc(db.get('buy_note', DEFAULT_BUY_NOTE))}\n"
            f"🚫 We are not responsible for any freeze/ban"
        )
    rows = [
        [InlineKeyboardButton(f"{E('cart')} Buy Account", callback_data=f"buyconf_{code}_{cidx}_{page}")],
    ]
    viewer = msg_or_query.from_user.id
    if is_admin(viewer):
        if srv_is_api(srv):
            rows.append([InlineKeyboardButton(f"{E('sync')} Sync Stock", callback_data=f"tgsync_now_{code}_{page}"),
                         InlineKeyboardButton(f"{E('chart')} Live Status", callback_data="tg_status")])
        else:
            rows.append([InlineKeyboardButton("💰 Change Price", callback_data=f"price_c_{code}_{cidx}"),
                         InlineKeyboardButton("🔍 Edit Tags", callback_data=f"tags_c_{code}_{cidx}")])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"cpg_{code}_{page}"),
                 InlineKeyboardButton("🏠 Back to Home", callback_data="home")])
    await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(rows))

async def send_buy_confirm(msg_or_query, code, cidx, page):
    srv = get_server(code)
    if not srv:
        return await _edit_or_reply(msg_or_query, "❌ Server not found.", None)
    names = [n for n in country_list(srv) if stock_count(srv["countries"][n]) > 0]
    if cidx >= len(names):
        return await send_country_page(msg_or_query, code, page)
    name = names[cidx]
    ids = unsold_ids(srv["countries"][name])
    if not ids:
        if not isinstance(msg_or_query, Message):
            await ack(msg_or_query, "❌ Out of stock!", show_alert=True)
        return
    item = min(ids, key=lambda i: i["price"])
    uid = msg_or_query.from_user.id
    bal = balance_of(uid)
    if item.get("api"):
        phone_line = f"{E('phone')} Number: <b>🎲 fresh number after payment</b>\n"
        twofa_line = f"{E('key')} 2FA: will be shown with OTP (if provided)\n"
    else:
        phone_line = f"{E('phone')} Number: <code>{mask_phone_confirm(item['number'])}</code>\n"
        twofa_line = f"{E('key')} 2FA: {'✅ Yes' if item.get('password') not in (None, '', 'None') else '⛔ No'}\n"
    text = (
        f"{E('cart')} <b>PURCHASE CONFIRMATION</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ {esc(item.get('label') or cname(srv, name))}\n\n"
        f"<b>Account Details:</b>\n"
        f"{phone_line}{twofa_line}\n"
        f"<b>Payment:</b>\n"
        f"{E('money')} Price: ₹{item['price']}\n"
        f"{E('card')} Balance: ₹{bal}\n"
    )
    if bal < item["price"]:
        text += f"{E('warn')} <b>Insufficient balance! Please deposit first (₹{item['price'] - bal} more needed).</b>\n"
    if item.get("api") and tg_cfg()["dry_run"]:
        text += f"\n{E('warn')} <b>Demo mode</b> — no real number is reserved in this mode.\n"
    text += (f"✅ {esc(db.get('buy_note', DEFAULT_BUY_NOTE))}\n"
             f"🚫 We are not responsible for any freeze/ban")
    rows = [
        [InlineKeyboardButton(f"{E('check')} Confirm &amp; Buy (1)", callback_data=f"confbuy_{code}_{cidx}_{page}")],
    ]
    bulk = db.get("bulk") or {}
    if bulk and stock_count(srv["countries"][name]) > 1:
        brow = []
        for q_s, pct in sorted(bulk.items(), key=lambda kv: int(kv[0])):
            unit = int(item["price"] * (1 - float(pct) / 100.0))
            brow.append(InlineKeyboardButton(
                f"🔥 {q_s} pcs • {cur()}{unit}/pc (−{pct}%)",
                callback_data=f"confbuyq_{q_s}_{code}_{cidx}_{page}"))
        rows.append(brow)
        text += (f"\n{E('gift')} <b>Bulk offer:</b> "
                 + ", ".join(f"{q} pcs = {p}% off" for q, p in
                             sorted(bulk.items(), key=lambda kv: int(kv[0]))) + "\n")
    if bal < item["price"]:
        rows.append([InlineKeyboardButton("💳 Deposit Now", callback_data="dep_menu")])
    rows.append([InlineKeyboardButton("« Back", callback_data=f"cid_{code}_{cidx}_{page}"),
                 InlineKeyboardButton("❌ Cancel", callback_data="home")])
    if not isinstance(msg_or_query, Message):
        await ack(msg_or_query)
    await _edit_or_reply(msg_or_query, text, InlineKeyboardMarkup(rows))

# ================= PROFILE =================

@app.on_message(filters.regex("^👤 Profile$") & filters.private)
async def profile_handler(client, message):
    user_states.pop(message.from_user.id, None)
    await send_profile(message)

@app.on_message(filters.private & filters.regex(r"(?i)^/myids\b"))
async def cmd_myids(client, message):
    await send_my_ids(message)

async def send_profile(msg_or_query):
    uid = msg_or_query.from_user.id
    rec = user_record(uid, msg_or_query.from_user.first_name)
    mine = [s for s in db.get("sales", []) if s["uid"] == uid]
    text = (
        f"{E('user')} <b>YOUR PROFILE — {esc(bot_name())}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>👤 Account Information</b>\n"
        f"🙋 Name: {esc(rec.get('name', 'Unknown'))}\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"📅 Joined: {pretty_ts(rec.get('joined', time.time()))}\n\n"
        f"<b>{E('card')} Wallet</b>\n"
        f"{E('money')} Balance: ₹{rec.get('balance', 0)}\n"
        f"📥 Deposited: ₹{rec.get('deposited', 0)}\n"
        f"🛒 Spent: ₹{rec.get('spent', 0)}\n"
        f"🧾 Purchases: {rec.get('purchases', 0)}\n"
    )
    btns = []
    if mine:
        btns.append([InlineKeyboardButton(f"{E('box')} My IDs ({len(mine)}) — OTP / Sessions",
                                          callback_data="myids")])
    btns.append([InlineKeyboardButton("💳 Deposit", callback_data="dep_menu"),
                 InlineKeyboardButton("🏠 Home", callback_data="home")])
    markup = InlineKeyboardMarkup(btns)
    if isinstance(msg_or_query, Message):
        await msg_or_query.reply_text(text, reply_markup=markup)
    else:
        try:
            await msg_or_query.message.edit_text(text, reply_markup=markup)
        except Exception:
            await msg_or_query.message.reply_text(text, reply_markup=markup)

# ================= SUPPORT =================

@app.on_message(filters.regex("^📞 Support$") & filters.private)
async def support_handler(client, message):
    await message.reply_text(
        f"{E('support')} <b>Support — {esc(bot_name())}</b>\n\n"
        f"For any query or issue, contact our support team.\n"
        f"⏰ Response time: 1-2 hours\n"
        f"🔖 Always keep your Deposit Ref ID ready.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🆘 Contact Support", url=format_url(db["support_link"]))],
            [InlineKeyboardButton("🏠 Home", callback_data="home")],
        ]))

# ================= USER COMMANDS =================

@app.on_message(filters.private & filters.regex(r"(?i)^/products\b"))
async def cmd_products(client, message):
    user_states.pop(message.from_user.id, None)
    await send_server_list(message)

@app.on_message(filters.private & filters.regex(r"(?i)^/profile\b"))
async def cmd_profile(client, message):
    user_states.pop(message.from_user.id, None)
    await send_profile(message)

@app.on_message(filters.private & filters.regex(r"(?i)^/deposit\b"))
async def cmd_deposit(client, message):
    user_states.pop(message.from_user.id, None)
    await send_dep_menu(message)

@app.on_message(filters.private & filters.regex(r"(?i)^/support\b"))
async def cmd_support(client, message):
    await support_handler(client, message)

@app.on_message(filters.private & filters.regex(r"(?i)^/help\b"))
async def cmd_help(client, message):
    await message.reply_text(
        f"{E('sparkle')} <b>How to use {esc(bot_name())}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>Buy an ID:</b> 🛒 Products → server → country → 📱 Buy Account → ✅ Confirm &amp; Buy\n"
        f"2️⃣ <b>Add balance:</b> 💳 Deposit → UPI QR → amount → pay exactly → ✅ I Have Paid → screenshot → admin approval\n"
        f"3️⃣ <b>After purchase:</b> OTP arrives automatically (~25 sec). Use 🔄 Request New OTP / 📱 Manage Sessions anytime\n"
        f"4️⃣ <b>Your IDs:</b> 👤 Profile → 📦 My IDs (or /myids) — numbers, OTP codes, sessions\n"
        f"5️⃣ <b>Problem?</b> 📞 Support button or /support\n\n"
        f"📜 /terms — rules &amp; conditions\n"
        f"💰 All prices are in ₹ (INR)",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Products", callback_data="home_products"),
             InlineKeyboardButton("💳 Deposit", callback_data="dep_menu")],
            [InlineKeyboardButton("👤 Profile", callback_data="home_profile"),
             InlineKeyboardButton("🏠 Home", callback_data="home")]]))
